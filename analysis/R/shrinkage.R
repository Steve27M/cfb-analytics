# M7 (Eager & Erickson, Ch.9) — multilevel / mixed-effects shrinkage in R.
# M1 showed rushing efficiency is noisy; M7 fixes what to DO about it. A random-intercept model
# on per-play RYOE partially pools each rusher toward the league mean; the pull is largest for
# small-sample rushers (regression to the mean). The BLUP is the rusher's shrunken RYOE — the
# estimate you'd actually trust over the raw average.
#   lmer(ryoe ~ 1 + (1 | rusher))
#
# Reads:  data/gold/plays_model.csv, data/results/pred__ryoe__r.csv
# Writes: data/results/pred__shrinkage__r.csv, coef__shrinkage__r.csv, metrics__shrinkage__r.csv

source("analysis/R/util_io.R")
suppressPackageStartupMessages({ library(dplyr); library(lme4) })
set.seed(42)

MIN_CARRIES <- 5

plays <- cfb_read_gold("plays_model") |>
  filter(is_rush == 1, !is.na(rusher_player_name)) |>
  select(play_key, rusher = rusher_player_name)
ryoe <- readr::read_csv(file.path("data", "results", "pred__ryoe__r.csv"),
                        show_col_types = FALSE) |>
  select(play_key, ryoe)

d <- inner_join(ryoe, plays, by = "play_key") |>
  group_by(rusher) |> filter(n() >= MIN_CARRIES) |> ungroup()

m <- lmer(ryoe ~ 1 + (1 | rusher), data = d)

grand <- as.numeric(fixef(m)[1])
re <- ranef(m)$rusher                        # per-rusher intercept deviation (shrunken)
vc <- as.data.frame(VarCorr(m))
tau <- vc$sdcor[vc$grp == "rusher"]          # between-rusher SD
sigma <- vc$sdcor[vc$grp == "Residual"]      # within-rusher (play) SD

raw <- d |> group_by(rusher) |>
  summarise(carries = n(), raw_ryoe = mean(ryoe), .groups = "drop")
shrunk <- tibble(rusher = rownames(re), shrunk_ryoe = grand + re[, 1])

pred <- raw |>
  inner_join(shrunk, by = "rusher") |>
  mutate(shrinkage = raw_ryoe - shrunk_ryoe, language = "r")

coef <- data.frame(model = "shrinkage", term = "(Intercept)", estimate = grand, language = "r")
metrics <- data.frame(
  model = "shrinkage",
  metric = c("grand_mean_ryoe", "tau_between_rusher_sd", "sigma_residual_sd",
             "icc", "n_rushers", "n_plays"),
  value = c(grand, tau, sigma, tau^2 / (tau^2 + sigma^2), nrow(pred), nrow(d)),
  language = "r")

cfb_write_result("pred__shrinkage__r", pred)
cfb_write_result("coef__shrinkage__r", coef)
cfb_write_result("metrics__shrinkage__r", metrics)
cat(sprintf("[shrinkage/R] tau=%.3f sigma=%.3f ICC=%.4f; %d rushers (>=%d carries)\n",
            tau, sigma, tau^2 / (tau^2 + sigma^2), nrow(pred), MIN_CARRIES))
