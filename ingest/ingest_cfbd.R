#!/usr/bin/env Rscript
# Phase 1 — CFBD -> data/bronze/*.csv (append-only, immutable, lineage-tagged).
# Python (load_bronze) then loads these CSVs into DuckDB bronze.* (Parquet/warehouse side).
#
# Quota strategy (§9: free tier = 1,000 API calls/month + Cloudflare anti-burst):
#   * Play-by-play loads QUOTA-FREE via cfbfastR::load_cfb_pbp() (cfbfastR data repo,
#     no CFBD API call, no key) — already carries EPA/wp. Bulk of the data.
#   * A handful of SEASON-LEVEL cfbd_* endpoints (games, lines, SP+, teams, calendar) spend
#     the budget — ~5 calls/season. Two seasons ~ 10 calls (well under 1,000/month).
#   * Idempotent + cached: a season already on disk is SKIPPED (0 re-pulls, 0 API spend).
#   * Throttled: a short sleep between API calls avoids Cloudflare bursts.
#
# Run from repo root:  Rscript ingest/ingest_cfbd.R
# Seasons from CFB_SEASONS (e.g. "2023,2024"); CFBD_API_KEY from .Renviron.

suppressPackageStartupMessages({
  library(cfbfastR)
  library(dplyr)
})
source("analysis/R/util_io.R")

THROTTLE_SEC <- 2  # polite pause between CFBD API calls

# cfbfastR PBP has ~365 columns; keep only what the book's models need (drops play_text and
# ~300 noise columns -> turns a 540MB CSV into a few MB gzipped). select(any_of()) is tolerant.
PBP_KEEP <- c(
  # identity / context
  "year", "week", "game_id", "id_play", "game_play_number", "pos_team", "def_pos_team",
  "home", "away", "pos_team_score", "def_pos_team_score", "pos_score_diff_start",
  "half", "period", "clock_minutes", "clock_seconds", "TimeSecsRem",
  "down", "distance", "yards_to_goal", "yards_gained", "play_type",
  "season_type", "neutral_site", "conference_game", "Goal_To_Go",
  # expected-value signal (already computed by cfbfastR)
  "EPA", "ep_before", "ep_after", "success", "wp_before", "wp_after",
  # rush / pass / result flags
  "rush", "rush_td", "pass", "pass_td", "completion", "pass_attempt", "target", "sack",
  "td_play", "touchdown", "fg_made",
  # players + yardage (RYOE / CPOE)
  "rusher_player_name", "yds_rushed", "passer_player_name", "receiver_player_name", "yds_receiving"
)

SEASONS <- as.integer(strsplit(Sys.getenv("CFB_SEASONS", "2023,2024"), ",")[[1]])
have_key <- nchar(Sys.getenv("CFBD_API_KEY")) > 0
if (!have_key) message("WARNING: CFBD_API_KEY not set — API endpoints skipped; PBP (quota-free) still loads.")
PULL_ID <- format(Sys.time(), "%Y%m%dT%H%M%S")

# Safely run one CFBD API endpoint: skip if cached, throttle, tolerate per-endpoint failure.
ingest_api <- function(name, season, fn) {
  if (cfb_bronze_present(name, season)) { message(sprintf("  [skip] %s %d (cached)", name, season)); return(invisible()) }
  if (!have_key) { message(sprintf("  [skip] %s (no API key)", name)); return(invisible()) }
  out <- tryCatch(fn(), error = function(e) { message(sprintf("  [warn] %s failed: %s", name, conditionMessage(e))); NULL })
  Sys.sleep(THROTTLE_SEC)
  n <- cfb_write_bronze(name, out, season, PULL_ID)
  cfb_log_ingest(name, season, n, "cfbd_api", PULL_ID)
  message(sprintf("  [ok]   %s %d: %d rows", name, season, n))
}

for (yr in SEASONS) {
  message(sprintf("=== Season %d ===", yr))

  # Quota-free play-by-play (carries EPA/wp); drives are derived in dbt from PBP.
  # Wide table -> select model columns + gzip to keep it tiny.
  if (!cfb_bronze_present("plays", yr, gz = TRUE)) {
    pbp <- tryCatch(cfbfastR::load_cfb_pbp(seasons = yr),
                    error = function(e) { message("  [warn] load_cfb_pbp: ", conditionMessage(e)); NULL })
    if (!is.null(pbp)) pbp <- dplyr::select(pbp, dplyr::any_of(PBP_KEEP))
    n <- cfb_write_bronze("plays", pbp, yr, PULL_ID, gz = TRUE)
    cfb_log_ingest("plays", yr, n, "load_cfb_pbp", PULL_ID)
    message(sprintf("  [ok]   plays %d: %d rows, %d cols (quota-free, gz)", yr, n,
                    if (is.null(pbp)) 0L else ncol(pbp)))
  } else message(sprintf("  [skip] plays %d (cached)", yr))

  # Budgeted season-level API endpoints (~5 calls/season)
  ingest_api("games",      yr, function() cfbfastR::cfbd_game_info(year = yr, season_type = "both"))
  ingest_api("lines",      yr, function() cfbfastR::cfbd_betting_lines(year = yr))
  ingest_api("ratings_sp", yr, function() cfbfastR::cfbd_ratings_sp(year = yr))
  ingest_api("teams",      yr, function() cfbfastR::cfbd_team_info(year = yr))
  ingest_api("calendar",   yr, function() cfbfastR::cfbd_calendar(year = yr))
}

message("Ingestion complete. Files in data/bronze/:")
for (f in list.files(cfb_dir("bronze"), pattern = "\\.csv$")) message("  ", f)
