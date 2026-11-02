import { useState, useEffect, useCallback, useMemo } from 'react'
import { API } from './App.jsx'

// ── NFL Trade Forecasts ──────────────────────────────────────────────────────
// Crowd page: the players in Kalshi's "NFL Players Traded" market, no prices.
// Anyone with the link types a name/handle and a 0-100% chance each player is
// traded before the deadline. Backend: /api/trades/* (trades.py) stores every
// submit in Supabase (trade_forecasts) with the market snapshot for scoring.

const C = { bg: '#0f172a', panel: '#1e293b', line: '#334155', text: '#f1f5f9', muted: '#94a3b8', dim: '#64748b', blue: '#2563eb', green: '#22c55e', red: '#ef4444', amber: '#f59e0b' }
const panel = { background: C.panel, border: `1px solid ${C.line}`, borderRadius: 12, padding: 12, marginBottom: 12 }
const h2 = { fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em', color: C.muted, margin: '0 0 8px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }
const inp = { background: C.bg, color: C.text, border: `1px solid ${C.line}`, borderRadius: 8, padding: '8px 10px', fontSize: 14, width: '100%', boxSizing: 'border-box' }
const btn = (extra = {}) => ({
  padding: '10px 14px', borderRadius: 8, border: `1px solid ${C.line}`, background: C.bg, color: C.text,
  fontSize: 13, fontWeight: 600, cursor: 'pointer', ...extra,
})
const when = iso => iso ? new Date(iso).toLocaleString('en-US', { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York' }) + ' ET' : '–'
const QUICK = [0, 25, 50, 75, 100]
const NUDGE = [-10, -5, 5, 10]
const pctColor = p => p == null ? C.dim : p >= 60 ? C.green : p >= 25 ? C.amber : C.muted

export default function TradesTab() {
  const [meta, setMeta] = useState(null)          // { event, title, closes, passcode_required, players, settled }
  const [down, setDown] = useState('')
  const [user, setUser] = useState(() => localStorage.getItem('trade_forecaster') || '')
  const [passcode, setPasscode] = useState(() => localStorage.getItem('trade_passcode') || '')
  const [draft, setDraft] = useState({})          // ticker -> number | ''
  const [saved, setSaved] = useState({})          // ticker -> number (last stored)
  const [notes, setNotes] = useState({})          // ticker -> text (draft)
  const [savedNotes, setSavedNotes] = useState({})
  const [noteOpen, setNoteOpen] = useState({})    // ticker -> bool
  const [lastAt, setLastAt] = useState(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)            // { text, err }
  const [filter, setFilter] = useState('')
  const [showSettled, setShowSettled] = useState(false)

  useEffect(() => { localStorage.setItem('trade_forecaster', user) }, [user])
  useEffect(() => { localStorage.setItem('trade_passcode', passcode) }, [passcode])

  // players (names only)
  useEffect(() => {
    let dead = false
    ;(async () => {
      try {
        const r = await fetch(`${API}/api/trades/players`)
        const d = await r.json()
        if (!r.ok) throw new Error(d.detail || r.status)
        if (!dead) { setMeta(d); setDown('') }
      } catch (e) { if (!dead) setDown(String(e.message || e)) }
    })()
    return () => { dead = true }
  }, [])

  // my previous guesses, once I have a name
  const loadMine = useCallback(async (u) => {
    if (!u.trim()) { setSaved({}); setLastAt(null); return }
    try {
      const r = await fetch(`${API}/api/trades/mine?user=${encodeURIComponent(u.trim())}`)
      const d = await r.json()
      if (!r.ok) throw new Error(d.detail || r.status)
      setSaved(d.forecasts || {}); setSavedNotes(d.notes || {}); setLastAt(d.last_submitted || null)
      setDraft(prev => ({ ...d.forecasts, ...prev }))
      setNotes(prev => ({ ...(d.notes || {}), ...prev }))
      setNoteOpen(prev => ({ ...Object.fromEntries(Object.keys(d.notes || {}).map(k => [k, true])), ...prev }))
    } catch (e) { setMsg({ text: `Could not load your earlier guesses: ${e.message || e}`, err: true }) }
  }, [])
  useEffect(() => { const t = setTimeout(() => loadMine(user), 400); return () => clearTimeout(t) }, [user, loadMine])

  const players = meta?.players || []
  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase()
    return q ? players.filter(p => p.player.toLowerCase().includes(q)) : players
  }, [players, filter])

  const setPct = (ticker, v) => {
    if (v === '') { setDraft(d => ({ ...d, [ticker]: '' })); return }
    const n = Math.max(0, Math.min(100, Math.round(Number(v))))
    if (Number.isNaN(n)) return
    setDraft(d => ({ ...d, [ticker]: n }))
  }

  const nudge = (ticker, d) => setPct(ticker, (draft[ticker] === '' || draft[ticker] == null ? 0 : draft[ticker]) + d)
  const noteOf = t => (notes[t] || '').trim()

  // a guess counts as changed when its % or its note differs from what is stored
  const changed = useMemo(() => {
    const out = {}
    for (const [t, v] of Object.entries(draft)) {
      if (v === '' || v == null) continue
      if (saved[t] !== v || (notes[t] || '').trim() !== (savedNotes[t] || '').trim()) out[t] = v
    }
    return out
  }, [draft, saved, notes, savedNotes])
  const filled = Object.values(draft).filter(v => v !== '' && v != null).length

  const [fallback, setFallback] = useState(null)   // { href, csv, to } when the server has no mail service

  const submit = async () => {
    if (!user.trim()) { setMsg({ text: 'Enter a name or handle first so your guesses have an owner.', err: true }); return }
    const forecasts = Object.fromEntries(Object.entries(draft).filter(([, v]) => v !== '' && v != null))
    if (!Object.keys(forecasts).length) { setMsg({ text: 'Set a chance on at least one player.', err: true }); return }
    setBusy(true); setMsg(null); setFallback(null)
    try {
      const r = await fetch(`${API}/api/trades/submit`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user: user.trim(), passcode, forecasts, notes: Object.fromEntries(Object.keys(forecasts).map(t => [t, noteOf(t)])) }),
      })
      const d = await r.json()
      if (!r.ok) throw new Error(d.detail || r.status)
      setSaved(s => ({ ...s, ...forecasts })); setSavedNotes(n => ({ ...n, ...Object.fromEntries(Object.keys(forecasts).map(t => [t, noteOf(t)])) })); setLastAt(d.at)
      if (d.emailed) {
        setMsg({ text: `Sent ${d.rows} guess${d.rows === 1 ? '' : 'es'} from ${d.user} to ${d.to}. Revise and submit again any time before the deadline.`, err: false })
      } else {
        // no mail service on the server yet: open the mail app with the CSV in the body
        const href = `mailto:${d.to}?subject=${encodeURIComponent(d.subject)}&body=${encodeURIComponent(d.csv)}`
        setFallback({ href, csv: d.csv, to: d.to })
        setMsg({ text: `Your ${d.rows} guess${d.rows === 1 ? '' : 'es'} are ready. Tap "Open mail" to send them to ${d.to}.`, err: false })
        window.location.href = href
      }
    } catch (e) { setMsg({ text: String(e.message || e), err: true }) }
    finally { setBusy(false) }
  }

  if (down) return <div style={{ ...panel, color: C.red }}>Trade board unavailable: {down}</div>
  if (!meta) return <div style={{ ...panel, color: C.dim }}>Loading players…</div>

  return (
    <div>
      <div style={panel}>
        <div style={h2}><span>{meta.title}</span><span style={{ color: C.dim, textTransform: 'none', letterSpacing: 0 }}>deadline {when(meta.closes)}</span></div>
        <p style={{ fontSize: 13, color: C.muted, margin: '0 0 10px', lineHeight: 1.45 }}>
          For each player, what is the % chance they are <b style={{ color: C.text }}>traded before the NFL deadline</b>?
          Guess from your own read, not from odds. Tap Submit when you're done and your guesses are emailed to Jordan as a spreadsheet. You can come back and revise; the newest submission counts.
        </p>
        <label style={{ fontSize: 11, color: C.muted }}>Your name or handle</label>
        <input value={user} onChange={e => setUser(e.target.value)} placeholder="e.g. jordan, @handle" maxLength={40} style={{ ...inp, marginTop: 4 }} autoCapitalize="off" autoCorrect="off" />
        {meta.passcode_required && (
          <>
            <label style={{ fontSize: 11, color: C.muted, display: 'block', marginTop: 8 }}>Group passcode</label>
            <input value={passcode} onChange={e => setPasscode(e.target.value)} placeholder="the word you were sent" style={{ ...inp, marginTop: 4 }} autoCapitalize="off" autoCorrect="off" />
          </>
        )}
        {lastAt && <div style={{ fontSize: 11, color: C.dim, marginTop: 6 }}>Last submitted {when(lastAt)} · {Object.keys(saved).length} of {players.length} players</div>}
      </div>

      <div style={panel}>
        <div style={h2}>
          <span>Players ({players.length})</span>
          <span style={{ color: C.dim, textTransform: 'none', letterSpacing: 0 }}>{filled} filled</span>
        </div>
        <input value={filter} onChange={e => setFilter(e.target.value)} placeholder="Find a player…" style={{ ...inp, marginBottom: 10 }} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {shown.map(p => {
            const v = draft[p.ticker] ?? ''
            const dirty = v !== '' && saved[p.ticker] !== v
            const col = pctColor(v === '' ? null : v)
            return (
              <div key={p.ticker} style={{ padding: '12px 12px 10px', borderRadius: 12, background: C.bg, border: `1px solid ${dirty ? C.blue : C.line}` }}>
                <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10 }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 16, fontWeight: 700, lineHeight: 1.2 }}>{p.player}</div>
                    <div style={{ fontSize: 12, color: C.muted, marginTop: 3 }}>
                      {p.team ? <span style={{ color: C.text, fontWeight: 600 }}>{p.team}</span> : <span style={{ color: C.dim }}>team n/a</span>}
                      {p.pos && <span> · {p.pos}</span>}
                    </div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 2, flexShrink: 0 }}>
                    <input inputMode="numeric" pattern="[0-9]*" value={v} onChange={e => setPct(p.ticker, e.target.value.replace(/[^0-9]/g, ''))} placeholder="–"
                      style={{ ...inp, width: 58, padding: '8px 6px', textAlign: 'right', color: col, fontWeight: 800, fontSize: 18 }} />
                    <span style={{ fontSize: 14, color: C.dim }}>%</span>
                  </div>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 6, marginTop: 10 }}>
                  {QUICK.map(q => (
                    <button key={q} onClick={() => setPct(p.ticker, q)} style={{
                      padding: '9px 0', borderRadius: 8, fontSize: 13, fontWeight: 700, cursor: 'pointer',
                      border: `1px solid ${v === q ? C.blue : C.line}`, background: v === q ? C.blue : C.panel, color: v === q ? '#fff' : C.muted,
                    }}>{q}</button>
                  ))}
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, marginTop: 6 }}>
                  {NUDGE.map(d => (
                    <button key={d} onClick={() => nudge(p.ticker, d)} style={{
                      padding: '8px 0', borderRadius: 8, fontSize: 13, fontWeight: 700, cursor: 'pointer',
                      border: `1px solid ${C.line}`, background: C.bg, color: d < 0 ? '#fca5a5' : '#86efac',
                    }}>{d > 0 ? `+${d}` : d}</button>
                  ))}
                </div>
                <input type="range" min={0} max={100} step={1} value={v === '' ? 0 : v} onChange={e => setPct(p.ticker, e.target.value)} style={{ width: '100%', marginTop: 10, accentColor: col }} />
                {noteOpen[p.ticker] ? (
                  <textarea value={notes[p.ticker] || ''} onChange={e => setNotes(n => ({ ...n, [p.ticker]: e.target.value.slice(0, 500) }))} rows={2} placeholder="Why? (optional, saved with your guess)"
                    style={{ ...inp, marginTop: 8, fontSize: 13, resize: 'vertical', fontFamily: 'inherit' }} />
                ) : (
                  <button onClick={() => setNoteOpen(o => ({ ...o, [p.ticker]: true }))} style={{ marginTop: 8, background: 'none', border: 'none', color: C.dim, fontSize: 12, padding: 0, cursor: 'pointer' }}>+ add a note</button>
                )}
              </div>
            )
          })}
          {!shown.length && <div style={{ color: C.dim, fontSize: 13 }}>No player matches.</div>}
        </div>
      </div>

      {meta.settled?.length > 0 && (
        <div style={panel}>
          <div style={{ ...h2, cursor: 'pointer' }} onClick={() => setShowSettled(s => !s)}>
            <span>Already traded / settled ({meta.settled.length})</span><span>{showSettled ? '▾' : '▸'}</span>
          </div>
          {showSettled && meta.settled.map(p => (
            <div key={p.ticker} style={{ fontSize: 13, color: C.muted, padding: '4px 0' }}>{p.player} <span style={{ color: p.result === 'yes' ? C.green : C.dim }}>{p.result === 'yes' ? 'traded' : p.result || 'closed'}</span></div>
          ))}
        </div>
      )}

      <div style={{ position: 'sticky', bottom: 12, background: C.panel, border: `1px solid ${C.line}`, borderRadius: 12, padding: 10, boxShadow: '0 -6px 24px rgba(0,0,0,0.4)' }}>
        {msg && <div style={{ fontSize: 12, color: msg.err ? C.red : C.green, marginBottom: 8 }}>{msg.text}</div>}
        {fallback && (
          <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
            <a href={fallback.href} style={{ ...btn({ flex: 1, textAlign: 'center', textDecoration: 'none', background: C.green, border: 'none', color: '#052e16' }) }}>Open mail</a>
            <button onClick={() => navigator.clipboard?.writeText(fallback.csv).then(() => setMsg({ text: `CSV copied — paste it into an email to ${fallback.to}.`, err: false }))} style={btn({ flex: 1 })}>Copy CSV</button>
          </div>
        )}
        <button onClick={submit} disabled={busy || !filled} style={btn({ width: '100%', background: filled ? C.blue : C.bg, border: 'none', color: filled ? '#fff' : C.dim, opacity: busy ? 0.6 : 1 })}>
          {busy ? 'Sending…' : filled ? `Submit ${filled} guess${filled === 1 ? '' : 'es'}${Object.keys(changed).length ? ` (${Object.keys(changed).length} changed)` : ''}` : 'Set a few chances to submit'}
        </button>
      </div>
    </div>
  )
}
