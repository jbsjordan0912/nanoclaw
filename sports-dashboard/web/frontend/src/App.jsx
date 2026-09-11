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
function PlayerSearch({ label, value, onSelect, apiBase = API }) {
  const [query, setQuery] = useState(value?.name || '')
  const [results, setResults] = useState([])
  const [open, setOpen] = useState(false)
  const timer = useRef(null)

  const search = (q) => {
    setQuery(q)
    clearTimeout(timer.current)
    if (q.length < 2) { setResults([]); setOpen(false); return }
    timer.current = setTimeout(async () => {
      const res = await fetch(`${apiBase}/api/players/search?q=${encodeURIComponent(q)}`)
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

// ── 1K Batch Simulator tab (TE engine) ───────────────────────────────────────
const PITCH_BAR_COLORS = ['#3b82f6','#ef4444','#22c55e','#f59e0b','#a855f7','#06b6d4','#f97316','#84cc16','#ec4899','#14b8a6','#eab308']
const OUTCOME_BAR_COLORS = {
  'Single':'#22c55e','Double':'#16a34a','Triple':'#15803d','Home Run':'#f59e0b',
  'Walk':'#3b82f6','Strikeout':'#ef4444','Out in Play':'#64748b',
}

function StatTile({ label, value, sub }) {
  return (
    <div style={{ flex: 1, background: '#1e293b', borderRadius: 10, padding: '12px 10px', textAlign: 'center' }}>
      <div style={{ fontSize: 24, fontWeight: 800, color: '#f1f5f9', lineHeight: 1.1 }}>{value}</div>
      <div style={{ fontSize: 10, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.04em', marginTop: 4 }}>{label}</div>
      {sub && <div style={{ fontSize: 11, color: '#475569', marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

function DistBar({ label, pct, count, color }) {
  return (
    <div style={{ marginBottom: 7 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 3 }}>
        <span style={{ color: '#e2e8f0', fontWeight: 600 }}>{label}</span>
        <span style={{ color: '#64748b', fontVariantNumeric: 'tabular-nums' }}>{(pct*100).toFixed(1)}% · {count}</span>
      </div>
      <div style={{ height: 8, borderRadius: 4, background: '#0f172a', overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${Math.min(pct*100,100)}%`, background: color, borderRadius: 4, transition: 'width 0.4s ease' }} />
      </div>
    </div>
  )
}

function BatchSimTab() {
  const [batter, setBatter] = useState(null)
  const [pitcher, setPitcher] = useState(null)
  const [n, setN] = useState(1000)
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState(null)
  const [elapsed, setElapsed] = useState(null)
  const [error, setError] = useState(null)
  const canSim = batter && pitcher && !loading

  const run = async () => {
    if (!canSim) return
    setLoading(true); setError(null); setData(null)
    const t0 = performance.now()
    try {
      const res = await fetch(`${API}/api/simulate1k`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ batter_id: batter.id, pitcher_id: pitcher.id, n }),
      })
      if (!res.ok) throw new Error(`Server error ${res.status}`)
      setData(await res.json())
      setElapsed(((performance.now() - t0) / 1000).toFixed(1))
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  const ab = data?.example_ab

  return (
    <div>
      <div style={{ display: 'flex', gap: 12, marginBottom: 12 }}>
        <PlayerSearch label="Batter" value={batter} onSelect={setBatter} />
        <PlayerSearch label="Pitcher" value={pitcher} onSelect={setPitcher} />
      </div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, alignItems: 'center' }}>
        <span style={{ fontSize: 11, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Sims</span>
        {[100, 1000, 5000].map(v => (
          <button key={v} onClick={() => setN(v)} style={{
            padding: '5px 12px', borderRadius: 6, border: 'none', fontSize: 13, fontWeight: 700,
            background: n === v ? '#2563eb' : '#1e293b', color: n === v ? '#fff' : '#64748b', cursor: 'pointer',
          }}>{v.toLocaleString()}</button>
        ))}
      </div>
      <button onClick={run} disabled={!canSim} style={{
        width: '100%', padding: '14px 0', borderRadius: 10, border: 'none',
        background: canSim ? '#2563eb' : '#1e293b', color: canSim ? '#fff' : '#475569',
        fontSize: 16, fontWeight: 700, cursor: canSim ? 'pointer' : 'not-allowed', marginBottom: 20,
      }}>{loading ? `⏳ Simulating ${n.toLocaleString()}...` : `▶ Run ${n.toLocaleString()} Simulations`}</button>
      {error && <div style={{ color: '#ef4444', fontSize: 14, textAlign: 'center', marginBottom: 16 }}>{error}</div>}

      {data && (
        <div style={{ animation: 'fadeIn 0.3s ease' }}>
          <div style={{ textAlign: 'center', fontSize: 13, color: '#94a3b8', marginBottom: 14 }}>
            {data.matchup.batter_name} <span style={{ color: '#475569' }}>({data.matchup.stand})</span>
            <span style={{ color: '#475569' }}> vs </span>
            {data.matchup.pitcher_name} <span style={{ color: '#475569' }}>({data.matchup.p_throws}HP)</span>
            {elapsed && <span style={{ color: '#475569' }}> · {data.n.toLocaleString()} ABs in {elapsed}s</span>}
          </div>

          {/* Headline stats */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 18 }}>
            <StatTile label="Avg AB Length" value={data.avg_ab_length} sub="pitches" />
            <StatTile label="1st-Pitch Velo" value={`${data.first_pitch_velo.mean}`} sub={`${data.first_pitch_velo.min}–${data.first_pitch_velo.max} mph`} />
            <StatTile label="wOBA" value={data.woba} sub="expected" />
          </div>

          {/* Outcomes over N ABs */}
          <div style={{ marginBottom: 18 }}>
            <div style={{ fontSize: 11, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10 }}>
              Outcomes · {data.n.toLocaleString()} ABs
            </div>
            {data.outcomes.map(o => (
              <DistBar key={o.key} label={o.label} pct={o.pct} count={o.count} color={OUTCOME_BAR_COLORS[o.label] || '#64748b'} />
            ))}
          </div>

          {/* Pitch mix */}
          <div style={{ marginBottom: 18 }}>
            <div style={{ fontSize: 11, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10 }}>
              Pitch Distribution
            </div>
            {data.pitch_distribution.filter(d => d.pct >= 0.005).map((d, i) => (
              <DistBar key={d.pitch_type} label={d.pitch_type} pct={d.pct} count={d.count} color={PITCH_BAR_COLORS[i % PITCH_BAR_COLORS.length]} />
            ))}
          </div>

          {/* One example AB played out */}
          {ab && (
            <div>
              <div style={{ fontSize: 11, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10 }}>
                Example At-Bat
              </div>
              <div style={{ marginBottom: 12 }}><StrikeZone pitches={ab.pitches} shownCount={ab.pitches.length} /></div>
              <ResultBanner result={{ ...ab, matchup: `${data.matchup.batter_name} vs ${data.matchup.pitcher_name}` }} />
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 12 }}>
                {ab.pitches.map((p, i) => <PitchCard key={i} pitch={p} delay={0} />)}
              </div>
            </div>
          )}
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
function getKalshiWsUrl({ ticker, gameKey, cfbGame } = {}) {
  const isLocal = window.location.hostname === 'localhost'
  const base = isLocal
    ? 'ws://localhost:8000'
    : 'wss://mlb-simulator-api.onrender.com'
  if (cfbGame) return `${base}/api/ws/kalshi?cfb_game=${encodeURIComponent(cfbGame)}`
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

  // Trading auth — persist in localStorage
  const [tradeUnlocked, setTradeUnlocked] = useState(() => !!localStorage.getItem('pitchpulse_token'))
  const [tradeToken, setTradeToken] = useState(() => localStorage.getItem('pitchpulse_token') || '')
  const [pinInput, setPinInput] = useState('')
  const [pinError, setPinError] = useState('')
  const [showPinModal, setShowPinModal] = useState(false)

  // Trading settings
  const [maxSpend, setMaxSpend] = useState(50)      // dollars
  const [buffer, setBuffer] = useState(5)            // cents
  const [lockedTarget, setLockedTarget] = useState(null)  // cents — locked target price
  const [tradeLoading, setTradeLoading] = useState(false)
  const [tradeResult, setTradeResult] = useState(null)
  const sliderTrackRef = useRef(null)
  const sliderXRef = useRef(0)
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
      sliderXRef.current = dx
      setSliderX(dx)
    }
    const onEnd = async (ev) => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onEnd)
      document.removeEventListener('touchmove', onMove)
      document.removeEventListener('touchend', onEnd)

      const threshold = trackRect.width - 80
      if (sliderXRef.current >= threshold && tradeUnlocked && lockedTarget && gameData && gameState) {
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
            const result = await r.json()
            setTradeResult(result)
            // Token expired/invalid — drop it and force a re-unlock
            if (r.status === 401 || result?.error === 'Unauthorized') {
              localStorage.removeItem('pitchpulse_token')
              setTradeUnlocked(false)
              setTradeToken('')
              setShowPinModal(true)
            }
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
        localStorage.setItem('pitchpulse_token', d.token)
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
          PITCHPULSE
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {tradeUnlocked
            ? <span style={{ fontSize: 10, color: '#f59e0b', fontWeight: 700, cursor: 'pointer' }}
                onClick={() => { setTradeUnlocked(false); setTradeToken(''); localStorage.removeItem('pitchpulse_token') }}>TRADING ●</span>
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
              {!tradeResult.ok && tradeResult.orders?.find(o => o.error) && (
                <div style={{ fontSize: 11, color: '#ef4444', wordBreak: 'break-word' }}>
                  {tradeResult.orders.find(o => o.error).error}
                </div>
              )}
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

// ── Research Tab ─────────────────────────────────────────────────────────────
function BvPCard({ batter, compact }) {
  if (batter.pa === 0) {
    if (compact) return null
    return (
      <div style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', fontSize: 12, color: '#334155' }}>
        <span>{batter.batter_name} ({batter.position})</span>
        <span>No history</span>
      </div>
    )
  }

  const avgColor = batter.avg >= 0.300 ? '#22c55e' : batter.avg >= 0.200 ? '#f59e0b' : '#ef4444'
  const evColor = batter.avg_ev >= 92 ? '#22c55e' : batter.avg_ev >= 86 ? '#f59e0b' : '#94a3b8'

  return (
    <div style={{
      background: '#0f172a', borderRadius: 10, padding: '10px 12px', marginBottom: 6,
      border: `1px solid ${batter.avg >= 0.300 ? '#22c55e33' : '#1e293b'}`,
    }}>
      {/* Name + AVG */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 800, color: '#e2e8f0' }}>{batter.batter_name}</div>
          <div style={{ display: 'flex', gap: 4, alignItems: 'center', marginTop: 2 }}>
            <span style={{ fontSize: 11, color: '#475569' }}>{batter.position}</span>
            {batter.stand && (
              <span style={{ fontSize: 10, color: '#64748b', padding: '1px 5px', borderRadius: 4, background: '#1e293b' }}>
                {batter.stand}HB
              </span>
            )}
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: 24, fontWeight: 900, color: avgColor, lineHeight: 1 }}>
            {batter.avg != null ? batter.avg.toFixed(3) : '—'}
          </div>
          <div style={{ fontSize: 10, color: '#475569', marginTop: 2 }}>AVG</div>
        </div>
      </div>
      {/* Counting stats grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 4, marginBottom: 6 }}>
        {[
          { label: 'PA', value: batter.pa },
          { label: 'AB', value: batter.ab },
          { label: 'H', value: batter.hits },
          { label: 'HR', value: batter.hr, color: batter.hr > 0 ? '#f59e0b' : '#94a3b8' },
          { label: 'K', value: batter.k },
          { label: 'BB', value: batter.bb },
        ].map((s, i) => (
          <div key={i} style={{ textAlign: 'center', background: '#1e293b', borderRadius: 5, padding: '4px 2px' }}>
            <div style={{ fontSize: 9, color: '#475569' }}>{s.label}</div>
            <div style={{ fontSize: 15, fontWeight: 700, color: s.color || '#e2e8f0' }}>{s.value}</div>
          </div>
        ))}
      </div>
      {/* Rate stats + EV */}
      <div style={{ display: 'flex', gap: 10, fontSize: 12, color: '#94a3b8' }}>
        <span>SLG <span style={{ fontWeight: 700, color: '#e2e8f0' }}>{batter.slg != null ? batter.slg.toFixed(3) : '—'}</span></span>
        {batter.obp != null && <span>OBP <span style={{ fontWeight: 700, color: '#e2e8f0' }}>{batter.obp.toFixed(3)}</span></span>}
        {batter.avg_ev != null && <span style={{ color: evColor }}>EV {batter.avg_ev}</span>}
        {batter.avg_la != null && <span>LA {batter.avg_la}°</span>}
      </div>
      <div style={{ fontSize: 10, color: '#334155', marginTop: 3 }}>
        {batter.pitches_seen} pitches seen
      </div>
    </div>
  )
}

function ResearchTab() {
  const [games, setGames] = useState([])
  const [selectedGame, setSelectedGame] = useState(null)
  const [viewSide, setViewSide] = useState('away') // which lineup to show
  const [matchups, setMatchups] = useState(null)
  const [loading, setLoading] = useState(false)
  const [selectedPitcher, setSelectedPitcher] = useState(null) // override pitcher (for bullpen)
  const [roster, setRoster] = useState(null) // opposing team's pitching roster
  const [pitchMix, setPitchMix] = useState(null)
  const [mixPeriod, setMixPeriod] = useState('2026')
  const [mixLoading, setMixLoading] = useState(false)
  const [mixHand, setMixHand] = useState('')  // '', 'L', or 'R'
  const [pitcherView, setPitcherView] = useState('mix') // 'mix' or 'stats'
  const [pitcherStats, setPitcherStats] = useState(null)
  const [statsLoading, setStatsLoading] = useState(false)
  const [statsSeason, setStatsSeason] = useState('2025')
  const [statsHand, setStatsHand] = useState('')  // '', 'L', 'R'

  // Load today's matchups
  useEffect(() => {
    fetch(`${API}/api/matchups/today`).then(r => r.json()).then(setGames).catch(() => {})
  }, [])

  // When game + side selected, load matchups vs starter
  useEffect(() => {
    if (!selectedGame) { setMatchups(null); setRoster(null); setSelectedPitcher(null); return }
    const g = games.find(gm => gm.game_pk === selectedGame)
    if (!g) return

    const battingTeamId = viewSide === 'away' ? g.away_team_id : g.home_team_id
    const pitcherId = selectedPitcher
      || (viewSide === 'away' ? g.home_starter?.id : g.away_starter?.id)
    const opposingTeamId = viewSide === 'away' ? g.home_team_id : g.away_team_id

    if (!pitcherId) return

    setLoading(true)
    Promise.all([
      fetch(`${API}/api/matchups/team-vs-pitcher?team_id=${battingTeamId}&pitcher_id=${pitcherId}`).then(r => r.json()),
      roster ? Promise.resolve(roster) : fetch(`${API}/api/matchups/roster/${opposingTeamId}`).then(r => r.json()),
    ])
      .then(([m, r]) => {
        setMatchups(m)
        if (!roster) setRoster(r)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [selectedGame, viewSide, selectedPitcher, games])

  // Fetch pitch mix when pitcher or period changes
  useEffect(() => {
    const g = games.find(gm => gm.game_pk === selectedGame)
    if (!g) { setPitchMix(null); return }
    const pitcherId = selectedPitcher
      || (viewSide === 'away' ? g.home_starter?.id : g.away_starter?.id)
    if (!pitcherId) { setPitchMix(null); return }

    setMixLoading(true)
    const handParam = mixHand ? `&batter_hand=${mixHand}` : ''
    fetch(`${API}/api/matchups/pitch-mix/${pitcherId}?period=${mixPeriod}${handParam}`)
      .then(r => r.json())
      .then(setPitchMix)
      .catch(() => setPitchMix(null))
      .finally(() => setMixLoading(false))
  }, [selectedGame, viewSide, selectedPitcher, mixPeriod, mixHand, games])

  // Fetch pitcher stats when switching to stats view
  useEffect(() => {
    if (pitcherView !== 'stats') return
    const g = games.find(gm => gm.game_pk === selectedGame)
    if (!g) return
    const pitcherId = selectedPitcher
      || (viewSide === 'away' ? g.home_starter?.id : g.away_starter?.id)
    if (!pitcherId) return

    setStatsLoading(true)
    const handParam = statsHand ? `&batter_hand=${statsHand}` : ''
    fetch(`${API}/api/matchups/pitcher-stats/${pitcherId}?season=${statsSeason}${handParam}`)
      .then(r => r.json())
      .then(setPitcherStats)
      .catch(() => setPitcherStats(null))
      .finally(() => setStatsLoading(false))
  }, [pitcherView, selectedGame, viewSide, selectedPitcher, statsSeason, statsHand, games])

  const game = games.find(g => g.game_pk === selectedGame)
  const currentPitcherName = selectedPitcher
    ? roster?.pitchers?.find(p => p.id === selectedPitcher)?.name || 'Unknown'
    : (viewSide === 'away' ? game?.home_starter?.name : game?.away_starter?.name) || 'TBD'

  return (
    <div style={{ animation: 'fadeIn 0.3s ease' }}>
      <div style={{ fontSize: 13, fontWeight: 700, color: '#94a3b8', marginBottom: 14 }}>
        MATCHUP RESEARCH
      </div>

      {/* Game picker */}
      <select
        value={selectedGame || ''}
        onChange={e => { setSelectedGame(e.target.value ? Number(e.target.value) : null); setSelectedPitcher(null); setRoster(null); setPitchMix(null); setMixPeriod('2026'); setMixHand(''); setPitcherView('mix'); setPitcherStats(null); setStatsSeason('2025'); setStatsHand('') }}
        style={{
          width: '100%', padding: '10px 12px', borderRadius: 8,
          background: '#1e293b', border: '1px solid #334155',
          color: '#f1f5f9', fontSize: 13, marginBottom: 10, outline: 'none',
        }}
      >
        <option value="">Select a game...</option>
        {games.map(g => (
          <option key={g.game_pk} value={g.game_pk}>
            {g.away_team} @ {g.home_team} — {g.away_starter.name} vs {g.home_starter.name}
          </option>
        ))}
      </select>

      {/* Side toggle + pitcher selector */}
      {game && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
            {['away', 'home'].map(side => (
              <button key={side} onClick={() => { setViewSide(side); setSelectedPitcher(null); setRoster(null) }} style={{
                flex: 1, padding: '8px 0', borderRadius: 8, border: 'none', fontSize: 12, fontWeight: 700,
                background: viewSide === side ? '#2563eb' : '#1e293b',
                color: viewSide === side ? '#fff' : '#64748b', cursor: 'pointer',
              }}>
                {side === 'away' ? `${game.away_team} Hitting` : `${game.home_team} Hitting`}
              </button>
            ))}
          </div>

          {/* Current pitcher */}
          <div style={{
            background: '#1e293b', borderRadius: 10, padding: '8px 12px', marginBottom: 8,
            border: '1px solid #334155', display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          }}>
            <div>
              <div style={{ fontSize: 10, color: '#475569' }}>VS PITCHER</div>
              <div style={{ fontSize: 15, fontWeight: 800, color: '#e2e8f0' }}>{currentPitcherName}</div>
            </div>
            {selectedPitcher && (
              <button onClick={() => setSelectedPitcher(null)} style={{
                padding: '4px 10px', borderRadius: 6, border: '1px solid #334155',
                background: 'transparent', color: '#94a3b8', fontSize: 10, cursor: 'pointer',
              }}>Back to Starter</button>
            )}
          </div>

          {/* Bullpen picker */}
          {roster?.pitchers && (
            <div style={{ marginBottom: 8 }}>
              <div style={{ fontSize: 10, color: '#475569', marginBottom: 4, textTransform: 'uppercase' }}>Bullpen</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                {roster.pitchers.map(p => (
                  <button key={p.id} onClick={() => setSelectedPitcher(p.id)} style={{
                    padding: '4px 8px', borderRadius: 6, border: 'none', fontSize: 11,
                    background: selectedPitcher === p.id ? '#2563eb' : '#0f172a',
                    color: selectedPitcher === p.id ? '#fff' : '#94a3b8',
                    cursor: 'pointer',
                  }}>{p.name.split(' ').pop()}</button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Pitch mix / stats */}
      {game && (
        <div style={{ background: '#1e293b', borderRadius: 10, padding: 12, marginBottom: 12, border: '1px solid #334155' }}>
          {/* View toggle */}
          <div style={{ display: 'flex', gap: 4, marginBottom: 8 }}>
            {[{ v: 'mix', l: 'Pitch Mix' }, { v: 'stats', l: 'Stats' }].map(t => (
              <button key={t.v} onClick={() => setPitcherView(t.v)} style={{
                padding: '4px 12px', borderRadius: 6, border: 'none', fontSize: 11, fontWeight: 700,
                background: pitcherView === t.v ? '#2563eb' : '#0f172a',
                color: pitcherView === t.v ? '#fff' : '#64748b', cursor: 'pointer',
              }}>{t.l}</button>
            ))}
          </div>

          {pitcherView === 'stats' && (
            <div>
              {/* Season + hand filters */}
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                <div style={{ display: 'flex', gap: 4 }}>
                  {['2026', '2025', '2024'].map(yr => (
                    <button key={yr} onClick={() => setStatsSeason(yr)} style={{
                      padding: '3px 8px', borderRadius: 5, border: 'none', fontSize: 10, fontWeight: 600,
                      background: statsSeason === yr ? '#2563eb' : '#0f172a',
                      color: statsSeason === yr ? '#fff' : '#64748b', cursor: 'pointer',
                    }}>{yr}</button>
                  ))}
                </div>
                <div style={{ display: 'flex', gap: 4 }}>
                  {[{ v: '', l: 'All' }, { v: 'L', l: 'vs L' }, { v: 'R', l: 'vs R' }].map(opt => (
                    <button key={opt.v} onClick={() => setStatsHand(opt.v)} style={{
                      padding: '3px 8px', borderRadius: 5, border: 'none', fontSize: 10, fontWeight: 600,
                      background: statsHand === opt.v ? '#334155' : '#0f172a',
                      color: statsHand === opt.v ? '#e2e8f0' : '#475569', cursor: 'pointer',
                    }}>{opt.l}</button>
                  ))}
                </div>
              </div>
              {statsLoading && <div style={{ fontSize: 11, color: '#475569', textAlign: 'center', padding: 8 }}>Loading...</div>}
              {pitcherStats && !statsLoading && (
                <div>
                  <div>
                    <div style={{ fontSize: 9, color: '#475569', marginBottom: 4, textTransform: 'uppercase' }}>
                      {pitcherStats.season}{statsHand ? ` vs ${statsHand}HB` : ''} · {pitcherStats.pa} PA · {pitcherStats.ip} IP · {pitcherStats.total_pitches} pitches
                    </div>
                    {/* Rate stats */}
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, marginBottom: 8 }}>
                      {[
                        pitcherStats.era != null && { label: 'ERA', value: pitcherStats.era, color: parseFloat(pitcherStats.era) <= 3.0 ? '#22c55e' : parseFloat(pitcherStats.era) <= 4.0 ? '#f59e0b' : '#ef4444' },
                        { label: 'BAA', value: pitcherStats.baa?.toFixed(3), color: pitcherStats.baa <= .220 ? '#22c55e' : pitcherStats.baa <= .260 ? '#f59e0b' : '#ef4444' },
                        { label: 'OBPA', value: pitcherStats.obpa?.toFixed(3) },
                        { label: 'SLGA', value: pitcherStats.slga?.toFixed(3) },
                        { label: 'WHIP', value: pitcherStats.whip?.toFixed(2), color: pitcherStats.whip <= 1.10 ? '#22c55e' : pitcherStats.whip <= 1.30 ? '#f59e0b' : '#ef4444' },
                        { label: 'K%', value: pitcherStats.k_pct != null ? `${pitcherStats.k_pct}%` : null },
                        { label: 'BB%', value: pitcherStats.bb_pct != null ? `${pitcherStats.bb_pct}%` : null },
                        { label: 'IP', value: pitcherStats.ip },
                      ].filter(s => s && s.value != null).map((s, i) => (
                        <div key={i} style={{ textAlign: 'center', background: '#0f172a', borderRadius: 6, padding: '6px 4px' }}>
                          <div style={{ fontSize: 10, color: '#475569', marginBottom: 2 }}>{s.label}</div>
                          <div style={{ fontSize: 18, fontWeight: 800, color: s.color || '#e2e8f0' }}>{s.value}</div>
                        </div>
                      ))}
                    </div>
                    {/* Counting stats */}
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 6 }}>
                      {[
                        { label: 'AB', value: pitcherStats.ab },
                        { label: 'H', value: pitcherStats.hits },
                        { label: 'HR', value: pitcherStats.hr, color: pitcherStats.hr > 0 ? '#f59e0b' : '#e2e8f0' },
                        { label: 'K', value: pitcherStats.k },
                        { label: 'BB', value: pitcherStats.bb },
                      ].filter(s => s.value != null).map((s, i) => (
                        <div key={i} style={{ textAlign: 'center', background: '#0f172a', borderRadius: 6, padding: '6px 4px' }}>
                          <div style={{ fontSize: 10, color: '#475569', marginBottom: 2 }}>{s.label}</div>
                          <div style={{ fontSize: 16, fontWeight: 700, color: s.color || '#94a3b8' }}>{s.value}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}
              {!pitcherStats && !statsLoading && (
                <div style={{ fontSize: 11, color: '#475569', textAlign: 'center', padding: 8 }}>No stats available</div>
              )}
            </div>
          )}

          {pitcherView === 'mix' && (<div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ fontSize: 11, color: '#94a3b8', fontWeight: 700, textTransform: 'uppercase' }}>Pitch Mix</span>
              {pitchMix?.throws && (
                <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 4, background: '#0f172a', color: '#64748b', fontWeight: 600 }}>
                  {pitchMix.throws}HP
                </span>
              )}
            </div>
            <div style={{ display: 'flex', gap: 4 }}>
              {[
                { value: '2026', label: '2026' },
                { value: '2025', label: '2025' },
                { value: 'last10', label: 'L10' },
                { value: 'last5', label: 'L5' },
                { value: 'last3', label: 'L3' },
              ].map(opt => (
                <button key={opt.value} onClick={() => setMixPeriod(opt.value)} style={{
                  padding: '3px 8px', borderRadius: 5, border: 'none', fontSize: 10, fontWeight: 600,
                  background: mixPeriod === opt.value ? '#2563eb' : '#0f172a',
                  color: mixPeriod === opt.value ? '#fff' : '#64748b', cursor: 'pointer',
                }}>{opt.label}</button>
              ))}
            </div>
          </div>
          {/* Batter hand filter */}
          <div style={{ display: 'flex', gap: 4, marginBottom: 8 }}>
            {[
              { value: '', label: 'All Batters' },
              { value: 'L', label: 'vs LHB' },
              { value: 'R', label: 'vs RHB' },
            ].map(opt => (
              <button key={opt.value} onClick={() => setMixHand(opt.value)} style={{
                padding: '3px 10px', borderRadius: 5, border: 'none', fontSize: 10, fontWeight: 600,
                background: mixHand === opt.value ? '#334155' : '#0f172a',
                color: mixHand === opt.value ? '#e2e8f0' : '#475569', cursor: 'pointer',
              }}>{opt.label}</button>
            ))}
          </div>

          {mixLoading && <div style={{ fontSize: 11, color: '#475569', textAlign: 'center', padding: 8 }}>Loading...</div>}

          {pitchMix && !mixLoading && pitchMix.mix?.length > 0 && (
            <div>
              {/* Header */}
              <div style={{ display: 'flex', padding: '0 4px 4px', fontSize: 9, color: '#475569', borderBottom: '1px solid #0f172a' }}>
                <span style={{ flex: 2 }}>PITCH</span>
                <span style={{ flex: 1, textAlign: 'right' }}>%</span>
                <span style={{ flex: 1, textAlign: 'right' }}>VELO</span>
                <span style={{ flex: 1, textAlign: 'right' }}>WHIFF</span>
                <span style={{ flex: 1, textAlign: 'right' }}>CSP</span>
              </div>
              {pitchMix.mix.map((p, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', padding: '4px', fontSize: 12 }}>
                  <span style={{ flex: 2, color: '#e2e8f0', fontWeight: 600 }}>{p.name}</span>
                  <span style={{ flex: 1, textAlign: 'right', color: '#94a3b8' }}>
                    <span style={{ fontWeight: 700, color: p.pct >= 20 ? '#e2e8f0' : '#64748b' }}>{p.pct}%</span>
                  </span>
                  <span style={{ flex: 1, textAlign: 'right', color: '#94a3b8' }}>
                    {p.avg_velo || '—'}
                  </span>
                  <span style={{ flex: 1, textAlign: 'right', color: p.whiff_rate >= 30 ? '#22c55e' : p.whiff_rate >= 20 ? '#f59e0b' : '#94a3b8' }}>
                    {p.whiff_rate != null ? `${p.whiff_rate}%` : '—'}
                  </span>
                  <span style={{ flex: 1, textAlign: 'right', color: '#94a3b8' }}>
                    {p.called_strike_pct}%
                  </span>
                </div>
              ))}
              <div style={{ fontSize: 10, color: '#334155', textAlign: 'right', marginTop: 4 }}>
                {pitchMix.pitches} total pitches
              </div>
            </div>
          )}

          {pitchMix && !mixLoading && pitchMix.pitches === 0 && (
            <div style={{ fontSize: 11, color: '#475569', textAlign: 'center', padding: 8 }}>No data for this period</div>
          )}
        </div>)}
        </div>
      )}

      {/* Matchup results */}
      {loading && <div style={{ textAlign: 'center', color: '#475569', padding: 20 }}>Loading matchups...</div>}

      {matchups && !loading && (
        <div>
          {matchups.map((b, i) => (
            <BvPCard key={b.batter_id} batter={b} compact={false} />
          ))}
          {matchups.length === 0 && (
            <div style={{ textAlign: 'center', color: '#475569', padding: 20 }}>No hitters on active roster</div>
          )}
        </div>
      )}

      {!selectedGame && (
        <div style={{ textAlign: 'center', color: '#475569', padding: 40 }}>
          Select a game to view batter vs pitcher matchups
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

// ── HR Scanner Tab ───────────────────────────────────────────────────────────
function HRScannerTab() {
  const [fvText, setFvText] = useState('')
  const [margin, setMargin] = useState(20)
  const [contracts, setContracts] = useState(10)
  const [results, setResults] = useState(null)
  const [loading, setLoading] = useState(false)
  const [orderStatus, setOrderStatus] = useState({}) // ticker -> {status, msg}
  const [cancelKey, setCancelKey] = useState('')
  const [gameTime, setGameTime] = useState('') // for auto-cancel
  const [autoCancelTimer, setAutoCancelTimer] = useState(null)

  const parseFV = () => {
    // Parse pasted text: "Player Name +500" per line
    const lines = fvText.trim().split('\n').filter(l => l.trim())
    const players = []
    for (const line of lines) {
      // Match: name followed by +/- number
      const match = line.match(/^(.+?)\s+([+-]\d+)\s*$/)
      if (match) {
        players.push({ name: match[1].trim(), fv: parseInt(match[2]) })
      }
    }
    return players
  }

  const scan = async () => {
    const players = parseFV()
    if (players.length === 0) return
    setLoading(true)
    setOrderStatus({})
    try {
      const res = await fetch(`${API}/api/hr/scan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ players, margin, contracts }),
      })
      const data = await res.json()
      setResults(data.results || [])
    } catch (e) {
      setResults([])
    }
    setLoading(false)
  }

  const postOrder = async (ticker, side, price) => {
    const key = `${ticker}-${side}`
    setOrderStatus(prev => ({ ...prev, [key]: { status: 'posting' } }))
    try {
      const res = await fetch(`${API}/api/hr/order`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticker, side, price, contracts }),
      })
      const data = await res.json()
      if (data.ok) {
        setOrderStatus(prev => ({ ...prev, [key]: { status: 'posted', msg: `Order placed: ${contracts}x @ ${price}¢` } }))
      } else {
        setOrderStatus(prev => ({ ...prev, [key]: { status: 'error', msg: data.error || 'Failed' } }))
      }
    } catch (e) {
      setOrderStatus(prev => ({ ...prev, [key]: { status: 'error', msg: e.message } }))
    }
  }

  const cancelGame = async (key) => {
    try {
      const res = await fetch(`${API}/api/hr/cancel-game?game_key=${key}`, { method: 'POST' })
      const data = await res.json()
      if (data.ok) {
        alert(`Cancelled ${data.cancelled} orders`)
        setOrderStatus({})
      } else {
        alert(`Error: ${data.error}`)
      }
    } catch (e) {
      alert(e.message)
    }
  }

  // Auto-cancel timer
  const startAutoCancel = () => {
    if (!gameTime || !cancelKey) return
    const [h, m] = gameTime.split(':').map(Number)
    const now = new Date()
    const target = new Date()
    target.setHours(h, m, 0, 0)
    const ms = target - now
    if (ms <= 0) { alert('Game time is in the past'); return }
    const timer = setTimeout(() => {
      cancelGame(cancelKey)
    }, ms)
    setAutoCancelTimer(timer)
    alert(`Auto-cancel set for ${gameTime} (${Math.round(ms / 60000)} min)`)
  }

  const inputStyle = {
    padding: '8px 12px', borderRadius: 8, background: '#1e293b',
    border: '1px solid #334155', color: '#f1f5f9', fontSize: 13,
    outline: 'none', boxSizing: 'border-box',
  }

  return (
    <div>
      {/* Input area */}
      <div style={{ marginBottom: 16 }}>
        <label style={{ display: 'block', fontSize: 11, color: '#94a3b8', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          Paste Fair Values (one per line: Player Name +odds)
        </label>
        <textarea value={fvText} onChange={e => setFvText(e.target.value)}
          placeholder={"Pete Alonso +504\nGunnar Henderson +591\nBobby Witt Jr. +566"}
          rows={6}
          style={{ ...inputStyle, width: '100%', fontFamily: 'monospace', resize: 'vertical' }} />
      </div>

      {/* Controls */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, alignItems: 'flex-end' }}>
        <div style={{ flex: 1 }}>
          <label style={{ display: 'block', fontSize: 11, color: '#94a3b8', marginBottom: 4 }}>Margin %</label>
          <input type="number" value={margin} onChange={e => setMargin(Number(e.target.value))}
            style={{ ...inputStyle, width: '100%' }} />
        </div>
        <div style={{ flex: 1 }}>
          <label style={{ display: 'block', fontSize: 11, color: '#94a3b8', marginBottom: 4 }}>Contracts</label>
          <input type="number" value={contracts} onChange={e => setContracts(Number(e.target.value))}
            style={{ ...inputStyle, width: '100%' }} />
        </div>
        <button onClick={scan} disabled={loading} style={{
          padding: '8px 20px', borderRadius: 8, border: 'none', fontSize: 13, fontWeight: 700,
          background: '#2563eb', color: '#fff', cursor: 'pointer', height: 37,
        }}>{loading ? 'Scanning...' : 'Scan'}</button>
      </div>

      {/* Auto-cancel controls */}
      {results && results.length > 0 && (
        <div style={{ display: 'flex', gap: 8, marginBottom: 16, alignItems: 'flex-end', padding: 10, background: '#1e293b', borderRadius: 8 }}>
          <div style={{ flex: 1 }}>
            <label style={{ display: 'block', fontSize: 11, color: '#94a3b8', marginBottom: 4 }}>Game Key (e.g. BALKC)</label>
            <input value={cancelKey} onChange={e => setCancelKey(e.target.value)}
              placeholder="BALKC" style={{ ...inputStyle, width: '100%' }} />
          </div>
          <div style={{ flex: 1 }}>
            <label style={{ display: 'block', fontSize: 11, color: '#94a3b8', marginBottom: 4 }}>Cancel at (ET)</label>
            <input type="time" value={gameTime} onChange={e => setGameTime(e.target.value)}
              style={{ ...inputStyle, width: '100%' }} />
          </div>
          <button onClick={startAutoCancel} style={{
            padding: '8px 14px', borderRadius: 8, border: 'none', fontSize: 12, fontWeight: 600,
            background: '#f59e0b', color: '#000', cursor: 'pointer', height: 37, whiteSpace: 'nowrap',
          }}>Set Timer</button>
          <button onClick={() => cancelKey && cancelGame(cancelKey)} style={{
            padding: '8px 14px', borderRadius: 8, border: 'none', fontSize: 12, fontWeight: 600,
            background: '#ef4444', color: '#fff', cursor: 'pointer', height: 37, whiteSpace: 'nowrap',
          }}>Cancel Now</button>
        </div>
      )}

      {/* Results */}
      {results && results.map((r, i) => {
        if (!r.matched) return (
          <div key={r.name} style={{ padding: '8px 12px', background: '#1e293b', borderRadius: 6, marginBottom: 2, color: '#64748b', fontSize: 13 }}>
            {r.name} — not found on Kalshi
          </div>
        )

        const yesKey = `${r.ticker}-yes`
        const noKey = `${r.ticker}-no`
        const yesStatus = orderStatus[yesKey]
        const noStatus = orderStatus[noKey]

        return (
          <div key={r.ticker} style={{
            padding: '12px', background: i % 2 === 0 ? '#1e293b' : '#0f172a',
            borderRadius: 8, marginBottom: 4,
            borderLeft: (r.yes_actionable || r.no_actionable) ? '3px solid #22c55e' : '3px solid transparent',
          }}>
            {/* Player header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: '#e2e8f0' }}>{r.name}</div>
              <div style={{ fontSize: 12, color: '#64748b' }}>FV: {r.fv_cents}¢ ({r.fv_american > 0 ? '+' : ''}{r.fv_american})</div>
            </div>

            {/* YES row */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4, padding: '6px 8px', background: '#0f172a33', borderRadius: 4 }}>
              <span style={{ fontSize: 12, fontWeight: 700, color: '#22c55e', minWidth: 30 }}>YES</span>
              <span style={{ fontSize: 12, color: '#94a3b8', fontVariantNumeric: 'tabular-nums' }}>
                bid:{r.yes_bid}¢ ask:{r.yes_ask}¢
              </span>
              <span style={{ fontSize: 11, color: '#64748b' }}>cut:{r.yes_cutoff}¢</span>
              <span style={{ fontSize: 12, fontWeight: 600, color: r.yes_actionable ? '#22c55e' : '#ef4444', fontVariantNumeric: 'tabular-nums' }}>
                {r.yes_edge > 0 ? '+' : ''}{r.yes_edge}%
              </span>
              {r.yes_actionable && !yesStatus && (
                <button onClick={() => postOrder(r.ticker, 'yes', r.yes_ask)} style={{
                  marginLeft: 'auto', padding: '4px 12px', borderRadius: 6, border: 'none',
                  fontSize: 11, fontWeight: 700, background: '#22c55e', color: '#000', cursor: 'pointer',
                }}>BUY {r.yes_ask}¢</button>
              )}
              {yesStatus && (
                <span style={{ marginLeft: 'auto', fontSize: 11, color: yesStatus.status === 'posted' ? '#22c55e' : yesStatus.status === 'error' ? '#ef4444' : '#f59e0b' }}>
                  {yesStatus.status === 'posting' ? '...' : yesStatus.msg}
                </span>
              )}
            </div>

            {/* NO row */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px', background: '#0f172a33', borderRadius: 4 }}>
              <span style={{ fontSize: 12, fontWeight: 700, color: '#ef4444', minWidth: 30 }}>NO</span>
              <span style={{ fontSize: 12, color: '#94a3b8', fontVariantNumeric: 'tabular-nums' }}>
                bid:{r.no_bid}¢ ask:{r.no_ask}¢
              </span>
              <span style={{ fontSize: 11, color: '#64748b' }}>cut:{r.no_cutoff}¢</span>
              <span style={{ fontSize: 12, fontWeight: 600, color: r.no_actionable ? '#22c55e' : '#ef4444', fontVariantNumeric: 'tabular-nums' }}>
                {r.no_edge > 0 ? '+' : ''}{r.no_edge}%
              </span>
              {r.no_actionable && !noStatus && (
                <button onClick={() => postOrder(r.ticker, 'no', r.no_ask)} style={{
                  marginLeft: 'auto', padding: '4px 12px', borderRadius: 6, border: 'none',
                  fontSize: 11, fontWeight: 700, background: '#ef4444', color: '#fff', cursor: 'pointer',
                }}>BUY {r.no_ask}¢</button>
              )}
              {noStatus && (
                <span style={{ marginLeft: 'auto', fontSize: 11, color: noStatus.status === 'posted' ? '#22c55e' : noStatus.status === 'error' ? '#ef4444' : '#f59e0b' }}>
                  {noStatus.status === 'posting' ? '...' : noStatus.msg}
                </span>
              )}
            </div>

            <div style={{ fontSize: 10, color: '#475569', marginTop: 4 }}>vol: {r.volume?.toLocaleString()}</div>
          </div>
        )
      })}
    </div>
  )
}

// ── College football game board (every Kalshi market for one game) ───────────
const CFB_GAME = '26SEP12RICEND'   // Rice @ Notre Dame, Sat 9/12
const CFB_TEAMS = ['RICE', 'ND']    // away, home: Kalshi's ticker codes
const CFB_SCORE_KEY = `cfb_score_${CFB_GAME}`
const CFB_SPEND_CHIPS = [10, 25, 50, 100]
const CFB_SWEEP_BUDGETS = [25, 50, 100, 250]
const CFB_BUMPS = [[0, 'Ask'], [1, '+1'], [3, '+3'], [5, '+5']]
const CFB_DEFAULT_OPEN = new Set(['KXNCAAFGAME', 'KXNCAAFSPREAD', 'KXNCAAFTOTAL', 'KXNCAAFTEAMTOTAL', 'KXNCAAFTEAMTD', 'KXNCAAFFIRSTTDTEAM'])
const CFB_SIDE_COLOR = { yes: '#22c55e', no: '#ef4444' }
// Game phases for the hand-kept score. `scoreIn` is the phase a new score moves
// the game to: scoring during a break means the next quarter has started.
const CFB_PHASES = [
  { key: 'pre', label: 'Pregame', period: 0, scoreIn: 'q1' },
  { key: 'q1', label: 'Q1', period: 1, scoreIn: 'q1' },
  { key: 'e1', label: 'End Q1', period: 1, end: true, scoreIn: 'q2' },
  { key: 'q2', label: 'Q2', period: 2, scoreIn: 'q2' },
  { key: 'half', label: 'Halftime', period: 2, end: true, scoreIn: 'q3' },
  { key: 'q3', label: 'Q3', period: 3, scoreIn: 'q3' },
  { key: 'e3', label: 'End Q3', period: 3, end: true, scoreIn: 'q4' },
  { key: 'q4', label: 'Q4', period: 4, scoreIn: 'q4' },
  { key: 'e4', label: 'End of regulation', period: 4, end: true, scoreIn: 'ot' },
  { key: 'ot', label: 'Overtime', period: 5, scoreIn: 'ot' },
  { key: 'final', label: 'Final', period: 5, final: true, scoreIn: null },
]
const CFB_SCORES = [['TD+1', 7, true], ['TD', 6, true], ['FG', 3, false], ['+2', 2, false], ['+1', 1, false]]
const CFB_BLANK_SCORE = { phase: 'pre', ot: false, lines: { RICE: [0, 0, 0, 0, 0], ND: [0, 0, 0, 0, 0] }, tds: { RICE: 0, ND: 0 }, firstTd: null }
// Sweeper periods: [series infix, label, periods counted (null = whole game incl. OT)]
const CFB_PERIODS = [['GAME', 'Game', null], ['1H', '1H', [1, 2]], ['1Q', 'Q1', [1]], ['2Q', 'Q2', [2]], ['3Q', 'Q3', [3]], ['4Q', 'Q4', [4]]]

// Kalshi taker fee: 7% × contracts × P × (1 − P), rounded up to the cent
const kalshiFeeCents = (contracts, priceCents) => {
  const p = priceCents / 100
  return Math.ceil(contracts * 0.07 * p * (1 - p) * 100 - 1e-9)
}

// The book from /api/kalshi/orderbook is YES-denominated. A NO ask is a YES
// bid seen from the other side (100 − price), and vice versa.
function sideLadder(ob, side) {
  if (!ob) return { asks: [], bids: [] }
  if (side === 'yes') return { asks: ob.asks || [], bids: ob.bids || [] }
  const flip = (l) => ({ price: 100 - l.price, size: l.size })
  return {
    asks: (ob.bids || []).map(flip).sort((a, b) => a.price - b.price),
    bids: (ob.asks || []).map(flip).sort((a, b) => b.price - a.price),
  }
}

// Mirror of the server's sweep (/api/trade/preview): walk the ask ladder up to
// the take price, buying whole contracts within budget.
function cfbSweep(asks, takePrice, budgetCents) {
  let left = budgetCents, contracts = 0, cost = 0, fee = 0
  for (const l of asks) {
    if (l.price > takePrice) break
    const n = Math.min(l.size, Math.floor(left / l.price))
    if (n <= 0) break
    contracts += n
    cost += n * l.price
    fee += kalshiFeeCents(n, l.price)
    left -= n * l.price
  }
  return { contracts, cost, fee }
}

// Points a team scored in the given periods (null = whole game, OT included)
const cfbPts = (gs, team, periods) => periods
  ? periods.reduce((s, p) => s + (gs.lines[team]?.[p - 1] || 0), 0)
  : gs.scores[team] || 0

// What the lock rules and sweeper read, derived from the hand-kept score
function cfbGameState(sc) {
  const ph = CFB_PHASES.find(p => p.key === sc.phase) || CFB_PHASES[0]
  return {
    state: ph.key === 'pre' ? 'pre' : ph.final ? 'post' : 'in',
    period: ph.final ? (sc.ot ? 5 : 4) : ph.period,
    ended: !!ph.end,
    scores: Object.fromEntries(CFB_TEAMS.map(t => [t, sc.lines[t].reduce((a, b) => a + (Number(b) || 0), 0)])),
    lines: sc.lines, tds: sc.tds, firstTd: sc.firstTd,
  }
}

// Which side of each market the score has already decided -> { ticker: 'yes'|'no' }.
// Per Kalshi's market rules: halves and quarters count only their own points,
// the 4th quarter excludes OT, full-game lines include it, and every TD counts.
function cfbLocks(groups, gs) {
  const locks = {}
  if (gs.state === 'pre') return locks
  const final = gs.state === 'post'
  const periodDone = (n) => final || gs.period > n || (gs.period === n && gs.ended)
  for (const g of groups) {
    const kind = g.series.replace(/^KXNCAAF/, '')
    const q = kind.match(/^([1-4])Q/)
    const periods = kind.startsWith('1H') ? [1, 2] : q ? [Number(q[1])] : null
    const done = periods ? periodDone(periods[periods.length - 1]) : final
    const base = kind.replace(/^(1H|[1-4]Q)/, '') || 'GAME'   // bare "1Q" / "1H" is a winner market
    for (const m of g.markets) {
      const suffix = m.ticker.split('-').pop()
      const team = suffix.replace(/\d+$/, '')
      const other = CFB_TEAMS.find(t => t !== team)
      const known = CFB_TEAMS.includes(team)
      let lock = null
      if (base === 'TOTAL') {
        const total = CFB_TEAMS.reduce((s, t) => s + cfbPts(gs, t, periods), 0)
        if (total > m.strike) lock = 'yes'
        else if (done) lock = 'no'
      } else if (base === 'TEAMTOTAL' && known) {
        if (cfbPts(gs, team, periods) > m.strike) lock = 'yes'
        else if (done) lock = 'no'
      } else if (base === 'SPREAD' && known) {
        if (done) lock = cfbPts(gs, team, periods) - cfbPts(gs, other, periods) > m.strike ? 'yes' : 'no'
      } else if (base === 'GAME') {
        if (done) {
          const [a, b] = CFB_TEAMS
          const pa = cfbPts(gs, a, periods), pb = cfbPts(gs, b, periods)
          lock = suffix === (pa === pb ? 'TIE' : pa > pb ? a : b) ? 'yes' : 'no'
        }
      } else if (base === 'TEAMTD' && known) {
        if ((gs.tds[team] || 0) > m.strike) lock = 'yes'
        else if (final) lock = 'no'
      } else if (base === 'FIRSTTDTEAM') {
        if (gs.firstTd) lock = suffix === gs.firstTd ? 'yes' : 'no'
        else if (final) lock = suffix === 'NONE' ? 'yes' : 'no'
      } else if (base === 'OT') {
        if (gs.period >= 5) lock = 'yes'
        else if (final) lock = 'no'
      }
      if (lock) locks[m.ticker] = lock
    }
  }
  return locks
}

// The sweeper for one period: spread lines `team` has covered by spreadCushion
// (YES) and the other side's lines they'd need that many points to flip (NO);
// total lines already passed (YES) and lines still totalCushion points away (NO).
function cfbComboLegs(groups, gs, cfg) {
  const [key, , periods] = CFB_PERIODS.find(p => p[0] === cfg.period)
  const prefix = key === 'GAME' ? 'KXNCAAF' : `KXNCAAF${key}`
  const markets = (s) => groups.find(g => g.series === prefix + s)?.markets || []
  const other = CFB_TEAMS.find(t => t !== cfg.team)
  const margin = cfbPts(gs, cfg.team, periods) - cfbPts(gs, other, periods)
  const total = CFB_TEAMS.reduce((s, t) => s + cfbPts(gs, t, periods), 0)
  const legs = []
  for (const m of markets('SPREAD')) {
    if (m.strike == null) continue
    const team = m.ticker.split('-').pop().replace(/\d+$/, '')
    if (team === cfg.team && cfg.spreadYes && margin - m.strike >= cfg.spreadCushion) legs.push({ m, side: 'yes', kind: 'SPR' })
    else if (team === other && cfg.spreadNo && margin + m.strike >= cfg.spreadCushion) legs.push({ m, side: 'no', kind: 'SPR' })
  }
  for (const m of markets('TOTAL')) {
    if (m.strike == null) continue
    if (cfg.totalYes && total > m.strike) legs.push({ m, side: 'yes', kind: 'TOT' })
    else if (cfg.totalNo && m.strike - total >= cfg.totalCushion) legs.push({ m, side: 'no', kind: 'TOT' })
  }
  const first = periods ? periods[0] : 1
  const started = gs.state !== 'pre' && gs.period >= first
  return { legs, margin, total, other, started }
}

function SlideToConfirm({ label, busy, disabled, onConfirm, color }) {
  const trackRef = useRef(null)
  const xRef = useRef(0)
  const cbRef = useRef(onConfirm)
  cbRef.current = onConfirm
  const [x, setX] = useState(0)
  const [dragging, setDragging] = useState(false)

  const start = (e) => {
    if (disabled || busy || !trackRef.current) return
    e.preventDefault()
    const rect = trackRef.current.getBoundingClientRect()
    const startX = (e.touches?.[0] || e).clientX
    setDragging(true)
    const move = (ev) => {
      const cx = (ev.touches?.[0] || ev).clientX
      xRef.current = Math.max(0, Math.min(cx - startX, rect.width - 48))
      setX(xRef.current)
    }
    const end = () => {
      document.removeEventListener('mousemove', move)
      document.removeEventListener('mouseup', end)
      document.removeEventListener('touchmove', move)
      document.removeEventListener('touchend', end)
      if (xRef.current >= rect.width - 80) cbRef.current()
      xRef.current = 0
      setX(0)
      setDragging(false)
    }
    document.addEventListener('mousemove', move)
    document.addEventListener('mouseup', end)
    document.addEventListener('touchmove', move, { passive: false })
    document.addEventListener('touchend', end)
  }

  const off = disabled && !busy
  return (
    <div ref={trackRef} style={{
      position: 'relative', height: 48, borderRadius: 24, background: '#0f172a',
      border: `1px solid ${off ? '#334155' : color + '55'}`, overflow: 'hidden',
      userSelect: 'none', WebkitUserSelect: 'none', touchAction: 'none',
    }}>
      <div style={{
        position: 'absolute', left: 0, top: 0, bottom: 0, width: x + 48, borderRadius: 24,
        background: dragging ? `linear-gradient(90deg, ${color}44, ${color}22)` : 'transparent',
        transition: dragging ? 'none' : 'width 0.3s',
      }} />
      <div style={{
        position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 12, fontWeight: 700, letterSpacing: '0.08em', pointerEvents: 'none',
        color: off ? '#475569' : color,
      }}>{busy ? 'EXECUTING...' : label}</div>
      {!off && !busy && (
        <div onMouseDown={start} onTouchStart={start} style={{
          position: 'absolute', top: 2, left: 2 + x, width: 44, height: 44, borderRadius: 22,
          background: color, cursor: 'grab', display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 18, color: '#000', fontWeight: 900, transition: dragging ? 'none' : 'left 0.3s',
        }}>⟩</div>
      )}
    </div>
  )
}

function TradeUnlockModal({ onUnlocked, onClose }) {
  const [pw, setPw] = useState('')
  const [err, setErr] = useState('')
  const submit = async () => {
    setErr('')
    try {
      const r = await fetch(`${API}/api/auth/trade`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: pw }),
      })
      const d = await r.json()
      if (d.ok) {
        localStorage.setItem('pitchpulse_token', d.token)
        onUnlocked(d.token)
      } else setErr(d.error || 'Wrong password')
    } catch { setErr('Connection error') }
  }
  return (
    <div onClick={onClose} style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 100,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <div onClick={e => e.stopPropagation()} style={{ background: '#1e293b', borderRadius: 16, padding: 24, width: 280, border: '1px solid #334155' }}>
        <div style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginBottom: 16, textAlign: 'center' }}>Unlock Trading</div>
        <input value={pw} onChange={e => setPw(e.target.value)} onKeyDown={e => e.key === 'Enter' && submit()}
          placeholder="Enter password" type="password" autoFocus style={{
            width: '100%', padding: '10px 12px', borderRadius: 8, background: '#0f172a',
            border: `1px solid ${err ? '#ef4444' : '#334155'}`, color: '#f1f5f9', fontSize: 15,
            outline: 'none', boxSizing: 'border-box', marginBottom: 8,
          }} />
        {err && <div style={{ fontSize: 12, color: '#ef4444', marginBottom: 8 }}>{err}</div>}
        <button onClick={submit} style={{
          width: '100%', padding: '10px 0', borderRadius: 8, border: 'none', background: '#2563eb',
          color: '#fff', fontSize: 14, fontWeight: 700, cursor: 'pointer',
        }}>Unlock</button>
      </div>
    </div>
  )
}

const cfbChip = (active, color = '#f59e0b') => ({
  flex: 1, padding: '6px 0', borderRadius: 8, fontSize: 12, fontWeight: 700, cursor: 'pointer',
  border: `1px solid ${active ? color : '#334155'}`,
  background: active ? `${color}22` : '#0f172a', color: active ? color : '#94a3b8',
})
const cfbStepBtn = {
  width: 40, height: 40, borderRadius: 10, border: '1px solid #334155', background: '#0f172a',
  color: '#e2e8f0', fontSize: 20, fontWeight: 700, cursor: 'pointer',
}
const cfbMiniBtn = { ...cfbStepBtn, width: 30, height: 30, fontSize: 15 }

// Hand-kept score: points by quarter, TD counts, and where the game is. It's the
// only game state the board uses, and it's saved in this browser.
function CFBScoreKeeper({ sc, setSc }) {
  const [history, setHistory] = useState([])      // undo stack of scoring taps
  const [armReset, setArmReset] = useState(false)
  const idx = Math.max(0, CFB_PHASES.findIndex(p => p.key === sc.phase))
  const ph = CFB_PHASES[idx]
  const scoreCol = ph.scoreIn ? CFB_PHASES.find(p => p.key === ph.scoreIn).period - 1 : -1
  const liveCol = ph.final ? -1 : ph.period - 1
  const tied = CFB_TEAMS.every(t => sc.lines[t].reduce((a, b) => a + b, 0) === sc.lines[CFB_TEAMS[0]].reduce((a, b) => a + b, 0))

  const goTo = (key) => setSc(s => ({ ...s, phase: key, ot: key === 'ot' || (key === 'final' && s.ot) }))
  const forward = () => {
    if (ph.key === 'e4') goTo(tied ? 'ot' : 'final')
    else if (ph.key === 'ot') goTo('final')
    else if (!ph.final) goTo(CFB_PHASES[idx + 1].key)
  }
  const back = () => {
    if (ph.key === 'final') goTo(sc.ot ? 'ot' : 'e4')
    else if (idx > 0) goTo(CFB_PHASES[idx - 1].key)
  }

  const score = (team, pts, td) => {
    if (!ph.scoreIn) return
    const col = scoreCol
    setHistory(h => [...h, { team, col, pts, td, phase: sc.phase, ot: sc.ot, wasFirst: td && !sc.firstTd }])
    setSc(s => ({
      ...s, phase: ph.scoreIn, ot: s.ot || ph.scoreIn === 'ot',
      lines: { ...s.lines, [team]: s.lines[team].map((v, i) => (i === col ? v + pts : v)) },
      tds: td ? { ...s.tds, [team]: s.tds[team] + 1 } : s.tds,
      firstTd: td && !s.firstTd ? team : s.firstTd,
    }))
  }
  const undo = () => {
    const last = history[history.length - 1]
    if (!last) return
    setHistory(h => h.slice(0, -1))
    setSc(s => ({
      ...s, phase: last.phase, ot: last.ot,
      lines: { ...s.lines, [last.team]: s.lines[last.team].map((v, i) => (i === last.col ? Math.max(0, v - last.pts) : v)) },
      tds: last.td ? { ...s.tds, [last.team]: Math.max(0, s.tds[last.team] - 1) } : s.tds,
      firstTd: last.wasFirst ? null : s.firstTd,
    }))
  }
  const setCell = (team, i, v) => setSc(s => ({ ...s, lines: { ...s.lines, [team]: s.lines[team].map((x, j) => (j === i ? Math.max(0, v) : x)) } }))
  const bumpTd = (team, d) => setSc(s => {
    const tds = { ...s.tds, [team]: Math.max(0, s.tds[team] + d) }
    const none = CFB_TEAMS.every(t => !tds[t])
    return { ...s, tds, firstTd: none ? null : s.firstTd || (d > 0 ? team : null) }
  })
  const reset = () => {
    if (!armReset) { setArmReset(true); setTimeout(() => setArmReset(false), 3000); return }
    setArmReset(false)
    setHistory([])
    setSc(CFB_BLANK_SCORE)
  }

  const cols = '46px repeat(5, 1fr) 30px 78px'
  const cell = (active) => ({
    width: '100%', padding: '4px 0', borderRadius: 6, textAlign: 'center', fontSize: 14, fontWeight: 700,
    background: '#0f172a', color: '#f1f5f9', outline: 'none',
    border: `1px solid ${active ? '#f59e0b' : '#334155'}`,
  })
  return (
    <div style={{ background: '#1e293b', borderRadius: 12, padding: 12, marginBottom: 10, border: '1px solid #f59e0b44' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <button style={cfbMiniBtn} disabled={idx === 0} onClick={back}>◀</button>
        <div style={{ textAlign: 'center', minWidth: 110 }}>
          <div style={{ fontSize: 9, color: '#475569' }}>GAME STATE</div>
          <div style={{ fontSize: 15, fontWeight: 800, color: '#f59e0b' }}>{ph.label}</div>
        </div>
        <button style={cfbMiniBtn} disabled={ph.final} onClick={forward}>▶</button>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 12, fontSize: 11 }}>
          <span onClick={undo} style={{ color: history.length ? '#3b82f6' : '#334155', cursor: history.length ? 'pointer' : 'default' }}>undo</span>
          <span onClick={reset} style={{ color: armReset ? '#ef4444' : '#475569', cursor: 'pointer' }}>{armReset ? 'tap to reset' : 'reset'}</span>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: cols, gap: 4, alignItems: 'center', fontSize: 10, color: '#475569', marginBottom: 4 }}>
        <span />
        {['Q1', 'Q2', 'Q3', 'Q4', 'OT'].map((q, i) => (
          <span key={q} style={{ textAlign: 'center', color: i === liveCol ? '#f59e0b' : '#475569', fontWeight: i === liveCol ? 800 : 400 }}>{q}</span>
        ))}
        <span style={{ textAlign: 'center' }}>T</span>
        <span style={{ textAlign: 'center' }}>TDs</span>
      </div>
      {CFB_TEAMS.map(t => (
        <div key={t} style={{ display: 'grid', gridTemplateColumns: cols, gap: 4, alignItems: 'center', marginBottom: 4 }}>
          <span style={{ fontSize: 13, fontWeight: 800, color: '#e2e8f0' }}>{t}</span>
          {sc.lines[t].map((v, i) => (
            <input key={i} type="number" inputMode="numeric" value={v} style={cell(i === liveCol)}
              onChange={e => setCell(t, i, Number(e.target.value) || 0)} />
          ))}
          <span style={{ textAlign: 'center', fontSize: 17, fontWeight: 900, color: '#f1f5f9' }}>
            {sc.lines[t].reduce((a, b) => a + b, 0)}
          </span>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 2 }}>
            <button style={{ ...cfbMiniBtn, width: 22, height: 24, fontSize: 12 }} onClick={() => bumpTd(t, -1)}>−</button>
            <span style={{ fontSize: 13, fontWeight: 700, color: '#e2e8f0', minWidth: 16, textAlign: 'center' }}>{sc.tds[t]}</span>
            <button style={{ ...cfbMiniBtn, width: 22, height: 24, fontSize: 12 }} onClick={() => bumpTd(t, 1)}>+</button>
          </div>
        </div>
      ))}

      <div style={{ marginTop: 8 }}>
        {CFB_TEAMS.map(t => (
          <div key={t} style={{ display: 'flex', gap: 4, alignItems: 'center', marginBottom: 4 }}>
            <span style={{ width: 42, fontSize: 11, fontWeight: 800, color: '#94a3b8' }}>{t}</span>
            {CFB_SCORES.map(([lab, pts, td]) => (
              <button key={lab} disabled={!ph.scoreIn} onClick={() => score(t, pts, td)} style={{
                ...cfbChip(false), padding: '7px 0', color: td ? '#22c55e' : '#e2e8f0', opacity: ph.scoreIn ? 1 : 0.4,
              }}>{lab}</button>
            ))}
          </div>
        ))}
      </div>
      <div style={{ fontSize: 10, color: '#475569', marginTop: 4 }}>
        {sc.firstTd ? `First TD: ${sc.firstTd} · ` : ''}Scoring buttons add to {scoreCol >= 0 ? ['Q1', 'Q2', 'Q3', 'Q4', 'OT'][scoreCol] : '—'} (a score during a break starts the next quarter). Tap a cell to fix a number.
      </div>
    </div>
  )
}

