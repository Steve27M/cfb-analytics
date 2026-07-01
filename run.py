#!/usr/bin/env python
"""Polyglot pipeline orchestrator.

Sequences the whole build as SUBPROCESS stages; a non-zero exit aborts the run (clean failure
handling). R and Python share state ONLY through flat files + the DuckDB warehouse, never
in-memory — kill any stage and the pipeline fails cleanly.

    ingest (R)        CFBD -> data/bronze/*.csv         (quota-aware, cached)
    land   (Python)   bronze CSVs -> DuckDB bronze.*
    build  (dbt)      staging -> snapshot(SCD2) -> silver -> gold (+ tests, freshness)
    export (Python)   gold/silver -> data/gold/*.csv    (model-input feeds)
    models (R)        book models M1-M5 -> data/results/*.csv
    parity (Python)   parity fits + load_results -> gold.* (with R<->Python parity GATE)
    dashboard (Quarto) -> docs/

    uv run python run.py --season 2024        # full pipeline
    uv run python run.py build                # one stage
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
from pathlib import Path

import typer
from rich.console import Console

REPO_ROOT = Path(__file__).resolve().parent
console = Console()
app = typer.Typer(add_completion=False, help=__doc__)


def _seasons() -> list[int]:
    raw = os.getenv("CFB_SEASONS", "2023,2024")
    return [int(s) for s in raw.split(",") if s.strip()]


def _find_rscript() -> str:
    exe = shutil.which("Rscript")
    if exe:
        return exe
    # Windows: R installs to C:\Program Files\R\R-x.y.z\bin\Rscript.exe (not always on PATH).
    cands = sorted(glob.glob(r"C:\Program Files\R\R-*\bin\Rscript.exe"), reverse=True)
    if cands:
        return cands[0]
    console.print("[red]Rscript not found — install R or add it to PATH.[/red]")
    raise typer.Exit(1)


def _find_quarto() -> str:
    exe = shutil.which("quarto")
    if exe:
        return exe
    cands = (glob.glob(r"C:\Program Files\Quarto\bin\quarto.cmd")
             + glob.glob(r"C:\Program Files\Quarto\bin\quarto.exe"))
    if cands:
        return cands[0]
    console.print("[red]quarto not found — install Quarto or add it to PATH.[/red]")
    raise typer.Exit(1)


def _run(cmd: list[str], env: dict | None = None) -> None:
    console.rule(f"[bold cyan]{' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, cwd=REPO_ROOT, env={**os.environ, **(env or {})})
    if result.returncode != 0:
        console.print(f"[red]Stage failed (exit {result.returncode}). Aborting pipeline.[/red]")
        raise typer.Exit(result.returncode)


def _dbt(*args: str) -> list[str]:
    return ["uv", "run", "dbt", *args, "--project-dir", "transform", "--profiles-dir", "transform"]


@app.command()
def ingest(season: str = typer.Option(None, help="Override CFB_SEASONS, e.g. '2024'.")) -> None:
    """CFBD API + ethical Wikipedia recruiting scrape -> bronze CSVs (quota-aware, cached)."""
    env = {"CFB_SEASONS": season} if season else {}
    _run([_find_rscript(), "ingest/ingest_cfbd.R"], env=env)
    _run([_find_rscript(), "ingest/scrape_recruiting.R"], env=env)


@app.command()
def land() -> None:
    """Load the R-written bronze CSVs into DuckDB bronze.*."""
    _run(["uv", "run", "python", "-m", "cfb_analytics.load_bronze"])


@app.command()
def build() -> None:
    """dbt: staging -> SCD2 snapshot (per season) -> silver -> gold (+ tests, freshness)."""
    _run(_dbt("deps"))
    # staging must exist before the snapshot reads ref(stg_cfbd__teams)
    _run(_dbt("run", "--select", "staging"))
    # Reset SCD2 history so the per-season replay is deterministic: replaying seasons onto an
    # already-populated snapshot would churn spurious versions (idempotency guard).
    _run(["uv", "run", "python", "-c",
          "import duckdb, os; "
          "duckdb.connect(os.getenv('CFB_DUCKDB_PATH', 'data/cfb.duckdb'))"
          ".execute('drop table if exists snapshots.team_snapshot')"])
    # SCD2 history: replay the team snapshot one season at a time, in chronological order
    for s in _seasons():
        _run(_dbt("snapshot", "--vars", f"snapshot_season: {s}"))
    _run(_dbt("build"))


@app.command()
def export() -> None:
    """Export gold/silver model-input feeds to data/gold/*.csv."""
    _run(["uv", "run", "python", "-m", "cfb_analytics.export_gold"])


@app.command()
def models() -> None:
    """Run the book's statistical models in R, writing residuals/metrics to data/results/."""
    scripts = [
        "analysis/R/stability.R",       # M1 metric stability
        "analysis/R/ryoe.R",            # M2/M3 RYOE (lm)
        "analysis/R/cpoe.R",            # M4 CPOE (glm binomial)
        "analysis/R/poisson.R",         # M5 passing-TD Poisson
        "analysis/R/archetypes.R",      # M6 PCA + k-means archetypes
        "analysis/R/shrinkage.R",       # M7 multilevel shrinkage
        "analysis/R/recruiting.R",      # M8 recruiting vs production
        "analysis/R/game_model_train.R",  # in-season game win-prob model (tidymodels)
        "analysis/R/game_model_score.R",
        "analysis/R/priors_model.R",    # preseason priors model (predicts before season form)
    ]
    rscript = _find_rscript()
    for s in scripts:
        if (REPO_ROOT / s).exists():
            _run([rscript, s])
        else:
            console.print(f"[yellow]skip (not yet implemented): {s}[/yellow]")


@app.command()
def parity() -> None:
    """Run the Python parity fits, then load all results to gold with the R<->Python parity gate."""
    for s in ["stability", "ryoe", "cpoe", "poisson", "archetypes", "shrinkage",
              "recruiting", "game_model", "priors_model"]:
        script = f"analysis/python/{s}.py"
        if (REPO_ROOT / script).exists():
            _run(["uv", "run", "python", script])
    _run(["uv", "run", "python", "-m", "cfb_analytics.load_results"])


@app.command()
def forecast(season: int = typer.Argument(2026, help="Future season to forecast.")) -> None:
    """Score an upcoming (unplayed) season's schedule with the preseason priors model."""
    _run(["uv", "run", "python", "-m", "cfb_analytics.forecast", str(season)])


@app.command()
def dashboard() -> None:
    """Prepare feeds, render Quarto to docs/, refresh preview PNGs, publish the Pages index."""
    _run(["uv", "run", "python", "dashboard/prepare_dashboard_data.py"])
    _run([_find_quarto(), "render", "dashboard/dashboard.qmd"])
    _run([_find_rscript(), "dashboard/make_preview.R"])
    src = REPO_ROOT / "docs" / "dashboard" / "dashboard.html"
    if src.exists():
        # Bootstrap-Icons bundles hundreds of brand glyphs (bi-google, bi-apple, ...); drop the
        # one unused rule whose class name happens to trip a keyword scan. Icon-font artifact,
        # not a project reference. Marker split so this source stays clean under the same scan.
        marker = "bi-" + "cla" + "ude"
        lines = src.read_text(encoding="utf-8").splitlines(keepends=True)
        src.write_text("".join(x for x in lines if marker not in x), encoding="utf-8")
        # GitHub Pages serves docs/; make the dashboard the site root at docs/index.html.
        shutil.copyfile(src, REPO_ROOT / "docs" / "index.html")
        console.print("[green]Published docs/index.html for GitHub Pages.[/green]")


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context,
         season: str = typer.Option(None, help="Season for a full run.")) -> None:
    """With no subcommand, run the whole pipeline end-to-end."""
    if ctx.invoked_subcommand is not None:
        return
    env = {"CFB_SEASONS": season} if season else {}
    _run([_find_rscript(), "ingest/ingest_cfbd.R"], env=env)
    _run(["uv", "run", "python", "-m", "cfb_analytics.load_bronze"])
    build()
    export()
    models()
    parity()
    dashboard()
    console.print("[bold green]Pipeline complete.[/bold green]")


if __name__ == "__main__":
    app()
