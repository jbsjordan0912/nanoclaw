import { useState, useEffect, useCallback, useMemo } from 'react'
import { API, TradeUnlockModal } from './App.jsx'

// ── Unranked Upsets ──────────────────────────────────────────────────────────
// Kalshi "College Football Unranked Upsets" weekly strikes (1+ … N+) against a
// Poisson-binomial fair value built from the exchanges' live moneylines on each
// qualifying game. Backend: /api/upsets/* (upsets.py). Trading uses the same
// dashboard trade token as the other boards.

const C = { bg: '#0f172a', panel: '#1e293b', line: '#334155', text: '#f1f5f9', muted: '#94a3b8', dim: '#64748b', blue: '#2563eb', green: '#22c55e', red: '#ef4444', amber: '#f59e0b' }
const pct1 = x => x == null ? '–' : `${Number(x).toFixed(1)}%`
const cents = x => x == null ? '–' : `${x}¢`
const signed = x => x == null ? '' : `${x > 0 ? '+' : ''}${Number(x).toFixed(1)}`
const edgeColor = x => x == null ? C.dim : x > 0 ? C.green : C.red
const kick = iso => new Date(iso).toLocaleString('en-US', { weekday: 'short', hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York' })
const age = s => s < 60 ? `${s}s` : s < 3600 ? `${Math.round(s / 60)}m` : `${Math.round(s / 3600)}h`
const hhmm = iso => iso ? new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) : '–'

const btn = (extra = {}) => ({
  padding: '7px 10px', borderRadius: 8, border: `1px solid ${C.line}`, background: '#0f172a', color: C.text,
  fontSize: 12, fontWeight: 600, cursor: 'pointer', ...extra,
})
const panel = { background: C.panel, border: `1px solid ${C.line}`, borderRadius: 12, padding: 12, marginBottom: 12 }
const h2 = { fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em', color: C.muted, margin: '0 0 8px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }
const inp = { background: C.bg, color: C.text, border: `1px solid ${C.line}`, borderRadius: 6, padding: '5px 6px', fontSize: 13, width: 64 }

const post = (path, body) => fetch(`${API}/api/upsets${path}`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
})

