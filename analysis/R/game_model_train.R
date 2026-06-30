# Game-level win-probability model — TRAIN (R / tidymodels).
# Predict P(home team wins) from book-derived, leakage-safe entering-form differentials
# (home minus away season-to-date efficiency). Trains on 2023 as a sealed time-ordered set;
# 2024 is the untouched holdout scored by game_model_score.R. Reports a walk-forward CV
# (train weeks 1..k, predict week k+1 — the no-leakage discipline the book insists on) and
# saves the fitted workflow as the artifact the score step consumes.
#
# Reads:  data/gold/game_model.csv
# Writes: artifacts/models/game_model.rds, data/results/coef__game__r.csv,
#         data/results/metrics__game_cv__r.csv

source("analysis/R/util_io.R")
suppressPackageStartupMessages({ library(dplyr); library(tidymodels); library(broom) })
set.seed(42)

# NOTE: net_epa_diff = off_epa_diff - def_epa_diff exactly, so it is excluded to avoid perfect
# collinearity (which makes the individual coefficients unidentifiable / R-vs-Python divergent).
FEATURES <- c("off_epa_diff", "def_epa_diff",
              "roll3_net_epa_diff", "win_pct_diff", "sos_diff")
f <- as.formula(paste("home_won ~", paste(FEATURES, collapse = " + ")))

df <- cfb_read_gold("game_model")
df$home_won <- factor(df$home_won, levels = c(0, 1))   # "1" = home win = event of interest

train <- df %>% filter(season == 2023) %>% arrange(week)

spec <- logistic_reg() %>% set_engine("glm")
wf <- workflow() %>% add_formula(f) %>% add_model(spec)

brier <- function(y, p) mean((as.numeric(as.character(y)) - p)^2)

# Walk-forward CV: for each week k (after a 2-week burn-in), train on weeks < k, predict week k.
weeks <- sort(unique(train$week))
cv_pred <- list()
for (k in weeks[weeks >= min(weeks) + 2]) {
  tr <- train %>% filter(week < k)
  te <- train %>% filter(week == k)
  if (nrow(tr) < 30 || nrow(te) == 0) next
  m <- fit(wf, tr)
  p <- predict(m, te, type = "prob")$.pred_1
  cv_pred[[length(cv_pred) + 1]] <- tibble(home_won = te$home_won, p = p)
}
cv <- bind_rows(cv_pred)
cv_metrics <- data.frame(
  model = "game_winprob",
  metric = c("cv_brier", "cv_log_loss", "cv_auc", "cv_n"),
  value = c(
    brier(cv$home_won, cv$p),
    mn_log_loss_vec(cv$home_won, cv$p, event_level = "second"),
    roc_auc_vec(cv$home_won, cv$p, event_level = "second"),
    nrow(cv)),
  language = "r")

# Final fit on ALL of 2023 → the artifact the holdout scorer loads
final_fit <- fit(wf, train)

coef <- tidy(extract_fit_engine(final_fit)) %>%
  transmute(model = "game_winprob", term, estimate, std_error = std.error,
            statistic, p_value = p.value, odds_ratio = exp(estimate), language = "r")

dir.create(file.path(getwd(), "artifacts", "models"), showWarnings = FALSE, recursive = TRUE)
saveRDS(final_fit, file.path(getwd(), "artifacts", "models", "game_model.rds"))
cfb_write_result("coef__game__r", coef)
cfb_write_result("metrics__game_cv__r", cv_metrics)
cat(sprintf("[game/train/R] CV Brier=%.4f AUC=%.3f over %d games; trained on %d (2023)\n",
            cv_metrics$value[1], cv_metrics$value[3], cv_metrics$value[4], nrow(train)))
