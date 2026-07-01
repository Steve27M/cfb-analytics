# M8 (Eager & Erickson, Ch.7) — web scraping, done ethically.
#
# Scrapes TEAM-level college-football recruiting-class rankings from Wikipedia, the deliberately-
# chosen source after a terms pre-flight:
#   * Wikipedia article pages explicitly welcome "friendly, low-speed bots" (robots.txt) and are
#     CC BY-SA licensed (reuse permitted with attribution).
#   * The major recruiting sites (247Sports/Rivals/On3/ESPN) were REJECTED: their ToS prohibit
#     automated extraction, and their pages carry individual-recruit (often minors') data.
#   * We take ONLY the aggregate "Top ranked classes" TEAM table — never the individual-recruit
#     section on the same page. No personal data of high-school athletes is collected.
#
# Guardrails: a descriptive User-Agent naming the project + contact; a courteous delay between
# requests; and caching — a season already scraped is never re-fetched (idempotent, minimal load).
# Raw HTML/CSV is gitignored like all other bronze; only derived aggregates are published.
# Attribution: rankings via 247Sports / Rivals / On3, page text CC BY-SA Wikipedia.

source("analysis/R/util_io.R")
suppressPackageStartupMessages({ library(rvest); library(httr); library(dplyr) })

SEASONS <- as.integer(strsplit(Sys.getenv("CFB_SEASONS", "2023,2024"), ",")[[1]])
UA <- paste("cfb-analytics/1.0 (college-football portfolio project;",
            "+https://github.com/Steve27M/cfb-analytics) rvest/httr")
REQUEST_DELAY_SEC <- 5   # be gentle: well under Wikipedia's tolerance, only 1 request per season

# Pull the "Top ranked classes" team table off one season's Wikipedia recruiting-class page.
scrape_recruiting_year <- function(season) {
  if (cfb_bronze_present("recruiting", season)) {
    message(sprintf("[recruiting] %d already cached — skipping fetch", season))
    return(invisible(0L))
  }
  url <- sprintf("https://en.wikipedia.org/wiki/%d_college_football_recruiting_class", season)
  Sys.sleep(REQUEST_DELAY_SEC)
  resp <- GET(url, user_agent(UA))
  if (http_error(resp)) {
    warning(sprintf("[recruiting] %d fetch failed: HTTP %d", season, status_code(resp)))
    return(invisible(0L))
  }
  page <- read_html(content(resp, as = "text", encoding = "UTF-8"))

  # Find the team table: a wikitable whose header names the ranking outlets, and whose first
  # column is the school. Take ONLY this table (ignore the individual-recruit table on the page).
  tables <- html_table(page, fill = TRUE)
  pick <- NULL
  for (tb in tables) {
    nm <- tolower(paste(names(tb), collapse = " "))
    if (grepl("247", nm) && (grepl("school", nm) || grepl("team", nm))) { pick <- tb; break }
  }
  if (is.null(pick)) {
    warning(sprintf("[recruiting] %d: team table not found", season))
    return(invisible(0L))
  }

  # normalise column names -> school, rank_247, rank_rivals, rank_on3
  names(pick) <- tolower(gsub("[^a-z0-9]+", "_", tolower(names(pick))))
  school_col <- names(pick)[grepl("school|team", names(pick))][1]
  col247 <- names(pick)[grepl("247", names(pick))][1]
  rivals_col <- names(pick)[grepl("rivals", names(pick))][1]
  on3_col <- names(pick)[grepl("on3", names(pick))][1]

  clean_rank <- function(x) suppressWarnings(as.integer(gsub("[^0-9].*$", "", trimws(x))))
  df <- tibble(
    school = trimws(gsub("\\[.*?\\]", "", pick[[school_col]])),   # strip footnote markers
    rank_247 = clean_rank(pick[[col247]]),
    rank_rivals = if (!is.na(rivals_col)) clean_rank(pick[[rivals_col]]) else NA_integer_,
    rank_on3 = if (!is.na(on3_col)) clean_rank(pick[[on3_col]]) else NA_integer_
  ) |>
    filter(!is.na(school), school != "", !is.na(rank_247))

  pull_id <- format(Sys.time(), "%Y%m%dT%H%M%S")
  n <- cfb_write_bronze("recruiting", as.data.frame(df), season, pull_id)
  cfb_log_ingest("recruiting", season, n, "wikipedia_scrape", pull_id)
  message(sprintf("[recruiting] %d scraped: %d teams", season, n))
  invisible(n)
}

for (s in SEASONS) scrape_recruiting_year(s)
