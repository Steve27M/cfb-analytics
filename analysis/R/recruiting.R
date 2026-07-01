# M8 (Eager & Erickson, Ch.7) — "do teams beat their recruiting?", in R.
# Uses the ETHICALLY-scraped Wikipedia recruiting rankings (see ingest/scrape_recruiting.R,
# validated to match CFBD's sanctioned API exactly). Regresses on-field production (SP+ rating)
# on recruiting-class rank; the residual is how much a team OVER- or UNDER-performed the talent
# it signed. Positive residual = punching above its recruiting weight.
#
# Reads:  data/gold/recruiting_production.csv
# Writes: data/results/coef__recruiting__r.csv, metrics__recruiting__r.csv, pred__recruiting__r.csv

source("analysis/R/util_io.R")
suppressPackageStartupMessages({ library(dplyr); library(broom) })
set.seed(42)

df <- cfb_read_gold("recruiting_production") |>
  filter(!is.na(sp_rating), !is.na(recruiting_rank_247))

m <- lm(sp_rating ~ recruiting_rank_247, data = df)
pred <- predict(m, df)

coef <- tidy(m) |>
  transmute(model = "recruiting", term, estimate, std_error = std.error,
            statistic, p_value = p.value, language = "r")

metrics <- data.frame(
  model = "recruiting",
  metric = c("r_squared", "corr_rank_sp", "n_obs"),
  value = c(summary(m)$r.squared,
            cor(df$recruiting_rank_247, df$sp_rating),
            nrow(df)),
  language = "r")

out <- df |>
  mutate(predicted_sp = pred,
         performance_vs_recruiting = sp_rating - pred,   # + = overperformed the talent
         language = "r") |>
  select(team, season, recruiting_rank_247, sp_rating, win_pct,
         predicted_sp, performance_vs_recruiting, language)

cfb_write_result("coef__recruiting__r", coef)
cfb_write_result("metrics__recruiting__r", metrics)
cfb_write_result("pred__recruiting__r", out)
cat(sprintf("[recruiting/R] SP+ ~ recruiting rank: R2=%.3f, corr=%.3f, %d team-seasons\n",
            summary(m)$r.squared, cor(df$recruiting_rank_247, df$sp_rating), nrow(df)))