export default function UpsetsTab() {
  const [state, setState] = useState(null)
  const [down, setDown] = useState(false)
  const [token, setToken] = useState(() => localStorage.getItem('pitchpulse_token') || '')
  const [showUnlock, setShowUnlock] = useState(false)
  const [account, setAccount] = useState(null)
  const [acctErr, setAcctErr] = useState('')
  const [ticket, setTicket] = useState(null)     // { ticker, side, action, price, count, tif }
  const [msg, setMsg] = useState(null)           // { text, err }
  const [showGames, setShowGames] = useState(true)

  const lock = () => { localStorage.removeItem('pitchpulse_token'); setToken(''); setAccount(null) }

  // state poll (the server only polls upstream while this is being asked for)
  const loadState = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/upsets/state`)
      setState(await r.json()); setDown(false)
    } catch { setDown(true) }
  }, [])
  useEffect(() => { loadState(); const t = setInterval(loadState, 5000); return () => clearInterval(t) }, [loadState])

  // account (needs the trade token)
  const loadAccount = useCallback(async () => {
    if (!token) { setAccount(null); return }
    try {
      const r = await fetch(`${API}/api/upsets/account`, { headers: { 'X-Trade-Token': token } })
      if (r.status === 401) { lock(); return }
      const a = await r.json()
      if (!r.ok) throw new Error(a.detail || r.status)
      setAccount(a); setAcctErr('')
    } catch (e) { setAcctErr(`account: ${e.message}`) }
  }, [token])
  useEffect(() => { loadAccount(); const t = setInterval(loadAccount, 5000); return () => clearInterval(t) }, [loadAccount])

  const strikes = state?.strikes || []
  const strikeFor = t => strikes.find(s => s.ticker === t)
  const liveFair = (t, side) => { const s = strikeFor(t); if (!s || s.fair == null) return null; return side === 'yes' ? s.fair : 100 - s.fair }
  const liveBest = (t, side) => { const s = strikeFor(t); if (!s) return null; return side === 'yes' ? s.yes_bid : s.no_bid }

  const flash = (text, err = false) => { setMsg({ text, err }); setTimeout(() => setMsg(null), 6000) }
  const needToken = () => { if (!token) { setShowUnlock(true); return true } return false }

  const refresh = async () => { await post('/refresh', {}); loadState(); loadAccount() }
  const override = async (id, v) => {
    if (needToken()) return
    const p = v === '' ? null : Math.max(0, Math.min(100, Number(v))) / 100
    const r = await post('/override', { game_id: id, p, trade_token: token })
    if (!r.ok) flash((await r.json()).detail || 'override failed', true)
    loadState()
  }
  const cancelOrder = async (id) => {
    const r = await post(`/orders/${id}/cancel`, { trade_token: token })
    flash(r.ok ? 'cancelled' : `cancel: ${(await r.json()).detail}`, !r.ok); loadAccount()
  }
  const cancelAll = async (ticker) => {
    const r = await post('/orders/cancel_all', { ticker, trade_token: token }); const j = await r.json()
    flash(r.ok ? `cancelled ${j.cancelled}${j.failed?.length ? `, ${j.failed.length} failed` : ''}` : j.detail, !r.ok); loadAccount()
  }
  const amend = async (id, price, count) => {
    if (price != null && (price < 1 || price > 99)) return flash('price out of range', true)
    const r = await post(`/orders/${id}/amend`, { price, count, trade_token: token }); const j = await r.json()
    flash(r.ok ? (j.method === 'amend' ? 'amended' : 'replaced (cancel + new order)') : j.detail, !r.ok); loadAccount()
  }

  // ticket
  const openTicket = (t, side) => {
    if (needToken()) return
    const s = strikeFor(t)
    setTicket({ ticker: t, side, action: 'buy', price: (side === 'yes' ? s.yes_ask : s.no_ask) ?? 50, count: 10, tif: '' })
  }
  const setTk = patch => setTicket(prev => {
    const next = { ...prev, ...patch }
    if ('side' in patch || 'action' in patch) {
      const s = strikeFor(next.ticker); const y = next.side === 'yes'
      next.price = (next.action === 'buy' ? (y ? s.yes_ask : s.no_ask) : (y ? s.yes_bid : s.no_bid)) ?? 50
    }
    return next
  })
  const submitOrder = async () => {
    const body = { ticker: ticket.ticker, side: ticket.side, action: ticket.action, count: Number(ticket.count), price: Number(ticket.price), time_in_force: ticket.tif || null, trade_token: token }
    setMsg({ text: 'sending…', err: false })
    const r = await post('/order', body); const j = await r.json()
    if (!r.ok) { flash(j.detail || String(r.status), true); return }
    const o = j.order || j
    const filled = Number(o.fill_count_fp ?? o.fill_count ?? 0), rem = Number(o.remaining_count_fp ?? o.remaining_count ?? NaN)
    flash(`${o.status || 'accepted'} · filled ${filled}${isNaN(rem) ? '' : `, resting ${rem}`}`)
    loadAccount()
  }

  const preview = useMemo(() => {
    if (!ticket) return null
    const s = strikeFor(ticket.ticker); if (!s) return null
    const y = ticket.side === 'yes'; const price = Number(ticket.price), count = Number(ticket.count)
    const bid = y ? s.yes_bid : s.no_bid, ask = y ? s.yes_ask : s.no_ask
    const fair = y ? s.fair : 100 - s.fair; const fv = Math.round(fair)
    const chips = ticket.action === 'buy'
      ? [['bid', bid], ['bid+1', bid != null ? bid + 1 : null], ['take', ask], ['fair−2', fv - 2], ['fair−5', fv - 5]]
      : [['ask', ask], ['ask−1', ask != null ? ask - 1 : null], ['hit', bid], ['fair+2', fv + 2]]
    const book = ticket.action === 'buy' ? (y ? s.yes_asks : s.no_asks) : (y ? s.yes_bids : s.no_bids)
    const levels = ticket.action === 'buy' ? [...book].sort((a, b) => a[0] - b[0]) : [...book].sort((a, b) => b[0] - a[0])
    let filled = 0, cost = 0
    for (const [p, q] of levels) {
      if (ticket.action === 'buy' ? p > price : p < price) break
      const take = Math.min(q, count - filled); filled += take; cost += take * p
      if (filled >= count) break
    }
    return { s, bid, ask, fair, chips: chips.filter(([, v]) => v != null && v >= 1 && v <= 99), filled, avg: filled ? cost / filled : null, rest: count - filled, limit: count * price / 100, edge: fair - price }
  }, [ticket, strikes])

  const ordersFor = ticker => (account?.orders || []).filter(o => o.ticker === ticker)

  const d = state?.dist || {}
  const errs = Object.entries(state?.poll?.errors || {})
  const closes = state?.close_time ? new Date(state.close_time).toLocaleString('en-US', { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', timeZone: 'America/New_York' }) : null

  return (
    <div style={{ animation: 'fadeIn 0.2s ease' }}>
      {/* header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
        <div style={{ flex: 1, minWidth: 180 }}>
          <div style={{ fontSize: 15, fontWeight: 800 }}>Unranked Upsets{state?.week ? ` · Week ${state.week}` : ''}</div>
          <div style={{ fontSize: 11, color: C.dim }}>
            {down ? 'backend unreachable' : !state?.event ? 'connecting…' : `${state.event}${closes ? ` · closes ${closes} ET` : ''}`}
            {state?.poll?.updated && <> · updated {hhmm(state.poll.updated)} · {state.poll.ms}ms</>}
          </div>
        </div>
        <button onClick={refresh} style={btn()}>Refresh</button>
        {token
          ? <span onClick={lock} title="tap to lock" style={{ fontSize: 10, fontWeight: 700, color: C.green, cursor: 'pointer' }}>TRADING ●</span>
          : <button onClick={() => setShowUnlock(true)} style={btn({ borderColor: C.amber, color: C.amber })}>Unlock</button>}
      </div>
      {errs.length > 0 && <div style={{ fontSize: 11, color: C.red, marginBottom: 8 }}>{errs.map(([k, v]) => `${k}: ${v}`).join(' · ')}</div>}
      {state && !state.oddsblaze && <div style={{ fontSize: 11, color: C.amber, marginBottom: 8 }}>ODDSBLAZE_API_KEY is not set on the server — no moneylines, so every game falls to "no data".</div>}
      {msg && <div style={{ fontSize: 12, color: msg.err ? C.red : C.green, marginBottom: 8 }}>{msg.text}</div>}

      {/* strikes */}
      <div style={panel}>
        <div style={h2}><span>Strikes</span><span style={{ textTransform: 'none', letterSpacing: 0 }}>{state?.poll?.kalshi_updated ? `Kalshi ${hhmm(state.poll.kalshi_updated)}` : ''}</span></div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          {strikes.map(st => (
            <div key={st.ticker} style={{ border: `1px solid ${C.line}`, borderRadius: 10, padding: 10, background: C.bg }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                <span style={{ fontSize: 15, fontWeight: 700 }}>{st.k}+</span>
                <span style={{ fontSize: 10, color: C.dim }}>{st.volume ?? ''} vol</span>
              </div>
              <div style={{ fontSize: 24, fontWeight: 800, margin: '2px 0 4px' }}>{pct1(st.fair)}</div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, fontVariantNumeric: 'tabular-nums' }}>
                <span>YES {cents(st.yes_bid)}/{cents(st.yes_ask)}</span><span style={{ color: edgeColor(st.edge_yes) }}>{signed(st.edge_yes)}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, fontVariantNumeric: 'tabular-nums' }}>
                <span>NO&nbsp; {cents(st.no_bid)}/{cents(st.no_ask)}</span><span style={{ color: edgeColor(st.edge_no) }}>{signed(st.edge_no)}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: C.dim, marginTop: 2 }}><span>last {cents(st.last)}</span><span>{st.status}</span></div>
              <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
                <button onClick={() => openTicket(st.ticker, 'yes')} style={btn({ flex: 1, borderColor: C.green, padding: '6px 0' })}>YES</button>
                <button onClick={() => openTicket(st.ticker, 'no')} style={btn({ flex: 1, borderColor: C.red, padding: '6px 0' })}>NO</button>
              </div>
              {ordersFor(st.ticker).map(o => {
                const fair = liveFair(o.ticker, o.side); const edge = fair == null ? null : fair - o.price
                const best = liveBest(o.ticker, o.side); const atBest = best != null && best === o.price
                return (
                  <div key={o.order_id} style={{ marginTop: 6, paddingTop: 6, borderTop: `1px dashed ${C.line}`, fontSize: 11 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span><b>{o.side.toUpperCase()}</b> {o.remaining}{o.filled ? <span style={{ color: C.dim }}> +{o.filled}</span> : null} @ <b>{o.price}¢</b></span>
                      <span style={{ color: edgeColor(edge) }}>{signed(edge)}</span>
                    </div>
                    <div style={{ display: 'flex', gap: 4, marginTop: 4, alignItems: 'center' }}>
                      <button onClick={() => amend(o.order_id, o.price - 1, null)} style={btn({ padding: '2px 6px', fontSize: 11 })}>−1</button>
                      <button onClick={() => amend(o.order_id, o.price + 1, null)} style={btn({ padding: '2px 6px', fontSize: 11 })}>+1</button>
                      {best != null && !atBest && <button onClick={() => amend(o.order_id, best, null)} style={btn({ padding: '2px 6px', fontSize: 11 })}>→{best}</button>}
                      {atBest && <span style={{ color: C.green }}>top</span>}
                      <span style={{ flex: 1 }} />
                      <button onClick={() => cancelOrder(o.order_id)} style={btn({ padding: '2px 6px', fontSize: 11, color: C.red })}>✕</button>
                    </div>
                  </div>
                )
              })}
            </div>
          ))}
          {strikes.length === 0 && <div style={{ color: C.dim, fontSize: 12, gridColumn: '1 / -1' }}>{state ? 'no open strikes' : 'loading…'}</div>}
        </div>
        {d.exact && (
          <div style={{ display: 'flex', gap: 10, overflowX: 'auto', fontSize: 11, color: C.muted, marginTop: 10, paddingBottom: 2, whiteSpace: 'nowrap' }}>
            <span>expected <b style={{ color: C.text }}>{d.expected}</b></span>
            <span>final <b style={{ color: C.text }}>{d.final_upsets}</b> in <b style={{ color: C.text }}>{d.final_games}</b>/{d.games}</span>
            {d.exact.map((v, k) => v >= 0.0005 && <span key={k}>={k} <b style={{ color: C.text }}>{(v * 100).toFixed(1)}%</b></span>)}
          </div>
        )}
      </div>

      {/* account */}
      {token && (
        <div style={panel}>
          <div style={h2}>
            <span>Positions{account?.balance ? ` · $${Number(account.balance.balance_dollars ?? account.balance.balance / 100).toFixed(2)} avail` : ''}</span>
            {(account?.orders?.length || 0) > 0 && <button onClick={() => cancelAll(null)} style={btn({ padding: '3px 8px', fontSize: 11, color: C.red })}>Cancel all</button>}
          </div>
          {acctErr && <div style={{ fontSize: 11, color: C.red, marginBottom: 6 }}>{acctErr}</div>}
          {(account?.positions || []).map(p => {
            const pos = Number(p.position_fp ?? p.position ?? 0); const expo = Number(p.market_exposure_dollars ?? (p.market_exposure ?? 0) / 100)
            const side = pos > 0 ? 'yes' : 'no'; const n = Math.abs(pos); const avg = n ? expo / n * 100 : null; const fair = liveFair(p.ticker, side)
            const unreal = (fair != null && n) ? (fair - avg) / 100 * n : null
            return (
              <div key={p.ticker} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, padding: '4px 0', borderBottom: `1px solid ${C.line}`, fontVariantNumeric: 'tabular-nums' }}>
                <span><b>{p.ticker.replace(`${state.event}-`, '')}+</b> {n ? `${side.toUpperCase()} ${n}` : 0} @ {avg != null ? `${avg.toFixed(1)}¢` : '–'}</span>
                <span>fair {fair != null ? `${fair.toFixed(1)}¢` : '–'} · <span style={{ color: unreal > 0 ? C.green : unreal < 0 ? C.red : C.muted }}>{unreal != null ? `${unreal >= 0 ? '+' : '−'}$${Math.abs(unreal).toFixed(2)}` : '–'}</span></span>
              </div>
            )
          })}
          {account && !account.positions?.length && <div style={{ fontSize: 11, color: C.dim }}>no positions on this event</div>}
          {(account?.orders?.length || 0) > 0 && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 10, color: C.dim, marginBottom: 4 }}>RESTING</div>
              {[...account.orders].sort((x, y) => (x.k - y.k) || (x.side === y.side ? 0 : x.side === 'yes' ? -1 : 1) || (y.price - x.price)).map(o => {
                const fair = liveFair(o.ticker, o.side); const edge = fair == null ? null : fair - o.price
                return (
                  <div key={o.order_id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 12, padding: '3px 0', gap: 6 }}>
                    <span><b>{o.k}+</b> {o.side.toUpperCase()} {o.remaining} @ {o.price}¢</span>
                    <span style={{ color: edgeColor(edge) }}>{signed(edge)}</span>
                    <button onClick={() => cancelOrder(o.order_id)} style={btn({ padding: '2px 6px', fontSize: 11, color: C.red })}>✕</button>
                  </div>
                )
              })}
            </div>
          )}
          {(account?.fills?.length || 0) > 0 && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 10, color: C.dim, marginBottom: 4 }}>RECENT FILLS</div>
              {account.fills.slice(0, 8).map((f, i) => (
                <div key={f.trade_id || i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: C.muted, padding: '2px 0' }}>
                  <span>{hhmm(f.created_time)} · {f.ticker.replace(`${state.event}-`, '')}+ {f.action} {f.side}</span>
                  <span>{f.side === 'yes' ? (f.yes_price ?? Math.round(Number(f.yes_price_dollars) * 100)) : (f.no_price ?? Math.round(Number(f.no_price_dollars) * 100))}¢ × {f.count ?? f.count_fp}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* games */}
      <div style={panel}>
        <div style={{ ...h2, cursor: 'pointer' }} onClick={() => setShowGames(v => !v)}>
          <span>Qualifying games · {state?.games?.length ?? 0}</span><span>{showGames ? '▾' : '▸'}</span>
        </div>
        {showGames && (state?.games || []).map(g => {
          const upset = g.state === 'post' && g.unranked_score > g.ranked_score
          const statusColor = g.state === 'in' ? C.amber : g.state === 'post' ? C.dim : C.muted
          const ov = state.overrides?.[g.id]
          const staleAfter = g.state === 'in' ? 600 : 21600
          return (
            <div key={g.id} style={{ padding: '8px 0', borderBottom: `1px solid ${C.line}` }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8 }}>
                <span style={{ fontSize: 13 }}>
                  <span style={{ color: C.dim, fontSize: 11 }}>#{g.rank}</span> <b>{g.ranked.short}</b>{g.ranked.home ? '' : <span style={{ color: C.dim }}> @</span>}
                  <span style={{ color: C.dim }}> vs </span>
                  <b style={{ color: upset ? C.green : C.text }}>{g.unranked.short}</b>{g.unranked.home ? '' : <span style={{ color: C.dim }}> @</span>}
                </span>
                <span style={{ fontSize: 16, fontWeight: 800, fontVariantNumeric: 'tabular-nums' }}>{pct1(g.p * 100)}</span>
              </div>
              <div style={{ height: 4, background: C.bg, borderRadius: 2, overflow: 'hidden', margin: '4px 0' }}><div style={{ width: `${(g.p * 100).toFixed(0)}%`, height: '100%', background: C.blue }} /></div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: C.muted, gap: 8 }}>
                <span><span style={{ color: statusColor }}>{g.state === 'pre' ? kick(g.kick) : `${g.ranked_score}-${g.unranked_score} · ${g.detail}`}{upset ? ' · UPSET' : ''}</span> · {g.p_source}</span>
                {!g.locked && (
                  <span style={{ whiteSpace: 'nowrap' }}>
                    <input type="number" min="0" max="100" step="1" placeholder="%" defaultValue={ov != null ? Math.round(ov * 100) : ''} key={`${g.id}-${ov}`}
                      onBlur={e => override(g.id, e.target.value)} onKeyDown={e => e.key === 'Enter' && e.target.blur()}
                      style={{ ...inp, width: 48, padding: '2px 4px', fontSize: 11 }} title="manual P(upset) %" />
                  </span>
                )}
              </div>
              <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 4 }}>
                {Object.entries(g.sources || {}).map(([b, v]) => (
                  <span key={b} style={{ fontSize: 10, padding: '1px 6px', borderRadius: 10, background: C.bg, color: C.muted, textDecoration: v.age > staleAfter ? 'line-through' : 'none', opacity: v.age > staleAfter ? 0.6 : 1 }}>
                    {b.slice(0, 4)} {(v.p * 100).toFixed(0)} <i>{age(v.age)}</i>
                  </span>
                ))}
                {!Object.keys(g.sources || {}).length && <span style={{ fontSize: 10, color: C.dim }}>no quotes</span>}
              </div>
            </div>
          )
        })}
      </div>

      {/* ticket */}
      {ticket && preview && (
        <div style={{ position: 'fixed', left: 0, right: 0, bottom: 0, zIndex: 50, display: 'flex', justifyContent: 'center', pointerEvents: 'none' }}>
          <div style={{ pointerEvents: 'auto', width: '100%', maxWidth: 480, background: '#111827', borderTop: `2px solid ${C.blue}`, borderRadius: '14px 14px 0 0', padding: '12px 16px 18px', boxShadow: '0 -10px 30px #0008' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
              <b style={{ fontSize: 14 }}>{preview.s.k}+ upsets · fair {pct1(preview.s.fair)}</b>
              <span style={{ fontSize: 11, color: C.dim }}>YES {cents(preview.s.yes_bid)}/{cents(preview.s.yes_ask)} · NO {cents(preview.s.no_bid)}/{cents(preview.s.no_ask)}</span>
            </div>
            <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
              {['yes', 'no'].map(s => <button key={s} onClick={() => setTk({ side: s })} style={btn({ flex: 1, borderColor: s === 'yes' ? C.green : C.red, background: ticket.side === s ? (s === 'yes' ? '#14532d' : '#7f1d1d') : C.bg })}>{s.toUpperCase()}</button>)}
              {['buy', 'sell'].map(a => <button key={a} onClick={() => setTk({ action: a })} style={btn({ flex: 1, background: ticket.action === a ? '#1e3a8a' : C.bg })}>{a}</button>)}
            </div>
            <div style={{ display: 'flex', gap: 8, marginTop: 8, alignItems: 'flex-end' }}>
              <label style={{ fontSize: 10, color: C.dim }}>Price ¢<br /><input type="number" min="1" max="99" value={ticket.price} onChange={e => setTk({ price: e.target.value })} style={inp} /></label>
              <label style={{ fontSize: 10, color: C.dim }}>Contracts<br /><input type="number" min="1" value={ticket.count} onChange={e => setTk({ count: e.target.value })} style={inp} /></label>
              <label style={{ fontSize: 10, color: C.dim }}>TIF<br />
                <select value={ticket.tif} onChange={e => setTk({ tif: e.target.value })} style={{ ...inp, width: 'auto' }}><option value="">Rest</option><option value="ioc">IOC</option></select>
              </label>
            </div>
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 6 }}>
              {preview.chips.map(([l, v]) => <button key={l} onClick={() => setTk({ price: v })} style={btn({ padding: '2px 7px', fontSize: 11 })}>{l} {v}¢</button>)}
            </div>
            <div style={{ fontSize: 11, color: C.muted, marginTop: 6 }}>
              {ticket.action === 'buy' ? 'Cost' : 'Proceeds'} at limit ≤ ${preview.limit.toFixed(2)} · fills now ≈ {preview.filled} @ {preview.avg != null ? `${preview.avg.toFixed(1)}¢` : '–'}{preview.rest > 0 ? `, ${preview.rest} rest${ticket.tif === 'ioc' ? ' cancelled' : ''}` : ''}
              <br />fair {preview.fair.toFixed(1)}¢ → edge <b style={{ color: edgeColor(preview.edge) }}>{preview.edge.toFixed(1)}¢</b> per contract
            </div>
            <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
              <button onClick={submitOrder} style={btn({ flex: 2, background: C.blue, borderColor: C.blue, color: '#fff', padding: '10px 0', fontSize: 13 })}>Place {ticket.action} {ticket.side.toUpperCase()}</button>
              <button onClick={() => setTicket(null)} style={btn({ flex: 1, padding: '10px 0' })}>Close</button>
            </div>
          </div>
        </div>
      )}

      {showUnlock && <TradeUnlockModal onUnlocked={t => { setToken(t); setShowUnlock(false) }} onClose={() => setShowUnlock(false)} />}
    </div>
  )
}
