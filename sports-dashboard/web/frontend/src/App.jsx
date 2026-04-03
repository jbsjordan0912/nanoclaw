import { useState, useCallback, useRef, useEffect } from 'react'

const API = window.location.hostname === 'localhost'
  ? ''  // proxied via vite dev server
  : 'https://mlb-simulator-api.onrender.com'

// ── Utility ──────────────────────────────────────────────────────────────────
const pct = (v) => v != null ? `${(v * 100).toFixed(1)}%` : '—'
const wpaColor = (v) => v > 0 ? '#22c55e' : v < 0 ? '#ef4444' : '#94a3b8'
const wpBarColor = (wp) => {
  if (wp >= 0.7) return '#22c55e'
  if (wp >= 0.55) return '#84cc16'
  if (wp >= 0.45) return '#f59e0b'
  if (wp >= 0.30) return '#f97316'
  return '#ef4444'
}

// ── Player search ─────────────────────────────────────────────────────────────
function PlayerSearch({ label, value, onSelect }) {
  const [query, setQuery] = useState(value?.name || '')
  const [results, setResults] = useState([])
  const [open, setOpen] = useState(false)
  const timer = useRef(null)

  const search = (q) => {
    setQuery(q)
    clearTimeout(timer.current)
    if (q.length < 2) { setResults([]); setOpen(false); return }
    timer.current = setTimeout(async () => {
      const res = await fetch(`${API}/api/players/search?q=${encodeURIComponent(q)}`)
      const data = await res.json()
      setResults(data)
      setOpen(true)
    }, 300)
  }

  const pick = (player) => {
    setQuery(player.name)
    setResults([])
    setOpen(false)
    onSelect(player)
  }

  return (
    <div style={{ position: 'relative', flex: 1 }}>
      <label style={{ display: 'block', fontSize: 11, color: '#94a3b8', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
        {label}
      </label>
      <input
        value={query}
        onChange={e => search(e.target.value)}
        onFocus={() => results.length && setOpen(true)}
        placeholder={`Search ${label.toLowerCase()}...`}
        style={{
          width: '100%', padding: '10px 12px', borderRadius: 8,
          background: '#1e293b', border: '1px solid #334155',
          color: '#f1f5f9', fontSize: 15, outline: 'none', boxSizing: 'border-box',
        }}
      />
      {open && results.length > 0 && (
        <div style={{
          position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 50,
          background: '#1e293b', border: '1px solid #334155', borderRadius: 8,
          marginTop: 4, overflow: 'hidden', boxShadow: '0 8px 24px rgba(0,0,0,0.4)'
        }}>
          {results.map(p => (
            <div key={p.id} onClick={() => pick(p)}
              style={{ padding: '10px 14px', cursor: 'pointer', fontSize: 14, borderBottom: '1px solid #0f172a' }}
              onMouseEnter={e => e.currentTarget.style.background = '#334155'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
            >
              {p.name}
              <span style={{ fontSize: 11, color: '#64748b', marginLeft: 8 }}>#{p.id}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Pitch card ────────────────────────────────────────────────────────────────
const OUTCOME_COLORS = {
  'Called Strike': '#ef4444', 'Swinging Strike': '#ef4444',
  'Ball': '#3b82f6', 'Hit Into Play': '#22c55e', 'Foul': '#f59e0b',
}

function PitchCard({ pitch, delay }) {
  const color = OUTCOME_COLORS[pitch.outcome] || '#94a3b8'
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 12,
      padding: '10px 14px', borderRadius: 8, background: '#1e293b',
      borderLeft: `3px solid ${color}`,
      animation: `fadeIn 0.3s ease ${delay}s both`,
    }}>
      <div style={{ minWidth: 24, fontSize: 13, color: '#64748b', fontVariantNumeric: 'tabular-nums' }}>#{pitch.num}</div>
      <div style={{ minWidth: 36, fontSize: 12, color: '#94a3b8', fontVariantNumeric: 'tabular-nums' }}>{pitch.count}</div>
      {pitch.pitch_type && <div style={{ minWidth: 36, fontSize: 13, fontWeight: 700, color: '#e2e8f0' }}>{pitch.pitch_type}</div>}
      {pitch.velocity && <div style={{ minWidth: 52, fontSize: 13, color: '#94a3b8' }}>{pitch.velocity} mph</div>}
      {pitch.location && <div style={{ flex: 1, fontSize: 12, color: '#64748b' }}>{pitch.location}</div>}
      <div style={{ fontSize: 12, fontWeight: 600, color }}>{pitch.outcome}</div>
    </div>
  )
}

// ── Result banner ─────────────────────────────────────────────────────────────
function ResultBanner({ result }) {
  return (
    <div style={{
      textAlign: 'center', padding: '20px 16px', borderRadius: 12,
      background: `${result.result_color}18`, border: `1px solid ${result.result_color}44`,
      animation: 'fadeIn 0.4s ease',
    }}>
      <div style={{ fontSize: 40, marginBottom: 8 }}>{result.result_emoji}</div>
      <div style={{ fontSize: 26, fontWeight: 800, color: result.result_color, letterSpacing: '-0.02em' }}>
        {result.result_label}
      </div>
      {result.narrative && <div style={{ fontSize: 14, color: '#94a3b8', marginTop: 6 }}>{result.narrative}</div>}
      {result.contact && (
        <div style={{ display: 'flex', justifyContent: 'center', gap: 20, marginTop: 12 }}>
          {result.contact.ev && (
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 20, fontWeight: 700, color: '#f1f5f9' }}>{result.contact.ev}</div>
              <div style={{ fontSize: 11, color: '#64748b', textTransform: 'uppercase' }}>Exit Velo</div>
            </div>
          )}
          {result.contact.la && (
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 20, fontWeight: 700, color: '#f1f5f9' }}>{result.contact.la}°</div>
              <div style={{ fontSize: 11, color: '#64748b', textTransform: 'uppercase' }}>Launch Angle</div>
            </div>
          )}
          {result.contact.dist && (
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 20, fontWeight: 700, color: '#f1f5f9' }}>{result.contact.dist}</div>
              <div style={{ fontSize: 11, color: '#64748b', textTransform: 'uppercase' }}>Distance ft</div>
            </div>
          )}
        </div>
      )}
      <div style={{ fontSize: 12, color: '#475569', marginTop: 10 }}>
        {result.pitch_count} pitch{result.pitch_count !== 1 ? 'es' : ''} · {result.matchup}
      </div>
    </div>
  )
}

// ── Strike Zone SVG ───────────────────────────────────────────────────────────
const PITCH_DOT_COLORS = {
  'Called Strike':   '#ef4444',
  'Swinging Strike': '#f97316',
  'Ball':            '#22c55e',
  'Foul':            '#f59e0b',
  'Hit Into Play':   '#3b82f6',
}

function StrikeZone({ pitches, shownCount }) {
  const W = 200, H = 230
  const cx = W / 2
  // plate_x in feet from center, plate_z feet from ground
  const toX = (px) => cx + (px ?? 0) * 55
  const toY = (pz) => H - 20 - ((pz ?? 2.5) - 0.5) * 50
  // Average strike zone: ±0.708 ft wide, 1.5–3.5 ft tall
  const zx = toX(-0.708), zy = toY(3.5)
  const zw = toX(0.708) - zx, zh = toY(1.5) - zy

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', maxWidth: 200, display: 'block', margin: '0 auto' }}>
      <rect width={W} height={H} fill="#0f172a" rx={8} />
      {/* Home plate */}
      <polygon
        points={`${cx-14},${H-6} ${cx+14},${H-6} ${cx+14},${H-18} ${cx},${H-8} ${cx-14},${H-18}`}
        fill="none" stroke="#334155" strokeWidth={1.5}
      />
      {/* Zone grid */}
      {[1/3, 2/3].map((t, i) => (
        <g key={i}>
          <line x1={zx+zw*t} y1={zy} x2={zx+zw*t} y2={zy+zh} stroke="#1e293b" strokeWidth={1} />
          <line x1={zx} y1={zy+zh*t} x2={zx+zw} y2={zy+zh*t} stroke="#1e293b" strokeWidth={1} />
        </g>
      ))}
      {/* Strike zone box */}
      <rect x={zx} y={zy} width={zw} height={zh} fill="none" stroke="#475569" strokeWidth={1.5} rx={2} />
      {/* Pitch dots — skip if no location data */}
      {pitches.slice(0, shownCount).filter(p => p.plate_x != null).map((p, i) => {
        const x = toX(p.plate_x), y = toY(p.plate_z)
        const color = PITCH_DOT_COLORS[p.outcome] ?? '#94a3b8'
        return (
          <g key={i} style={{ animation: 'fadeIn 0.2s ease' }}>
            <circle cx={x} cy={y} r={10} fill={color} fillOpacity={0.2} />
            <circle cx={x} cy={y} r={7} fill={color} />
            <text x={x} y={y+1} textAnchor="middle" dominantBaseline="middle"
              fontSize={8} fontWeight="bold" fill="#fff">{i + 1}</text>
          </g>
        )
      })}
    </svg>
  )
}

