// Flow collector: rests a post-only YES bid and NO bid at the best bid on each
// side of the ticked markets while the switch is on. Server side is flow.py;
// the switch turns itself off after the failsafe and orders expire on Kalshi.
import { useState, useEffect, useRef, useCallback } from 'react'

const MAKER_FEE = 0.0175
// Cents left from buying both sides one tick apart... i.e. spread minus both maker fees.
export const flowNetPerPair = (bid, ask) => {
  if (bid == null || ask == null) return null
  const p = (bid + ask) / 200
  return (ask - bid) - 2 * MAKER_FEE * p * (1 - p) * 100
}

export function useFlow(API, game, token) {
  const [st, setSt] = useState(null)
  const [msg, setMsg] = useState('')
  const key = `flow_${game}`
  const restored = useRef(false)

  const call = useCallback(async (path, extra = {}) => {
    try {
      const r = await fetch(`${API}/api/flow/${path}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ trade_token: token, game, ...extra }),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) { setMsg(d.detail || `Flow: request failed (${r.status})`); return null }
      setSt(d)
      return d
    } catch (e) { setMsg('Flow: server not reachable. Resting orders expire on their own within seconds of the timer.'); return null }
  }, [API, game, token])

  useEffect(() => {
    if (!token) { setSt(null); return }
    let alive = true
    const tick = async () => {
      if (!alive || document.hidden) return
      const d = await call('state')
      // After a server restart its memory is blank: push back what this browser had.
      if (d && !restored.current) {
        restored.current = true
        try {
          const saved = JSON.parse(localStorage.getItem(key))
          if (saved && !d.enabled.length && (saved.enabled?.length || saved.settings)) {
            await call('settings', { settings: saved.settings, enabled: saved.enabled || [] })
          }
        } catch {}
      }
    }
    tick()
    const t = setInterval(tick, 700)
    return () => { alive = false; clearInterval(t) }
  }, [token, call, key])

  const save = (settings, enabled) => { try { localStorage.setItem(key, JSON.stringify({ settings, enabled })) } catch {} }
  const labelled = (tickers, extra) => tickers.map(t => ({ ticker: t, label: (extra && extra[t]) || st?.markets.find(m => m.ticker === t)?.label || t }))

  return {
    st, msg, clearMsg: () => setMsg(''),
    on: () => call('on'),
    off: () => { setSt(s => s && { ...s, armed: false, left: 0 }); return call('off') },
    reset: () => call('reset'),
    test: () => call('test'),
    set: async (patch) => {
      const d = await call('settings', { settings: patch })
      if (d) save(d.settings, labelled(d.enabled))
    },
    toggle: async (ticker, label) => {
      if (!st) return
      const has = st.enabled.includes(ticker)
      const next = has ? st.enabled.filter(t => t !== ticker) : [...st.enabled, ticker]
      const d = await call('settings', { enabled: labelled(next, { [ticker]: label }) })
      if (d) save(d.settings, labelled(d.enabled, { [ticker]: label }))
    },
  }
}

const usd = (v) => <span style={{ color: v >= 0 ? '#22c55e' : '#ef4444', fontWeight: 700 }}>{v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(2)}</span>
const FIELDS = [
  ['size', 'Contracts / order', 1], ['max_pos', 'Max position', 1], ['min_spread', 'Min spread ¢', 1],
  ['failsafe', 'Auto-off s', 1], ['jump', 'Pull if moves ¢', 0.5], ['loss_stop', 'Stop at −$', 1],
]

export default function FlowPanel({ flow, token, onUnlock }) {
  const { st } = flow
  const [open, setOpen] = useState(true)
  const [, force] = useState(0)
  const until = useRef(0)
  const [draft, setDraft] = useState({})

  if (st) until.current = st.armed ? performance.now() + st.left * 1000 : 0
  useEffect(() => { const t = setInterval(() => force(n => n + 1), 100); return () => clearInterval(t) }, [])
  const left = Math.max(0, (until.current - performance.now()) / 1000)
  const armed = left > 0

  const flowRef = useRef(flow)
  flowRef.current = flow
  const toggle = () => (until.current > performance.now() ? flowRef.current.off() : flowRef.current.on())
  const ready = !!st
  useEffect(() => {
    if (!ready) return
    const h = (e) => {
      const tag = e.target?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      if (e.code === 'Space') { e.preventDefault(); document.activeElement?.blur?.(); toggle() }
      else if (e.code === 'Enter' && until.current > performance.now()) { e.preventDefault(); document.activeElement?.blur?.(); flowRef.current.on() }
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [ready])

  const card = { background: '#1e293b', borderRadius: 12, border: `1px solid ${armed ? '#16a34a' : '#334155'}`, padding: 12, marginBottom: 10 }
  const head = (
    <div onClick={() => setOpen(o => !o)} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}>
      <span style={{ fontSize: 13, fontWeight: 700, color: '#e2e8f0' }}>
        🧲 Flow collector
        {st?.dry && <span style={{ marginLeft: 8, fontSize: 10, color: '#f59e0b' }}>DRY RUN</span>}
      </span>
      <span style={{ fontSize: 11, color: '#64748b' }}>
        {st ? <>{usd(st.pnl.usd)} · {st.pnl.pairs} pairs · {st.enabled.length} markets </> : null}{open ? '▼' : '▶'}
      </span>
    </div>
  )
  if (!token) {
    return <div style={card}>{head}{open && <div onClick={onUnlock} style={{ fontSize: 12, color: '#3b82f6', marginTop: 8, cursor: 'pointer' }}>Unlock trading to use it</div>}</div>
  }
  if (!st) return <div style={card}>{head}<div style={{ fontSize: 12, color: '#64748b', marginTop: 8 }}>{flow.msg || 'Connecting…'}</div></div>

  const banner = st.alert || (st.locked && `Locked: ${st.locked}`) || flow.msg
  return (
    <div style={card}>
      {head}
      {banner && (
        <div onClick={flow.clearMsg} style={{ background: '#7f1d1d', color: '#fff', fontWeight: 700, fontSize: 12, padding: '8px 10px', borderRadius: 8, marginTop: 8 }}>
          {banner}
          {st.locked && <span onClick={(e) => { e.stopPropagation(); flow.reset() }} style={{ marginLeft: 10, textDecoration: 'underline', cursor: 'pointer' }}>Reset</span>}
        </div>
      )}
      <button onClick={toggle} disabled={!!st.locked} style={{
        width: '100%', padding: '18px 0', marginTop: 10, border: 0, borderRadius: 10, fontSize: 17, fontWeight: 800,
        cursor: st.locked ? 'default' : 'pointer', background: st.locked ? '#7f1d1d' : armed ? '#16a34a' : '#0f172a',
        color: armed || st.locked ? '#fff' : '#94a3b8',
      }}>
        {st.locked ? 'LOCKED' : armed
          ? `ON — ${left.toFixed(0)}s · ${st.resting} order${st.resting === 1 ? '' : 's'} resting`
          : `OFF${st.resting ? ` · ${st.resting} STILL RESTING` : ''}${st.enabled.length ? '' : ' — tick MM on markets below'}`}
      </button>
      <div style={{ height: 4, background: '#0f172a', borderRadius: 2, marginTop: 4, overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${100 * left / st.settings.failsafe}%`, background: '#22c55e' }} />
      </div>
      {open && (
        <>
          <div style={{ fontSize: 10, color: '#475569', marginTop: 6 }}>
            Space = on/off · Enter = restart the timer (replaces orders) · last off: {st.last_off || '—'} · bought {st.pnl.yes} YES / {st.pnl.no} NO · fees ${st.pnl.fees.toFixed(2)}
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 12px', marginTop: 8 }}>
            {FIELDS.map(([k, label, step]) => (
              <label key={k} style={{ fontSize: 10, color: '#64748b' }}>{label}{' '}
                <input type="number" step={step} value={draft[k] ?? st.settings[k]}
                  onChange={(e) => setDraft(d => ({ ...d, [k]: e.target.value }))}
                  onBlur={() => { if (draft[k] != null && draft[k] !== '') flow.set({ [k]: draft[k] }); setDraft(d => { const n = { ...d }; delete n[k]; return n }) }}
                  onKeyDown={(e) => { if (e.key === 'Enter') e.target.blur() }}
                  style={{ width: 52, background: '#0f172a', border: '1px solid #334155', color: '#e2e8f0', borderRadius: 4, padding: '2px 4px', fontSize: 12 }} />
              </label>
            ))}
            {!st.dry && <span onClick={flow.test} style={{ fontSize: 11, color: '#3b82f6', cursor: 'pointer' }}>test order path</span>}
          </div>
          {st.markets.length > 0 && (
            <div style={{ marginTop: 8 }}>
              {st.markets.map(m => (
                <div key={m.ticker} style={{ display: 'flex', gap: 8, alignItems: 'baseline', fontSize: 11, padding: '4px 0', borderTop: '1px solid #0f172a' }}>
                  <span onClick={() => flow.toggle(m.ticker, m.label)} title="Stop quoting this market" style={{ color: '#64748b', cursor: 'pointer' }}>✕</span>
                  <span style={{ flex: 1, minWidth: 0, color: '#e2e8f0', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{m.label}</span>
                  <span style={{ color: '#94a3b8' }}>{m.bid ?? '–'}/{m.ask ?? '–'}</span>
                  <span style={{ color: m.net_per_pair >= 0.5 ? '#22c55e' : '#f59e0b' }}>{m.net_per_pair == null ? '' : `net ${m.net_per_pair.toFixed(1)}¢`}</span>
                  <span style={{ color: '#cbd5e1', minWidth: 90, textAlign: 'right' }}>
                    {m.orders.length ? m.orders.map(o => `${o.side === 'yes' ? 'Y' : 'N'} ${o.left}@${o.price}`).join(' · ')
                      : <span style={{ color: '#475569' }}>{m.quoting ? 'no orders' : 'too tight'}</span>}
                  </span>
                  <span style={{ minWidth: 48, textAlign: 'right', color: m.pos > 0 ? '#22c55e' : m.pos < 0 ? '#ef4444' : '#475569' }}>
                    {m.pos ? `${Math.abs(m.pos)} ${m.pos > 0 ? 'YES' : 'NO'}` : 'flat'}
                  </span>
                  <span style={{ minWidth: 52, textAlign: 'right' }}>{m.pnl.yes || m.pnl.no ? usd(m.pnl.usd) : ''}</span>
                </div>
              ))}
            </div>
          )}
          {(st.fills.length > 0 || st.notes.length > 0) && (
            <div style={{ marginTop: 8, fontSize: 10, color: '#64748b', maxHeight: 96, overflowY: 'auto' }}>
              {st.notes.map((n, i) => (
                <div key={i} style={{ color: n.level === 'bad' ? '#f87171' : '#94a3b8' }}>
                  {new Date(n.ts * 1000).toLocaleTimeString()} · {n.msg}
                </div>
              ))}
            </div>
          )}
          {Object.keys(st.errors).length > 0 && (
            <div style={{ marginTop: 6, fontSize: 10, color: '#f59e0b' }}>{Object.entries(st.errors).map(([k, v]) => `${k}: ${v}`).join(' · ')}</div>
          )}
        </>
      )}
    </div>
  )
}
