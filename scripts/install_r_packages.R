#!/usr/bin/env Rscript
# Installs the R toolchain for cfb-analytics. Run once after R is installed:
#   Rscript scripts/install_r_packages.R
# Uses a CRAN binary mirror (fast on Windows; avoids most source compiles).

options(repos = c(CRAN = "https://cloud.r-project.org"))
options(install.packages.check.source = "no")  # prefer binaries on Windows

# The default library (C:/Program Files/R/.../library) is not writable without admin.
# Use a per-user library and put it first on the search path.
user_lib <- Sys.getenv("R_LIBS_USER")
if (!nzchar(user_lib) || user_lib == "NULL") {
  ver <- paste(R.version$major, sub("\\..*", "", R.version$minor), sep = ".")
  base <- Sys.getenv("LOCALAPPDATA", unset = file.path(Sys.getenv("HOME"), "R"))
  user_lib <- file.path(base, "R", "win-library", ver)
}
dir.create(user_lib, recursive = TRUE, showWarnings = FALSE)
.libPaths(c(user_lib, .libPaths()))
message("Installing into user library: ", user_lib)

pkgs <- c(
  # --- env / reproducibility ---
  "renv",
  # --- warehouse access (same DuckDB file the pipeline writes) ---
  "DBI", "duckdb", "dbplyr",
  # --- tidyverse core (EDA / wrangling / viz) ---
  "dplyr", "tidyr", "readr", "purrr", "ggplot2", "stringr", "tibble", "forcats",
  # --- modeling: the book's methods ---
  "tidymodels",   # parsnip, recipes, rsample, yardstick, tune, workflows
  "lme4",          # M7 multilevel / mixed-effects
  "MASS",          # glm.nb (Poisson overdispersion -> negative binomial)
  "broom",         # tidy model coefficients (odds ratios, etc.)
  "xgboost",       # game-model booster
  # --- football data + presentation ---
  "cfbfastR",      # CFBD ingestion
  "gt", "gtExtras", "cfbplotR",
  # --- io ---
  "jsonlite"
)

to_install <- setdiff(pkgs, rownames(installed.packages()))
if (length(to_install)) {
  message("Installing: ", paste(to_install, collapse = ", "))
  install.packages(to_install, lib = user_lib)
} else {
  message("All R packages already installed.")
}

# cfbfastR pulls some packages from the sportsdataverse; ensure it loads.
ok <- requireNamespace("cfbfastR", quietly = TRUE)
message("cfbfastR available: ", ok)