function CFBMarketRow({ m, sel, isLine, lock, onPick }) {
  const btn = (side) => {
    const ask = side === 'yes' ? m.yes_ask : m.no_ask
    const active = sel?.ticker === m.ticker && sel?.side === side
    const color = CFB_SIDE_COLOR[side]
    return (
      <button disabled={ask == null} onClick={() => onPick(m, side)} style={{
        width: 58, padding: '5px 0', borderRadius: 8, lineHeight: 1.15,
        border: `1px solid ${active ? color : '#334155'}`, background: active ? `${color}22` : '#0f172a',
        color: ask == null ? '#334155' : color, fontSize: 15, fontWeight: 800,
        cursor: ask == null ? 'default' : 'pointer',
      }}>
        <div style={{ fontSize: 9, fontWeight: 700, opacity: 0.7 }}>{side.toUpperCase()}</div>
        {ask != null ? `${ask}¢` : '—'}
      </button>
    )
  }
  const spread = m.yes_ask != null && m.yes_bid != null ? m.yes_ask - m.yes_bid : null
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 6, padding: '6px 0 6px 8px',
      borderTop: '1px solid #0f172a', borderLeft: `2px solid ${isLine ? '#f59e0b' : 'transparent'}`,
    }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, color: '#e2e8f0', lineHeight: 1.25 }}>
          {m.label}
          {lock && (
            <span title="Decided by the score" style={{ marginLeft: 6, fontSize: 10, fontWeight: 800, color: CFB_SIDE_COLOR[lock] }}>
              🔒 {lock.toUpperCase()}
            </span>
          )}
        </div>
        <div style={{ fontSize: 10, color: '#475569' }}>
          {spread != null ? `spread ${spread}¢` : 'one-sided'} · vol {m.volume.toLocaleString()}
          {m.pos ? (
            <span style={{ color: m.pos > 0 ? CFB_SIDE_COLOR.yes : CFB_SIDE_COLOR.no, fontWeight: 700 }}>
              {' '}· you {Math.abs(m.pos)} {m.pos > 0 ? 'YES' : 'NO'}
            </span>
          ) : null}
        </div>
      </div>
      {btn('yes')}
      {btn('no')}
    </div>
  )
}

