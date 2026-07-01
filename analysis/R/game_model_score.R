# Game-level win-probability model — SCORE the sealed holdout (R / tidymodels).
# Loads the 2023-trained workflow and scores 2024 (never seen in training). Reports honest
# holdout metrics and pits the model against two baselines the book demands you beat:
#   (1) home-field naive  — predict the training home-win base rate for every game
#   (2) the betting market — implied P(home win) from the consensus spread (margin ~ N(-spread, 13.5))
# The market line is the benchmark; beating its Brier is the bar for "the model is useful".
#
# Reads:  data/gold/game_model.csv, artifacts/models/game_model.rds
# Writes: data/results/metrics__game__r.csv, data/results/gamepred__game__r.csv

source("analysis/R/util_io.R")
suppressPackageStartupMessages({ library(dplyr); library(tidymodels) })
set.seed(42)

MARGIN_SD <- 13.5   # well-known CFB final-margin standard deviation, for the market mapping

df <- cfb_read_gold("game_model")
df$home_won <- factor(df$home_won, levels = c(0, 1))

# Holdout = latest season (matches game_model_train.R); train = every earlier season.
holdout_season <- max(df$season)
train <- df %>% filter(season < holdout_season)
test  <- df %>% filter(season == holdout_season)

final_fit <- readRDS(file.path(getwd(), "artifacts", "models", "game_model.rds"))

y <- as.numeric(as.character(test$home_won))
p_model  <- predict(final_fit, test, type = "prob")$.pred_1
p_naive  <- rep(mean(as.numeric(as.character(train$home_won))), nrow(test))
# spread is home-perspective (negative = home favored) → P(home win) = Phi(-spread / sd)
p_market <- pnorm(-test$home_spread_consensus / MARGIN_SD)

brier <- function(p) mean((y - p)^2)
logloss <- function(p) { p <- pmin(pmax(p, 1e-15), 1 - 1e-15); -mean(y * log(p) + (1 - y) * log(1 - p)) }
acc <- function(p) mean((p >= 0.5) == (y == 1))

metrics <- data.frame(
  model = "game_winprob",
  metric = c("brier", "log_loss", "auc", "accuracy",
             "brier_naive_homefield", "brier_market_line",
             "accuracy_market_line", "n_test"),
  value = c(
    brier(p_model), logloss(p_model),
    roc_auc_vec(test$home_won, p_model, event_level = "second"),
    acc(p_model),
    brier(p_naive), brier(p_market), acc(p_market), nrow(test)),
  language = "r")

pred <- data.frame(
  game_id = test$game_id,
  season = test$season,
  week = test$week,
  home_won = y,
  home_win_prob = p_model,
  market_win_prob = p_market,
  language = "r")

cfb_write_result("metrics__game__r", metrics)
cfb_write_result("gamepred__game__r", pred)
cat(sprintf(paste0("[game/score/R] holdout Brier=%.4f (naive %.4f, market %.4f), ",
                   "AUC=%.3f, acc=%.3f, %d games\n"),
            brier(p_model), brier(p_naive), brier(p_market),
            metrics$value[3], metrics$value[4], nrow(test)))
