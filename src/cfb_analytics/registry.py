"""The prediction registry: predictions/<season>/<version>/ — load it, and prove it is intact.

Two kinds of version (see predictions/README.md):
  * flat (v1-preseason): one forecast, one generated_at, scored forward from that.
  * series (v2-inseason): a sealed model plus snapshots/<UTC ts>/, each an immutable re-forecast.

verify(season) is the registry's own integrity gate, run on every scoreboard refresh and in CI:
every file's SHA-256 matches its manifest (a silently edited or corrupted forecast is caught),
snapshot timestamps are monotone and match their directory names, every snapshot predicts
exactly the frozen game list, and the frozen schedule has no duplicate ids. A failing registry
is reported on the page and fails the workflow; it is never "fixed" by a refresh.

Hashes and line endings: every registry file is text. Versions sealed before 2026-09-13 were
hashed over the bytes the writer produced on Windows (CRLF), while git stores LF — so those
manifests only ever verified on a Windows checkout. New manifests hash LF-normalized bytes
(`hash_rule`), `.gitattributes` pins predictions/** to LF on every platform, and verification
accepts a file whose LF- or CRLF-normalized bytes match the sealed hash: a line-ending
conversion is not tampering, any change to content still is.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from .config import REPO_ROOT

PREDICTIONS_DIR = REPO_ROOT / "predictions"
SCHEDULE_VERSION = "v1-preseason"   # the frozen game list + kickoff times every snapshot reuses


HASH_RULE = "sha256 of the file's bytes with CRLF normalized to LF"


def sha256(path: Path) -> str:
    """Raw-byte SHA-256 (what pre-2026-09-13 manifests recorded)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(path: Path) -> str:
    """Line-ending-normalized SHA-256: the hash new manifests seal (see HASH_RULE)."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def hash_matches(path: Path, sealed: str) -> bool:
    """True when the file's raw, LF-normalized or CRLF-normalized bytes hash to `sealed`."""
    raw = path.read_bytes()
    lf = raw.replace(b"\r\n", b"\n")
    crlf = lf.replace(b"\n", b"\r\n")
    return sealed in {hashlib.sha256(b).hexdigest() for b in (raw, lf, crlf)}


def registry_dir(season: int) -> Path:
    return PREDICTIONS_DIR / str(season)


def read_manifest(d: Path) -> dict:
    return json.loads((d / "manifest.json").read_text(encoding="utf-8"))


def read_version(d: Path, season: int) -> dict:
    return {"dir": d.name, "manifest": read_manifest(d),
            "games": pd.read_csv(d / f"forecast_{season}.csv"),
            "teams": pd.read_csv(d / f"forecast_{season}_teams.csv")}


def load_schedule(season: int) -> pd.DataFrame:
    """The frozen game list every snapshot predicts: the original preseason version's games."""
    path = registry_dir(season) / SCHEDULE_VERSION / f"forecast_{season}.csv"
    sched = pd.read_csv(path)
    return sched[["game_id", "week", "start_date", "neutral_site", "home_team", "away_team"]]


def load_versions(season: int) -> list[dict]:
    """Every version, flat ones first then series, each in generated_at order; a series carries
    its snapshots sorted oldest -> newest."""
    root = registry_dir(season)
    versions: list[dict] = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        manifest = read_manifest(d)
        if manifest.get("kind") == "series":
            snap_root = d / "snapshots"
            snaps = ([read_version(s, season) for s in sorted(snap_root.iterdir()) if s.is_dir()]
                     if snap_root.exists() else [])
            snaps.sort(key=lambda v: v["manifest"]["generated_at"])
            versions.append({"dir": d.name, "manifest": manifest, "series": True,
                             "snapshots": snaps})
        else:
            versions.append({**read_version(d, season), "series": False})
    if not versions:
        raise SystemExit(f"no frozen versions under {root}")
    versions.sort(key=lambda v: (v["series"], v["manifest"]["generated_at"]))
    return versions


# --------------------------------------------------------------------------- integrity
def _check_files(d: Path, manifest: dict, label: str, problems: list[str]) -> None:
    files = manifest.get("files") or {}
    if not files:
        problems.append(f"{label}: manifest lists no files")
    for name, meta in files.items():
        p = d / name
        if not p.exists():
            problems.append(f"{label}: {name} missing")
            continue
        if meta.get("sha256") and not hash_matches(p, meta["sha256"]):
            problems.append(f"{label}: {name} SHA-256 does not match its manifest")
        if "rows" in meta and name.endswith(".csv"):
            n = sum(1 for _ in p.open(encoding="utf-8")) - 1
            if n != meta["rows"]:
                problems.append(f"{label}: {name} has {n} rows, manifest says {meta['rows']}")


