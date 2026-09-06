# In-season update model (R) — update the preseason forecast as results arrive.
# The priors model predicts a season before it starts; this model starts every team at that
# preseason strength and moves it toward season-to-date, opponent-adjusted scoring margins. It is
# a Bayesian ridge on margins whose prior mean is the preseason strength:
#   1. strength s_T = priors-model linear predictor per team (centered within season), logit scale
#   2. OLS  home_margin ~ 0 + home_ind + (s_home - s_away)  ->  home_adv, gamma (logit -> points)
#   3. before each kickoff, ratings r = gamma*s + delta with
#        delta = argmin sum_g (margin_g - home_adv*home_ind_g - (r_h - r_a))^2 + k*sum_T delta_T^2
#      over the games already played (k = games of trust in the preseason prior)
#   4. glm(home_won ~ pred_margin), pred_margin = r_h - r_a + home_adv*home_ind;
#      k chosen by training-season deviance over K_GRID; latest season = sealed holdout
# Closed-form solves + an unregularised glm, so Python (inseason.py) must reproduce every number;
# ridge_k / gamma / home_adv are written as coefficient rows so they enter the parity gate too.
#
# Reads:  data/gold/team_priors.csv, data/gold/inseason_games.csv, data/results/coef__priors__r.csv
# Writes: coef__inseason__r, metrics__inseason__r, metrics__inseason_k__r, gamepred__inseason__r

source("analysis/R/util_io.R")
suppressPackageStartupMessages({ library(dplyr); library(broom); library(yardstick) })

K_GRID <- c(1, 2, 3, 4, 6, 8, 12, 16, 24, 32)
PRIOR_TERMS <- c(prior_sp_diff = "prior_sp", prior_net_epa_diff = "prior_net_epa",
                 prior_win_pct_diff = "prior_win_pct")

tp <- cfb_read_gold("team_priors")
games <- cfb_read_gold("inseason_games")
pcoef <- readr::read_csv(file.path(cfb_dir("results"), "coef__priors__r.csv"), show_col_types = FALSE)
b <- setNames(pcoef$estimate, pcoef$term)

# 1. preseason strength, centered within season
tp$strength <- 0
for (term in names(PRIOR_TERMS)) tp$strength <- tp$strength + b[[term]] * tp[[PRIOR_TERMS[[term]]]]
tp <- tp %>% group_by(season) %>% mutate(strength = strength - mean(strength)) %>% ungroup()
strength <- tp %>% select(season, team, strength)

games <- games %>%
  inner_join(strength %>% rename(home_team = team, s_home = strength), by = c("season", "home_team")) %>%
  inner_join(strength %>% rename(away_team = team, s_away = strength), by = c("season", "away_team")) %>%
  mutate(ps_diff = s_home - s_away, home_ind = 1 - neutral_site,
         prior_win_prob = 1 / (1 + exp(-(b[["(Intercept)"]] + ps_diff)))) %>%
  arrange(season, start_date, game_id)

holdout_season <- max(games$season)
train <- games %>% filter(season < holdout_season)
test  <- games %>% filter(season == holdout_season)

# 2. logit-scale strength -> points, plus home field
scale_fit <- lm(home_margin ~ 0 + home_ind + ps_diff, data = train)
home_adv <- unname(coef(scale_fit)[["home_ind"]])
gamma    <- unname(coef(scale_fit)[["ps_diff"]])

# 3. posterior ratings given the games played so far (closed-form ridge)
ridge_ratings <- function(played, st, k) {
  teams <- st$team
  prior <- gamma * st$strength
  names(prior) <- teams
  if (nrow(played) == 0) return(prior)
  n <- nrow(played); Tn <- length(teams)
  hi <- match(played$home_team, teams); ai <- match(played$away_team, teams)
  X <- matrix(0, n, Tn)
  X[cbind(seq_len(n), hi)] <- 1
  X[cbind(seq_len(n), ai)] <- -1
  y <- played$home_margin - home_adv * played$home_ind - (prior[hi] - prior[ai])
  delta <- solve(crossprod(X) + k * diag(Tn), crossprod(X, y))
  r <- prior + as.vector(delta)
  names(r) <- teams
  r
}

