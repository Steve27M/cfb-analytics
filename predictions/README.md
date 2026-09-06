# Prediction registry

Frozen, versioned forecasts — the project's public, tamper-evident record of what its models
predicted **before** the games were played.

## Contract

- `predictions/<season>/<version>/` is **immutable once committed**. Improving a model never
  rewrites an old version; it adds a new one (`v2-...`, `v3-...`). The commit history is the
  timestamp seal — anyone can verify a forecast predates the games it's scored on.
- Every version carries a `manifest.json`: when it was generated, what it was trained on, the
  exact coefficients used, SHA-256 of each file, and its scoring scope.
- **Before-kickoff rule:** a game counts toward a version's accuracy only if the version's
  `generated_at` precedes kickoff. A model improved mid-season is scored forward-only — it never
  gets credit for games it could have known the result of.
- The scoreboard (`docs/forecast.html`, built by `dashboard/build_forecast.py`) scores every
  version against settled results side by side, next to naive baselines. At season's end the
  original `v1-preseason` projections stand against the actual standings, untouched.

## Series versions (in-season snapshots)

A version may be a **series** (`"kind": "series"` in its manifest): a sealed model — coefficients,
hyper-parameters and every team's preseason strength — plus `snapshots/<UTC timestamp>/`, one
per re-forecast. The scoreboard refresh writes a snapshot only when new results have settled
since the previous one (quiet days add nothing), and each snapshot is immutable and scored
forward-only from its own `generated_at`. The **live series** takes, for every game, the latest
snapshot that predates its kickoff — the forecast a reader following the season actually saw.
The model itself is never refitted inside a series: a better model is a new version.

## Why this is publishable

These are derived outputs authored by this project (model probabilities and win projections),
not CFBD raw data. CFBD's terms expressly permit publishing independently created predictions,
projections, and rankings; raw API data stays gitignored as always.

## Versions

| Season | Version | Generated | What it is |
|---|---|---|---|
| 2026 | `v1-preseason` | 2026-07-01 | Original preseason priors-model forecast: 740 FBS-vs-FBS games, 136 team win projections. Frozen 2026-08-31, before scoring began. |
| 2026 | `v2-inseason` | 2026-09-06 (series) | In-season update model: Bayesian ridge on scoring margins, prior mean = preseason strength (worth 2 games of evidence), win probability from predicted margin. Trained on 2024, held out on 2025 (Brier 0.174 vs 0.205 preseason-only). Re-forecasts the same 740 games after every game day; each re-forecast sealed under `snapshots/`. |
