"""Minimal Kalshi API client.

Public market-data endpoints need no auth. Order execution / portfolio
endpoints are signed with an RSA private key (RSA-PSS, SHA-256) per Kalshi's
API-key auth scheme:

    message   = timestamp_ms + METHOD + path_without_query
    signature = base64( RSA-PSS-SHA256( message ) )

Headers sent on authed requests:
    KALSHI-ACCESS-KEY        <api key id>
    KALSHI-ACCESS-SIGNATURE  <base64 signature>
    KALSHI-ACCESS-TIMESTAMP  <timestamp in ms>
"""
from __future__ import annotations

import base64
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"


class KalshiError(Exception):
    pass


def _load_private_key(pem: Optional[str], path: Optional[str]):
    """Load an RSA private key from a PEM string or a file path (PKCS#8/PKCS#1)."""
    data: Optional[bytes] = None
    if pem:
        data = pem.encode() if isinstance(pem, str) else pem
    elif path:
        with open(path, "rb") as fh:
            data = fh.read()
    if not data:
        return None
    return serialization.load_pem_private_key(data, password=None)


class KalshiClient:
    def __init__(
        self,
        api_key_id: Optional[str] = None,
        private_key_pem: Optional[str] = None,
        private_key_path: Optional[str] = None,
        base_url: str = BASE_URL,
        timeout: float = 20.0,
    ):
        self.api_key_id = api_key_id
        self.base_url = base_url.rstrip("/")
        self._key = _load_private_key(private_key_pem, private_key_path)
        self._client = httpx.Client(timeout=timeout, headers={"Accept": "application/json"})

    # ------------------------------------------------------------------ auth
    @property
    def authed(self) -> bool:
        return bool(self.api_key_id and self._key)

    def _sign(self, ts_ms: str, method: str, path: str) -> str:
        if not self._key:
            raise KalshiError("No private key loaded; cannot sign request.")
        msg = f"{ts_ms}{method}{path}".encode()
        sig = self._key.sign(
            msg,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return base64.b64encode(sig).decode()

    def _headers(self, method: str, path: str) -> Dict[str, str]:
        if not self.authed:
            return {}
        ts_ms = str(int(time.time() * 1000))
        # path signed must NOT include the query string
        sign_path = path.split("?", 1)[0]
        return {
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-SIGNATURE": self._sign(ts_ms, method, sign_path),
            "KALSHI-ACCESS-TIMESTAMP": ts_ms,
        }

    # --------------------------------------------------------------- request
    def _request(self, method: str, path: str, *, params=None, json=None, auth=False) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        # For signing we need the full path including the /trade-api/v2 prefix.
        full_path = url.replace("https://api.elections.kalshi.com", "")
        headers = self._headers(method, full_path) if auth else {}
        try:
            resp = self._client.request(method, url, params=params, json=json, headers=headers)
        except httpx.HTTPError as e:
            raise KalshiError(f"network error: {e}") from e
        if resp.status_code >= 400:
            raise KalshiError(f"{resp.status_code} {resp.text[:400]}")
        return resp.json() if resp.content else {}

    # --------------------------------------------------------- public: data
    def get_sports_series(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        data = self._request("GET", "/series", params={"category": "Sports"})
        out.extend(data.get("series", []))
        return out

    def get_markets(
        self,
        *,
        status: str = "open",
        series_ticker: Optional[str] = None,
        limit: int = 1000,
        max_pages: int = 40,
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        for _ in range(max_pages):
            params: Dict[str, Any] = {"status": status, "limit": limit}
            if series_ticker:
                params["series_ticker"] = series_ticker
            if cursor:
                params["cursor"] = cursor
            data = self._request("GET", "/markets", params=params)
            out.extend(data.get("markets", []))
            cursor = data.get("cursor")
            if not cursor:
                break
        return out

    def get_sports_markets(self, max_workers: int = 32) -> Dict[str, Any]:
        """Sweep every Sports series in parallel for its open markets.

        The bulk /markets feed is dominated by tens of thousands of
        auto-generated multivariate parlay markets (KXMVE* collections, which
        aren't even in the Sports series list), so per-series is the only way
        to reliably reach real single-game markets."""
        series = self.get_sports_series()
        series_title = {s["ticker"]: s.get("title", s["ticker"]) for s in series if s.get("ticker")}
        tickers = [s["ticker"] for s in series if s.get("ticker")]

        def _one(tk: str) -> List[Dict[str, Any]]:
            try:
                return self.get_markets(status="open", series_ticker=tk, max_pages=5)
            except KalshiError:
                return []

        markets: List[Dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            for ms in ex.map(_one, tickers):
                markets.extend(ms)
        return {"series_title": series_title, "series_count": len(tickers), "markets": markets}

    def get_orderbook(self, ticker: str, depth: int = 10) -> Dict[str, Any]:
        return self._request("GET", f"/markets/{ticker}/orderbook", params={"depth": depth})

    # ------------------------------------------------------ authed: account
    def get_balance(self) -> Dict[str, Any]:
        return self._request("GET", "/portfolio/balance", auth=True)

    def get_positions(self, **params) -> Dict[str, Any]:
        return self._request("GET", "/portfolio/positions", params=params or None, auth=True)

    def get_orders(self, **params) -> Dict[str, Any]:
        return self._request("GET", "/portfolio/orders", params=params or None, auth=True)

    def get_fills(self, **params) -> Dict[str, Any]:
        return self._request("GET", "/portfolio/fills", params=params or None, auth=True)

    def get_order(self, order_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/portfolio/orders/{order_id}", auth=True).get("order", {})

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        # DELETE /portfolio/orders/{id} answers 410 now; the v2 path is under events.
        return self._request("DELETE", f"/portfolio/events/orders/{order_id}", auth=True)

    def place_order_v2(self, *, ticker: str, side: str, action: str, count: int, price_cents: int,
                       time_in_force: Optional[str] = None, client_order_id: Optional[str] = None) -> Dict[str, Any]:
        """POST /portfolio/events/orders -- the endpoint that replaced
        /portfolio/orders (which now answers 410 deprecated_v1_order_endpoint).

        The book is expressed in YES terms: "bid" adds long-YES exposure, "ask"
        adds short-YES (= long NO). So buy YES @p is bid@p, buy NO @q is
        ask@(100-q), sell YES @p is ask@p, sell NO @q is bid@(100-q). Price is a
        dollar string, count a string; no time_in_force means the order rests."""
        if not self.authed:
            raise KalshiError("Credentials required to place orders.")
        if side not in ("yes", "no") or action not in ("buy", "sell"):
            raise KalshiError("side must be yes|no and action buy|sell")
        long_yes = (side == "yes") == (action == "buy")
        yes_price = price_cents if side == "yes" else 100 - price_cents
        body: Dict[str, Any] = {
            "ticker": ticker,
            "side": "bid" if long_yes else "ask",
            "count": f"{int(count)}.00",
            "price": f"{yes_price / 100:.4f}",
            "self_trade_prevention_type": "taker_at_cross",
            "client_order_id": client_order_id or str(int(time.time() * 1000)),
        }
        # Required on v2: good_till_canceled rests, immediate_or_cancel takes what
        # is there and cancels the rest, fill_or_kill is all or nothing.
        body["time_in_force"] = time_in_force or "good_till_canceled"
        return self._request("POST", "/portfolio/events/orders", json=body, auth=True)

    def amend_order_v2(self, *, order_id: str, ticker: str, book_side: str, yes_price_cents: int, count: int,
                       client_order_id: str, updated_client_order_id: str) -> Dict[str, Any]:
        """POST /portfolio/events/orders/{id}/amend. book_side is bid|ask (YES
        terms), price a dollar string on the YES book, count the order's new
        size. Both client ids are required: the original and a fresh one."""
        body = {
            "ticker": ticker, "side": book_side, "price": f"{yes_price_cents / 100:.4f}",
            "count": f"{int(count)}.00", "client_order_id": client_order_id,
            "updated_client_order_id": updated_client_order_id,
        }
        return self._request("POST", f"/portfolio/events/orders/{order_id}/amend", json=body, auth=True)

    def decrease_order_v2(self, *, order_id: str, ticker: str, reduce_by: int) -> Dict[str, Any]:
        return self._request("POST", f"/portfolio/events/orders/{order_id}/decrease",
                             json={"ticker": ticker, "reduce_by": f"{int(reduce_by)}.00"}, auth=True)

    def get_event(self, event_ticker: str) -> Dict[str, Any]:
        return self._request("GET", f"/events/{event_ticker}", params={"with_nested_markets": "true"})

    def place_order(
        self,
        *,
        ticker: str,
        side: str,          # "yes" | "no"
        action: str,        # "buy" | "sell"
        count: int,
        order_type: str = "limit",   # "limit" | "market"
        yes_price: Optional[int] = None,  # cents, for limit on the yes book
        no_price: Optional[int] = None,   # cents, for limit on the no book
        client_order_id: Optional[str] = None,
        time_in_force: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self.authed:
            raise KalshiError("Credentials required to place orders.")
        body: Dict[str, Any] = {
            "ticker": ticker,
            "side": side,
            "action": action,
            "count": int(count),
            "type": order_type,
        }
        if client_order_id:
            body["client_order_id"] = client_order_id
        if order_type == "limit":
            if yes_price is not None:
                body["yes_price"] = int(yes_price)
            if no_price is not None:
                body["no_price"] = int(no_price)
        if time_in_force:
            body["time_in_force"] = time_in_force
        return self._request("POST", "/portfolio/orders", json=body, auth=True)
