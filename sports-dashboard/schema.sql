-- Run this in your Supabase SQL editor

-- Stores latest odds for each game (upserted every 10 min)
create table if not exists yrfi_odds (
  game_id    text primary key,
  away       text not null,
  home       text not null,
  start_time text,
  yrfi_pct   float,
  over_odds  int,
  under_odds int,
  fetched_at timestamptz
);

-- Tracks which games we've already sent a Discord alert for
create table if not exists yrfi_alerts_sent (
  id         bigint generated always as identity primary key,
  game_id    text not null,
  matchup    text,
  alerted_at timestamptz default now()
);

create index if not exists idx_yrfi_alerts_game_date
  on yrfi_alerts_sent (game_id, alerted_at);
