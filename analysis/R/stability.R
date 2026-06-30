# M1 (Eager & Erickson, Ch.2) — metric stability / reliability in R.
# Question the book asks: is a per-player efficiency stat SKILL or NOISE? We answer it two ways
# for rushing yards-per-carry: (a) split-half reliability (odd vs even play numbers within a
# season) and (b) year-over-year stability (2023 vs 2024). High reliability => trust the metric
# as a feature; low => regress it toward the mean (motivates the M7 multilevel shrinkage).
#
# Reads:  data/gold/player_rushing.csv   (Python export)
# Writes: data/results/metrics__stability__r.csv  (parity-checked vs the Python mirror)

source("analysis/R/util_io.R")
suppressPackageStartupMessages(library(dplyr))

MIN_SPLIT_ATTEMPTS <- 40   # require this many carries in EACH half for a stable split estimate
MIN_YOY_ATTEMPTS   <- 50   # and this many in EACH season for the year-over-year estimate

pr <- cfb_read_gold("player_rushing")

# Spearman-Brown prophecy: reliability of the FULL test from a half-split correlation.
spearman_brown <- function(r) (2 * r) / (1 + r)

rows <- list()

# (a) split-half reliability, per season
for (s in sort(unique(pr$season))) {
  d <- pr %>%
    filter(season == s, attempts_odd >= MIN_SPLIT_ATTEMPTS, attempts_even >= MIN_SPLIT_ATTEMPTS)
  if (nrow(d) >= 10) {
    r <- cor(d$ypc_odd_plays, d$ypc_even_plays, use = "complete.obs")
    rows[[length(rows) + 1]] <- data.frame(
      model = "stability", metric = "split_half_r_ypc",
      basis = as.character(s), n = nrow(d), value = r)
    rows[[length(rows) + 1]] <- data.frame(
      model = "stability", metric = "split_half_reliability_ypc",
      basis = as.character(s), n = nrow(d), value = spearman_brown(r))
  }
}

# (b) year-over-year stability: same rusher, 2023 ypc vs 2024 ypc
wide <- pr %>%
  filter(rush_attempts >= MIN_YOY_ATTEMPTS) %>%
  select(rusher_player_name, season, yards_per_carry) %>%
  tidyr::pivot_wider(names_from = season, values_from = yards_per_carry,
                     names_prefix = "ypc_")
if (all(c("ypc_2023", "ypc_2024") %in% names(wide))) {
  d <- wide %>% filter(!is.na(ypc_2023), !is.na(ypc_2024))
  if (nrow(d) >= 10) {
    r <- cor(d$ypc_2023, d$ypc_2024)
    rows[[length(rows) + 1]] <- data.frame(
      model = "stability", metric = "year_over_year_r_ypc",
      basis = "2023-2024", n = nrow(d), value = r)
  }
}

out <- bind_rows(rows)
out$language <- "r"
n <- cfb_write_result("metrics__stability__r", out)
cat(sprintf("[stability/R] wrote %d reliability metrics\n", n))
print(out)
