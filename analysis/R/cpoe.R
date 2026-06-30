# M4 (Eager & Erickson, Ch.5) — Completion Percentage Over Expected in R.
# GLM / logistic regression: model the PROBABILITY a pass is completed from game situation;
# the residual (actual completion - predicted prob) is QB/offense skill = CPOE. We have no
# air-yards in the feed, so situation = down + distance + yards_to_goal + score diff.
#   glm(is_completion ~ ..., family = binomial)
# Odds ratios (exp(coef)) are reported as the book emphasises.
#
# Reads:  data/gold/plays_model.csv
# Writes: data/results/coef__cpoe__r.csv, metrics__cpoe__r.csv, pred__cpoe__r.csv

source("analysis/R/util_io.R")
suppressPackageStartupMessages({ library(dplyr); library(broom) })
set.seed(42)

FEATURES <- c("down", "distance", "yards_to_goal", "offense_score_diff_start")

plays <- cfb_read_gold("plays_model")

pass <- plays %>%
  filter(is_pass_attempt == 1, !is.na(is_completion),
         !is.na(down), !is.na(distance), !is.na(yards_to_goal),
         !is.na(offense_score_diff_start))

f <- as.formula(paste("is_completion ~", paste(FEATURES, collapse = " + ")))
m <- glm(f, data = pass, family = binomial())

prob <- predict(m, pass, type = "response")
cpoe <- pass$is_completion - prob

# Brier score (mean squared error of the probability) vs the base-rate baseline it must beat.
brier <- mean((pass$is_completion - prob)^2)
base_rate <- mean(pass$is_completion)
brier_base <- mean((pass$is_completion - base_rate)^2)
# log-loss
eps <- 1e-15; p <- pmin(pmax(prob, eps), 1 - eps)
log_loss <- -mean(pass$is_completion * log(p) + (1 - pass$is_completion) * log(1 - p))

coef <- tidy(m) %>%
  transmute(model = "cpoe", term, estimate, std_error = std.error,
            statistic, p_value = p.value,
            odds_ratio = exp(estimate), language = "r")

metrics <- data.frame(
  model = "cpoe",
  metric = c("brier", "brier_baseline", "log_loss", "completion_rate", "n_obs"),
  value = c(brier, brier_base, log_loss, base_rate, nrow(pass)),
  language = "r")

pred <- data.frame(
  play_key = pass$play_key,
  completion_prob = prob,
  cpoe = cpoe,
  language = "r")

cfb_write_result("coef__cpoe__r", coef)
cfb_write_result("metrics__cpoe__r", metrics)
cfb_write_result("pred__cpoe__r", pred)
cat(sprintf("[cpoe/R] Brier=%.4f (baseline %.4f), logloss=%.4f, %d attempts\n",
            brier, brier_base, log_loss, nrow(pass)))
