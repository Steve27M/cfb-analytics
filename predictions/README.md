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

## Why this is publishable

These are derived outputs authored by this project (model probabilities and win projections),
not CFBD raw data. CFBD's terms expressly permit publishing independently created predictions,
projections, and rankings; raw API data stays gitignored as always.

## Versions

| Season | Version | Generated | What it is |
|---|---|---|---|
| 2026 | `v1-preseason` | 2026-07-01 | Original preseason priors-model forecast: 740 FBS-vs-FBS games, 136 team win projections. Frozen 2026-08-31, before scoring began. |