// ── At-Bat Simulator tab ──────────────────────────────────────────────────────
function AtBatTab() {
  const [batter, setBatter] = useState(null)
  const [pitcher, setPitcher] = useState(null)
  const [loading, setLoading] = useState(false)
  const [simData, setSimData] = useState(null)   // full result from API
  const [shownCount, setShownCount] = useState(0) // pitches revealed so far
  const [error, setError] = useState(null)
  const [history, setHistory] = useState([])
  const revealTimer = useRef(null)
  const canSim = batter && pitcher && !loading
  const pitches = simData?.pitches ?? []
  const isDone = simData && shownCount >= pitches.length

  const simulate = async () => {
    if (!canSim) return
    clearTimeout(revealTimer.current)
    setLoading(true); setSimData(null); setShownCount(0); setError(null)
    try {
      const res = await fetch(`${API}/api/simulate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ batter_id: batter.id, pitcher_id: pitcher.id }),
      })
      if (!res.ok) throw new Error(`Server error ${res.status}`)
      const data = await res.json()
      setSimData(data)
      setHistory(h => [data, ...h].slice(0, 10))
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  // Auto-advance one pitch every 1.2s
  useEffect(() => {
    if (!simData || shownCount >= pitches.length) return
    revealTimer.current = setTimeout(() => setShownCount(c => c + 1), 1200)
    return () => clearTimeout(revealTimer.current)
  }, [simData, shownCount, pitches.length])

  const skipToEnd = () => {
    clearTimeout(revealTimer.current)
    setShownCount(pitches.length)
  }

  // Live count from revealed pitches
  const liveCount = pitches.slice(0, shownCount).reduce((acc, p) => {
    const o = p.outcome
    if (o === 'Ball') return { ...acc, b: Math.min(acc.b + 1, 3) }
    if (o === 'Called Strike' || o === 'Swinging Strike') return { ...acc, s: Math.min(acc.s + 1, 2) }
    return acc
  }, { b: 0, s: 0 })

  return (
    <div>
      <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
        <PlayerSearch label="Batter" value={batter} onSelect={setBatter} />
        <PlayerSearch label="Pitcher" value={pitcher} onSelect={setPitcher} />
      </div>
      {batter && pitcher && (
        <div style={{ textAlign: 'center', fontSize: 13, color: '#94a3b8', marginBottom: 16 }}>
          {batter.name} <span style={{ color: '#475569' }}>vs</span> {pitcher.name}
        </div>
      )}
      <button onClick={simulate} disabled={!canSim} style={{
        width: '100%', padding: '14px 0', borderRadius: 10, border: 'none',
        background: canSim ? '#2563eb' : '#1e293b',
        color: canSim ? '#fff' : '#475569', fontSize: 16, fontWeight: 700,
        cursor: canSim ? 'pointer' : 'not-allowed', transition: 'background 0.2s', marginBottom: 20,
      }}>
        {loading ? '⏳ Simulating...' : '▶ Simulate At-Bat'}
      </button>
      {error && <div style={{ color: '#ef4444', fontSize: 14, textAlign: 'center', marginBottom: 16 }}>{error}</div>}

      {simData && (
        <div style={{ marginBottom: 24 }}>
          {/* Live count display */}
          {!isDone && (
            <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 16, marginBottom: 14 }}>
              <span style={{ fontSize: 28, fontWeight: 800, color: '#22c55e', fontVariantNumeric: 'tabular-nums' }}>{liveCount.b}</span>
              <span style={{ fontSize: 20, color: '#334155' }}>–</span>
              <span style={{ fontSize: 28, fontWeight: 800, color: '#ef4444', fontVariantNumeric: 'tabular-nums' }}>{liveCount.s}</span>
              <span style={{ fontSize: 12, color: '#475569', marginLeft: 4 }}>B – S</span>
            </div>
          )}

          {/* Strike zone — always show once sim starts; dots only appear when plate_x is present */}
          {pitches.length > 0 && (
            <div style={{ marginBottom: 16 }}>
              <StrikeZone pitches={pitches} shownCount={shownCount} />
            </div>
          )}

          {/* Skip button while revealing */}
          {!isDone && (
            <button onClick={skipToEnd} style={{
              width: '100%', padding: '8px 0', borderRadius: 8, border: '1px solid #334155',
              background: 'transparent', color: '#64748b', fontSize: 13,
              cursor: 'pointer', marginBottom: 14,
            }}>⏩ Skip to result</button>
          )}

          {/* Result banner — only after all pitches shown */}
          {isDone && (
            <>
              <ResultBanner result={simData} />
              <button onClick={simulate} style={{
                width: '100%', padding: '12px 0', borderRadius: 10, border: '1px solid #334155',
                background: 'transparent', color: '#94a3b8', fontSize: 14, fontWeight: 600,
                cursor: 'pointer', marginTop: 16,
              }}>🔄 Simulate Again</button>
            </>
          )}

          {/* Pitch log */}
          {shownCount > 0 && (
            <div style={{ marginTop: 16 }}>
              <div style={{ fontSize: 11, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>
                Pitch Sequence
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {pitches.slice(0, shownCount).map((p, i) => <PitchCard key={i} pitch={p} delay={0} />)}
              </div>
            </div>
          )}
        </div>
      )}
      {history.length > 1 && (
        <div>
          <div style={{ fontSize: 11, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10 }}>
            Recent Results
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {history.slice(1).map((r, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', borderRadius: 8, background: '#1e293b' }}>
                <span style={{ fontSize: 16 }}>{r.result_emoji}</span>
                <span style={{ fontSize: 14, fontWeight: 600, color: r.result_color }}>{r.result_label}</span>
                <span style={{ fontSize: 12, color: '#475569', marginLeft: 'auto' }}>{r.pitch_count}p</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Game picker ───────────────────────────────────────────────────────────────
function GamePicker({ selectedPk, onSelect }) {
  const [games, setGames] = useState([])
  const [open, setOpen] = useState(false)

  useEffect(() => {
    fetch(`${API}/api/games/today`)
      .then(r => r.json())
      .then(data => setGames(data.filter(g => g.status !== 'Postponed')))
      .catch(() => {})
  }, [])

  const selected = games.find(g => g.game_pk === selectedPk)

  const statusBadge = (g) => {
    if (g.status === 'Live') return { label: `${g.inning_half?.slice(0,3) || ''} ${g.inning || ''}`, color: '#22c55e' }
    return { label: 'Preview', color: '#64748b' }
  }

  return (
    <div style={{ position: 'relative', marginBottom: 14 }}>
      <label style={labelStyle}>Select Game</label>
      <button onClick={() => setOpen(o => !o)} style={{
        width: '100%', padding: '10px 14px', borderRadius: 8,
        background: '#0f172a', border: '1px solid #334155',
        color: selected ? '#f1f5f9' : '#475569', fontSize: 14, fontWeight: 600,
        cursor: 'pointer', textAlign: 'left', display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      }}>
        <span>
          {selected
            ? `${selected.away_team} @ ${selected.home_team}`
            : games.length ? 'Choose a game...' : 'Loading games...'}
        </span>
        {selected && (() => { const b = statusBadge(selected); return <span style={{ fontSize: 12, color: b.color, fontWeight: 700 }}>{b.label}</span> })()}
      </button>
      {open && games.length > 0 && (
        <div style={{
          position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 50, marginTop: 4,
          background: '#1e293b', border: '1px solid #334155', borderRadius: 8,
          boxShadow: '0 8px 24px rgba(0,0,0,0.5)', overflow: 'hidden',
        }}>
          {games.map(g => {
            const b = statusBadge(g)
            return (
              <div key={g.game_pk} onClick={() => { onSelect(g.game_pk); setOpen(false) }}
                style={{ padding: '11px 14px', cursor: 'pointer', borderBottom: '1px solid #0f172a',
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  background: g.game_pk === selectedPk ? '#1e3a5f' : 'transparent' }}
                onMouseEnter={e => e.currentTarget.style.background = '#334155'}
                onMouseLeave={e => e.currentTarget.style.background = g.game_pk === selectedPk ? '#1e3a5f' : 'transparent'}>
                <div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: '#f1f5f9' }}>
                    {g.away_team} @ {g.home_team}
                  </div>
                  {g.status === 'Live' && (
                    <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>
                      {g.away_score} – {g.home_score}
                    </div>
                  )}
                </div>
                <span style={{ fontSize: 12, fontWeight: 700, color: b.color }}>{b.label}</span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── WP / Kalshi Dashboard tab ─────────────────────────────────────────────────
function BaseToggle({ value, options, onChange }) {
  return (
    <div style={{ display: 'flex', borderRadius: 8, overflow: 'hidden', border: '1px solid #334155' }}>
      {options.map(opt => (
        <button key={opt.value} onClick={() => onChange(opt.value)} style={{
          flex: 1, padding: '8px 0', border: 'none', fontSize: 13, fontWeight: 600,
          background: value === opt.value ? '#2563eb' : '#1e293b',
          color: value === opt.value ? '#fff' : '#64748b',
          cursor: 'pointer', transition: 'background 0.15s',
        }}>{opt.label}</button>
      ))}
    </div>
  )
}

function BaseDiamond({ on1b, on2b, on3b, onChange }) {
  const Base = ({ id, label, active, style }) => (
    <div onClick={() => onChange(id)} style={{
      width: 28, height: 28, borderRadius: 4, border: `2px solid ${active ? '#f59e0b' : '#334155'}`,
      background: active ? '#f59e0b22' : 'transparent',
      cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: 10, color: active ? '#f59e0b' : '#475569', fontWeight: 700,
      transform: 'rotate(45deg)', ...style,
    }}>
      <span style={{ transform: 'rotate(-45deg)' }}>{label}</span>
    </div>
  )
  return (
    <div style={{ position: 'relative', width: 90, height: 90, margin: '0 auto' }}>
      <div style={{ position: 'absolute', top: 0, left: '50%', transform: 'translateX(-50%)' }}>
        <Base id="on_2b" label="2B" active={on2b} onChange={() => onChange('on_2b')} />
      </div>
      <div style={{ position: 'absolute', top: '50%', left: 0, transform: 'translateY(-50%)' }}>
        <Base id="on_3b" label="3B" active={on3b} onChange={() => onChange('on_3b')} />
      </div>
      <div style={{ position: 'absolute', top: '50%', right: 0, transform: 'translateY(-50%)' }}>
        <Base id="on_1b" label="1B" active={on1b} onChange={() => onChange('on_1b')} />
      </div>
      <div style={{ position: 'absolute', bottom: 0, left: '50%', transform: 'translateX(-50%)', width: 20, height: 20, borderRadius: 4, background: '#334155', transform: 'translateX(-50%) rotate(45deg)' }} />
    </div>
  )
}

function WPBar({ wp }) {
  const color = wpBarColor(wp)
  return (
    <div style={{ marginBottom: 4 }}>
      <div style={{ height: 10, borderRadius: 5, background: '#1e293b', overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${wp * 100}%`, background: color, borderRadius: 5, transition: 'width 0.4s ease' }} />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Spring Training Odds Tab
// ---------------------------------------------------------------------------
function SpringOddsTab() {
  const [games, setGames]       = useState([])
  const [loading, setLoading]   = useState(true)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [error, setError]       = useState(null)

  const load = useCallback(async () => {
    try {
      const r = await fetch('/api/kalshi/prices/all')
      const d = await r.json()
      setGames(d.games || [])
      setLastUpdated(new Date())
      setError(null)
    } catch (e) {
      setError('Failed to load Kalshi prices')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const id = setInterval(load, 30_000)
    return () => clearInterval(id)
  }, [load])

  const fmtPct = v => v != null ? `${Math.round(v * 100)}¢` : '—'
  const fmtVol = v => v >= 1000 ? `${(v / 1000).toFixed(1)}k` : String(v)

  const priceColor = p => {
    if (p == null) return '#64748b'
    if (p >= 0.6)  return '#22c55e'
    if (p >= 0.45) return '#f59e0b'
    return '#ef4444'
  }

  return (
    <div style={{ animation: 'fadeIn 0.3s ease' }}>
      {/* Header row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: '#94a3b8' }}>
          🌸 SPRING TRAINING ODDS
          {games.length > 0 && <span style={{ color: '#475569', fontWeight: 400, marginLeft: 6 }}>({games.length} games)</span>}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {lastUpdated && (
            <span style={{ fontSize: 11, color: '#475569' }}>
              Updated {lastUpdated.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
            </span>
          )}
          <button onClick={load} style={{
            background: '#1e293b', border: '1px solid #334155', color: '#94a3b8',
            borderRadius: 6, padding: '4px 10px', fontSize: 12, cursor: 'pointer',
          }}>↻ Refresh</button>
        </div>
      </div>

      {loading && (
        <div style={{ textAlign: 'center', color: '#475569', padding: '40px 0', fontSize: 14 }}>Loading Kalshi markets…</div>
      )}
      {error && (
        <div style={{ background: '#1e293b', border: '1px solid #ef4444', borderRadius: 10, padding: 14, color: '#ef4444', fontSize: 13 }}>{error}</div>
      )}
      {!loading && !error && games.length === 0 && (
        <div style={{ textAlign: 'center', color: '#475569', padding: '40px 0', fontSize: 14 }}>No open Kalshi MLB markets found.</div>
      )}

      {/* Game cards */}
      {games.map(g => (
        <div key={g.game_key} style={{
          background: '#1e293b', borderRadius: 12, padding: 14, marginBottom: 10,
          border: '1px solid #334155',
        }}>
          {/* Game title */}
          <div style={{ fontSize: 12, color: '#64748b', marginBottom: 10, letterSpacing: '0.02em' }}>
            {(g.title || g.game_key).toUpperCase()}
          </div>

          {/* Markets */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {g.markets.map(m => (
              <div key={m.ticker} style={{
                background: '#0f172a', borderRadius: 8, padding: '10px 12px',
                border: '1px solid #1e293b', display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              }}>
                {/* Left: ticker label */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: '#e2e8f0', marginBottom: 2 }}>
                    {(m.ticker || '').split('-').pop()}
                  </div>
                  <div style={{ fontSize: 10, color: '#475569' }}>
                    Vol: {fmtVol(m.volume)}
                  </div>
                </div>

                {/* Middle: bid / ask */}
                <div style={{ textAlign: 'center', flex: 1 }}>
                  <div style={{ fontSize: 11, color: '#475569', marginBottom: 2 }}>BID / ASK</div>
                  <div style={{ fontSize: 13, color: '#94a3b8' }}>
                    {fmtPct(m.yes_bid)} / {fmtPct(m.yes_ask)}
                  </div>
                </div>

                {/* Right: best price */}
                <div style={{ textAlign: 'right', flex: 1 }}>
                  <div style={{ fontSize: 11, color: '#475569', marginBottom: 2 }}>PRICE</div>
                  <div style={{ fontSize: 22, fontWeight: 800, color: priceColor(m.price), lineHeight: 1 }}>
                    {m.price != null ? `${Math.round(m.price * 100)}¢` : '—'}
                  </div>
                  {m.last_price > 0 && (
                    <div style={{ fontSize: 10, color: '#475569', marginTop: 2 }}>
                      last {fmtPct(m.last_price)}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* Total volume */}
          <div style={{ marginTop: 8, fontSize: 11, color: '#334155', textAlign: 'right' }}>
            Total volume: {fmtVol(g.total_volume)}
          </div>
        </div>
      ))}

      <div style={{ fontSize: 11, color: '#334155', textAlign: 'center', paddingTop: 8 }}>
        Auto-refreshes every 30s · Kalshi spring training markets
      </div>
    </div>
  )
}

// Derive WebSocket base URL from current host
function getKalshiWsUrl({ ticker, gameKey } = {}) {
  const isLocal = window.location.hostname === 'localhost'
  const base = isLocal
    ? 'ws://localhost:8000'
    : 'wss://mlb-simulator-api.onrender.com'
  if (gameKey) return `${base}/api/ws/kalshi?game_key=${encodeURIComponent(gameKey)}`
  return `${base}/api/ws/kalshi?ticker=${encodeURIComponent(ticker)}`
}

function WPDashboard() {
  const [mode, setMode] = useState('manual')          // 'auto' | 'manual'
  const [selectedGame, setSelectedGame] = useState(null)
  const [gameInfo, setGameInfo] = useState(null)       // full game state from MLB API
  const [liveStatus, setLiveStatus] = useState(null)   // e.g. "Synced 0s ago"
  const [state, setState] = useState({
    inning: 7, topbot: 'Bot', outs: 1,
    balls: 0, strikes: 0,
    on_1b: false, on_2b: false, on_3b: false,
    away_score: 0, home_score: 0, season: 2025,
  })
  const [lineupIds, setLineupIds] = useState(null)
  const [pitcherId, setPitcherId] = useState(null)
  const [kalshiInput, setKalshiInput] = useState('')
  const [kalshiLive, setKalshiLive] = useState(false)
  const kalshiPricesRef = useRef({}) // { "TB": {bid, ask, last}, "STL": {bid, ask, last} }
  const [wpData, setWpData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const pollRef = useRef(null)
  const lastSyncRef = useRef(null)
  const kalshiWsRef = useRef(null)
  const kalshiOverrideRef = useRef(null) // holds live price (0-1) for calculate()

  const toggleBase = (base) => setState(s => ({ ...s, [base]: !s[base] }))
  const update = (key, val) => setState(s => ({ ...s, [key]: val }))

  // Fetch live game state from MLB API and sync into local state
  const syncGameState = useCallback(async (gamePk) => {
    try {
      const res = await fetch(`${API}/api/games/${gamePk}/state`)
      if (!res.ok) return
      const g = await res.json()
      setGameInfo(g)

      // Stop polling if game is over
      if (g.status === 'Final') {
        if (pollRef.current) clearInterval(pollRef.current)
        setLiveStatus('Final — game over')
        return
      }

      // Game not started yet (Preview)
      if (g.status === 'Preview') {
        setLiveStatus('Not started yet')
        return
      }

      setState({
        inning: g.inning || 1,
        topbot: g.topbot || 'Top',
        outs: g.outs || 0,
        balls: g.balls || 0,
        strikes: g.strikes || 0,
        on_1b: g.on_1b || false,
        on_2b: g.on_2b || false,
        on_3b: g.on_3b || false,
        away_score: g.topbot === 'Top' ? g.bat_score : g.fld_score,
        home_score: g.topbot === 'Bot' ? g.bat_score : g.fld_score,
        season: 2025,
      })
      if (g.batting_lineup?.length) setLineupIds(g.batting_lineup.map(p => p.id))
      if (g.pitcher_id) setPitcherId(g.pitcher_id)
      lastSyncRef.current = Date.now()
      setLiveStatus('Just synced')
    } catch {}
  }, [])

  // Start/stop polling when mode or game changes
  useEffect(() => {
    if (pollRef.current) clearInterval(pollRef.current)
    if (mode === 'auto' && selectedGame) {
      syncGameState(selectedGame)
      pollRef.current = setInterval(() => syncGameState(selectedGame), 15000)
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [mode, selectedGame, syncGameState])

  // Update "synced Xs ago" every 5s
  useEffect(() => {
    if (mode !== 'auto') return
    const t = setInterval(() => {
      if (lastSyncRef.current) {
        const s = Math.round((Date.now() - lastSyncRef.current) / 1000)
        setLiveStatus(`${s}s ago`)
      }
    }, 5000)
    return () => clearInterval(t)
  }, [mode])

  // Connect Kalshi WebSocket — subscribes to BOTH sides of the game
  const connectKalshiWs = useCallback(async (gamePk) => {
    // Tear down any existing connection
    if (kalshiWsRef.current) {
      kalshiWsRef.current.close()
      kalshiWsRef.current = null
    }
    kalshiOverrideRef.current = null
    kalshiPricesRef.current = {}
    setKalshiLive(false)
    if (!gamePk) return

    try {
      // Resolve game → Kalshi game key
      const gr = await fetch(`${API}/api/games/${gamePk}/state`)
      if (!gr.ok) return
      const g = await gr.json()
      const kr = await fetch(`${API}/api/kalshi/price?home_team=${encodeURIComponent(g.home_team)}&away_team=${encodeURIComponent(g.away_team)}`)
      const kd = await kr.json()
      if (!kd.ticker) return

      // Extract game key (ticker without the team suffix)
      const gameKey = kd.ticker.replace(/-[A-Z]{2,4}$/, '')

      // Seed from REST — use the primary ticker's price
      const primaryTeam = kd.ticker.split('-').pop()
      kalshiPricesRef.current[primaryTeam] = { bid: kd.yes_bid, ask: kd.yes_ask, last: kd.last_price }
      kalshiPricesRef.current._homeTeam = g.home_team
      kalshiPricesRef.current._awayTeam = g.away_team

      // Set initial display from REST seed
      const mid = (kd.yes_bid > 0 && kd.yes_ask > 0)
        ? (kd.yes_bid + kd.yes_ask) / 2
        : kd.last_price || kd.yes_bid
      if (mid > 0) {
        kalshiOverrideRef.current = mid
        setKalshiInput(String(Math.round(mid * 100)))
      }

      // Connect WS to both tickers
      const ws = new WebSocket(getKalshiWsUrl({ gameKey }))
      kalshiWsRef.current = ws

      ws.onmessage = (e) => {
        const data = JSON.parse(e.data)
        if (data.status === 'connected') {
          setKalshiLive(true)
        } else if (data.type === 'price') {
          const team = data.team
          kalshiPricesRef.current[team] = {
            bid: data.yes_bid,
            ask: data.yes_ask,
            last: data.last_price,
          }
          // Update display with this team's midpoint
          const mid = (data.yes_bid > 0 && data.yes_ask > 0)
            ? (data.yes_bid + data.yes_ask) / 2
            : data.last_price || data.yes_bid
          if (mid > 0) {
            kalshiOverrideRef.current = mid
            setKalshiInput(String(Math.round(mid * 100)))
          }
          setKalshiLive(true)
        } else if (data.error) {
          console.warn('Kalshi WS error:', data.error)
          setKalshiLive(false)
        }
      }
      ws.onclose = () => { setKalshiLive(false) }
      ws.onerror = () => { setKalshiLive(false) }
    } catch (err) {
      console.error('Kalshi WS setup failed:', err)
    }
  }, [])

  // Update Kalshi display based on current batting team
  const updateKalshiDisplay = useCallback(() => {
    const prices = kalshiPricesRef.current
    const homeAbbr = prices._homeAbbr
    const awayAbbr = prices._awayAbbr
    if (!homeAbbr && !awayAbbr) return

    // Show home team price by default (edge calculation uses batting team,
    // but display shows the home team's win probability)
    const homeP = prices[homeAbbr]
    const awayP = prices[awayAbbr]
    if (homeP) {
      const mid = (homeP.bid > 0 && homeP.ask > 0)
        ? (homeP.bid + homeP.ask) / 2
        : homeP.last || homeP.bid
      kalshiOverrideRef.current = mid
      setKalshiInput(String(Math.round(mid * 100)))
    }
  }, [])

  // Pure WS — seed once from REST on connect, then WS handles all updates
  useEffect(() => {
    if (mode === 'auto' && selectedGame) {
      connectKalshiWs(selectedGame)
    } else {
      if (kalshiWsRef.current) { kalshiWsRef.current.close(); kalshiWsRef.current = null }
      kalshiOverrideRef.current = null
      setKalshiLive(false)
    }
    return () => {
      if (kalshiWsRef.current) { kalshiWsRef.current.close(); kalshiWsRef.current = null }
    }
  }, [mode, selectedGame, connectKalshiWs])

  const calculate = async (kalshiOverride = null) => {
    setLoading(true); setError(null)
    try {
      const isTop = state.topbot === 'Top'
      // Pick the batting team's Kalshi price from live WS data
      let kPrice = null
      const prices = kalshiPricesRef.current
      const battingAbbr = isTop ? prices._awayAbbr : prices._homeAbbr
      const battingP = prices[battingAbbr]
      if (battingP) {
        kPrice = (battingP.bid > 0 && battingP.ask > 0)
          ? (battingP.bid + battingP.ask) / 2
          : battingP.last || battingP.bid
      }
      // Fall back to manual input if no live data
      if (kPrice == null && kalshiInput) {
        kPrice = parseFloat(kalshiInput) / 100
      }
      // Explicit primitives only — safe to serialize
      const body = {
        inning:           Number(state.inning),
        topbot:           String(state.topbot),
        outs:             Number(state.outs),
        balls:            Number(state.balls),
        strikes:          Number(state.strikes),
        on_1b:            Boolean(state.on_1b),
        on_2b:            Boolean(state.on_2b),
        on_3b:            Boolean(state.on_3b),
        season:           Number(state.season),
        bat_score:        isTop ? Number(state.away_score) : Number(state.home_score),
        fld_score:        isTop ? Number(state.home_score) : Number(state.away_score),
        batting_lineup:   Array.isArray(lineupIds) ? lineupIds.map(Number) : null,
        fielding_pitcher: pitcherId != null ? Number(pitcherId) : null,
        kalshi_price:     kPrice != null ? Number(kPrice) : null,
      }
      let bodyStr
      try {
        bodyStr = JSON.stringify(body)
      } catch (serr) {
        console.error('Serialize failed:', serr)
        Object.entries(body).forEach(([k, v]) => console.log(k, typeof v, v))
        throw serr
      }
      const res = await fetch(`${API}/api/wp`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: bodyStr,
      })
      if (!res.ok) throw new Error(`Server error ${res.status}`)
      setWpData(await res.json())
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  // Auto-recalculate when state changes
  useEffect(() => { calculate() }, [state])

  const wp = wpData?.adjusted_wp ?? wpData?.base_wp
  const edge = wpData?.edge
  const edgeColor = edge > 0.04 ? '#22c55e' : edge < -0.04 ? '#ef4444' : '#f59e0b'

  return (
    <div>
      {/* Auto / Manual mode toggle */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 16, alignItems: 'center' }}>
        <div style={{ flex: 1 }}>
          <BaseToggle
            value={mode}
            options={[{ value: 'auto', label: '📺 Auto' }, { value: 'manual', label: '✏️ Manual' }]}
            onChange={v => { setMode(v); if (v === 'manual') setLiveStatus(null) }}
          />
        </div>
        {mode === 'auto' && liveStatus && (
          <div style={{ fontSize: 11, color: '#22c55e', minWidth: 80, textAlign: 'right' }}>
            🟢 {liveStatus}
          </div>
        )}
      </div>

      {/* Game picker — auto mode only */}
      {mode === 'auto' && (
        <div style={{ background: '#1e293b', borderRadius: 12, padding: 16, marginBottom: 16 }}>
          <GamePicker selectedPk={selectedGame} onSelect={setSelectedGame} />
          {gameInfo && (
            <div style={{ fontSize: 13, color: '#94a3b8', marginTop: 4 }}>
              <span style={{ color: '#f1f5f9', fontWeight: 700 }}>{gameInfo.batting_team}</span>
              <span style={{ color: '#475569' }}> batting · </span>
              <span style={{ color: '#f1f5f9', fontWeight: 600 }}>{gameInfo.pitcher_name || '—'}</span>
              <span style={{ color: '#475569' }}> pitching</span>
            </div>
          )}
          {mode === 'auto' && !selectedGame && (
            <div style={{ fontSize: 13, color: '#475569', marginTop: 4 }}>Select a live game above to start auto-tracking</div>
          )}
        </div>
      )}

      {/* Game state inputs */}
      <div style={{ background: '#1e293b', borderRadius: 12, padding: 16, marginBottom: 16, opacity: mode === 'auto' ? 0.7 : 1 }}>

        {/* Inning + Top/Bot + Outs */}
        <div style={{ display: 'flex', gap: 10, marginBottom: 12, alignItems: 'flex-end' }}>
          <div>
            <label style={labelStyle}>Inning</label>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <button onClick={() => update('inning', Math.max(1, state.inning - 1))} style={nudgeBtn}>−</button>
              <span style={{ fontSize: 18, fontWeight: 800, color: '#f1f5f9', minWidth: 22, textAlign: 'center' }}>{state.inning}</span>
              <button onClick={() => update('inning', Math.min(12, state.inning + 1))} style={nudgeBtn}>+</button>
            </div>
          </div>
          <div style={{ flex: 1 }}>
            <label style={labelStyle}>Half</label>
            <BaseToggle value={state.topbot} options={[{ value: 'Top', label: '▲' }, { value: 'Bot', label: '▼' }]} onChange={v => update('topbot', v)} />
          </div>
          <div style={{ flex: 1 }}>
            <label style={labelStyle}>Outs</label>
            <BaseToggle value={state.outs} options={[{ value: 0, label: '0' }, { value: 1, label: '1' }, { value: 2, label: '2' }]} onChange={v => update('outs', v)} />
          </div>
        </div>

        {/* Balls + Strikes */}
        <div style={{ display: 'flex', gap: 10, marginBottom: 12 }}>
          <div style={{ flex: 1 }}>
            <label style={labelStyle}>Balls</label>
            <div style={{ display: 'flex', gap: 6 }}>
              {[0,1,2,3].map(b => (
                <button key={b} onClick={() => update('balls', b)} style={{
                  flex: 1, padding: '7px 0', borderRadius: 6, border: 'none', fontSize: 13, fontWeight: 700,
                  background: state.balls === b ? '#22c55e' : '#0f172a',
                  color: state.balls === b ? '#fff' : '#475569', cursor: 'pointer',
                }}>{b}</button>
              ))}
            </div>
          </div>
          <div style={{ flex: 1 }}>
            <label style={labelStyle}>Strikes</label>
            <div style={{ display: 'flex', gap: 6 }}>
              {[0,1,2].map(s => (
                <button key={s} onClick={() => update('strikes', s)} style={{
                  flex: 1, padding: '7px 0', borderRadius: 6, border: 'none', fontSize: 13, fontWeight: 700,
                  background: state.strikes === s ? '#ef4444' : '#0f172a',
                  color: state.strikes === s ? '#fff' : '#475569', cursor: 'pointer',
                }}>{s}</button>
              ))}
            </div>
          </div>
        </div>

        {mode === 'auto' && (
          <div style={{ fontSize: 11, color: '#475569', marginBottom: 10, textAlign: 'center' }}>
            Auto mode — tap to override any value
          </div>
        )}

        {/* Score + Bases */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <div style={{ flex: 1 }}>
            <div style={{ display: 'flex', gap: 12 }}>
              <div style={{ flex: 1 }}>
                <label style={labelStyle}>Away</label>
                <div style={{ textAlign: 'center' }}>
                  <button onClick={() => update('away_score', Math.max(0, state.away_score - 1))} style={nudgeBtn}>−</button>
                  <span style={{ fontSize: 22, fontWeight: 800, color: '#f1f5f9', display: 'block', lineHeight: '32px' }}>{state.away_score}</span>
                  <button onClick={() => update('away_score', state.away_score + 1)} style={nudgeBtn}>+</button>
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', paddingTop: 18 }}>
                <span style={{ color: '#334155', fontSize: 18, fontWeight: 700 }}>@</span>
              </div>
              <div style={{ flex: 1 }}>
                <label style={labelStyle}>Home</label>
                <div style={{ textAlign: 'center' }}>
                  <button onClick={() => update('home_score', Math.max(0, state.home_score - 1))} style={nudgeBtn}>−</button>
                  <span style={{ fontSize: 22, fontWeight: 800, color: '#f1f5f9', display: 'block', lineHeight: '32px' }}>{state.home_score}</span>
                  <button onClick={() => update('home_score', state.home_score + 1)} style={nudgeBtn}>+</button>
                </div>
              </div>
            </div>
          </div>
          <div style={{ flex: 1 }}>
            <label style={{ ...labelStyle, textAlign: 'center', display: 'block' }}>Bases (tap)</label>
            <BaseDiamond on1b={state.on_1b} on2b={state.on_2b} on3b={state.on_3b} onChange={toggleBase} />
          </div>
        </div>
      </div>

      {/* Kalshi price input */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 16, alignItems: 'flex-end' }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
            <label style={{ ...labelStyle, marginBottom: 0 }}>Kalshi Price (yes %)</label>
            {kalshiLive
              ? <span style={{ fontSize: 10, color: '#22c55e', fontWeight: 700, letterSpacing: '0.05em' }}>● LIVE</span>
              : mode === 'auto' && selectedGame
                ? <span style={{ fontSize: 10, color: '#475569', fontWeight: 600 }}>connecting…</span>
                : null
            }
          </div>
          <input
            value={kalshiInput}
            onChange={e => { setKalshiInput(e.target.value); kalshiOverrideRef.current = null }}
            onBlur={calculate}
            placeholder="e.g. 48"
            type="number"
            style={{
              width: '100%', padding: '10px 12px', borderRadius: 8,
              background: '#1e293b',
              border: `1px solid ${kalshiLive ? '#22c55e55' : '#334155'}`,
              color: '#f1f5f9', fontSize: 15, outline: 'none', boxSizing: 'border-box',
            }}
          />
        </div>
        {edge != null && (
          <div style={{ textAlign: 'center', minWidth: 80 }}>
            <div style={{ fontSize: 11, color: '#94a3b8', textTransform: 'uppercase', marginBottom: 4 }}>Edge</div>
            <div style={{ fontSize: 22, fontWeight: 800, color: edgeColor }}>
              {edge > 0 ? '+' : ''}{(edge * 100).toFixed(1)}%
            </div>
          </div>
        )}
      </div>

      {error && <div style={{ color: '#ef4444', fontSize: 14, textAlign: 'center', marginBottom: 16 }}>{error}</div>}

      {/* WP Display */}
      {wp != null && (
        <div style={{ background: '#1e293b', borderRadius: 12, padding: 16, marginBottom: 16, animation: 'fadeIn 0.3s ease' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
            <div style={{ fontSize: 13, color: '#94a3b8' }}>Win Probability (batting team)</div>
            {loading && <div style={{ fontSize: 12, color: '#475569' }}>updating...</div>}
          </div>
          <div style={{ fontSize: 48, fontWeight: 900, color: wpBarColor(wp), letterSpacing: '-0.03em', lineHeight: 1, marginBottom: 10 }}>
            {pct(wp)}
          </div>
          <WPBar wp={wp} />
          {wpData.base_wp !== wpData.adjusted_wp && (
            <div style={{ fontSize: 12, color: '#475569', marginTop: 6 }}>
              Base: {pct(wpData.base_wp)} → Team-adjusted: {pct(wpData.adjusted_wp)}
            </div>
          )}

          {/* Factors */}
          {wpData.factors && (
            <div style={{ marginTop: 14, borderTop: '1px solid #0f172a', paddingTop: 12 }}>
              <div style={{ fontSize: 11, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>Adjustments</div>
              {[
                { label: 'Offense', detail: `wRC+ ${wpData.factors.offense.wrc_plus}`, val: wpData.factors.offense.adjustment },
                { label: 'Pitching', detail: wpData.factors.pitching.name ? `${wpData.factors.pitching.name} FIP ${wpData.factors.pitching.fip}` : `FIP ${wpData.factors.pitching.fip}`, val: wpData.factors.pitching.adjustment },
                { label: 'Bullpen', detail: '', val: wpData.factors.bullpen.adjustment },
              ].map(f => (
                <div key={f.label} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                  <div>
                    <span style={{ fontSize: 13, color: '#94a3b8' }}>{f.label}</span>
                    {f.detail && <span style={{ fontSize: 11, color: '#475569', marginLeft: 8 }}>{f.detail}</span>}
                  </div>
                  <span style={{ fontSize: 13, fontWeight: 700, color: f.val > 0 ? '#22c55e' : f.val < 0 ? '#ef4444' : '#475569' }}>
                    {f.val > 0 ? '+' : ''}{(f.val * 100).toFixed(1)}%
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Outcome table */}
      {wpData?.outcomes?.length > 0 && (
        <div style={{ background: '#1e293b', borderRadius: 12, overflow: 'hidden' }}>
          <div style={{ padding: '12px 16px', borderBottom: '1px solid #0f172a', fontSize: 11, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', display: 'flex', justifyContent: 'space-between' }}>
            <span>Outcome</span>
            <span>New WP · WPA</span>
          </div>
          {wpData.outcomes.map((o, i) => (
            <div key={i} style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              padding: '13px 16px', borderBottom: i < wpData.outcomes.length - 1 ? '1px solid #0f172a' : 'none',
            }}>
              <div style={{ fontSize: 15, fontWeight: 600, color: '#e2e8f0' }}>{o.label}</div>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: 15, fontWeight: 700, color: '#f1f5f9' }}>{pct(o.new_wp)}</div>
                <div style={{ fontSize: 12, color: wpaColor(o.wpa), marginTop: 1 }}>
                  {o.wpa > 0 ? '+' : ''}{(o.wpa * 100).toFixed(1)}%
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── PLAKATA ──────────────────────────────────────────────────────────────────
function OrderbookSide({ levels, side, bestPrice }) {
  const [expanded, setExpanded] = useState(false)
  const isBid = side === 'bid'
  const color = isBid ? '#3b82f6' : '#ef4444'
  const label = isBid ? 'BID' : 'ASK'

  if (!levels || levels.length === 0) return null

  const best = levels[0]
  const maxSize = Math.max(...levels.map(l => l.size))
  const shown = expanded ? levels : [best]

  return (
    <div>
      <div
        onClick={() => setExpanded(!expanded)}
        style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}
      >
        <span style={{ fontSize: 10, color: '#475569', fontWeight: 700, textTransform: 'uppercase' }}>{label}</span>
        <span style={{ fontSize: 10, color: '#334155' }}>{expanded ? '▼' : '▶'} {levels.length} levels</span>
      </div>
      {shown.map((level, i) => (
        <div key={i} style={{ position: 'relative', marginBottom: 2 }}>
          <div style={{
            position: 'absolute', top: 0, [isBid ? 'right' : 'left']: 0, bottom: 0,
            width: `${(level.size / maxSize) * 100}%`,
            background: `${color}15`, borderRadius: 4,
          }} />
          <div style={{
            position: 'relative', display: 'flex', justifyContent: 'space-between',
            padding: '3px 8px', fontSize: i === 0 ? 15 : 13,
            fontWeight: i === 0 ? 800 : 400,
            color: i === 0 ? color : '#94a3b8',
          }}>
            <span>{level.price}¢</span>
            <span style={{ color: '#475569', fontSize: i === 0 ? 13 : 11 }}>
              {level.size.toLocaleString()}
            </span>
          </div>
        </div>
      ))}
    </div>
  )
}

function TeamOrderbook({ team, abbr, ticker, wsData }) {
  const [orderbook, setOrderbook] = useState(null)
  const [loading, setLoading] = useState(false)

  // Fetch orderbook on mount and every 10s
  const fetchOb = useCallback(async () => {
    if (!ticker) return
    try {
      const r = await fetch(`${API}/api/kalshi/orderbook/${ticker}`)
      const d = await r.json()
      if (!d.error) setOrderbook(d)
    } catch {}
  }, [ticker])

  useEffect(() => {
    fetchOb()
    const t = setInterval(fetchOb, 10000)
    return () => clearInterval(t)
  }, [fetchOb])

  // Merge WS top-of-book into orderbook display
  const liveAsk = wsData?.ask
  const liveBid = wsData?.bid

  const bestAsk = orderbook?.best_ask
  const bestBid = orderbook?.best_bid
  const displayAsk = liveAsk > 0 ? Math.round(liveAsk * 100) : bestAsk?.price
  const displayBid = liveBid > 0 ? Math.round(liveBid * 100) : bestBid?.price

  return (
    <div style={{
      background: '#1e293b', borderRadius: 12, padding: 16, marginBottom: 12,
      border: '1px solid #334155',
    }}>
      {/* Team header + best ask */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 800, color: '#e2e8f0' }}>{abbr}</div>
          <div style={{ fontSize: 11, color: '#475569' }}>{team}</div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: 10, color: '#475569', marginBottom: 2 }}>BEST ASK</div>
          <div style={{ fontSize: 28, fontWeight: 900, color: '#ef4444', lineHeight: 1 }}>
            {displayAsk != null ? `${displayAsk}¢` : '—'}
          </div>
          {bestAsk?.size && (
            <div style={{ fontSize: 10, color: '#475569', marginTop: 2 }}>
              {bestAsk.size.toLocaleString()} contracts
            </div>
          )}
        </div>
      </div>

      {/* Orderbook */}
      {orderbook && (
        <div style={{ display: 'flex', gap: 12 }}>
          <div style={{ flex: 1 }}>
            <OrderbookSide levels={orderbook.bids} side="bid" bestPrice={displayBid} />
          </div>
          <div style={{ flex: 1 }}>
            <OrderbookSide levels={orderbook.asks} side="ask" bestPrice={displayAsk} />
          </div>
        </div>
      )}

      {loading && <div style={{ fontSize: 11, color: '#475569', textAlign: 'center' }}>Loading...</div>}
    </div>
  )
}

// ── Scorebug ─────────────────────────────────────────────────────────────────
function Scorebug({ gameState, awayAsk, homeAsk }) {
  if (!gameState) return null
  const g = gameState
  const isTop = g.topbot === 'Top'
  const bases = [g.on_1b, g.on_2b, g.on_3b]

  return (
    <div style={{ background: '#1e293b', borderRadius: 12, padding: 14, marginBottom: 12, border: '1px solid #334155' }}>
      {/* Teams + score + Kalshi ask */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 10 }}>
        {[
          { label: g.away_team, score: isTop ? g.bat_score : g.fld_score, batting: isTop, ask: awayAsk },
          { label: g.home_team, score: isTop ? g.fld_score : g.bat_score, batting: !isTop, ask: homeAsk },
        ].map((t, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {t.batting && <span style={{ fontSize: 8, color: '#f59e0b' }}>▶</span>}
            {!t.batting && <span style={{ fontSize: 8, color: 'transparent' }}>▶</span>}
            <span style={{ flex: 1, fontSize: 14, fontWeight: t.batting ? 800 : 400, color: t.batting ? '#f1f5f9' : '#94a3b8' }}>
              {t.label}
            </span>
            <span style={{ fontSize: 18, fontWeight: 800, color: '#f1f5f9', minWidth: 24, textAlign: 'right' }}>
              {t.score}
            </span>
            <span style={{
              fontSize: 13, fontWeight: 700, color: '#ef4444',
              minWidth: 40, textAlign: 'right',
              opacity: t.ask != null ? 1 : 0.3,
            }}>
              {t.ask != null ? `${t.ask}¢` : '—'}
            </span>
          </div>
        ))}
      </div>

      {/* Inning + count + outs + bases */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        {/* Inning */}
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 9, color: '#475569' }}>{isTop ? '▲' : '▼'}</div>
          <div style={{ fontSize: 16, fontWeight: 800, color: '#e2e8f0' }}>{g.inning || 1}</div>
        </div>

        {/* Count */}
        <div style={{ display: 'flex', gap: 12 }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 9, color: '#475569' }}>B</div>
            <div style={{ fontSize: 14, fontWeight: 700, color: '#22c55e' }}>{g.balls || 0}</div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 9, color: '#475569' }}>S</div>
            <div style={{ fontSize: 14, fontWeight: 700, color: '#ef4444' }}>{g.strikes || 0}</div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 9, color: '#475569' }}>O</div>
            <div style={{ fontSize: 14, fontWeight: 700, color: '#f59e0b' }}>{g.outs || 0}</div>
          </div>
        </div>

        {/* Bases diamond */}
        <svg width="40" height="40" viewBox="0 0 40 40">
          <rect x="15" y="2" width="12" height="12" rx="1" transform="rotate(45 21 8)"
            fill={bases[1] ? '#f59e0b' : 'none'} stroke={bases[1] ? '#f59e0b' : '#334155'} strokeWidth="1.5" />
          <rect x="24" y="11" width="12" height="12" rx="1" transform="rotate(45 30 17)"
            fill={bases[0] ? '#f59e0b' : 'none'} stroke={bases[0] ? '#f59e0b' : '#334155'} strokeWidth="1.5" />
          <rect x="6" y="11" width="12" height="12" rx="1" transform="rotate(45 12 17)"
            fill={bases[2] ? '#f59e0b' : 'none'} stroke={bases[2] ? '#f59e0b' : '#334155'} strokeWidth="1.5" />
        </svg>

        {/* Batter/Pitcher */}
        <div style={{ textAlign: 'right', maxWidth: 100 }}>
          {g.batter?.name && (
            <div style={{ fontSize: 11, color: '#e2e8f0', fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {g.batter.name.split(' ').pop()}
            </div>
          )}
          {g.pitcher_name && (
            <div style={{ fontSize: 10, color: '#475569', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              vs {g.pitcher_name.split(' ').pop()}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── WPA Outcome Table (anchored to Kalshi price) ─────────────────────────────
function WPATable({ wpData, battingTeam, kalshiAsk, onTrade }) {
  if (!wpData?.outcomes) return null

  // Use Kalshi ask as the anchor. WPA shifts are relative — apply them to Kalshi price.
  const baseWp = wpData.adjusted_wp ?? wpData.base_wp
  const anchor = kalshiAsk || baseWp  // Kalshi ask (0-1) or fall back to model

  return (
    <div style={{ background: '#1e293b', borderRadius: 12, padding: 14, marginBottom: 12, border: '1px solid #334155' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <div style={{ fontSize: 11, color: '#94a3b8', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          If {battingTeam || 'batter'}...
        </div>
        {kalshiAsk && (
          <div style={{ fontSize: 11, color: '#475569' }}>
            now {Math.round(kalshiAsk * 100)}¢
          </div>
        )}
      </div>
      {wpData.outcomes.map((o, i) => {
        const shift = o.wpa
        const shiftCents = Math.round(shift * 100)
        const projected = Math.round(anchor * 100) + shiftCents
        const isPositive = shift > 0
        const isBig = Math.abs(shift) >= 0.05
        const color = isPositive ? '#22c55e' : '#ef4444'

        const canTrade = onTrade && isPositive && shiftCents >= 3

        return (
          <div key={i} onClick={() => canTrade && onTrade(o)} style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            padding: '6px 8px', borderRadius: 6, marginBottom: 2,
            background: isBig ? `${color}10` : 'transparent',
            border: isBig ? `1px solid ${color}22` : '1px solid transparent',
            cursor: canTrade ? 'pointer' : 'default',
            transition: 'background 0.1s',
          }}>
            <span style={{ fontSize: 13, color: '#e2e8f0', fontWeight: isBig ? 700 : 400 }}>
              {canTrade && <span style={{ marginRight: 4 }}>⚡</span>}
              {o.label}
            </span>
            <div style={{ textAlign: 'right' }}>
              <span style={{ fontSize: 14, fontWeight: 700, color }}>
                {isPositive ? '+' : ''}{shiftCents}¢
              </span>
              <span style={{ fontSize: 11, color: '#475569', marginLeft: 6 }}>
                → {Math.max(0, Math.min(100, projected))}¢
              </span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function PlakataTab() {
  const [games, setGames] = useState([])
  const [selectedGame, setSelectedGame] = useState(null)
  const [gameData, setGameData] = useState(null)
  const [gameState, setGameState] = useState(null)
  const [wsConnected, setWsConnected] = useState(false)
  const [wsPrices, setWsPrices] = useState({})
  const [wpData, setWpData] = useState(null)
  const wsRef = useRef(null)
  const pollRef = useRef(null)

  // Trading auth
  const [tradeUnlocked, setTradeUnlocked] = useState(false)
  const [tradeToken, setTradeToken] = useState('')
  const [pinInput, setPinInput] = useState('')
  const [pinError, setPinError] = useState('')
  const [showPinModal, setShowPinModal] = useState(false)

  // Trading settings
  const [maxSpend, setMaxSpend] = useState(50)      // dollars
  const [buffer, setBuffer] = useState(5)            // cents
  const [lockedTarget, setLockedTarget] = useState(null)  // cents — locked target price
  const [tradeLoading, setTradeLoading] = useState(false)
  const [tradeResult, setTradeResult] = useState(null)
  const sliderRef = useRef(null)
  const sliderTrackRef = useRef(null)
  const [sliderX, setSliderX] = useState(0)
  const [sliding, setSliding] = useState(false)

  // Tap outcome → lock target
  const lockTarget = (outcome) => {
    if (!tradeUnlocked || !gameState) return
    const isTop = gameState.topbot === 'Top'
    const battingAbbr = isTop ? gameData?.away?.abbr : gameData?.home?.abbr
    const battingWs = wsPrices[battingAbbr]
    const currentAsk = battingWs?.ask > 0 ? Math.round(battingWs.ask * 100) : null
    if (!currentAsk) return

    const shiftCents = Math.round(outcome.wpa * 100)
    const target = currentAsk + shiftCents
    setLockedTarget(target)
    setTradeResult(null)
  }

  // Slider to execute
  const handleSliderStart = (e) => {
    e.preventDefault()
    setSliding(true)
    const track = sliderTrackRef.current
    if (!track) return
    const trackRect = track.getBoundingClientRect()
    const startX = (e.touches?.[0] || e).clientX

    const onMove = (ev) => {
      const x = (ev.touches?.[0] || ev).clientX
      const dx = Math.max(0, Math.min(x - startX, trackRect.width - 48))
      setSliderX(dx)
    }
    const onEnd = async (ev) => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onEnd)
      document.removeEventListener('touchmove', onMove)
      document.removeEventListener('touchend', onEnd)

      const threshold = trackRect.width - 80
      if (sliderX >= threshold && tradeUnlocked && lockedTarget && gameData && gameState) {
        // Execute trade
        const isTop = gameState.topbot === 'Top'
        const battingTicker = isTop ? gameData.away?.ticker : gameData.home?.ticker
        const maxPrice = lockedTarget - buffer
        if (battingTicker && maxPrice > 0) {
          setTradeLoading(true)
          setTradeResult(null)
          try {
            const r = await fetch(`${API}/api/trade/execute`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                ticker: battingTicker,
                max_spend_cents: maxSpend * 100,
                max_price_cents: maxPrice,
                side: 'yes',
                trade_token: tradeToken,
              }),
            })
            setTradeResult(await r.json())
          } catch (e) { setTradeResult({ error: e.message, ok: false }) }
          finally { setTradeLoading(false) }
        }
      }
      setSliderX(0)
      setSliding(false)
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onEnd)
    document.addEventListener('touchmove', onMove, { passive: false })
    document.addEventListener('touchend', onEnd)
  }

  const unlockTrading = async () => {
    setPinError('')
    try {
      const r = await fetch(`${API}/api/auth/trade`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: pinInput }),
      })
      const d = await r.json()
      if (d.ok) {
        setTradeToken(d.token)
        setTradeUnlocked(true)
        setShowPinModal(false)
        setPinInput('')
      } else {
        setPinError(d.error || 'Wrong password')
      }
    } catch { setPinError('Connection error') }
  }

  // Load today's games
  useEffect(() => {
    fetch(`${API}/api/games/today`).then(r => r.json()).then(setGames).catch(() => {})
  }, [])

  // When game selected, find both tickers
  useEffect(() => {
    if (!selectedGame) { setGameData(null); setGameState(null); setWpData(null); return }
    const g = games.find(g => g.game_pk === selectedGame)
    if (!g) return
    fetch(`${API}/api/kalshi/game-tickers?home_team=${encodeURIComponent(g.home_team)}&away_team=${encodeURIComponent(g.away_team)}`)
      .then(r => r.json())
      .then(d => { if (!d.error) setGameData(d) })
      .catch(() => {})
  }, [selectedGame, games])

  // Poll game state every 10s
  const syncGame = useCallback(async (gamePk) => {
    try {
      const r = await fetch(`${API}/api/games/${gamePk}/state`)
      if (!r.ok) return
      const g = await r.json()
      setGameState(g)
    } catch {}
  }, [])

  useEffect(() => {
    if (pollRef.current) clearInterval(pollRef.current)
    if (selectedGame) {
      syncGame(selectedGame)
      pollRef.current = setInterval(() => syncGame(selectedGame), 10000)
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [selectedGame, syncGame])

  // Calculate WPA when game state changes (anchored to Kalshi price)
  useEffect(() => {
    if (!gameState || gameState.status === 'Final') { setWpData(null); return }

    const isTop = gameState.topbot === 'Top'
    // Get batting team's Kalshi ask as current WP
    const homeAbbr = gameData?.home?.abbr
    const awayAbbr = gameData?.away?.abbr
    const battingAbbr = isTop ? awayAbbr : homeAbbr
    const battingWs = wsPrices[battingAbbr]
    const kalshiPrice = battingWs?.ask > 0 ? battingWs.ask : null

    const body = {
      inning: gameState.inning || 1,
      topbot: gameState.topbot || 'Top',
      outs: gameState.outs || 0,
      on_1b: gameState.on_1b || false,
      on_2b: gameState.on_2b || false,
      on_3b: gameState.on_3b || false,
      bat_score: gameState.bat_score || 0,
      fld_score: gameState.fld_score || 0,
      season: 2025,
      batting_lineup: gameState.batting_lineup?.map(p => p.id) || null,
      fielding_pitcher: gameState.pitcher_id || null,
      kalshi_price: kalshiPrice,
    }

    fetch(`${API}/api/wp`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then(r => r.json())
      .then(setWpData)
      .catch(() => {})
  }, [gameState, wsPrices, gameData])

  // Connect WS when we have game data
  useEffect(() => {
    if (wsRef.current) { wsRef.current.close(); wsRef.current = null }
    setWsConnected(false)
    setWsPrices({})
    if (!gameData?.game_key) return

    let reconnectTimer = null
    const connect = () => {
      const ws = new WebSocket(getKalshiWsUrl({ gameKey: gameData.game_key }))
      wsRef.current = ws

      ws.onmessage = (e) => {
        const data = JSON.parse(e.data)
        if (data.status === 'connected') {
          setWsConnected(true)
        } else if (data.type === 'price') {
          setWsPrices(prev => ({
            ...prev,
            [data.team]: { bid: data.yes_bid, ask: data.yes_ask, last: data.last_price },
          }))
        }
      }
      ws.onclose = () => {
        setWsConnected(false)
        reconnectTimer = setTimeout(connect, 2000)
      }
      ws.onerror = () => { ws.close() }
    }
    connect()

    return () => {
      if (reconnectTimer) clearTimeout(reconnectTimer)
      if (wsRef.current) wsRef.current.close()
    }
  }, [gameData])

  // Derive ask prices for scorebug
  const homeAsk = wsPrices[gameData?.home?.abbr]?.ask > 0
    ? Math.round(wsPrices[gameData.home.abbr].ask * 100) : null
  const awayAsk = wsPrices[gameData?.away?.abbr]?.ask > 0
    ? Math.round(wsPrices[gameData.away.abbr].ask * 100) : null

  const battingTeam = gameState
    ? (gameState.topbot === 'Top' ? gameState.away_team : gameState.home_team)?.split(' ').pop()
    : null

  // Batting team's raw Kalshi ask (0-1) for WPA anchoring
  const battingKalshiAsk = gameState
    ? (gameState.topbot === 'Top'
        ? wsPrices[gameData?.away?.abbr]?.ask
        : wsPrices[gameData?.home?.abbr]?.ask) || null
    : null

  return (
    <div style={{ animation: 'fadeIn 0.3s ease' }}>
      {/* PIN modal */}
      {showPinModal && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 100,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }} onClick={() => setShowPinModal(false)}>
          <div style={{
            background: '#1e293b', borderRadius: 16, padding: 24, width: 280,
            border: '1px solid #334155',
          }} onClick={e => e.stopPropagation()}>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginBottom: 16, textAlign: 'center' }}>
              Unlock Trading
            </div>
            <input
              value={pinInput}
              onChange={e => setPinInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && unlockTrading()}
              placeholder="Enter password"
              type="password"
              autoFocus
              style={{
                width: '100%', padding: '10px 12px', borderRadius: 8,
                background: '#0f172a', border: `1px solid ${pinError ? '#ef4444' : '#334155'}`,
                color: '#f1f5f9', fontSize: 15, outline: 'none', boxSizing: 'border-box',
                marginBottom: 8,
              }}
            />
            {pinError && <div style={{ fontSize: 12, color: '#ef4444', marginBottom: 8 }}>{pinError}</div>}
            <button
              onClick={unlockTrading}
              style={{
                width: '100%', padding: '10px 0', borderRadius: 8, border: 'none',
                background: '#2563eb', color: '#fff', fontSize: 14, fontWeight: 700,
                cursor: 'pointer',
              }}
            >Unlock</button>
          </div>
        </div>
      )}

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: '#94a3b8' }}>
          PLAKATA
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {tradeUnlocked
            ? <span style={{ fontSize: 10, color: '#f59e0b', fontWeight: 700, cursor: 'pointer' }}
                onClick={() => { setTradeUnlocked(false); setTradeToken('') }}>TRADING ●</span>
            : <span style={{ fontSize: 10, color: '#475569', fontWeight: 600, cursor: 'pointer' }}
                onClick={() => setShowPinModal(true)}>VIEW ONLY</span>
          }
          {wsConnected && <span style={{ fontSize: 10, color: '#22c55e', fontWeight: 700 }}>● LIVE</span>}
          {gameState?.status === 'Live' && (
            <span style={{ fontSize: 10, color: '#475569' }}>
              {gameState.topbot === 'Top' ? '▲' : '▼'}{gameState.inning}
            </span>
          )}
        </div>
      </div>

      {/* Game picker */}
      <select
        value={selectedGame || ''}
        onChange={e => setSelectedGame(e.target.value ? Number(e.target.value) : null)}
        style={{
          width: '100%', padding: '10px 12px', borderRadius: 8,
          background: '#1e293b', border: '1px solid #334155',
          color: '#f1f5f9', fontSize: 14, marginBottom: 12, outline: 'none',
        }}
      >
        <option value="">Select a game...</option>
        {games.map(g => (
          <option key={g.game_pk} value={g.game_pk}>
            {g.away_team} @ {g.home_team} — {g.status}
            {g.status === 'Live' ? ` (${g.inning_half} ${g.inning})` : ''}
          </option>
        ))}
      </select>

      <Scorebug gameState={gameState} awayAsk={awayAsk} homeAsk={homeAsk} />

      {/* Trade settings + swipe bar — only when unlocked */}
      {tradeUnlocked && (
        <div style={{ marginBottom: 12 }}>
          {/* Settings row */}
          <div style={{
            background: '#1e293b', borderRadius: '10px 10px 0 0', padding: '8px 12px',
            border: '1px solid #f59e0b33', borderBottom: 'none',
            display: 'flex', gap: 12, alignItems: 'center',
          }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 9, color: '#475569', marginBottom: 2 }}>MAX SPEND</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <span style={{ fontSize: 13, color: '#94a3b8' }}>$</span>
                <input value={maxSpend} onChange={e => setMaxSpend(Number(e.target.value) || 0)} type="number"
                  style={{ width: 60, padding: '4px 6px', borderRadius: 6, background: '#0f172a', border: '1px solid #334155', color: '#f1f5f9', fontSize: 14, outline: 'none' }} />
              </div>
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 9, color: '#475569', marginBottom: 2 }}>BUFFER</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <input value={buffer} onChange={e => setBuffer(Number(e.target.value) || 0)} type="number"
                  style={{ width: 50, padding: '4px 6px', borderRadius: 6, background: '#0f172a', border: '1px solid #334155', color: '#f1f5f9', fontSize: 14, outline: 'none' }} />
                <span style={{ fontSize: 13, color: '#94a3b8' }}>¢</span>
              </div>
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 9, color: '#475569', marginBottom: 2 }}>TARGET</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <input value={lockedTarget || ''} onChange={e => setLockedTarget(Number(e.target.value) || null)} type="number"
                  placeholder="—"
                  style={{ width: 50, padding: '4px 6px', borderRadius: 6, background: '#0f172a', border: `1px solid ${lockedTarget ? '#f59e0b' : '#334155'}`, color: lockedTarget ? '#f59e0b' : '#f1f5f9', fontSize: 14, fontWeight: 700, outline: 'none' }} />
                <span style={{ fontSize: 13, color: '#94a3b8' }}>¢</span>
              </div>
            </div>
          </div>

          {/* Slide to trade */}
          {lockedTarget && (() => {
            const isTop = gameState?.topbot === 'Top'
            const liveAsk = isTop ? awayAsk : homeAsk
            const maxPrice = lockedTarget - buffer
            const hasEdge = liveAsk != null && maxPrice > liveAsk

            return (
              <div style={{
                background: hasEdge ? '#22c55e08' : '#1e293b',
                borderRadius: '0 0 10px 10px', padding: '10px 12px',
                border: `1px solid ${hasEdge ? '#22c55e33' : '#33415533'}`,
              }}>
                {/* Price info row */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                  <div>
                    <div style={{ fontSize: 9, color: '#475569' }}>LIVE ASK</div>
                    <div style={{ fontSize: 18, fontWeight: 800, color: '#ef4444' }}>
                      {liveAsk != null ? `${liveAsk}¢` : '—'}
                    </div>
                  </div>
                  <div style={{ fontSize: 16, color: '#334155' }}>→</div>
                  <div style={{ textAlign: 'center' }}>
                    <div style={{ fontSize: 9, color: '#475569' }}>SWEEP TO</div>
                    <div style={{ fontSize: 18, fontWeight: 800, color: '#f59e0b' }}>{maxPrice}¢</div>
                  </div>
                  <div style={{ fontSize: 16, color: '#334155' }}>→</div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontSize: 9, color: '#475569' }}>TARGET</div>
                    <div style={{ fontSize: 18, fontWeight: 800, color: '#22c55e' }}>{lockedTarget}¢</div>
                  </div>
                </div>

                {/* Slider track */}
                {hasEdge ? (
                  <div ref={sliderTrackRef} style={{
                    position: 'relative', height: 48, borderRadius: 24,
                    background: '#0f172a', border: '1px solid #22c55e33',
                    overflow: 'hidden', userSelect: 'none', WebkitUserSelect: 'none',
                    touchAction: 'none',
                  }}>
                    {/* Fill */}
                    <div style={{
                      position: 'absolute', left: 0, top: 0, bottom: 0,
                      width: sliderX + 48, borderRadius: 24,
                      background: sliding
                        ? 'linear-gradient(90deg, #22c55e44, #22c55e22)'
                        : 'transparent',
                      transition: sliding ? 'none' : 'width 0.3s',
                    }} />
                    {/* Label */}
                    <div style={{
                      position: 'absolute', inset: 0,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontSize: 12, fontWeight: 700, color: '#22c55e',
                      letterSpacing: '0.1em', pointerEvents: 'none',
                    }}>
                      {tradeLoading ? 'EXECUTING...' : 'SLIDE TO BUY →'}
                    </div>
                    {/* Thumb */}
                    <div
                      onMouseDown={handleSliderStart}
                      onTouchStart={handleSliderStart}
                      style={{
                        position: 'absolute', top: 2, left: 2 + sliderX,
                        width: 44, height: 44, borderRadius: 22,
                        background: '#22c55e', cursor: 'grab',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        fontSize: 18, color: '#000', fontWeight: 900,
                        transition: sliding ? 'none' : 'left 0.3s',
                        boxShadow: '0 2px 8px rgba(34,197,94,0.3)',
                      }}
                    >⟩</div>
                  </div>
                ) : (
                  <div style={{
                    height: 48, borderRadius: 24, background: '#0f172a',
                    border: '1px solid #33415533',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 12, color: '#475569',
                  }}>
                    {liveAsk != null ? 'No edge — ask past sweep ceiling' : 'Waiting for live price...'}
                  </div>
                )}
              </div>
            )
          })()}

          {/* Trade result */}
          {tradeResult && (
            <div style={{
              background: '#1e293b', borderRadius: 8, padding: '8px 12px', marginTop: 4,
              border: `1px solid ${tradeResult.ok ? '#22c55e33' : '#ef444433'}`,
            }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: tradeResult.ok ? '#22c55e' : '#ef4444' }}>
                {tradeResult.ok ? `Filled ${tradeResult.summary?.total_contracts} contracts` : 'Failed'}
              </div>
              {tradeResult.error && <div style={{ fontSize: 11, color: '#ef4444' }}>{tradeResult.error}</div>}
              {tradeResult.summary && (
                <div style={{ fontSize: 11, color: '#475569' }}>
                  Cost: ${(tradeResult.summary.total_cost_cents / 100).toFixed(2)} ·
                  {tradeResult.summary.successful}/{tradeResult.summary.total_orders} orders
                </div>
              )}
              <span onClick={() => setTradeResult(null)} style={{ fontSize: 10, color: '#475569', cursor: 'pointer' }}>dismiss</span>
            </div>
          )}
        </div>
      )}

      {/* WPA Outcome Table */}
      <WPATable wpData={wpData} battingTeam={battingTeam} kalshiAsk={battingKalshiAsk}
        onTrade={tradeUnlocked ? lockTarget : null} />

      {/* Orderbooks */}
      {gameData?.away && (
        <TeamOrderbook
          team={games.find(g => g.game_pk === selectedGame)?.away_team || ''}
          abbr={gameData.away.abbr}
          ticker={gameData.away.ticker}
          wsData={wsPrices[gameData.away.abbr]}
        />
      )}
      {gameData?.home && (
        <TeamOrderbook
          team={games.find(g => g.game_pk === selectedGame)?.home_team || ''}
          abbr={gameData.home.abbr}
          ticker={gameData.home.ticker}
          wsData={wsPrices[gameData.home.abbr]}
        />
      )}

      {selectedGame && !gameData && (
        <div style={{ fontSize: 13, color: '#475569', textAlign: 'center', padding: 20 }}>
          Loading Kalshi markets...
        </div>
      )}

      {!selectedGame && (
        <div style={{ fontSize: 13, color: '#475569', textAlign: 'center', padding: 40 }}>
          Select a game to view live trading data
        </div>
      )}
    </div>
  )
}

// ── Shared styles ─────────────────────────────────────────────────────────────
const labelStyle = { display: 'block', fontSize: 11, color: '#94a3b8', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em' }
const nudgeBtn = {
  width: 28, height: 28, borderRadius: 6, border: '1px solid #334155',
  background: '#0f172a', color: '#94a3b8', fontSize: 16, cursor: 'pointer',
  display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 0,
}

// ── Root App ──────────────────────────────────────────────────────────────────
export default function App() {
  const [tab, setTab] = useState('wp')

  return (
    <div style={{ maxWidth: 480, margin: '0 auto', padding: '16px 16px 60px', fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif', color: '#f1f5f9', background: '#0f172a', minHeight: '100vh' }}>

      {/* Header */}
      <div style={{ textAlign: 'center', marginBottom: 20 }}>
        <div style={{ fontSize: 24, marginBottom: 2 }}>⚾</div>
        <h1 style={{ fontSize: 20, fontWeight: 800, letterSpacing: '-0.03em', margin: 0 }}>MLB Dashboard</h1>
        <p style={{ fontSize: 12, color: '#475569', marginTop: 2 }}>Statcast 2023–2025</p>
      </div>

      {/* Tab switcher */}
      <div style={{ display: 'flex', borderRadius: 10, overflow: 'hidden', border: '1px solid #1e293b', marginBottom: 20, background: '#1e293b' }}>
        {[
          { id: 'wp',       label: '📊 WP' },
          { id: 'sim',      label: '⚾ Sim' },
          { id: 'plakata',  label: '💥 Plakata' },
          { id: 'spring',   label: '🌸 Odds' },
        ].map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            flex: 1, padding: '11px 0', border: 'none', fontSize: 13, fontWeight: 600,
            background: tab === t.id ? '#2563eb' : 'transparent',
            color: tab === t.id ? '#fff' : '#64748b',
            cursor: 'pointer', transition: 'background 0.15s',
          }}>{t.label}</button>
        ))}
      </div>

      {tab === 'wp' ? <WPDashboard /> : tab === 'sim' ? <AtBatTab /> : tab === 'plakata' ? <PlakataTab /> : <SpringOddsTab />}

      <style>{`
        * { box-sizing: border-box; }
        body { background: #0f172a; margin: 0; }
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(6px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        input[type=number]::-webkit-outer-spin-button,
        input[type=number]::-webkit-inner-spin-button { -webkit-appearance: none; }
        input::placeholder { color: #475569; }
        input:focus { border-color: #3b82f6 !important; }
        button:active { opacity: 0.8; }
      `}</style>
    </div>
  )
}