# leakage-safe predicted margin: ratings use only games that kicked off strictly earlier
as_of_pred_margin <- function(g, st, k) {
  g <- g %>% arrange(start_date, game_id)
  out <- numeric(nrow(g))
  ratings <- ridge_ratings(g[0, ], st, k)
  seen_until <- NA
  for (i in seq_len(nrow(g))) {
    if (is.na(seen_until) || g$start_date[i] != seen_until) {
      ratings <- ridge_ratings(g[g$start_date < g$start_date[i], ], st, k)
      seen_until <- g$start_date[i]
    }
    out[i] <- ratings[[g$home_team[i]]] - ratings[[g$away_team[i]]] + home_adv * g$home_ind[i]
  }
  g$pred_margin <- out
  g
}

season_margins <- function(df, k) {
  bind_rows(lapply(split(df, df$season), function(g) {
    st <- strength %>% filter(season == g$season[1])
    as_of_pred_margin(g, st, k)
  }))
}

# 4. choose k by training deviance (2-parameter map; margins are already pre-kickoff)
grid <- data.frame(model = "inseason_winprob", metric = paste0("deviance_k", K_GRID),
                   value = sapply(K_GRID, function(k) {
                     tr <- season_margins(train, k)
                     deviance(glm(home_won ~ pred_margin, data = tr, family = binomial()))
                   }), language = "r")
best_k <- K_GRID[which.min(grid$value)]

tr <- season_margins(train, best_k)
final <- glm(home_won ~ pred_margin, data = tr, family = binomial())
te <- season_margins(test, best_k)
y <- te$home_won
p_model <- predict(final, te, type = "response")
p_prior <- te$prior_win_prob
p_naive <- rep(mean(train$home_won), nrow(te))

# min games already played by either side (phase-of-season reporting)
long <- bind_rows(te %>% transmute(game_id, start_date, team = home_team),
                  te %>% transmute(game_id, start_date, team = away_team)) %>%
  arrange(team, start_date, game_id) %>% group_by(team) %>% mutate(n = row_number() - 1) %>%
  ungroup() %>% group_by(game_id) %>% summarise(n = min(n), .groups = "drop")
entering <- long$n[match(te$game_id, long$game_id)]
late <- entering >= 4

brier <- function(y, p) mean((y - p)^2)
logloss <- function(y, p) { p <- pmin(pmax(p, 1e-15), 1 - 1e-15); -mean(y * log(p) + (1 - y) * log(1 - p)) }
auc <- roc_auc_vec(factor(y, levels = c(0, 1)), p_model, event_level = "second")

coef <- data.frame(
  model = "inseason_winprob",
  term = c("(Intercept)", "pred_margin", "ridge_k", "gamma", "home_adv"),
  estimate = c(unname(coef(final)), best_k, gamma, home_adv),
  language = "r")
coef$odds_ratio <- ifelse(coef$term %in% c("(Intercept)", "pred_margin"), exp(coef$estimate), NA)

metrics <- data.frame(
  model = "inseason_winprob",
  metric = c("brier", "log_loss", "auc", "accuracy", "brier_naive", "brier_priors",
             "accuracy_priors", "brier_from_game4", "brier_priors_from_game4", "n_from_game4",
             "ridge_k", "n_test", "n_train"),
  value = c(brier(y, p_model), logloss(y, p_model), auc, mean((p_model >= 0.5) == (y == 1)),
            brier(y, p_naive), brier(y, p_prior), mean((p_prior >= 0.5) == (y == 1)),
            brier(y[late], p_model[late]), brier(y[late], p_prior[late]), sum(late),
            best_k, nrow(te), nrow(tr)),
  language = "r")

pred <- data.frame(
  game_id = te$game_id, season = te$season, week = te$week, home_won = y,
  pred_margin = te$pred_margin, inseason_win_prob = as.numeric(p_model),
  prior_win_prob = p_prior, games_entering_min = entering, language = "r")

cfb_write_result("coef__inseason__r", coef)
cfb_write_result("metrics__inseason__r", metrics)
cfb_write_result("metrics__inseason_k__r", grid)
cfb_write_result("gamepred__inseason__r", pred)
cat(sprintf("[inseason/R] k=%g gamma=%.3f home_adv=%.2f | holdout Brier=%.4f (priors-only %.4f, naive %.4f), AUC=%.3f, from game 4: %.4f vs priors %.4f, %d games\n",
            best_k, gamma, home_adv, brier(y, p_model), brier(y, p_prior), brier(y, p_naive), auc,
            brier(y[late], p_model[late]), brier(y[late], p_prior[late]), nrow(te)))
