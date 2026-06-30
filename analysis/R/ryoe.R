# M2/M3 (Eager & Erickson, Ch.3-4) — Rushing Yards Over Expected in R.
# The book's "over expected" spine: model EXPECTED rush yards from game situation; the residual
# (actual - expected) is the rusher/offense skill signal (RYOE).
#   M2 simple linear regression:   rush_yards ~ yards_to_goal
#   M3 multiple regression:        rush_yards ~ down + distance + yards_to_goal +
#                                               offense_score_diff_start + defense_def_rating
# M3 is the production model: its residual is written back per-play as RYOE.
#
# Reads:  data/gold/plays_model.csv
# Writes: data/results/coef__ryoe__r.csv, metrics__ryoe__r.csv, pred__ryoe__r.csv

source("analysis/R/util_io.R")
suppressPackageStartupMessages({ library(dplyr); library(broom) })
set.seed(42)

FEATURES_M3 <- c("down", "distance", "yards_to_goal",
                 "offense_score_diff_start", "defense_def_rating")

plays <- cfb_read_gold("plays_model")

rush <- plays %>%
  filter(is_rush == 1, !is.na(rush_yards),
         !is.na(down), !is.na(distance), !is.na(yards_to_goal),
         !is.na(offense_score_diff_start))

# Mean-impute the opponent-defense control so every FBS rush keeps a residual (FCS defenses
# have no SP+ rating). Imputing to the mean leaves that row's contribution neutral.
def_mean <- mean(rush$defense_def_rating, na.rm = TRUE)
rush <- rush %>% mutate(defense_def_rating = coalesce(defense_def_rating, def_mean))

rmse <- function(actual, pred) sqrt(mean((actual - pred)^2))

fit_and_record <- function(formula, model_name) {
  m <- lm(formula, data = rush)
  pred <- predict(m, rush)
  list(
    model = m,
    pred = pred,
    coef = tidy(m) %>%
      transmute(model = model_name, term, estimate, std_error = std.error,
                statistic, p_value = p.value, language = "r"),
    metrics = data.frame(
      model = model_name,
      metric = c("rmse", "r_squared", "n_obs"),
      value = c(rmse(rush$rush_yards, pred), summary(m)$r.squared, nrow(rush)),
      language = "r")
  )
}

m2 <- fit_and_record(rush_yards ~ yards_to_goal, "ryoe_simple")
m3 <- fit_and_record(
  as.formula(paste("rush_yards ~", paste(FEATURES_M3, collapse = " + "))),
  "ryoe_multiple")

# baseline = predict the global mean rush_yards for everyone (what RYOE must beat)
base_rmse <- rmse(rush$rush_yards, mean(rush$rush_yards))

coef <- bind_rows(m2$coef, m3$coef)
metrics <- bind_rows(
  m2$metrics, m3$metrics,
  data.frame(model = "baseline_mean", metric = "rmse", value = base_rmse, language = "r"))

# production RYOE = M3 residual, written back per play_key
pred <- data.frame(
  play_key = rush$play_key,
  expected_rush_yards = m3$pred,
  ryoe = rush$rush_yards - m3$pred,
  language = "r")

cfb_write_result("coef__ryoe__r", coef)
cfb_write_result("metrics__ryoe__r", metrics)
cfb_write_result("pred__ryoe__r", pred)
cat(sprintf("[ryoe/R] M3 RMSE=%.3f (baseline %.3f), R2=%.4f, %d plays\n",
            m3$metrics$value[1], base_rmse, m3$metrics$value[2], nrow(rush)))
