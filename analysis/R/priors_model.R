# Preseason priors model (R) — predict games BEFORE current-season form exists.
# The in-season game model needs a few weeks of this-year results; this one uses only PRIOR-season
# carryover (last year's SP+ rating, net EPA, win rate), so it can forecast week-1 / openers and a
# whole schedule the moment it's loaded. It is deliberately expected to be LESS accurate than the
# in-season model — preseason uncertainty is real — and that gap is the honest headline.
#
# Reads:  data/gold/game_priors.csv
# Writes: artifacts/models/priors_model.rds, coef__priors__r.csv, metrics__priors__r.csv,
#         gamepred__priors__r.csv
# Apply to a future season: score data/gold/game_priors rows for that season with the saved model.

source("analysis/R/util_io.R")
suppressPackageStartupMessages({ library(dplyr); library(broom); library(yardstick) })
set.seed(42)

FEATURES <- c("prior_sp_diff", "prior_net_epa_diff", "prior_win_pct_diff")
f <- as.formula(paste("home_won ~", paste(FEATURES, collapse = " + ")))

df <- cfb_read_gold("game_priors")

# holdout = latest season (auto-adapts); train on earlier seasons
holdout_season <- max(df$season)
train <- df %>% filter(season < holdout_season)
test  <- df %>% filter(season == holdout_season)

m <- glm(f, data = train, family = binomial())

p_model <- predict(m, test, type = "response")
p_naive <- rep(mean(train$home_won), nrow(test))
y <- test$home_won
brier <- function(p) mean((y - p)^2)
logloss <- function(p) { p <- pmin(pmax(p, 1e-15), 1 - 1e-15); -mean(y * log(p) + (1 - y) * log(1 - p)) }
auc <- roc_auc_vec(factor(y, levels = c(0, 1)), p_model, event_level = "second")

coef <- tidy(m) %>%
  transmute(model = "priors_winprob", term, estimate, std_error = std.error,
            statistic, p_value = p.value, odds_ratio = exp(estimate), language = "r")

metrics <- data.frame(
  model = "priors_winprob",
  metric = c("brier", "log_loss", "auc", "accuracy", "brier_naive", "n_test", "n_train"),
  value = c(brier(p_model), logloss(p_model), auc,
            mean((p_model >= 0.5) == (y == 1)), brier(p_naive), nrow(test), nrow(train)),
  language = "r")

pred <- data.frame(
  game_id = test$game_id, season = test$season,
  home_won = y, prior_win_prob = p_model, language = "r")

dir.create(file.path(getwd(), "artifacts", "models"), showWarnings = FALSE, recursive = TRUE)
saveRDS(m, file.path(getwd(), "artifacts", "models", "priors_model.rds"))
cfb_write_result("coef__priors__r", coef)
cfb_write_result("metrics__priors__r", metrics)
cfb_write_result("gamepred__priors__r", pred)
cat(sprintf("[priors/R] preseason holdout Brier=%.4f (naive %.4f), AUC=%.3f, acc=%.3f, %d games\n",
            brier(p_model), brier(p_naive), auc, mean((p_model >= 0.5) == (y == 1)), nrow(test)))
