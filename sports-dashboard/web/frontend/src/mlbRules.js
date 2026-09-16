// Lock and sweep rules for the MLB board. Everything here is pure: it reads
// the market list from /api/mlb/board/markets and the linescore from
// /api/mlb/board/state, and says which side of each market is already decided.
//
// state: { status: 'pre'|'in'|'post', inning, half: 'top'|'mid'|'bot'|'end',
//          runs: { away, home }, innings: [{ n, away, home }], teams: { away, home } }
// market: { ticker, kind, inning, team, strike, yes_ask, no_ask, label }
//
// One fact drives the mid-inning locks: runs never come off the board, and in
// the bottom half only the home team can add any. So while the home team bats,
// a home lead in that segment is final and an away cover can only shrink.

// Which innings a market kind is settled on (null = whole game, extras included)
const SEGMENT = { F3: 3, F5: 5, F5SPREAD: 5, F5TOTAL: 5, F7: 7 }
const WINNER_KINDS = new Set(['GAME', 'F3', 'F5', 'F7', 'INNINGWIN'])
const SPREAD_KINDS = new Set(['SPREAD', 'F5SPREAD'])
const TOTAL_KINDS = new Set(['TOTAL', 'F5TOTAL', 'INNINGTOTAL', 'RFI'])

export const mlbInningDone = (st, n) =>
  st.status === 'post' || (st.status === 'in' && (st.inning > n || (st.inning === n && st.half === 'end')))

const homeBatting = (st, n) => st.status === 'in' && st.inning === n && st.half === 'bot'

export const mlbInningRuns = (st, n) => st.innings?.find(i => i.n === n) || { n, away: 0, home: 0 }

// Runs, and whether anything can still change, for the segment a market settles on
export function mlbSegment(st, m) {
  if (m.kind === 'INNINGWIN' || m.kind === 'INNINGTOTAL' || m.kind === 'RFI') {
    const r = mlbInningRuns(st, m.inning)
    return { away: r.away, home: r.home, done: mlbInningDone(st, m.inning), homeBatting: homeBatting(st, m.inning) }
  }
  const N = SEGMENT[m.kind]
  if (N == null) {
    // Whole game: a walk-off ends the game, so nothing is certain before Final
    return { away: st.runs?.away || 0, home: st.runs?.home || 0, done: st.status === 'post', homeBatting: false }
  }
  let away = 0, home = 0
  for (const i of st.innings || []) if (i.n <= N) { away += i.away; home += i.home }
  return { away, home, done: mlbInningDone(st, N), homeBatting: homeBatting(st, N) }
}

const role = (st, code) => code === st.teams?.away ? 'away' : code === st.teams?.home ? 'home' : code === 'TIE' ? 'tie' : null

// Which side of one market the linescore has decided: 'yes' | 'no' | null
export function mlbLock(st, m) {
  if (!st || st.status === 'pre') return null
  const seg = mlbSegment(st, m)
  const t = role(st, m.team)
  if (WINNER_KINDS.has(m.kind)) {
    if (!t) return null
    if (seg.done) {
      const winner = seg.away > seg.home ? 'away' : seg.home > seg.away ? 'home' : 'tie'
      return t === winner ? 'yes' : 'no'
    }
    if (seg.homeBatting) {
      // Away is done batting: it can't win once home has caught up, and a home lead is final
      if (t === 'away' && seg.home >= seg.away) return 'no'
      if (seg.home > seg.away) return t === 'home' ? 'yes' : 'no'
    }
    return null
  }
  if (SPREAD_KINDS.has(m.kind)) {
    if (!t || t === 'tie' || m.strike == null) return null
    const margin = t === 'away' ? seg.away - seg.home : seg.home - seg.away
    if (seg.done) return margin > m.strike ? 'yes' : 'no'
    if (seg.homeBatting) {
      if (t === 'home' && margin > m.strike) return 'yes'
      if (t === 'away' && margin <= m.strike) return 'no'
    }
    return null
  }
  if (TOTAL_KINDS.has(m.kind)) {
    if (m.strike == null) return null
    if (seg.away + seg.home > m.strike) return 'yes'
    return seg.done ? 'no' : null
  }
  if (m.kind === 'TEAMTOTAL') {
    if (!t || t === 'tie' || m.strike == null) return null
    if (seg[t] > m.strike) return 'yes'
    return seg.done ? 'no' : null
  }
  if (m.kind === 'EXTRAS') {
    if (st.inning >= 10) return 'yes'
    return st.status === 'post' ? 'no' : null
  }
  return null
}

