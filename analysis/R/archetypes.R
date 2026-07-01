# M6 (Eager & Erickson, Ch.8) — team archetypes via PCA + k-means, in R.
# Reduce each FBS team-season's 7-stat style profile (offensive/defensive efficiency, success,
# explosiveness, run-rate, pace) to 2 principal components, then cluster into archetypes.
#
# Reads:  data/gold/team_profile.csv
# Writes: data/results/pred__archetype__r.csv (PC coords + cluster), metrics__archetype__r.csv
#
# Parity note: PCA eigenvectors are sign-ambiguous and k-means labels are an arbitrary
# permutation, so this is NOT in the strict coefficient gate. We align PC signs deterministically
# (largest-magnitude loading made positive) so R and Python agree; the Python mirror then reports
# variance-explained match + cluster agreement (adjusted Rand index) vs this R output.

source("analysis/R/util_io.R")
suppressPackageStartupMessages(library(dplyr))
set.seed(42)

K <- 5  # number of archetypes
FEATURES <- c("off_epa_play", "off_success_rate", "off_explosiveness", "rush_rate",
              "off_pace", "def_epa_play", "def_success_rate")

df <- cfb_read_gold("team_profile")

# standardize with sample sd (n-1) so the R and Python pipelines use identical scaling
X <- scale(as.matrix(df[FEATURES]))
pca <- prcomp(X, center = FALSE, scale. = FALSE)

# deterministic sign convention: force each PC's largest-|loading| variable to load positive
for (j in seq_len(ncol(pca$rotation))) {
  lead <- which.max(abs(pca$rotation[, j]))
  if (pca$rotation[lead, j] < 0) {
    pca$rotation[, j] <- -pca$rotation[, j]
    pca$x[, j] <- -pca$x[, j]
  }
}

var_explained <- pca$sdev^2 / sum(pca$sdev^2)
km <- kmeans(X, centers = K, nstart = 50)

pred <- data.frame(
  team = df$team, season = df$season,
  pc1 = pca$x[, 1], pc2 = pca$x[, 2],
  cluster = km$cluster, language = "r")

metrics <- data.frame(
  model = "archetype",
  metric = c("pc1_var_explained", "pc2_var_explained", "cumulative_2pc",
             "n_obs", "k", "total_within_ss"),
  value = c(var_explained[1], var_explained[2], sum(var_explained[1:2]),
            nrow(df), K, km$tot.withinss),
  language = "r")

cfb_write_result("pred__archetype__r", pred)
cfb_write_result("metrics__archetype__r", metrics)
cat(sprintf("[archetype/R] PC1+PC2 explain %.1f%% of variance; %d teams -> %d archetypes\n",
            100 * sum(var_explained[1:2]), nrow(df), K))
