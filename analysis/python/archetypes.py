"""M6 (Eager & Erickson, Ch.8) — team archetypes via PCA + k-means, Python parity of archetypes.R.

PCA eigenvalues are deterministic given identical scaling, so variance-explained must match R to
tolerance; PC scores match after the same sign convention. k-means labels are an arbitrary
permutation, so agreement with R is measured by the adjusted Rand index (label-invariant). This
script reads the R output to report those agreement metrics.

Reads data/gold/team_profile.csv (+ data/results/pred__archetype__r.csv for the parity report);
writes pred__archetype__py / metrics__archetype__py / metrics__archetype_parity__py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import adjusted_rand_score

from cfb_analytics.config import REPO_ROOT

GOLD = REPO_ROOT / "data" / "gold"
RESULTS = REPO_ROOT / "data" / "results"
K = 5
FEATURES = ["off_epa_play", "off_success_rate", "off_explosiveness", "rush_rate",
            "off_pace", "def_epa_play", "def_success_rate"]


def _sign_align(scores: np.ndarray, loadings: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    # force each PC's largest-|loading| variable to load positive (matches archetypes.R)
    for j in range(loadings.shape[1]):
        lead = int(np.argmax(np.abs(loadings[:, j])))
        if loadings[lead, j] < 0:
            loadings[:, j] = -loadings[:, j]
            scores[:, j] = -scores[:, j]
    return scores, loadings


def main() -> None:
    df = pd.read_csv(GOLD / "team_profile.csv")
    # standardize with sample sd (ddof=1) to match R's scale()
    raw = df[FEATURES]
    X = ((raw - raw.mean()) / raw.std(ddof=1)).to_numpy()

    pca = PCA()
    scores = pca.fit_transform(X)
    loadings = pca.components_.T.copy()
    scores, loadings = _sign_align(scores, loadings)
    var_explained = pca.explained_variance_ratio_

    km = KMeans(n_clusters=K, n_init=50, random_state=42).fit(X)
    # k-means labels 0..K-1; shift to 1..K to line up with R's convention cosmetically
    clusters = km.labels_ + 1

    pred = pd.DataFrame({
        "team": df["team"], "season": df["season"],
        "pc1": scores[:, 0], "pc2": scores[:, 1],
        "cluster": clusters, "language": "py",
    })
    metrics = pd.DataFrame([
        dict(model="archetype", metric="pc1_var_explained", value=float(var_explained[0])),
        dict(model="archetype", metric="pc2_var_explained", value=float(var_explained[1])),
        dict(model="archetype", metric="cumulative_2pc", value=float(var_explained[:2].sum())),
        dict(model="archetype", metric="n_obs", value=float(len(df))),
        dict(model="archetype", metric="k", value=float(K)),
        dict(model="archetype", metric="total_within_ss", value=float(km.inertia_)),
    ])
    metrics["language"] = "py"

    RESULTS.mkdir(parents=True, exist_ok=True)
    pred.to_csv(RESULTS / "pred__archetype__py.csv", index=False)
    metrics.to_csv(RESULTS / "metrics__archetype__py.csv", index=False)

    # agreement vs R (variance-explained match, PC1 |corr|, cluster ARI)
    r_path = RESULTS / "pred__archetype__r.csv"
    if r_path.exists():
        r = pd.read_csv(r_path)
        rm = pd.read_csv(RESULTS / "metrics__archetype__r.csv")
        merged = pred.merge(r, on=["team", "season"], suffixes=("_py", "_r"))
        pc1_corr = abs(np.corrcoef(merged["pc1_py"], merged["pc1_r"])[0, 1])
        ari = adjusted_rand_score(merged["cluster_r"], merged["cluster_py"])
        r_cum = rm.loc[rm.metric == "cumulative_2pc", "value"].iloc[0]
        parity = pd.DataFrame([
            dict(model="archetype", metric="pc1_abs_corr_r_vs_py", value=float(pc1_corr)),
            dict(model="archetype", metric="cluster_adjusted_rand_index", value=float(ari)),
            dict(model="archetype", metric="cum2pc_abs_diff_r_vs_py",
                 value=float(abs(r_cum - var_explained[:2].sum()))),
        ])
        parity["language"] = "parity"
        parity.to_csv(RESULTS / "metrics__archetype_parity__py.csv", index=False)
        print(f"[archetype/py] var(2PC)={var_explained[:2].sum():.3f}; "
              f"vs R: PC1 |corr|={pc1_corr:.4f}, cluster ARI={ari:.3f}")
    else:
        print(f"[archetype/py] var(2PC)={var_explained[:2].sum():.3f} (R output not found)")


if __name__ == "__main__":
    main()