// Every decided market -> { ticker: 'yes'|'no' }
export function mlbLocks(groups, st) {
  const locks = {}
  for (const g of groups) for (const m of g.markets) {
    const l = mlbLock(st, m)
    if (l) locks[m.ticker] = l
  }
  return locks
}

const askFor = (m, side) => (side === 'yes' ? m.yes_ask : m.no_ask)
const leg = (m, side, kind, sure) => ({ ticker: m.ticker, side, label: m.label, ask: askFor(m, side), kind, sure })

// The inning sweeper: one inning's winner and runs markets. Winners and passed
// overs are locks; unders are locks once the inning is over and a cushion bet
// while it's still being played.
export function mlbInningLegs(groups, st, cfg) {
  const g = groups.find(x => x.inning === cfg.inning)
  const markets = g ? g.markets : []
  const r = mlbInningRuns(st, cfg.inning)
  const done = mlbInningDone(st, cfg.inning)
  const started = st.status === 'post' || (st.status === 'in' && st.inning >= cfg.inning)
  const legs = []
  for (const m of markets) {
    const lock = mlbLock(st, m)
    if (m.kind === 'INNINGWIN') {
      if (cfg.winner && lock) legs.push(leg(m, lock, 'WIN', true))
    } else if (m.strike != null) {
      const runs = r.away + r.home
      if (cfg.totalYes && runs > m.strike) legs.push(leg(m, 'yes', 'RUNS', true))
      else if (cfg.totalNo && started && runs <= m.strike && (done || m.strike - runs >= cfg.totalCushion)) legs.push(leg(m, 'no', 'RUNS', done))
    }
  }
  return { legs, runs: r, done, started }
}

// The end-of-game sweeper: moneyline, run line, totals, team totals and extras.
// At Final everything is a lock. Before that, legs are cushion bets: the leader
// by at least `leadCushion` runs from inning `fromInning` on, totals at least
// `runsCushion` runs away from their line.
export function mlbGameLegs(groups, st, cfg) {
  const by = (kind) => groups.flatMap(g => g.markets.filter(m => m.kind === kind))
  const final = st.status === 'post'
  const lead = role(st, cfg.team)
  const other = lead === 'away' ? 'home' : 'away'
  const margin = lead ? (st.runs?.[lead] || 0) - (st.runs?.[other] || 0) : 0
  const total = (st.runs?.away || 0) + (st.runs?.home || 0)
  const late = final || (st.status === 'in' && st.inning >= cfg.fromInning)
  const legs = []
  const push = (m, side, kind) => { if (side) legs.push(leg(m, side, kind, !!mlbLock(st, m))) }
  if (cfg.ml) for (const m of by('GAME')) {
    const t = role(st, m.team)
    if (final) push(m, mlbLock(st, m), 'ML')
    else if (late && lead && margin >= cfg.leadCushion && t) push(m, t === lead ? 'yes' : 'no', 'ML')
  }
  if (cfg.spread) for (const m of by('SPREAD')) {
    const t = role(st, m.team)
    if (m.strike == null || !t) continue
    if (final) push(m, mlbLock(st, m), 'SPR')
    else if (late && lead) {
      if (t === lead && margin - m.strike >= cfg.leadCushion) push(m, 'yes', 'SPR')
      else if (t === other && margin + m.strike >= cfg.leadCushion) push(m, 'no', 'SPR')
    }
  }
  if (cfg.teamTotal) for (const m of by('TEAMTOTAL')) {
    const t = role(st, m.team)
    if (m.strike == null || !t || t === 'tie') continue
    const runs = st.runs?.[t] || 0
    if (runs > m.strike) push(m, 'yes', 'TT')
    else if (final) push(m, 'no', 'TT')
    else if (late && m.strike - runs >= cfg.runsCushion) push(m, 'no', 'TT')
  }
  if (cfg.total) for (const m of by('TOTAL')) {
    if (m.strike == null) continue
    if (total > m.strike) push(m, 'yes', 'TOT')
    else if (final) push(m, 'no', 'TOT')
    else if (late && m.strike - total >= cfg.runsCushion) push(m, 'no', 'TOT')
  }
  if (cfg.extras) for (const m of by('EXTRAS')) {
    if (st.inning >= 10 && st.status !== 'pre') push(m, 'yes', 'EXT')
    else if (final) push(m, 'no', 'EXT')
    else if (late && lead && st.inning >= 9 && margin >= cfg.leadCushion) push(m, 'no', 'EXT')
  }
  return { legs, margin, total, late, lead, other }
}
