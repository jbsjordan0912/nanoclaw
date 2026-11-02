-- Postgres schema for trade_forecasts (used when DATABASE_URL is set; SQLite is the default, see trades.py).
-- One row per submitted guess; the latest row per (forecaster, market) is the current guess.
create table if not exists trade_forecasts (
  id bigserial primary key,
  event_ticker text not null,
  market_ticker text not null,
  player text not null,
  forecaster text not null,
  pct smallint not null check (pct between 0 and 100),
  market_bid smallint,          -- Kalshi YES bid at submit time (never shown to forecasters)
  market_ask smallint,          -- Kalshi YES ask at submit time
  submitted_at timestamptz not null default now()
);
create index if not exists trade_forecasts_lookup
  on trade_forecasts (event_ticker, forecaster, market_ticker, submitted_at desc);
