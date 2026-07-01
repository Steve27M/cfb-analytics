# Generate the committable dashboard preview PNGs (the HTML embeds data and is gitignored, so a
# static attributed image is the public artifact — the OpenSky/portfolio pattern). Reads the same
# flat-file results the dashboard uses; writes docs/*.png.

source("analysis/R/util_io.R")
suppressPackageStartupMessages({ library(dplyr); library(tidyr); library(ggplot2); library(scales) })

theme_set(theme_minimal(base_size = 13))
MODEL <- "#2C7FB8"; MARKET <- "#D95F0E"
ATTRIB <- "Data: CollegeFootballData.com  ·  cfb-analytics (R + Python + dbt + DuckDB)"

gp <- readr::read_csv(file.path("data", "results", "gamepred__game__r.csv"), show_col_types = FALSE)

# 1. Calibration curve — predicted vs observed home-win rate (2024 holdout)
calib <- gp %>%
  mutate(bin = cut(home_win_prob, breaks = seq(0, 1, 0.1), include.lowest = TRUE)) %>%
  group_by(bin) %>%
  summarise(pred = mean(home_win_prob), obs = mean(home_won), n = n(), .groups = "drop")

p_cal <- ggplot(calib, aes(pred, obs)) +
  geom_abline(slope = 1, intercept = 0, linetype = "dashed", colour = "grey60") +
  geom_line(colour = MODEL, linewidth = 0.9) +
  geom_point(aes(size = n), colour = MODEL) +
  scale_size_area(max_size = 9, guide = "none") +
  scale_x_continuous(labels = percent, limits = c(0, 1)) +
  scale_y_continuous(labels = percent, limits = c(0, 1)) +
  labs(title = "Game win-probability model — calibration (2024 holdout)",
       subtitle = "Points on the diagonal = well-calibrated probabilities. Size = games in bin.",
       x = "Predicted P(home win)", y = "Observed home-win rate", caption = ATTRIB) +
  coord_equal()

ggsave(file.path("docs", "preview_calibration.png"), p_cal,
       width = 7, height = 6, dpi = 150, bg = "white")

# 2. Brier by week — model vs betting market (the headline "we approach Vegas" story)
bw <- gp %>%
  group_by(week) %>%
  summarise(Model = mean((home_won - home_win_prob)^2),
            Market = mean((home_won - market_win_prob)^2), .groups = "drop") %>%
  pivot_longer(c(Model, Market), names_to = "source", values_to = "brier")

p_bw <- ggplot(bw, aes(week, brier, colour = source)) +
  geom_line(linewidth = 0.9) + geom_point(size = 2) +
  scale_colour_manual(values = c(Model = MODEL, Market = MARKET), name = NULL) +
  labs(title = "Brier score by week — efficiency model vs betting market (2024)",
       subtitle = "Lower is better. The model tracks the market using only on-field efficiency.",
       x = "Week", y = "Brier score", caption = ATTRIB)

ggsave(file.path("docs", "preview_brier_by_week.png"), p_bw,
       width = 9, height = 5, dpi = 150, bg = "white")

cat("wrote docs/preview_calibration.png and docs/preview_brier_by_week.png\n")
