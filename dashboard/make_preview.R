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
  labs(title = "Game win-probability model — calibration (2025 holdout)",
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
  labs(title = "Brier score by week — efficiency model vs betting market (2025)",
       subtitle = "Lower is better. The model tracks the market using only on-field efficiency.",
       x = "Week", y = "Brier score", caption = ATTRIB)

ggsave(file.path("docs", "preview_brier_by_week.png"), p_bw,
       width = 9, height = 5, dpi = 150, bg = "white")

# 3. M7 shrinkage — raw vs partially-pooled RYOE (regression to the mean)
sh <- readr::read_csv(file.path("data", "results", "pred__shrinkage__r.csv"),
                      show_col_types = FALSE) %>%
  select(carries, Raw = raw_ryoe, Shrunk = shrunk_ryoe) %>%
  tidyr::pivot_longer(c(Raw, Shrunk), names_to = "estimate", values_to = "ryoe")

p_sh <- ggplot(sh, aes(carries, ryoe, colour = estimate)) +
  geom_hline(yintercept = 0, colour = "grey70") +
  geom_point(alpha = 0.4, size = 1.3) +
  scale_x_log10() +
  scale_colour_manual(values = c(Raw = "grey60", Shrunk = MODEL), name = NULL) +
  labs(title = "Multilevel shrinkage of rushing RYOE (M7)",
       subtitle = "Grey = raw per-rusher average; blue = shrunken estimate. Small samples regress to the mean.",
       x = "Carries (log scale)", y = "RYOE per carry", caption = ATTRIB)

ggsave(file.path("docs", "preview_shrinkage.png"), p_sh,
       width = 9, height = 5, dpi = 150, bg = "white")

# 4. M8 recruiting vs production — who beats their recruiting (ethically-scraped rankings)
rec <- readr::read_csv(file.path("data", "results", "pred__recruiting__r.csv"),
                       show_col_types = FALSE)
ext <- dplyr::bind_rows(dplyr::slice_max(rec, performance_vs_recruiting, n = 3),
                        dplyr::slice_min(rec, performance_vs_recruiting, n = 3))
p_rec <- ggplot(rec, aes(recruiting_rank_247, sp_rating)) +
  geom_smooth(method = "lm", se = FALSE, colour = "grey55", linewidth = 0.8) +
  geom_point(aes(colour = performance_vs_recruiting), size = 2.6) +
  geom_text(data = ext, aes(label = paste0(team, " '", substr(season, 3, 4))),
            size = 3, vjust = -0.9) +
  scale_colour_gradient2(low = "#B2182B", mid = "grey80", high = "#2166AC", name = "Over /\nunder") +
  labs(title = "On-field production vs recruiting rank (top-25 classes, 2023-25)",
       subtitle = "Above line = beat recruiting; below = underachieved.",
       x = "Recruiting-class rank (1 = best)", y = "SP+ rating", caption = ATTRIB)
ggsave(file.path("docs", "preview_recruiting.png"), p_rec,
       width = 9, height = 5.5, dpi = 150, bg = "white")

cat("wrote docs/preview_{calibration,brier_by_week,shrinkage,recruiting}.png\n")
