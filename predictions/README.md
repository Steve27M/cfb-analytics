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

## Validation gates — what every refresh checks before it scores or seals anything

The frozen schedule is the registry's **key space** (the 740 games every version predicts).
Everything else about a game is live and changes after a freeze: CFBD re-designates neutral-site
hosts, moves games to the other team's field, resolves placeholder kickoff times, re-keys a
postponed game under a new id, drops cancelled games. The refresh therefore never trusts the
frozen copy for anything but identity, and it runs three gates in order
(`cfb_analytics.registry.verify` → `results.reconcile` → `results.validate`; all reported on the
scoreboard under **Data integrity** and written to `data/gold/forecast_checks.json`):

| Gate | Check | On failure |
|---|---|---|
| Registry | every sealed file's SHA-256 and row count match its manifest | workflow fails; nothing sealed |
| Registry | snapshot directories are timestamped, monotone, postdate their model, predict exactly the frozen game list; no duplicate frozen ids | workflow fails; nothing sealed |
| Reconcile | results are matched **by team**, in the frozen orientation (`mirrored` = host re-designated, points swapped; `-1` home indicator when a non-neutral game moved to the other team's field) | — (handled) |
| Reconcile | a frozen id CFBD dropped is re-keyed to the unique CFBD game between the same two teams; otherwise `missing` (never settles, never counts) | soft note on the page |
| Reconcile | the before-kickoff rule uses CFBD's **current** kickoff, not the frozen one | — (handled) |
| Validate (hard) | the winner our frame names = the winner CFBD names, for every settled game | **quarantine** |
| Validate (hard) | per-team W-L derived from our frame = W-L derived independently from CFBD's rows by team name | **quarantine** |
| Validate (hard) | no result before its kickoff; no ties; scores are non-negative integers with a plausible total; no CFBD id claimed twice | **quarantine** |
| Validate (soft) | CFBD's own postgame win probability names its scored winner; changed pairings; missing / re-keyed games; kickoff moves | noted on the page |
| Snapshot | before writing: ratings finite, probabilities in (0, 1), wins + losses + remaining = games, projected wins within [wins, wins + remaining], the team table's record equals the settled games' | refuses to seal |

**Hashes are line-ending-normalized.** Versions sealed before 2026-09-13 recorded the SHA-256
of the bytes their Windows writer produced (CRLF) while git stores LF, so they only ever verified
on a Windows checkout — CI caught this the first time the registry gate ran on Linux. New
manifests carry `hash_rule` and hash LF-normalized bytes, `.gitattributes` pins `predictions/**`
to LF on every platform, and verification accepts the sealed hash against the file's raw, LF- or
CRLF-normalized bytes: a line-ending conversion is not tampering; any change to content still is.

**Quarantine** means: the page is still rebuilt with the frozen predictions intact and a banner,
nothing from that pull is scored, no snapshot is sealed, the flagged page is committed, and the
`score` workflow then fails so it is noticed. The next clean pull resumes normally. The gates are
unit-tested (`tests/test_results.py`, `tests/test_registry.py`, `tests/test_snapshot_guard.py`)
and CI (`.github/workflows/ci.yml`) runs those tests, the registry gate and a keyless build on
every push; the scheduled refresh runs the tests again before trusting the gates.

## Errata

Withdrawing a sealed file is the one exception to immutability, and it is recorded here so the
history stays legible (git keeps the withdrawn files; nothing is rewritten).

- **2026-09-12 — `v2-inseason` snapshots `2026-09-07T08-24Z`, `2026-09-08T08-09Z` and
  `2026-09-12T07-58Z` withdrawn.** CFBD re-designated the home team of the week-1 Notre
  Dame–Wisconsin game at Lambeau Field (frozen as Wisconsin home, settled as Notre Dame home,
  41–13) after the schedule was sealed. The refresh attached CFBD's home score to the *frozen*
  home team, so the model was fed a 28-point Wisconsin win instead of a 28-point Notre Dame win,
  and every rating in those three snapshots — and the scoreboard's record for both teams — was
  built on that reversed result. Results are now aligned by team, not by orientation
  (`inseason.align_results`, covered by `tests/test_inseason_results.py`), the before-kickoff rule
  uses CFBD's current kickoff time rather than the frozen one, and the next refresh re-snapshots
  from the corrected results. The `2026-09-06T11-24Z` snapshot predates the game and stands.

## Why this is publishable

These are derived outputs authored by this project (model probabilities and win projections),
not CFBD raw data. CFBD's terms expressly permit publishing independently created predictions,
projections, and rankings; raw API data stays gitignored as always.

## Versions

| Season | Version | Generated | What it is |
|---|---|---|---|
| 2026 | `v1-preseason` | 2026-07-01 | Original preseason priors-model forecast: 740 FBS-vs-FBS games, 136 team win projections. Frozen 2026-08-31, before scoring began. |
| 2026 | `v2-inseason` | 2026-09-06 (series) | In-season update model: Bayesian ridge on scoring margins, prior mean = preseason strength (worth 2 games of evidence), win probability from predicted margin. Trained on 2024, held out on 2025 (Brier 0.174 vs 0.205 preseason-only). Re-forecasts the same 740 games after every game day; each re-forecast sealed under `snapshots/`. |