def verify(season: int) -> dict:
    """Integrity report: {"ok", "checks": [{"id","name","ok","n","detail"}], "n_versions",
    "n_snapshots"}. Read-only; never touches the registry."""
    root = registry_dir(season)
    hashes: list[str] = []
    chain: list[str] = []
    scope: list[str] = []
    n_versions = n_snaps = 0
    frozen_ids: set[int] | None = None

    sched_path = root / SCHEDULE_VERSION / f"forecast_{season}.csv"
    if sched_path.exists():
        ids = pd.read_csv(sched_path).game_id
        if ids.duplicated().any():
            scope.append(f"{SCHEDULE_VERSION}: duplicate game ids "
                         f"{sorted(set(ids[ids.duplicated()].astype(int)))[:10]}")
        frozen_ids = set(ids.astype(int))
    else:
        scope.append(f"{SCHEDULE_VERSION}/forecast_{season}.csv missing — no frozen schedule")

    version_dirs: list[Path] = (sorted(p for p in root.iterdir() if p.is_dir())
                                if root.exists() else [])
    for d in version_dirs:
        n_versions += 1
        try:
            manifest = read_manifest(d)
        except (OSError, ValueError) as e:
            hashes.append(f"{d.name}: unreadable manifest ({e})")
            continue
        _check_files(d, manifest, d.name, hashes)
        if manifest.get("kind") != "series":
            if frozen_ids is not None and d.name != SCHEDULE_VERSION:
                got = set(pd.read_csv(d / f"forecast_{season}.csv").game_id.astype(int))
                if got != frozen_ids:
                    scope.append(f"{d.name}: predicts {len(got)} games, frozen list has "
                                 f"{len(frozen_ids)} ({len(got ^ frozen_ids)} differ)")
            continue
        snap_root = d / "snapshots"
        prev_ts = ""
        snap_dirs: list[Path] = sorted(snap_root.iterdir()) if snap_root.exists() else []
        for s in snap_dirs:
            if not s.is_dir():
                continue
            n_snaps += 1
            label = f"{d.name}/snapshots/{s.name}"
            try:
                sm = read_manifest(s)
            except (OSError, ValueError) as e:
                hashes.append(f"{label}: unreadable manifest ({e})")
                continue
            _check_files(s, sm, label, hashes)
            ts = sm.get("generated_at", "")
            if not ts or not sm.get("results_hash"):
                chain.append(f"{label}: manifest lacks generated_at/results_hash")
            if ts[:16].replace(":", "-") != s.name[:16]:
                chain.append(f"{label}: directory name does not match generated_at {ts}")
            if ts <= prev_ts:
                chain.append(f"{label}: generated_at {ts} not after previous snapshot {prev_ts}")
            prev_ts = ts
            if ts and ts < manifest.get("generated_at", ""):
                chain.append(f"{label}: snapshot predates its model "
                             f"({manifest.get('generated_at')})")
            if frozen_ids is not None:
                got = set(pd.read_csv(s / f"forecast_{season}.csv").game_id.astype(int))
                if got != frozen_ids:
                    scope.append(f"{label}: predicts {len(got)} games, frozen list has "
                                 f"{len(frozen_ids)} ({len(got ^ frozen_ids)} differ)")

    checks: list[dict] = [
        {"id": "manifest-hashes",
         "name": "Every sealed file matches its manifest SHA-256 and row count",
         "ok": not hashes, "n": len(hashes), "detail": "; ".join(hashes)},
        {"id": "snapshot-chain",
         "name": "Snapshots are timestamped, monotone and postdate their model",
         "ok": not chain, "n": len(chain), "detail": "; ".join(chain)},
        {"id": "frozen-scope", "name": "Every version predicts exactly the frozen game list",
         "ok": not scope, "n": len(scope), "detail": "; ".join(scope)},
    ]
    ok = all(c["ok"] for c in checks)
    print(f"  registry {'intact' if ok else 'INTEGRITY FAILURE'}: {n_versions} version(s), "
          f"{n_snaps} snapshot(s)" + ("" if ok else " — " + "; ".join(
              c["detail"][:200] for c in checks if not c["ok"])))
    return {"ok": ok, "n_versions": n_versions, "n_snapshots": n_snaps, "checks": checks}
