"use client";

import { useEffect, useState, useCallback } from "react";
import { supabase } from "@/lib/supabase";

const PAGE_SIZE = 25;

type SortColumn = "game_date" | "batter_name" | "player_name" | "pitch_name" | "launch_speed" | "launch_angle" | "hit_distance_sc";
type SortDirection = "asc" | "desc";

const COLUMN_CONFIG: { key: SortColumn; label: string }[] = [
  { key: "game_date", label: "Date" },
  { key: "batter_name", label: "Batter" },
  { key: "player_name", label: "Pitcher" },
  { key: "pitch_name", label: "Pitch" },
  { key: "launch_speed", label: "Exit Velo" },
  { key: "launch_angle", label: "Launch Angle" },
  { key: "hit_distance_sc", label: "Distance" },
];

interface HomeRun {
  game_date: string;
  batter_name: string;
  batter_team: string;
  player_name: string;
  pitcher_team: string;
  pitch_name: string;
  launch_speed: number;
  launch_angle: number;
  hit_distance_sc: number;
  home_team: string;
  away_team: string;
  plate_x: number | null;
  plate_z: number | null;
  sz_top: number | null;
  sz_bot: number | null;
  hc_x: number | null;
  hc_y: number | null;
  release_speed: number | null;
  stand: string | null;
}

interface Filters {
  batter_name: string;
  batter_team: string;
  player_name: string;
  pitcher_team: string;
  pitch_name: string;
  date_from: string;
  date_to: string;
  min_exit_velo: string;
  max_exit_velo: string;
  min_launch_angle: string;
  max_launch_angle: string;
  min_distance: string;
  max_distance: string;
}

const emptyFilters: Filters = {
  batter_name: "",
  batter_team: "",
  player_name: "",
  pitcher_team: "",
  pitch_name: "",
  date_from: "",
  date_to: "",
  min_exit_velo: "",
  max_exit_velo: "",
  min_launch_angle: "",
  max_launch_angle: "",
  min_distance: "",
  max_distance: "",
};

// ── Strike Zone Chart ──
function StrikeZone({ plateX, plateZ, szTop, szBot }: { plateX: number; plateZ: number; szTop: number; szBot: number }) {
  // Strike zone in feet: plate is 17 inches wide = ~0.708 ft each side
  // We'll work in the Statcast coordinate system (feet from center of plate)
  const width = 200;
  const height = 250;
  const pad = 30;

  // Zone boundaries in feet
  const zoneLeft = -0.833;  // ~10 inches each side (with ball width)
  const zoneRight = 0.833;
  const viewLeft = -1.5;
  const viewRight = 1.5;
  const viewBot = 1.0;
  const viewTop = 4.2;

  const scaleX = (x: number) => pad + ((x - viewLeft) / (viewRight - viewLeft)) * (width - pad * 2);
  const scaleY = (z: number) => pad + ((viewTop - z) / (viewTop - viewBot)) * (height - pad * 2);

  const zx1 = scaleX(zoneLeft);
  const zx2 = scaleX(zoneRight);
  const zy1 = scaleY(szTop);
  const zy2 = scaleY(szBot);

  const dotX = scaleX(plateX);
  const dotY = scaleY(plateZ);

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-full">
      {/* Background */}
      <rect x={0} y={0} width={width} height={height} fill="#18181b" rx={8} />

      {/* Strike zone box */}
      <rect x={zx1} y={zy1} width={zx2 - zx1} height={zy2 - zy1} fill="none" stroke="#3f3f46" strokeWidth={1.5} />

      {/* Zone grid (3x3) */}
      {[1, 2].map((i) => (
        <g key={i}>
          <line
            x1={zx1 + ((zx2 - zx1) / 3) * i} y1={zy1}
            x2={zx1 + ((zx2 - zx1) / 3) * i} y2={zy2}
            stroke="#27272a" strokeWidth={0.5}
          />
          <line
            x1={zx1} y1={zy1 + ((zy2 - zy1) / 3) * i}
            x2={zx2} y2={zy1 + ((zy2 - zy1) / 3) * i}
            stroke="#27272a" strokeWidth={0.5}
          />
        </g>
      ))}

      {/* Home plate */}
      <polygon
        points={`${scaleX(0)},${scaleY(0.9)} ${scaleX(-0.35)},${scaleY(0.7)} ${scaleX(-0.708)},${scaleY(0.4)} ${scaleX(0.708)},${scaleY(0.4)} ${scaleX(0.35)},${scaleY(0.7)}`}
        fill="none" stroke="#52525b" strokeWidth={1}
      />

      {/* Pitch location dot */}
      <circle cx={dotX} cy={dotY} r={8} fill="#ef4444" fillOpacity={0.9} stroke="#fca5a5" strokeWidth={1.5} />

      {/* Label */}
      <text x={width / 2} y={height - 6} textAnchor="middle" fill="#71717a" fontSize={10}>
        Pitch Location
      </text>
    </svg>
  );
}