function CFBSweepPanel({ sweep, setSweep, combo, legs, plan, max, setMax, budget, setBudget, token, busy, result, onUnlock, onExecute, onClose, onDismiss }) {
  const amber = '#f59e0b'
  const planned = Object.fromEntries((plan?.legs || []).map(l => [`${l.ticker}:${l.side}`, l]))
  const cost = plan?.total_cost_cents || 0, fee = plan?.fee_cents || 0, payout = plan?.payout_cents || 0
  const nFill = plan?.legs?.length || 0
  const set = (patch) => setSweep({ ...sweep, ...patch })
  const check = (key, label) => (
    <label style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer', fontSize: 12, color: sweep[key] ? '#e2e8f0' : '#475569' }}>
      <input type="checkbox" checked={sweep[key]} onChange={e => set({ [key]: e.target.checked })} />{label}
    </label>
  )
  const cushion = (key) => (
    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
      <button style={cfbMiniBtn} onClick={() => set({ [key]: Math.max(1, sweep[key] - 1) })}>−</button>
      <b style={{ color: '#e2e8f0', fontSize: 12, minWidth: 40, textAlign: 'center' }}>{sweep[key]} pts</b>
      <button style={cfbMiniBtn} onClick={() => set({ [key]: sweep[key] + 1 })}>+</button>
    </div>
  )
  const rowLabel = { width: 44, fontSize: 10, fontWeight: 800, color: '#475569' }
  return (
    <div style={{ position: 'fixed', left: 0, right: 0, bottom: 0, zIndex: 50, display: 'flex', justifyContent: 'center', pointerEvents: 'none' }}>
      <div style={{
        width: '100%', maxWidth: 480, maxHeight: '88vh', overflowY: 'auto', pointerEvents: 'auto', background: '#1e293b',
        borderTop: `2px solid ${amber}`, borderRadius: '14px 14px 0 0',
        padding: '12px 16px calc(12px + env(safe-area-inset-bottom))', boxShadow: '0 -8px 24px rgba(0,0,0,0.5)',
      }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8, marginBottom: 8 }}>
          <span style={{ fontSize: 11, fontWeight: 800, color: '#000', background: amber, borderRadius: 4, padding: '2px 6px' }}>SWEEP</span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: '#e2e8f0' }}>{sweep.title}</div>
            <div style={{ fontSize: 10, color: '#475569' }}>{legs.length} markets with asks ≤{max}¢ · cheapest asks fill first</div>
          </div>
          <span onClick={onClose} style={{ fontSize: 18, color: '#475569', cursor: 'pointer', lineHeight: 1 }}>×</span>
        </div>

        {sweep.kind === 'combo' && combo && (
          <div style={{ marginBottom: 8 }}>
            <div style={{ display: 'flex', gap: 4, marginBottom: 6 }}>
              {CFB_PERIODS.map(([key, label]) => (
                <button key={key} style={{ ...cfbChip(sweep.period === key), padding: '5px 0' }} onClick={() => set({ period: key })}>{label}</button>
              ))}
            </div>
            <div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 6 }}>
              {sweep.team} {combo.margin >= 0 ? '+' : ''}{combo.margin} · total {combo.total}
              {!combo.started && <span style={{ color: amber }}> · this period hasn't started, so nothing here is covered yet</span>}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6, flexWrap: 'wrap' }}>
              <span style={rowLabel}>SPREAD</span>
              {CFB_TEAMS.map(t => (
                <button key={t} style={{ ...cfbChip(sweep.team === t), flex: 'none', width: 48, padding: '5px 0' }} onClick={() => set({ team: t })}>{t}</button>
              ))}
              {cushion('spreadCushion')}
              {check('spreadYes', `YES ${sweep.team}`)}
              {check('spreadNo', `NO ${combo.other}`)}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
              <span style={rowLabel}>TOTAL</span>
              {cushion('totalCushion')}
              {check('totalYes', 'YES passed')}
              {check('totalNo', 'NO unders')}
            </div>
          </div>
        )}

        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
          <button style={cfbStepBtn} onClick={() => setMax(v => Math.max(1, v - 1))}>−</button>
          <div style={{ flex: 1, textAlign: 'center' }}>
            <div style={{ fontSize: 9, color: '#475569' }}>MAX PRICE (EVERY MARKET)</div>
            <div style={{ fontSize: 26, fontWeight: 900, color: amber, lineHeight: 1 }}>{max}¢</div>
          </div>
          <button style={cfbStepBtn} onClick={() => setMax(v => Math.min(99, v + 1))}>+</button>
        </div>
        <input type="range" min={1} max={99} value={max} onChange={e => setMax(Number(e.target.value))}
          style={{ width: '100%', accentColor: amber, margin: '2px 0 8px' }} />

        <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8 }}>
          {CFB_SWEEP_BUDGETS.map(v => (
            <button key={v} style={cfbChip(budget === v)} onClick={() => setBudget(v)}>${v}</button>
          ))}
          <div style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <span style={{ fontSize: 12, color: '#94a3b8' }}>$</span>
            <input value={budget} onChange={e => setBudget(Number(e.target.value) || 0)} type="number" inputMode="decimal"
              style={{ width: 56, padding: '5px 6px', borderRadius: 8, background: '#0f172a', border: '1px solid #334155', color: '#f1f5f9', fontSize: 13, outline: 'none' }} />
          </div>
        </div>

        <div style={{ maxHeight: 130, overflowY: 'auto', marginBottom: 8, borderTop: '1px solid #0f172a' }}>
          {legs.length === 0 && <div style={{ fontSize: 12, color: '#475569', padding: '6px 0' }}>No markets qualify right now.</div>}
          {legs.map(l => {
            const p = planned[`${l.ticker}:${l.side}`]
            return (
              <div key={l.ticker} style={{ display: 'flex', gap: 6, fontSize: 11, padding: '3px 0', color: '#94a3b8' }}>
                <span style={{ width: 30, color: '#475569', fontWeight: 700 }}>{l.kind}</span>
                <span style={{ color: CFB_SIDE_COLOR[l.side], fontWeight: 800, width: 26 }}>{l.side.toUpperCase()}</span>
                <span style={{ flex: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', color: '#e2e8f0' }}>{l.label}</span>
                <span>{l.ask}¢</span>
                <span style={{ width: 66, textAlign: 'right', color: p ? '#e2e8f0' : '#334155' }}>
                  {p ? `${p.contracts} @ ${(p.cost_cents / p.contracts).toFixed(1)}` : '—'}
                </span>
              </div>
            )
          })}
        </div>

        <div style={{ fontSize: 12, color: '#94a3b8', marginBottom: 10, minHeight: 16 }}>
          {plan?.error ? <span style={{ color: '#ef4444' }}>{plan.error}</span>
            : !plan ? (legs.length ? 'Pricing...' : '')
            : plan.total_contracts === 0 ? <span style={{ color: '#475569' }}>Nothing fills at ≤{max}¢</span>
            : <>≈ <b style={{ color: '#e2e8f0' }}>{plan.total_contracts}</b> in {nFill} mkts · ${(cost / 100).toFixed(2)} + ~${(fee / 100).toFixed(2)} fee · pays ${(payout / 100).toFixed(2)} · <b style={{ color: '#22c55e' }}>+${((payout - cost - fee) / 100).toFixed(2)}</b> if all win</>}
        </div>

        {token
          ? <SlideToConfirm color={amber} busy={busy} disabled={!plan?.total_contracts}
              label={`SLIDE TO SWEEP ${nFill} MARKETS →`} onConfirm={onExecute} />
          : <button onClick={onUnlock} style={{
              width: '100%', height: 48, borderRadius: 24, border: '1px solid #f59e0b55',
              background: '#0f172a', color: amber, fontSize: 13, fontWeight: 700, cursor: 'pointer',
            }}>Unlock trading</button>}

        {result && (
          <div style={{ marginTop: 8, fontSize: 12 }}>
            {result.ok
              ? <span style={{ color: '#22c55e', fontWeight: 700 }}>
                  Filled {result.summary.filled}/{result.summary.planned} across {result.summary.legs_filled} markets · ≤${(result.summary.cost_cents / 100).toFixed(2)}
                </span>
              : <span style={{ color: '#ef4444', wordBreak: 'break-word' }}>Not filled: {result.error || result.summary?.errors?.[0] || 'nothing at that price'}</span>}
            {result.ok && result.summary.failed > 0 && (
              <div style={{ color: '#ef4444', wordBreak: 'break-word' }}>{result.summary.failed} orders failed: {result.summary.errors[0]}</div>
            )}
            <span onClick={onDismiss} style={{ marginLeft: 8, color: '#475569', cursor: 'pointer' }}>dismiss</span>
          </div>
        )}
      </div>
    </div>
  )
}

