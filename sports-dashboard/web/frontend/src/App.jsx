import { useState, useCallback, useRef, useEffect } from 'react'

const API = ''  // proxied via vite dev server

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

// ── At-Bat Simulator tab ──────────────────────────────────────────────────────
function AtBatTab() {
  const [batter, setBatter] = useState(null)
  const [pitcher, setPitcher] = useState(null)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [history, setHistory] = useState([])
  const canSim = batter && pitcher && !loading

  const simulate = async () => {
    if (!canSim) return
    setLoading(true); setResult(null); setError(null)
    try {
      const res = await fetch(`${API}/api/simulate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ batter_id: batter.id, pitcher_id: pitcher.id }),
      })
      if (!res.ok) throw new Error(`Server error ${res.status}`)
      const data = await res.json()
      setResult(data)
      setHistory(h => [data, ...h].slice(0, 10))
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

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
        cursor: canSim ? 'pointer' : 'not-allowed', transition: 'background 0.2s', marginBottom: 24,
      }}>
        {loading ? '⏳ Simulating...' : '▶ Simulate At-Bat'}
      </button>
      {error && <div style={{ color: '#ef4444', fontSize: 14, textAlign: 'center', marginBottom: 16 }}>{error}</div>}
      {result && (
        <div style={{ marginBottom: 24 }}>
          <ResultBanner result={result} />
          {result.pitches?.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <div style={{ fontSize: 11, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>
                Pitch Sequence
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {result.pitches.map((p, i) => <PitchCard key={i} pitch={p} delay={i * 0.08} />)}
              </div>
            </div>
          )}
          <button onClick={simulate} style={{
            width: '100%', padding: '12px 0', borderRadius: 10, border: '1px solid #334155',
            background: 'transparent', color: '#94a3b8', fontSize: 14, fontWeight: 600,
            cursor: 'pointer', marginTop: 16,
          }}>🔄 Simulate Again</button>
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
  const [wpData, setWpData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const pollRef = useRef(null)
  const lastSyncRef = useRef(null)

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

  const calculate = async () => {
    setLoading(true); setError(null)
    try {
      const isTop = state.topbot === 'Top'
      const body = {
        ...state,
        bat_score: isTop ? state.away_score : state.home_score,
        fld_score: isTop ? state.home_score : state.away_score,
        batting_lineup: lineupIds || null,
        fielding_pitcher: pitcherId || null,
        kalshi_price: kalshiInput ? parseFloat(kalshiInput) / 100 : null,
      }
      const res = await fetch(`${API}/api/wp`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
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
          <label style={labelStyle}>Kalshi Price (yes %)</label>
          <input
            value={kalshiInput}
            onChange={e => setKalshiInput(e.target.value)}
            onBlur={calculate}
            placeholder="e.g. 48"
            type="number"
            style={{
              width: '100%', padding: '10px 12px', borderRadius: 8,
              background: '#1e293b', border: '1px solid #334155',
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
        {[{ id: 'wp', label: '📊 WP / Kalshi' }, { id: 'sim', label: '⚾ At-Bat Sim' }].map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            flex: 1, padding: '11px 0', border: 'none', fontSize: 14, fontWeight: 600,
            background: tab === t.id ? '#2563eb' : 'transparent',
            color: tab === t.id ? '#fff' : '#64748b',
            cursor: 'pointer', transition: 'background 0.15s',
          }}>{t.label}</button>
        ))}
      </div>

      {tab === 'wp' ? <WPDashboard /> : <AtBatTab />}

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