// ── Spray Chart (field view) ──
function SprayChart({ hcX, hcY, distance, stand }: { hcX: number; hcY: number; distance: number | null; stand: string | null }) {
  // We derive the spray ANGLE from Statcast hc_x/hc_y, but use the actual
  // hit_distance_sc (feet) for the radial distance so home runs plot beyond the wall.
  const size = 250;

  // Home plate position in SVG coords
  const homeX = 125;
  const homeY = 210;

  // Scale: 1 foot = this many SVG pixels
  const ftToPx = 0.42;

  // Compute spray angle from Statcast coords (home plate at 126, 204)
  const rawDx = hcX - 126;
  const rawDy = 204 - hcY;
  const sprayAngle = Math.atan2(rawDx, rawDy); // 0 = center field

  // Use actual distance in feet for radial placement, fallback to Statcast distance
  const rawDist = Math.sqrt(rawDx * rawDx + rawDy * rawDy);
  const distFt = distance && distance > 0 ? distance : rawDist / ftToPx;
  const r = distFt * ftToPx;

  const dotX = homeX + r * Math.sin(sprayAngle);
  const dotY = homeY - r * Math.cos(sprayAngle);

  // Wall at ~340 ft (foul poles) to ~400 ft (center) — draw as simple arc at ~350 ft avg
  const wallFt = 350;
  const wallR = wallFt * ftToPx;

  // Foul lines at 45 degrees from center
  const foulLineLen = 420 * ftToPx; // extend past deepest HR
  const lfPoleX = homeX - foulLineLen * Math.sin(Math.PI / 4);
  const lfPoleY = homeY - foulLineLen * Math.cos(Math.PI / 4);
  const rfPoleX = homeX + foulLineLen * Math.sin(Math.PI / 4);
  const rfPoleY = homeY - foulLineLen * Math.cos(Math.PI / 4);

  // Wall arc endpoints at foul lines (45 degrees)
  const wallLfX = homeX - wallR * Math.sin(Math.PI / 4);
  const wallLfY = homeY - wallR * Math.cos(Math.PI / 4);
  const wallRfX = homeX + wallR * Math.sin(Math.PI / 4);
  const wallRfY = homeY - wallR * Math.cos(Math.PI / 4);

  // Warning track at ~340 ft
  const warnR = 340 * ftToPx;

  // Infield diamond: 90ft base paths, ~127ft to 2nd base
  const baseR = 90 * ftToPx;
  const first = { x: homeX + baseR * 0.707, y: homeY - baseR * 0.707 };
  const second = { x: homeX, y: homeY - baseR * 1.414 };
  const third = { x: homeX - baseR * 0.707, y: homeY - baseR * 0.707 };


  return (
    <svg viewBox={`0 0 ${size} ${size}`} className="w-full h-full">
      {/* Background */}
      <rect x={0} y={0} width={size} height={size} fill="#18181b" rx={8} />

      {/* Outfield grass fill */}
      <path
        d={`M ${homeX} ${homeY} L ${wallLfX} ${wallLfY} A ${wallR} ${wallR} 0 0 1 ${wallRfX} ${wallRfY} Z`}
        fill="#1a2e0a" fillOpacity={0.4}
      />

      {/* Outfield wall arc */}
      <path
        d={`M ${wallLfX} ${wallLfY} A ${wallR} ${wallR} 0 0 1 ${wallRfX} ${wallRfY}`}
        fill="none" stroke="#4d7c0f" strokeWidth={2}
      />

      {/* Warning track arc */}
      <path
        d={`M ${homeX - warnR * Math.sin(Math.PI / 4)} ${homeY - warnR * Math.cos(Math.PI / 4)} A ${warnR} ${warnR} 0 0 1 ${homeX + warnR * Math.sin(Math.PI / 4)} ${homeY - warnR * Math.cos(Math.PI / 4)}`}
        fill="none" stroke="#365314" strokeWidth={0.5} strokeDasharray="3,3"
      />

      {/* Foul lines */}
      <line x1={homeX} y1={homeY} x2={lfPoleX} y2={lfPoleY} stroke="#4d7c0f" strokeWidth={1} />
      <line x1={homeX} y1={homeY} x2={rfPoleX} y2={rfPoleY} stroke="#4d7c0f" strokeWidth={1} />

      {/* Infield diamond */}
      <polygon
        points={`${homeX},${homeY} ${first.x},${first.y} ${second.x},${second.y} ${third.x},${third.y}`}
        fill="none" stroke="#52525b" strokeWidth={0.8}
      />

      {/* Bases */}
      <rect x={first.x - 2} y={first.y - 2} width={4} height={4} fill="#a8a29e" transform={`rotate(45,${first.x},${first.y})`} />
      <rect x={second.x - 2} y={second.y - 2} width={4} height={4} fill="#a8a29e" transform={`rotate(45,${second.x},${second.y})`} />
      <rect x={third.x - 2} y={third.y - 2} width={4} height={4} fill="#a8a29e" transform={`rotate(45,${third.x},${third.y})`} />

      {/* Home plate */}
      <polygon
        points={`${homeX},${homeY + 2} ${homeX - 3},${homeY - 1} ${homeX - 2},${homeY - 3} ${homeX + 2},${homeY - 3} ${homeX + 3},${homeY - 1}`}
        fill="#a8a29e"
      />

      {/* Batter silhouette */}
      {(() => {
        const isLeft = stand === "L";
        const flip = isLeft ? 1 : -1;
        const bx = homeX + flip * 10;
        const by = homeY + 1;
        return (
          <g transform={`translate(${bx},${by}) scale(${flip},1)`} opacity={0.6}>
            {/* Head */}
            <circle cx={0} cy={-14} r={2.8} fill="#a1a1aa" />
            {/* Torso */}
            <line x1={0} y1={-11} x2={0} y2={-3} stroke="#a1a1aa" strokeWidth={1.5} strokeLinecap="round" />
            {/* Front leg (stride) */}
            <line x1={0} y1={-3} x2={-3} y2={4} stroke="#a1a1aa" strokeWidth={1.3} strokeLinecap="round" />
            {/* Back leg */}
            <line x1={0} y1={-3} x2={3} y2={4} stroke="#a1a1aa" strokeWidth={1.3} strokeLinecap="round" />
            {/* Arms holding bat — hands near back shoulder */}
            <line x1={0} y1={-9} x2={3} y2={-11} stroke="#a1a1aa" strokeWidth={1.3} strokeLinecap="round" />
            {/* Bat — angled up from hands */}
            <line x1={3} y1={-11} x2={1} y2={-20} stroke="#d4d4d8" strokeWidth={1.2} strokeLinecap="round" />
          </g>
        );
      })()}

      {/* Hit location dot */}
      <circle cx={dotX} cy={dotY} r={6} fill="#ef4444" fillOpacity={0.9} stroke="#fca5a5" strokeWidth={1.5} />

      {/* Label */}
      <text x={size / 2} y={size - 4} textAnchor="middle" fill="#71717a" fontSize={10}>
        Hit Location
      </text>
    </svg>
  );
}