function CFBTab() {
  const [snap, setSnap] = useState(null)
  const [err, setErr] = useState('')
  const [live, setLive] = useState({})        // ticker -> { yes_bid, yes_ask } (0-1, from WS)
  const [wsUp, setWsUp] = useState(false)
  const [open, setOpen] = useState({})        // series -> expanded?
  const [sel, setSel] = useState(null)        // { ticker, side, label, group }
  const [ob, setOb] = useState(null)
  const [take, setTake] = useState(50)        // cents: the most we'll pay per contract
  const [spend, setSpend] = useState(25)      // dollars
  const [token, setToken] = useState(() => localStorage.getItem('pitchpulse_token') || '')
  const [showPin, setShowPin] = useState(false)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const [sc, setSc] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(CFB_SCORE_KEY))
      if (saved?.lines && saved?.tds) return saved
    } catch {}
    return CFB_BLANK_SCORE
  })
  const [sweep, setSweep] = useState(null)    // { kind: 'locks'|'combo', ... } — see openSweep calls
  const [sweepMax, setSweepMax] = useState(97)
  const [sweepBudget, setSweepBudget] = useState(50)
  const [sweepPlan, setSweepPlan] = useState(null)
  const [sweepResult, setSweepResult] = useState(null)

  useEffect(() => {
    try { localStorage.setItem(CFB_SCORE_KEY, JSON.stringify(sc)) } catch {}
  }, [sc])

  // Snapshot every 30s picks up new/closed markets; the socket carries prices between.
  useEffect(() => {
    let alive = true
    const load = () => fetch(`${API}/api/cfb/markets?game=${CFB_GAME}`)
      .then(r => r.json())
      .then(d => {
        if (!alive) return
        if (d.groups?.length) { setSnap(d); setErr('') } else setErr(d.error || 'No open markets found')
      })
      .catch(e => alive && setErr(e.message))
    load()
    const t = setInterval(load, 30000)
    return () => { alive = false; clearInterval(t) }
  }, [])

  useEffect(() => {
    let ws, timer, alive = true
    const connect = () => {
      ws = new WebSocket(getKalshiWsUrl({ cfbGame: CFB_GAME }))
      ws.onmessage = (e) => {
        const d = JSON.parse(e.data)
        if (d.status === 'connected') setWsUp(true)
        else if (d.type === 'price') setLive(prev => ({ ...prev, [d.ticker]: { yes_bid: d.yes_bid, yes_ask: d.yes_ask } }))
      }
      ws.onclose = () => { setWsUp(false); if (alive) timer = setTimeout(connect, 3000) }
      ws.onerror = () => ws.close()
    }
    connect()
    return () => { alive = false; clearTimeout(timer); ws?.close() }
  }, [])

  // My positions on this game (account data, so it needs the trade token)
  const [pos, setPos] = useState({})          // ticker -> signed contracts (+YES / −NO)
  useEffect(() => {
    if (!token) { setPos({}); return }
    let alive = true
    const load = () => fetch(`${API}/api/cfb/positions`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ game: CFB_GAME, trade_token: token }),
    }).then(r => r.json()).then(d => {
      if (alive && d.ok) setPos(Object.fromEntries(Object.entries(d.positions).map(([t, p]) => [t, p.position])))
    }).catch(() => {})
    load()
    const t = setInterval(load, 5000)
    return () => { alive = false; clearInterval(t) }
  }, [token])

  const withLive = (m) => {
    const l = live[m.ticker]
    const base = pos[m.ticker] ? { ...m, pos: pos[m.ticker] } : m
    if (!l) return base
    const yb = l.yes_bid > 0 ? Math.round(l.yes_bid * 100) : null
    const ya = l.yes_ask > 0 && l.yes_ask < 1 ? Math.round(l.yes_ask * 100) : null
    return { ...base, yes_bid: yb, yes_ask: ya, no_bid: ya != null ? 100 - ya : null, no_ask: yb != null ? 100 - yb : null }
  }

  // Full book for the market in the ticket, refreshed fast while it's open
  const selTicker = sel?.ticker
  const fetchOb = useCallback(async () => {
    if (!selTicker) return
    try {
      const r = await fetch(`${API}/api/kalshi/orderbook/${selTicker}`)
      const d = await r.json()
      if (!d.error && d.ticker === selTicker) setOb(d)
    } catch {}
  }, [selTicker])

  useEffect(() => {
    setOb(null)
    if (!selTicker) return
    fetchOb()
    const t = setInterval(fetchOb, 2000)
    return () => clearInterval(t)
  }, [selTicker, fetchOb])

  const groups = snap ? snap.groups.map(g => ({ ...g, markets: g.markets.map(withLive) })) : []
  const gs = cfbGameState(sc)
  const locks = cfbLocks(groups, gs)
  const pregame = gs.state === 'pre'

  const askFor = (m, side) => (side === 'yes' ? m.yes_ask : m.no_ask)
  const lockLegs = (series) => groups
    .filter(g => !series || g.series === series)
    .flatMap(g => g.markets
      .filter(m => locks[m.ticker] && askFor(m, locks[m.ticker]) != null)
      .map(m => ({ ticker: m.ticker, side: locks[m.ticker], label: m.label, ask: askFor(m, locks[m.ticker]), kind: 'LOCK' })))
  const allLockLegs = lockLegs(null)
  const leader = [...CFB_TEAMS].sort((a, b) => gs.scores[b] - gs.scores[a])[0]

  let sweepLegs = [], combo = null
  if (sweep?.kind === 'locks') {
    sweepLegs = lockLegs(sweep.series).filter(l => l.ask <= sweepMax)
  } else if (sweep?.kind === 'combo') {
    combo = cfbComboLegs(groups, gs, sweep)
    sweepLegs = combo.legs
      .map(({ m, side, kind }) => ({ ticker: m.ticker, side, label: m.label, ask: askFor(m, side), kind }))
      .filter(l => l.ask != null && l.ask <= sweepMax)
  }

  const legKey = sweepLegs.map(l => `${l.ticker}:${l.side}`).join(',')
  useEffect(() => {
    if (!legKey) { setSweepPlan(null); return }
    let alive = true
    const legs = legKey.split(',').map(k => { const [ticker, side] = k.split(':'); return { ticker, side } })
    const load = () => fetch(`${API}/api/cfb/sweep/preview`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ legs, max_price_cents: sweepMax, budget_cents: Math.round(sweepBudget * 100) }),
    }).then(r => r.json()).then(d => { if (alive) setSweepPlan(d) }).catch(() => {})
    const first = setTimeout(load, 300)
    const t = setInterval(load, 4000)
    return () => { alive = false; clearTimeout(first); clearInterval(t) }
  }, [legKey, sweepMax, sweepBudget])

  const pick = (m, side, group) => {
    if (sel?.ticker === m.ticker && sel?.side === side) { setSel(null); return }
    const ask = side === 'yes' ? m.yes_ask : m.no_ask
    setSweep(null)
    setSel({ ticker: m.ticker, side, label: m.label, group })
    setTake(ask ?? 50)
    setResult(null)
  }

  const openSweep = (cfg) => {
    setSel(null)
    setSweepResult(null)
    setSweepPlan(null)
    setSweep(cfg)
  }

  const lock = () => { localStorage.removeItem('pitchpulse_token'); setToken('') }

  const ladder = sideLadder(ob, sel?.side)
  const liveSel = sel && groups.flatMap(g => g.markets).find(m => m.ticker === sel.ticker)
  const bestAsk = ladder.asks[0]?.price ?? (liveSel ? (sel.side === 'yes' ? liveSel.yes_ask : liveSel.no_ask) : null)
  const plan = cfbSweep(ladder.asks, take, Math.round(spend * 100))
  const depth = ladder.asks.filter(l => l.price <= take).reduce((s, l) => s + l.size, 0)
  const over = bestAsk != null ? take - bestAsk : null
  const sideColor = CFB_SIDE_COLOR[sel?.side] || '#22c55e'

  const execute = async () => {
    if (!sel || !token) return
    const { ticker, side, label } = sel
    setBusy(true)
    setResult(null)
    try {
      const r = await fetch(`${API}/api/trade/execute`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ticker, side, max_price_cents: take,
          max_spend_cents: Math.round(spend * 100), trade_token: token,
        }),
      })
      const d = await r.json()
      setResult({ ...d, label, side, take })
      if (d?.error === 'Unauthorized') { lock(); setShowPin(true) }
    } catch (e) {
      setResult({ ok: false, error: e.message })
    } finally {
      setBusy(false)
      fetchOb()
    }
  }

  const executeSweep = async () => {
    if (!token || !sweepLegs.length) return
    setBusy(true)
    setSweepResult(null)
    try {
      const r = await fetch(`${API}/api/cfb/sweep/execute`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          legs: sweepLegs.map(({ ticker, side }) => ({ ticker, side })),
          max_price_cents: sweepMax, budget_cents: Math.round(sweepBudget * 100), trade_token: token,
        }),
      })
      const d = await r.json()
      setSweepResult(d)
      if (d?.error === 'Unauthorized') { lock(); setShowPin(true) }
    } catch (e) {
      setSweepResult({ ok: false, error: e.message })
    } finally {
      setBusy(false)
    }
  }

  const expanded = (s) => open[s] ?? CFB_DEFAULT_OPEN.has(s)
  const setAll = (v) => setOpen(Object.fromEntries((snap?.groups || []).map(g => [g.series, v])))
  const chip = (activeNow) => cfbChip(activeNow, sideColor)
  const canLocks = !pregame && allLockLegs.length > 0
  const nLocked = Object.keys(locks).length

  return (
    <div style={{ animation: 'fadeIn 0.3s ease' }}>
      {showPin && <TradeUnlockModal onClose={() => setShowPin(false)}
        onUnlocked={(t) => { setToken(t); setShowPin(false) }} />}

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 800, color: '#e2e8f0' }}>{(snap?.title || 'Rice vs Notre Dame').toUpperCase()}</div>
          <div style={{ fontSize: 11, color: '#475569' }}>
            Sat 9/12 · 3:30 PM ET{snap ? ` · ${snap.market_count} markets · ${snap.groups.length} types` : ''}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {token
            ? <span onClick={lock} style={{ fontSize: 10, color: '#f59e0b', fontWeight: 700, cursor: 'pointer' }}>TRADING ●</span>
            : <span onClick={() => setShowPin(true)} style={{ fontSize: 10, color: '#475569', fontWeight: 600, cursor: 'pointer' }}>VIEW ONLY</span>}
          {wsUp && <span style={{ fontSize: 10, color: '#22c55e', fontWeight: 700 }}>● LIVE</span>}
        </div>
      </div>

      <CFBScoreKeeper sc={sc} setSc={setSc} />

      {snap && (
        <>
          <div style={{ display: 'flex', gap: 8, marginBottom: 4 }}>
            <button disabled={!canLocks} onClick={() => openSweep({ kind: 'locks', series: null, title: 'Every locked market' })} style={{
              ...cfbChip(canLocks), flex: 1, padding: '9px 0', opacity: canLocks ? 1 : 0.5, cursor: canLocks ? 'pointer' : 'default',
            }}>🔒 Sweep locks ({pregame ? 0 : allLockLegs.length})</button>
            <button disabled={pregame} onClick={() => openSweep({
              kind: 'combo', title: 'Sweeper', period: 'GAME', team: leader,
              spreadCushion: 9, totalCushion: 14, spreadYes: true, spreadNo: true, totalYes: true, totalNo: true,
            })} style={{ ...cfbChip(false), flex: 1, padding: '9px 0', opacity: pregame ? 0.5 : 1, cursor: pregame ? 'default' : 'pointer' }}>
              ⚡ Sweeper
            </button>
          </div>
          <div style={{ fontSize: 10, color: '#475569', marginBottom: 10 }}>
            {pregame ? 'Sweeps unlock once you move the game state past Pregame.'
              : `${nLocked} markets decided by your score.`}
          </div>
        </>
      )}

      {err && !snap && <div style={{ fontSize: 13, color: '#ef4444', textAlign: 'center', padding: 20 }}>{err}</div>}
      {!snap && !err && <div style={{ fontSize: 13, color: '#475569', textAlign: 'center', padding: 40 }}>Loading Kalshi markets...</div>}

      {snap && (
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 12, marginBottom: 8, fontSize: 11 }}>
          <span onClick={() => setAll(true)} style={{ color: '#3b82f6', cursor: 'pointer' }}>expand all</span>
          <span onClick={() => setAll(false)} style={{ color: '#3b82f6', cursor: 'pointer' }}>collapse all</span>
        </div>
      )}

      {groups.map(g => {
        const isOpen = expanded(g.series)
        const markets = g.markets
        const groupLocks = lockLegs(g.series).length
        // Flag the market priced closest to a coin flip — the de facto line on a ladder
        let lineIdx = -1
        if (markets.length > 3) {
          let best = Infinity
          markets.forEach((m, i) => {
            if (m.yes_bid == null || m.yes_ask == null) return
            const d = Math.abs((m.yes_bid + m.yes_ask) / 2 - 50)
            if (d < best) { best = d; lineIdx = i }
          })
        }
        return (
          <div key={g.series} style={{ background: '#1e293b', borderRadius: 12, marginBottom: 8, border: '1px solid #334155', overflow: 'hidden' }}>
            <div onClick={() => setOpen(o => ({ ...o, [g.series]: !isOpen }))} style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              padding: '10px 12px', cursor: 'pointer', gap: 8,
            }}>
              <span style={{ flex: 1, fontSize: 13, fontWeight: 700, color: '#e2e8f0' }}>{g.title}</span>
              {groupLocks > 0 && (
                <span onClick={(e) => { e.stopPropagation(); openSweep({ kind: 'locks', series: g.series, title: `Locked · ${g.title}` }) }}
                  style={{ fontSize: 11, fontWeight: 700, color: '#f59e0b', cursor: 'pointer' }}>🔒 sweep {groupLocks}</span>
              )}
              <span style={{ fontSize: 11, color: '#475569' }}>{markets.length} {isOpen ? '▼' : '▶'}</span>
            </div>
            {isOpen && (
              <div style={{ padding: '0 10px 6px 4px' }}>
                {markets.map((m, i) => (
                  <CFBMarketRow key={m.ticker} m={m} sel={sel} isLine={i === lineIdx} lock={locks[m.ticker]}
                    onPick={(mk, side) => pick(mk, side, g.title)} />
                ))}
              </div>
            )}
          </div>
        )
      })}

      {/* Room so the fixed ticket / sweep panel never covers the last rows */}
      {(sel || sweep) && <div style={{ height: sweep ? 560 : 340 }} />}

      {sweep && (
        <CFBSweepPanel sweep={sweep} setSweep={setSweep} combo={combo} legs={sweepLegs} plan={sweepPlan}
          max={sweepMax} setMax={setSweepMax} budget={sweepBudget} setBudget={setSweepBudget}
          token={token} busy={busy} result={sweepResult} onUnlock={() => setShowPin(true)}
          onExecute={executeSweep} onClose={() => setSweep(null)} onDismiss={() => setSweepResult(null)} />
      )}

      {sel && (
        <div style={{ position: 'fixed', left: 0, right: 0, bottom: 0, zIndex: 50, display: 'flex', justifyContent: 'center', pointerEvents: 'none' }}>
          <div style={{
            width: '100%', maxWidth: 480, pointerEvents: 'auto', background: '#1e293b',
            borderTop: `2px solid ${sideColor}`, borderRadius: '14px 14px 0 0',
            padding: '12px 16px calc(12px + env(safe-area-inset-bottom))',
            boxShadow: '0 -8px 24px rgba(0,0,0,0.5)',
          }}>
            {/* What we're buying */}
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8, marginBottom: 10 }}>
              <span style={{ fontSize: 11, fontWeight: 800, color: '#000', background: sideColor, borderRadius: 4, padding: '2px 6px' }}>
                BUY {sel.side.toUpperCase()}
              </span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: '#e2e8f0', lineHeight: 1.25 }}>{sel.label}</div>
                <div style={{ fontSize: 10, color: '#475569' }}>{sel.group}</div>
              </div>
              <span onClick={() => setSel(null)} style={{ fontSize: 18, color: '#475569', cursor: 'pointer', lineHeight: 1 }}>×</span>
            </div>

            {/* Take price */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
              <button style={cfbStepBtn} onClick={() => setTake(t => Math.max(1, t - 1))}>−</button>
              <div style={{ flex: 1, textAlign: 'center' }}>
                <div style={{ fontSize: 9, color: '#475569' }}>MAX PRICE</div>
                <div style={{ fontSize: 28, fontWeight: 900, color: sideColor, lineHeight: 1 }}>{take}¢</div>
                <div style={{ fontSize: 10, color: over != null && over >= 5 ? '#f59e0b' : '#475569' }}>
                  {bestAsk == null ? 'no ask' : over === 0 ? 'at best ask' : over > 0 ? `${over}¢ over ask (${bestAsk}¢)` : `${-over}¢ under ask (${bestAsk}¢)`}
                </div>
              </div>
              <button style={cfbStepBtn} onClick={() => setTake(t => Math.min(99, t + 1))}>+</button>
            </div>
            <input type="range" min={1} max={99} value={take} onChange={e => setTake(Number(e.target.value))}
              style={{ width: '100%', accentColor: sideColor, margin: '2px 0 8px' }} />
            <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
              {CFB_BUMPS.map(([b, lab]) => (
                <button key={lab} disabled={bestAsk == null} style={chip(bestAsk != null && take === Math.min(99, bestAsk + b))}
                  onClick={() => setTake(Math.min(99, bestAsk + b))}>{lab}</button>
              ))}
            </div>

            {/* Spend */}
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8 }}>
              {CFB_SPEND_CHIPS.map(v => (
                <button key={v} style={chip(spend === v)} onClick={() => setSpend(v)}>${v}</button>
              ))}
              <div style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                <span style={{ fontSize: 12, color: '#94a3b8' }}>$</span>
                <input value={spend} onChange={e => setSpend(Number(e.target.value) || 0)} type="number" inputMode="decimal"
                  style={{ width: 52, padding: '5px 6px', borderRadius: 8, background: '#0f172a', border: '1px solid #334155', color: '#f1f5f9', fontSize: 13, outline: 'none' }} />
              </div>
            </div>

            {/* Fill preview from the live book */}
            <div style={{ fontSize: 12, color: '#94a3b8', marginBottom: 10, minHeight: 16 }}>
              {!ob ? 'Loading book...'
                : plan.contracts === 0 ? <span style={{ color: '#475569' }}>Nothing fills at ≤{take}¢ ({depth.toLocaleString()} available)</span>
                : <>≈ <b style={{ color: '#e2e8f0' }}>{plan.contracts}</b> @ avg {(plan.cost / plan.contracts).toFixed(1)}¢ · ${(plan.cost / 100).toFixed(2)} + ~${(plan.fee / 100).toFixed(2)} fee · pays <b style={{ color: '#22c55e' }}>${plan.contracts.toFixed(2)}</b></>}
            </div>

            {token
              ? <SlideToConfirm color={sideColor} busy={busy} disabled={!ob || plan.contracts === 0}
                  label={`SLIDE TO BUY ${sel.side.toUpperCase()} ≤${take}¢ →`} onConfirm={execute} />
              : <button onClick={() => setShowPin(true)} style={{
                  width: '100%', height: 48, borderRadius: 24, border: '1px solid #f59e0b55',
                  background: '#0f172a', color: '#f59e0b', fontSize: 13, fontWeight: 700, cursor: 'pointer',
                }}>Unlock trading</button>}

            {result && (
              <div style={{ marginTop: 8, fontSize: 12 }}>
                {result.ok
                  ? <span style={{ color: '#22c55e', fontWeight: 700 }}>
                      Filled {result.summary.total_contracts} {result.side?.toUpperCase()} @ avg {(result.summary.total_cost_cents / result.summary.total_contracts).toFixed(1)}¢ · ${(result.summary.total_cost_cents / 100).toFixed(2)}
                    </span>
                  : <span style={{ color: '#ef4444', wordBreak: 'break-word' }}>
                      Not filled: {result.error || result.orders?.find(o => o.error)?.error || 'no contracts at that price'}
                    </span>}
                <span onClick={() => setResult(null)} style={{ marginLeft: 8, color: '#475569', cursor: 'pointer' }}>dismiss</span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Fantasy draft board (multi-source PPR consensus) ─────────────────────────
const FF_POSITIONS = ['ALL', 'FLEX', 'QB', 'RB', 'WR', 'TE', 'K', 'DEF']
const FF_SORTS = [['consensus', 'Board'], ['value', 'Value'], ['spread', 'Disagree']]
const FF_POS_COLOR = { QB: '#f97316', RB: '#22c55e', WR: '#3b82f6', TE: '#a855f7', K: '#eab308', DEF: '#64748b' }
const FF_SRC_COLOR = {
  fantasypros: '#3b82f6', espn: '#ef4444', yahoo: '#a855f7', ffc: '#22c55e', sleeper: '#f59e0b',
}
const FF_SRC_SHORT = { fantasypros: 'FPros', espn: 'ESPN', yahoo: 'Yahoo', ffc: 'FFC', sleeper: 'Sleep' }

const ffInjColor = (s) => {
  if (!s) return null
  if (/^(out|ir|pup|sus|na)/i.test(s)) return '#ef4444'
  if (/doubt/i.test(s)) return '#f97316'
  return '#f59e0b'
}
const ffInj = (s) => !s ? '' : /doubt/i.test(s) ? 'D' : /quest/i.test(s) ? 'Q' : s.slice(0, 3).toUpperCase()

// Final keepers, 12 teams x 3. Keyed by the board's player key.
const FF_KEEPERS = {
  T1: ['ashton jeanty', 'amonra st brown', 'jonathan taylor'],   // Ashton Jeanty, Amon-Ra St. Brown, Jonathan Taylor
  T2: ['bo nix', 'aj brown', 'chase brown'],   // Bo Nix, A.J. Brown, Chase Brown
  T3: ['jayden daniels', 'kyren williams', 'quinshon judkins'],   // Jayden Daniels, Kyren Williams, Quinshon Judkins
  T4: ['alec pierce', 'harold fannin', 'jacory croskeymerritt'],   // Alec Pierce, Harold Fannin Jr., Jacory Croskey-Merritt
  T5: ['josh allen', 'ceedee lamb', 'devon achane'],   // Josh Allen, CeeDee Lamb, De'Von Achane
  T6: ['chris olave', 'christian mccaffrey', 'saquon barkley'],   // Chris Olave, Christian McCaffrey, Saquon Barkley
  T7: ['jamarr chase', 'david montgomery', 'terry mclaurin'],   // Ja'Marr Chase, David Montgomery, Terry McLaurin
  T8: ['puka nacua', 'nico collins', 'brock bowers'],   // Puka Nacua, Nico Collins, Brock Bowers
  T9: ['jaxon smithnjigba', 'omarion hampton', 'bijan robinson'],   // Jaxon Smith-Njigba, Omarion Hampton, Bijan Robinson
  T10: ['kenneth walker', 'jahmyr gibbs', 'trey mcbride'],   // Kenneth Walker III, Jahmyr Gibbs, Trey McBride
  T11: ['devonta smith', 'zay flowers', 'james cook'],   // DeVonta Smith, Zay Flowers, James Cook III
  T12: ['lamar jackson', 'derrick henry', 'justin jefferson'],   // Lamar Jackson, Derrick Henry, Justin Jefferson
}
const FF_KEEPER_OWNER = Object.fromEntries(
  Object.entries(FF_KEEPERS).flatMap(([t, ks]) => ks.map(k => [k, t])))
const FF_KEEPER_COUNT = Object.keys(FF_KEEPER_OWNER).length

// Each draft gets its own board, keyed by ?draft=<name> in the URL so two tabs
// (or two people) never share a tracker. Storage stays per-browser.
const ffSlotFromUrl = () => {
  try { return new URLSearchParams(window.location.search).get('draft') || 'main' }
  catch { return 'main' }
}
const ffSlotKey = (slot) => `ff_drafted:${slot}`
const ffLoad = (k, fallback) => {
  try { const v = localStorage.getItem(k); return v == null ? fallback : JSON.parse(v) }
  catch { return fallback }
}
const ffSave = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)) } catch { /* private mode */ } }

