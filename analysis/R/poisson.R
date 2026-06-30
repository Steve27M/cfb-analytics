# M5 (Eager & Erickson, Ch.6) — Passing-TD counts via Poisson regression in R.
# Count model: passing TDs per team-game ~ exposure (pass attempts) + opponent defense quality.
# The book flags OVERDISPERSION (variance > mean) in count data and reaches for the negative
# binomial; we fit BOTH glm(poisson) and MASS::glm.nb and report the dispersion + which fits
# better (AIC). This is the betting-prop framing (expected passing TDs vs a book line).
#
# Reads:  data/gold/team_game_passing.csv
# Writes: data/results/coef__poisson__r.csv, metrics__poisson__r.csv

source("analysis/R/util_io.R")
suppressPackageStartupMessages({ library(dplyr); library(broom); library(MASS) })
set.seed(42)

tg <- cfb_read_gold("team_game_passing") %>%
  filter(!is.na(passing_tds), !is.na(pass_attempts), pass_attempts > 0,
         !is.na(opponent_defense_rating))

# log(attempts) as an offset-like control + opponent defense rating as the difficulty term
f <- passing_tds ~ log(pass_attempts) + opponent_defense_rating

pois <- glm(f, data = tg, family = poisson())

# overdispersion check: Pearson chi-sq / residual df ; >> 1 signals the NB is warranted
disp <- sum(residuals(pois, type = "pearson")^2) / pois$df.residual

nb <- tryCatch(glm.nb(f, data = tg), error = function(e) NULL)

coef <- tidy(pois) %>%
  transmute(model = "passing_td_poisson", term, estimate, std_error = std.error,
            statistic, p_value = p.value, rate_ratio = exp(estimate), language = "r")

metrics <- data.frame(
  model = "passing_td_poisson",
  metric = c("dispersion", "aic_poisson", "mean_tds", "var_tds", "n_obs"),
  value = c(disp, AIC(pois), mean(tg$passing_tds), var(tg$passing_tds), nrow(tg)),
  language = "r")

if (!is.null(nb)) {
  nb_coef <- tidy(nb) %>%
    transmute(model = "passing_td_negbin", term, estimate, std_error = std.error,
              statistic, p_value = p.value, rate_ratio = exp(estimate), language = "r")
  coef <- bind_rows(coef, nb_coef)
  metrics <- bind_rows(metrics, data.frame(
    model = "passing_td_negbin",
    metric = c("aic_negbin", "theta"),
    value = c(AIC(nb), nb$theta), language = "r"))
}

cfb_write_result("coef__poisson__r", coef)
cfb_write_result("metrics__poisson__r", metrics)
cat(sprintf("[poisson/R] dispersion=%.3f, AIC poisson=%.1f%s, %d team-games\n",
            disp, AIC(pois),
            if (!is.null(nb)) sprintf(" / NB=%.1f", AIC(nb)) else "", nrow(tg)))