// ── Detail Popup ──
function DetailPopup({ hr, onClose }: { hr: HomeRun; onClose: () => void }) {
  const hasPitchLocation = hr.plate_x != null && hr.plate_z != null && hr.sz_top != null && hr.sz_bot != null;
  const hasHitLocation = hr.hc_x != null && hr.hc_y != null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70" onClick={onClose}>
      <div
        className="bg-zinc-900 rounded-xl p-6 max-w-2xl w-full mx-4 border border-zinc-800"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between mb-4">
          <div>
            <h3 className="text-lg font-bold">
              {hr.batter_name || "Unknown"}{" "}
              <span className="text-zinc-500 font-normal text-sm">
                {hr.batter_team && `(${hr.batter_team})`}
              </span>
            </h3>
            <p className="text-zinc-400 text-sm">
              vs {hr.player_name}{" "}
              {hr.pitcher_team && <span className="text-zinc-500">({hr.pitcher_team})</span>}
              {" "}&middot; {hr.game_date} &middot; {hr.away_team} @ {hr.home_team}
            </p>
          </div>
          <button onClick={onClose} className="text-zinc-500 hover:text-zinc-300 text-xl leading-none">&times;</button>
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-4 gap-4 mb-6">
          <div className="bg-zinc-800 rounded-lg p-3 text-center">
            <div className="text-xs text-zinc-500">Pitch</div>
            <div className="text-sm font-medium mt-1">{hr.pitch_name || "—"}</div>
            {hr.release_speed && <div className="text-xs text-zinc-500 mt-0.5">{hr.release_speed.toFixed(1)} mph</div>}
          </div>
          <div className="bg-zinc-800 rounded-lg p-3 text-center">
            <div className="text-xs text-zinc-500">Exit Velo</div>
            <div className="text-sm font-medium mt-1">{hr.launch_speed ? `${hr.launch_speed.toFixed(1)} mph` : "—"}</div>
          </div>
          <div className="bg-zinc-800 rounded-lg p-3 text-center">
            <div className="text-xs text-zinc-500">Launch Angle</div>
            <div className="text-sm font-medium mt-1">{hr.launch_angle != null ? `${hr.launch_angle}°` : "—"}</div>
          </div>
          <div className="bg-zinc-800 rounded-lg p-3 text-center">
            <div className="text-xs text-zinc-500">Distance</div>
            <div className="text-sm font-medium mt-1">{hr.hit_distance_sc ? `${hr.hit_distance_sc} ft` : "—"}</div>
          </div>
        </div>

        {/* Charts */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            {hasPitchLocation ? (
              <StrikeZone plateX={hr.plate_x!} plateZ={hr.plate_z!} szTop={hr.sz_top!} szBot={hr.sz_bot!} />
            ) : (
              <div className="aspect-[4/5] bg-zinc-800 rounded-lg flex items-center justify-center text-zinc-600 text-sm">
                No pitch location data
              </div>
            )}
          </div>
          <div>
            {hasHitLocation ? (
              <SprayChart hcX={hr.hc_x!} hcY={hr.hc_y!} distance={hr.hit_distance_sc} stand={hr.stand} />
            ) : (
              <div className="aspect-square bg-zinc-800 rounded-lg flex items-center justify-center text-zinc-600 text-sm">
                No hit location data
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function Home() {
  const [homeRuns, setHomeRuns] = useState<HomeRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [totalCount, setTotalCount] = useState(0);
  const [filters, setFilters] = useState<Filters>(emptyFilters);
  const [sortCol, setSortCol] = useState<SortColumn>("game_date");
  const [sortDir, setSortDir] = useState<SortDirection>("desc");
  const [teams, setTeams] = useState<string[]>([]);
  const [pitchTypes, setPitchTypes] = useState<string[]>([]);
  const [selectedHR, setSelectedHR] = useState<HomeRun | null>(null);

  // Load filter options on mount
  useEffect(() => {
    async function loadOptions() {
      const { data: teamData } = await supabase
        .from("mlb_pitches")
        .select("batter_team")
        .eq("events", "home_run")
        .not("batter_team", "is", null);

      if (teamData) {
        const unique = [...new Set(teamData.map((r) => r.batter_team))].sort();
        setTeams(unique);
      }

      const { data: pitchData } = await supabase
        .from("mlb_pitches")
        .select("pitch_name")
        .eq("events", "home_run")
        .not("pitch_name", "is", null);

      if (pitchData) {
        const unique = [...new Set(pitchData.map((r) => r.pitch_name))].sort();
        setPitchTypes(unique);
      }
    }
    loadOptions();
  }, []);

  const fetchHomeRuns = useCallback(async () => {
    setLoading(true);
    const from = page * PAGE_SIZE;
    const to = from + PAGE_SIZE - 1;

    let query = supabase
      .from("mlb_pitches")
      .select(
        "game_date, batter_name, batter_team, player_name, pitcher_team, pitch_name, launch_speed, launch_angle, hit_distance_sc, home_team, away_team, plate_x, plate_z, sz_top, sz_bot, hc_x, hc_y, release_speed, stand",
        { count: "exact" }
      )
      .eq("events", "home_run");

    // Text filters
    if (filters.batter_name) query = query.ilike("batter_name", `%${filters.batter_name}%`);
    if (filters.player_name) query = query.ilike("player_name", `%${filters.player_name}%`);
    if (filters.batter_team) query = query.eq("batter_team", filters.batter_team);
    if (filters.pitcher_team) query = query.eq("pitcher_team", filters.pitcher_team);
    if (filters.pitch_name) query = query.eq("pitch_name", filters.pitch_name);

    // Date filters
    if (filters.date_from) query = query.gte("game_date", filters.date_from);
    if (filters.date_to) query = query.lte("game_date", filters.date_to);

    // Numeric range filters
    if (filters.min_exit_velo) query = query.gte("launch_speed", parseFloat(filters.min_exit_velo));
    if (filters.max_exit_velo) query = query.lte("launch_speed", parseFloat(filters.max_exit_velo));
    if (filters.min_launch_angle) query = query.gte("launch_angle", parseInt(filters.min_launch_angle));
    if (filters.max_launch_angle) query = query.lte("launch_angle", parseInt(filters.max_launch_angle));
    if (filters.min_distance) query = query.gte("hit_distance_sc", parseInt(filters.min_distance));
    if (filters.max_distance) query = query.lte("hit_distance_sc", parseInt(filters.max_distance));

    const { data, error, count } = await query
      .order(sortCol, { ascending: sortDir === "asc" })
      .range(from, to);

    if (error) {
      setError(error.message);
    } else {
      setHomeRuns(data || []);
      setTotalCount(count || 0);
      setError(null);
    }
    setLoading(false);
  }, [page, filters, sortCol, sortDir]);

  useEffect(() => {
    fetchHomeRuns();
  }, [fetchHomeRuns]);

  const updateFilter = (key: keyof Filters, value: string) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
    setPage(0);
  };

  const clearFilters = () => {
    setFilters(emptyFilters);
    setPage(0);
  };

  const toggleSort = (col: SortColumn) => {
    if (sortCol === col) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortCol(col);
      setSortDir("desc");
    }
    setPage(0);
  };

  const sortIndicator = (col: SortColumn) => {
    if (sortCol !== col) return <span className="ml-1 text-zinc-700">↕</span>;
    return <span className="ml-1">{sortDir === "asc" ? "↑" : "↓"}</span>;
  };

  const hasActiveFilters = Object.values(filters).some((v) => v !== "");
  const totalPages = Math.ceil(totalCount / PAGE_SIZE);

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 p-8">
      <div className="max-w-7xl mx-auto">
        <h1 className="text-4xl font-bold mb-2">Sports Dashboard</h1>
        <p className="text-zinc-400 mb-6">
          MLB Statcast Home Runs
          {totalCount > 0 && <span className="ml-2 text-zinc-500">({totalCount} total)</span>}
        </p>

        {/* Filters */}
        <div className="bg-zinc-900 rounded-lg p-4 mb-6">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-medium text-zinc-400">Filters</h2>
            {hasActiveFilters && (
              <button onClick={clearFilters} className="text-xs text-zinc-500 hover:text-zinc-300">
                Clear all
              </button>
            )}
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
            <div>
              <label className="block text-xs text-zinc-500 mb-1">Batter</label>
              <input
                type="text"
                placeholder="Search..."
                value={filters.batter_name}
                onChange={(e) => updateFilter("batter_name", e.target.value)}
                className="w-full bg-zinc-800 rounded px-2 py-1.5 text-sm border border-zinc-700 focus:border-zinc-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-xs text-zinc-500 mb-1">Batter Team</label>
              <select
                value={filters.batter_team}
                onChange={(e) => updateFilter("batter_team", e.target.value)}
                className="w-full bg-zinc-800 rounded px-2 py-1.5 text-sm border border-zinc-700 focus:border-zinc-500 focus:outline-none"
              >
                <option value="">All</option>
                {teams.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs text-zinc-500 mb-1">Pitcher</label>
              <input
                type="text"
                placeholder="Search..."
                value={filters.player_name}
                onChange={(e) => updateFilter("player_name", e.target.value)}
                className="w-full bg-zinc-800 rounded px-2 py-1.5 text-sm border border-zinc-700 focus:border-zinc-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-xs text-zinc-500 mb-1">Pitcher Team</label>
              <select
                value={filters.pitcher_team}
                onChange={(e) => updateFilter("pitcher_team", e.target.value)}
                className="w-full bg-zinc-800 rounded px-2 py-1.5 text-sm border border-zinc-700 focus:border-zinc-500 focus:outline-none"
              >
                <option value="">All</option>
                {teams.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs text-zinc-500 mb-1">Pitch Type</label>
              <select
                value={filters.pitch_name}
                onChange={(e) => updateFilter("pitch_name", e.target.value)}
                className="w-full bg-zinc-800 rounded px-2 py-1.5 text-sm border border-zinc-700 focus:border-zinc-500 focus:outline-none"
              >
                <option value="">All</option>
                {pitchTypes.map((p) => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs text-zinc-500 mb-1">Date From</label>
              <input
                type="date"
                value={filters.date_from}
                onChange={(e) => updateFilter("date_from", e.target.value)}
                className="w-full bg-zinc-800 rounded px-2 py-1.5 text-sm border border-zinc-700 focus:border-zinc-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-xs text-zinc-500 mb-1">Date To</label>
              <input
                type="date"
                value={filters.date_to}
                onChange={(e) => updateFilter("date_to", e.target.value)}
                className="w-full bg-zinc-800 rounded px-2 py-1.5 text-sm border border-zinc-700 focus:border-zinc-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-xs text-zinc-500 mb-1">Exit Velo Min</label>
              <input
                type="number"
                placeholder="mph"
                value={filters.min_exit_velo}
                onChange={(e) => updateFilter("min_exit_velo", e.target.value)}
                className="w-full bg-zinc-800 rounded px-2 py-1.5 text-sm border border-zinc-700 focus:border-zinc-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-xs text-zinc-500 mb-1">Exit Velo Max</label>
              <input
                type="number"
                placeholder="mph"
                value={filters.max_exit_velo}
                onChange={(e) => updateFilter("max_exit_velo", e.target.value)}
                className="w-full bg-zinc-800 rounded px-2 py-1.5 text-sm border border-zinc-700 focus:border-zinc-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-xs text-zinc-500 mb-1">Launch Angle Min</label>
              <input
                type="number"
                placeholder="°"
                value={filters.min_launch_angle}
                onChange={(e) => updateFilter("min_launch_angle", e.target.value)}
                className="w-full bg-zinc-800 rounded px-2 py-1.5 text-sm border border-zinc-700 focus:border-zinc-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-xs text-zinc-500 mb-1">Launch Angle Max</label>
              <input
                type="number"
                placeholder="°"
                value={filters.max_launch_angle}
                onChange={(e) => updateFilter("max_launch_angle", e.target.value)}
                className="w-full bg-zinc-800 rounded px-2 py-1.5 text-sm border border-zinc-700 focus:border-zinc-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-xs text-zinc-500 mb-1">Distance Min</label>
              <input
                type="number"
                placeholder="ft"
                value={filters.min_distance}
                onChange={(e) => updateFilter("min_distance", e.target.value)}
                className="w-full bg-zinc-800 rounded px-2 py-1.5 text-sm border border-zinc-700 focus:border-zinc-500 focus:outline-none"
              />
            </div>
          </div>
        </div>

        {loading && <p className="text-zinc-500">Loading...</p>}
        {error && (
          <p className="text-red-400">
            Error: {error} — Make sure you&apos;ve added your Supabase credentials to .env.local
            and run the SQL migration.
          </p>
        )}

        {!loading && !error && homeRuns.length === 0 && (
          <p className="text-zinc-500">
            {hasActiveFilters
              ? "No home runs match your filters."
              : "No home runs found. Run the data pipeline first to load Statcast data."}
          </p>
        )}

        {homeRuns.length > 0 && (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-zinc-800 text-left text-zinc-400">
                    {COLUMN_CONFIG.map(({ key, label }) => (
                      <th
                        key={key}
                        className="pb-3 pr-4 cursor-pointer select-none hover:text-zinc-200"
                        onClick={() => toggleSort(key)}
                      >
                        {label}{sortIndicator(key)}
                      </th>
                    ))}
                    <th className="pb-3">Matchup</th>
                  </tr>
                </thead>
                <tbody>
                  {homeRuns.map((hr, i) => (
                    <tr
                      key={i}
                      className="border-b border-zinc-900 hover:bg-zinc-900/50 cursor-pointer"
                      onClick={() => setSelectedHR(hr)}
                    >
                      <td className="py-3 pr-4">{hr.game_date}</td>
                      <td className="py-3 pr-4 font-medium">
                        {hr.batter_name || "—"}
                        {hr.batter_team && <span className="ml-1 text-zinc-500 text-xs">{hr.batter_team}</span>}
                      </td>
                      <td className="py-3 pr-4">
                        {hr.player_name}
                        {hr.pitcher_team && <span className="ml-1 text-zinc-500 text-xs">{hr.pitcher_team}</span>}
                      </td>
                      <td className="py-3 pr-4">{hr.pitch_name}</td>
                      <td className="py-3 pr-4">
                        {hr.launch_speed ? `${hr.launch_speed.toFixed(1)} mph` : "—"}
                      </td>
                      <td className="py-3 pr-4">
                        {hr.launch_angle != null ? `${hr.launch_angle}°` : "—"}
                      </td>
                      <td className="py-3 pr-4">
                        {hr.hit_distance_sc ? `${hr.hit_distance_sc} ft` : "—"}
                      </td>
                      <td className="py-3">
                        {hr.away_team} @ {hr.home_team}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="flex items-center justify-between mt-6">
              <button
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0}
                className="px-4 py-2 rounded bg-zinc-800 hover:bg-zinc-700 disabled:opacity-30 disabled:cursor-not-allowed"
              >
                Previous
              </button>
              <span className="text-zinc-400 text-sm">
                Page {page + 1} of {totalPages}
              </span>
              <button
                onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                disabled={page >= totalPages - 1}
                className="px-4 py-2 rounded bg-zinc-800 hover:bg-zinc-700 disabled:opacity-30 disabled:cursor-not-allowed"
              >
                Next
              </button>
            </div>
          </>
        )}

        {/* Detail popup */}
        {selectedHR && <DetailPopup hr={selectedHR} onClose={() => setSelectedHR(null)} />}
      </div>
    </div>
  );
}