function FantasyTab() {
  const [position, setPosition] = useState('ALL')
  const [sort, setSort] = useState('consensus')
  const [search, setSearch] = useState('')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [openKey, setOpenKey] = useState(null)
  const [hideDrafted, setHideDrafted] = useState(true)
  const [hideKeepers, setHideKeepers] = useState(() => ffLoad(`ff_hidekeepers:${ffSlotFromUrl()}`, false))
  // Draft night survives a refresh, and each slot is tracked separately.
  const [slot, setSlot] = useState(ffSlotFromUrl)
  const [slots, setSlots] = useState(() => {
    const known = ffLoad('ff_slots', ['main'])
    const cur = ffSlotFromUrl()
    return known.includes(cur) ? known : [...known, cur]
  })
  const [drafted, setDrafted] = useState(() => ffLoad(ffSlotKey(ffSlotFromUrl()), []))

  useEffect(() => { ffSave('ff_slots', slots) }, [slots])
  useEffect(() => { ffSave(`ff_hidekeepers:${slot}`, hideKeepers) }, [slot, hideKeepers])
  // slot and drafted always change together, so this never writes one board's
  // picks into another's key.
  useEffect(() => { ffSave(ffSlotKey(slot), drafted) }, [slot, drafted])

  // If the same slot is open in another tab, converge instead of clobbering.
  useEffect(() => {
    const onStorage = (e) => {
      if (e.key !== ffSlotKey(slot)) return
      try { setDrafted(JSON.parse(e.newValue || '[]')) } catch { /* ignore */ }
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [slot])

  const switchSlot = (next) => {
    if (!next || next === slot) return
    setSlot(next)
    setDrafted(ffLoad(ffSlotKey(next), []))
    setHideKeepers(ffLoad(`ff_hidekeepers:${next}`, false))
    setSlots(s => s.includes(next) ? s : [...s, next])
    try {
      const u = new URL(window.location.href)
      u.searchParams.set('draft', next)
      window.history.replaceState({}, '', u)
    } catch { /* ignore */ }
  }

  const newSlot = () => {
    const name = (window.prompt('Name this draft (e.g. work, dynasty):') || '').trim()
      .toLowerCase().replace(/[^a-z0-9-]+/g, '-').replace(/^-+|-+$/g, '')
    if (name) switchSlot(name)
  }

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const p = new URLSearchParams({ position, search, limit: 300, min_sources: 2 })
      const res = await fetch(`${API}/api/nfl/fantasy/draftboard?${p}`)
      if (!res.ok) throw new Error(`API ${res.status}`)
      setData(await res.json())
    } catch (e) { setError(e.message); setData(null) }
    setLoading(false)
  }, [position, search])

  useEffect(() => {
    const t = setTimeout(load, search ? 350 : 0)
    return () => clearTimeout(t)
  }, [load])

  const toggleDrafted = (key) =>
    setDrafted(d => d.includes(key) ? d.filter(x => x !== key) : [...d, key])

  const all = data?.players || []
  const sorted = [...all].sort((a, b) =>
    sort === 'value' ? (b.value ?? -999) - (a.value ?? -999)
      : sort === 'spread' ? b.spread - a.spread
      : a.consensus - b.consensus)
  const rows = sorted
    .filter(p => !(hideDrafted && drafted.includes(p.key)))
    .filter(p => !(hideKeepers && FF_KEEPER_OWNER[p.key]))
  const keepersOnBoard = all.filter(p => FF_KEEPER_OWNER[p.key]).length
  // FantasyPros' overall tiers are cross-positional, so they answer a different
  // question than "which tier of RB is he". Show the positional tier whenever a
  // single position is in view.
  const singlePos = !['ALL', 'FLEX'].includes(position)
  const tierBadge = (p) => singlePos && p.pos_tier != null
    ? `${p.pos} T${p.pos_tier}`
    : p.tier != null ? `T${p.tier}` : null
  const maxSpread = Math.max(20, ...all.map(p => p.spread || 0))
  const okSources = (data?.sources || []).filter(s => s.ok)

  const ctlStyle = {
    padding: '8px 10px', borderRadius: 8, background: '#1e293b', border: '1px solid #334155',
    color: '#f1f5f9', fontSize: 13, outline: 'none', width: '100%', boxSizing: 'border-box',
  }

  return (
    <div>
      {/* Source status */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 8 }}>
        {(data?.sources || []).map(s => (
          <div key={s.key} title={s.ok ? `${s.count} players` : s.error} style={{
            fontSize: 10, fontWeight: 600, padding: '3px 7px', borderRadius: 999,
            background: s.ok ? 'rgba(255,255,255,0.04)' : 'rgba(239,68,68,0.12)',
            border: `1px solid ${s.ok ? FF_SRC_COLOR[s.key] || '#334155' : '#ef4444'}`,
            color: s.ok ? FF_SRC_COLOR[s.key] || '#94a3b8' : '#ef4444',
          }}>{s.ok ? FF_SRC_SHORT[s.key] || s.label : `${FF_SRC_SHORT[s.key] || s.label} ✕`}</div>
        ))}
        {data && (
          <div style={{ fontSize: 10, color: '#475569', alignSelf: 'center', marginLeft: 'auto' }}>
            {okSources.length}/{(data.sources || []).length} sources · PPR
          </div>
        )}
      </div>

      {/* Position chips */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 8, overflowX: 'auto', paddingBottom: 2 }}>
        {FF_POSITIONS.map(p => (
          <button key={p} onClick={() => setPosition(p)} style={{
            flex: '0 0 auto', padding: '6px 11px', borderRadius: 999, fontSize: 12, fontWeight: 600,
            cursor: 'pointer', border: `1px solid ${position === p ? '#2563eb' : '#334155'}`,
            background: position === p ? '#2563eb' : 'transparent',
            color: position === p ? '#fff' : '#64748b',
          }}>{p}</button>
        ))}
      </div>

      {/* Sort + search */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
        <div style={{ display: 'flex', borderRadius: 8, overflow: 'hidden', border: '1px solid #334155', flex: '0 0 auto' }}>
          {FF_SORTS.map(([id, label]) => (
            <button key={id} onClick={() => setSort(id)} style={{
              padding: '8px 10px', border: 'none', fontSize: 12, fontWeight: 600, cursor: 'pointer',
              background: sort === id ? '#2563eb' : '#1e293b', color: sort === id ? '#fff' : '#64748b',
            }}>{label}</button>
          ))}
        </div>
        <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search…" style={ctlStyle} />
      </div>

      {/* Draft slots — one board per draft */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 8, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 10, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', marginRight: 2 }}>Draft</span>
        {slots.map(s => (
          <button key={s} onClick={() => switchSlot(s)} style={{
            padding: '4px 9px', borderRadius: 999, fontSize: 11, fontWeight: 600, cursor: 'pointer',
            border: `1px solid ${s === slot ? '#22c55e' : '#334155'}`,
            background: s === slot ? 'rgba(34,197,94,0.15)' : 'transparent',
            color: s === slot ? '#22c55e' : '#64748b',
          }}>{s}</button>
        ))}
        <button onClick={newSlot} title="New draft board" style={{
          padding: '4px 9px', borderRadius: 999, fontSize: 11, fontWeight: 700, cursor: 'pointer',
          border: '1px dashed #334155', background: 'transparent', color: '#64748b',
        }}>+</button>
      </div>

      {/* Draft tracker */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#94a3b8', cursor: 'pointer' }}>
          <input type="checkbox" checked={hideDrafted} onChange={e => setHideDrafted(e.target.checked)} />
          Hide drafted ({drafted.length})
        </label>
        <button onClick={() => setHideKeepers(v => !v)} title={`${FF_KEEPER_COUNT} keepers across 12 teams`} style={{
          padding: '4px 10px', borderRadius: 999, fontSize: 11, fontWeight: 600, cursor: 'pointer',
          border: `1px solid ${hideKeepers ? '#a855f7' : '#334155'}`,
          background: hideKeepers ? 'rgba(168,85,247,0.15)' : 'transparent',
          color: hideKeepers ? '#a855f7' : '#64748b',
        }}>{hideKeepers ? `Keepers hidden (${keepersOnBoard})` : `Hide keepers (${keepersOnBoard})`}</button>
        {drafted.length > 0 && (
          <button onClick={() => setDrafted([])} style={{
            marginLeft: 'auto', background: 'none', border: 'none', color: '#64748b',
            fontSize: 11, cursor: 'pointer', padding: 0,
          }}>reset board</button>
        )}
      </div>

      <div style={{ fontSize: 10, color: '#475569', marginBottom: 8 }}>
        {loading ? 'Loading…' : error ? '' : data
          ? `${rows.length} of ${data.total} · ${data.season} · tap a row for source split`
          : ''}
      </div>

      {error && <div style={{ color: '#ef4444', fontSize: 13, padding: 12 }}>Failed to load: {error}</div>}
      {!loading && !error && rows.length === 0 && (
        <div style={{ color: '#64748b', fontSize: 13, padding: 12, textAlign: 'center' }}>No players match.</div>
      )}

      {/* Column header */}
      {rows.length > 0 && (
        <div style={{ display: 'flex', gap: 8, padding: '0 10px 5px', fontSize: 9, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          <div style={{ width: 26 }}>#</div>
          <div style={{ flex: 1 }}>Player</div>
          <div style={{ width: 42, textAlign: 'right' }}>Cons</div>
          <div style={{ width: 42, textAlign: 'right' }}>ADP</div>
          <div style={{ width: 34, textAlign: 'right' }}>Val</div>
        </div>
      )}

      {rows.map((p, i) => {
        const isOpen = openKey === p.key
        const isDrafted = drafted.includes(p.key)
        const injColor = ffInjColor(p.inj)
        return (
          <div key={p.key} style={{
            marginBottom: 3, borderRadius: 8, overflow: 'hidden',
            background: isOpen ? '#172033' : i % 2 === 0 ? '#1e293b' : '#0f172a',
            borderLeft: `3px solid ${FF_POS_COLOR[p.pos] || 'transparent'}`,
            opacity: isDrafted ? 0.45 : 1,
          }}>
            <div onClick={() => setOpenKey(isOpen ? null : p.key)}
              style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '9px 10px', cursor: 'pointer' }}>
              <div style={{ width: 26, fontSize: 12, color: '#64748b', fontVariantNumeric: 'tabular-nums' }}>{p.ovr_rank}</div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{
                  fontSize: 13, fontWeight: 600, color: '#e2e8f0', whiteSpace: 'nowrap',
                  overflow: 'hidden', textOverflow: 'ellipsis',
                  textDecoration: isDrafted ? 'line-through' : 'none',
                }}>
                  {p.name}
                  {injColor && <span style={{ marginLeft: 5, fontSize: 9, fontWeight: 700, color: injColor }}>{ffInj(p.inj)}</span>}
                </div>
                <div style={{ fontSize: 10, color: '#64748b', marginTop: 1, display: 'flex', alignItems: 'center', gap: 4 }}>
                  <span style={{ color: FF_POS_COLOR[p.pos] || '#64748b', fontWeight: 600 }}>{p.pos_label}</span>
                  <span>· {p.team}</span>
                  {p.bye && <span>· bye {p.bye}</span>}
                  {tierBadge(p) && <span style={{ color: '#475569' }}>· {tierBadge(p)}</span>}
                  {FF_KEEPER_OWNER[p.key] && (
                    <span style={{
                      color: '#a855f7', fontWeight: 700, border: '1px solid rgba(168,85,247,0.4)',
                      borderRadius: 4, padding: '0 3px', fontSize: 9,
                    }}>K {FF_KEEPER_OWNER[p.key]}</span>
                  )}
                  {/* disagreement bar */}
                  <span style={{ flex: 1, height: 3, background: '#0f172a', borderRadius: 2, marginLeft: 2, maxWidth: 46 }}>
                    <span style={{
                      display: 'block', height: '100%', borderRadius: 2,
                      width: `${Math.min(100, (p.spread / maxSpread) * 100)}%`,
                      background: p.spread > maxSpread * 0.5 ? '#f59e0b' : '#334155',
                    }} />
                  </span>
                </div>
              </div>
              <div style={{ width: 42, textAlign: 'right', fontSize: 14, fontWeight: 700, color: '#e2e8f0', fontVariantNumeric: 'tabular-nums' }}>
                {p.consensus.toFixed(1)}
              </div>
              <div style={{ width: 42, textAlign: 'right', fontSize: 12, color: '#94a3b8', fontVariantNumeric: 'tabular-nums' }}>
                {p.adp_avg != null ? p.adp_avg.toFixed(1) : '—'}
              </div>
              <div style={{
                width: 34, textAlign: 'right', fontSize: 12, fontWeight: 600, fontVariantNumeric: 'tabular-nums',
                color: p.value == null ? '#475569' : p.value >= 5 ? '#22c55e' : p.value <= -5 ? '#ef4444' : '#94a3b8',
              }}>
                {p.value == null ? '—' : `${p.value > 0 ? '+' : ''}${p.value.toFixed(0)}`}
              </div>
            </div>

            {/* Per-source split */}
            {isOpen && (
              <div style={{ padding: '0 10px 10px', borderTop: '1px solid #1e293b' }}>
                <div style={{ fontSize: 9, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '8px 0 6px' }}>
                  Rank by source · {p.n_sources} of 5 · range {p.high.toFixed(0)}–{p.low.toFixed(0)}
                </div>
                <div style={{ display: 'flex', gap: 4, marginBottom: 8 }}>
                  {Object.keys(FF_SRC_COLOR).map(k => {
                    const v = p.ranks[k]
                    return (
                      <div key={k} style={{
                        flex: 1, textAlign: 'center', padding: '6px 2px', borderRadius: 6,
                        background: '#0f172a', border: `1px solid ${v != null ? FF_SRC_COLOR[k] : '#1e293b'}`,
                        opacity: v != null ? 1 : 0.35,
                      }}>
                        <div style={{ fontSize: 8, color: '#64748b', textTransform: 'uppercase' }}>{FF_SRC_SHORT[k]}</div>
                        <div style={{ fontSize: 14, fontWeight: 700, color: v != null ? FF_SRC_COLOR[k] : '#475569', fontVariantNumeric: 'tabular-nums' }}>
                          {v != null ? v.toFixed(0) : '—'}
                        </div>
                        {p.adp[k] != null && (
                          <div style={{ fontSize: 8, color: '#475569', fontVariantNumeric: 'tabular-nums' }}>adp {p.adp[k].toFixed(0)}</div>
                        )}
                      </div>
                    )
                  })}
                </div>
                <div style={{ display: 'flex', gap: 12, fontSize: 10, color: '#64748b', marginBottom: 8, fontVariantNumeric: 'tabular-nums' }}>
                  {p.proj != null && <span>Proj <b style={{ color: '#94a3b8' }}>{p.proj.toFixed(1)}</b> pts</span>}
                  {p.ecr_std != null && <span>ECR σ <b style={{ color: '#94a3b8' }}>{p.ecr_std.toFixed(1)}</b></span>}
                  {p.pos_tier != null && <span>{p.pos} tier <b style={{ color: '#94a3b8' }}>{p.pos_tier}</b></span>}
                  {p.tier != null && <span>Ovr tier <b style={{ color: '#94a3b8' }}>{p.tier}</b></span>}
                  <span>Spread <b style={{ color: p.spread > maxSpread * 0.5 ? '#f59e0b' : '#94a3b8' }}>{p.spread.toFixed(0)}</b></span>
                </div>
                <button onClick={() => toggleDrafted(p.key)} style={{
                  width: '100%', padding: '8px 0', borderRadius: 8, border: 'none', fontSize: 12, fontWeight: 700,
                  cursor: 'pointer', background: isDrafted ? '#334155' : '#2563eb', color: '#fff',
                }}>{isDrafted ? 'Undo — put back on board' : 'Mark drafted'}</button>
              </div>
            )}
          </div>
        )
      })}

      {rows.length > 0 && (
        <div style={{ fontSize: 10, color: '#475569', marginTop: 8, lineHeight: 1.5 }}>
          Cons = mean rank across sources. Val = avg ADP minus board rank; positive means he's
          lasting past where the experts have him. The amber bar flags where the sources disagree most.
          <br />Running two drafts at once? Open each in its own tab and pick a different Draft chip —
          the URL (?draft={slot}) keeps them separate.
        </div>
      )}
    </div>
  )
}

