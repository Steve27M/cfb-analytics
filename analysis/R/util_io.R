# Shared file-IO helpers for R (ingestion + models). Source from repo root:
#   source("analysis/R/util_io.R")
#
# R and Python exchange data through FLAT FILES (the contract), never in-memory:
#   * R writes bronze CSVs to data/bronze/ ; Python loads them into DuckDB.
#   * Python exports gold tables to data/gold/*.csv ; R models read those.
#   * R models write results to data/results/*.csv ; Python loads them back to DuckDB.
# CSV (via readr, already installed) is used on the R edge because the duckdb/arrow/nanoparquet
# R packages have no Windows binary for the just-released R 4.6.1; Python re-encodes to Parquet.

suppressPackageStartupMessages({
  library(readr)
})

cfb_dir <- function(sub) {
  d <- file.path(getwd(), "data", sub)
  dir.create(d, showWarnings = FALSE, recursive = TRUE)
  d
}

# Bronze CSV path for one table+season (season-partitioned so caching is per-season).
# gz=TRUE for wide tables (plays) -> .csv.gz keeps the dataset tiny; DuckDB reads .gz natively.
cfb_bronze_path <- function(name, season, gz = FALSE) {
  ext <- if (gz) "csv.gz" else "csv"
  file.path(cfb_dir("bronze"), sprintf("%s__%d.%s", name, season, ext))
}

# TRUE if this table+season is already on disk (idempotency / quota saver).
cfb_bronze_present <- function(name, season, gz = FALSE) file.exists(cfb_bronze_path(name, season, gz))

# Write a bronze table to CSV with lineage columns. Append-only semantics: we never rewrite an
# existing season file (immutable bronze). Returns rows written (0 if skipped/empty).
cfb_write_bronze <- function(name, df, season, pull_id, gz = FALSE) {
  if (is.null(df) || nrow(df) == 0) return(0L)
  path <- cfb_bronze_path(name, season, gz)
  if (file.exists(path)) return(0L)  # immutable: do not overwrite
  df$cfb_season <- season
  df$cfb_pull_id <- pull_id
  df$cfb_fetched_at <- format(Sys.time(), "%Y-%m-%d %H:%M:%S")
  readr::write_csv(df, path, na = "")
  nrow(df)
}

# Append one row to the ingest log CSV.
cfb_log_ingest <- function(name, season, rows, source, pull_id) {
  path <- file.path(cfb_dir("bronze"), "_ingest_log.csv")
  row <- data.frame(
    table_name = name, season = season, rows = rows, source = source,
    pull_id = pull_id, fetched_at = format(Sys.time(), "%Y-%m-%d %H:%M:%S"),
    stringsAsFactors = FALSE)
  readr::write_csv(row, path, append = file.exists(path))
  invisible(TRUE)
}

# Read a gold table that Python exported to data/gold/<name>.csv (for model scripts).
cfb_read_gold <- function(name) {
  path <- file.path(cfb_dir("gold"), sprintf("%s.csv", name))
  if (!file.exists(path)) stop(sprintf("gold export not found: %s (run the export step first)", path))
  readr::read_csv(path, show_col_types = FALSE)
}

# Write a model result that Python will load into DuckDB gold.<name>.
cfb_write_result <- function(name, df) {
  path <- file.path(cfb_dir("results"), sprintf("%s.csv", name))
  readr::write_csv(df, path, na = "")
  nrow(df)
}