// ── Root App ──────────────────────────────────────────────────────────────────
export default function App() {
  const [tab, setTab] = useState('research')

  return (
    <div style={{ maxWidth: 480, margin: '0 auto', padding: '16px 16px 60px', fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif', color: '#f1f5f9', background: '#0f172a', minHeight: '100vh' }}>

      {/* Header */}
      <div style={{ textAlign: 'center', marginBottom: 20 }}>
        <div style={{ fontSize: 24, marginBottom: 2 }}>⚾</div>
        <h1 style={{ fontSize: 20, fontWeight: 800, letterSpacing: '-0.03em', margin: 0 }}>MLB Dashboard</h1>
        <p style={{ fontSize: 12, color: '#475569', marginTop: 2 }}>Statcast 2023–2026</p>
      </div>

      {/* Tab switcher */}
      <div style={{ display: 'flex', flexWrap: 'wrap', borderRadius: 10, overflow: 'hidden', border: '1px solid #1e293b', marginBottom: 20, background: '#1e293b', gap: 1 }}>
        {[
          { id: 'research', label: '🔍 Research' },
          { id: 'sim',      label: '⚾ Sim' },
          { id: 'batch',    label: '📊 1K' },
          { id: 'plakata',  label: '💥 PitchPulse' },
          { id: 'cfb',      label: '🏟️ CFB' },
          { id: 'spring',   label: '🌸 Odds' },
          { id: 'hr',       label: '💣 HR' },
          { id: 'ff',       label: '🏈 FF' },
        ].map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            flex: '1 0 24%', padding: '10px 4px', border: 'none', fontSize: 12, fontWeight: 600, whiteSpace: 'nowrap',
            background: tab === t.id ? '#2563eb' : 'transparent',
            color: tab === t.id ? '#fff' : '#64748b',
            cursor: 'pointer', transition: 'background 0.15s',
          }}>{t.label}</button>
        ))}
      </div>

      {tab === 'research' ? <ResearchTab /> : tab === 'sim' ? <AtBatTab /> : tab === 'batch' ? <BatchSimTab /> : tab === 'plakata' ? <PlakataTab /> : tab === 'cfb' ? <CFBTab /> : tab === 'hr' ? <HRScannerTab /> : tab === 'ff' ? <FantasyTab /> : <SpringOddsTab />}

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
