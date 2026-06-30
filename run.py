#!/usr/bin/env python
"""Polyglot pipeline orchestrator.

Sequences: ingest (R) -> dbt build -> R/Python models -> Quarto render. Each stage is a
SUBPROCESS; a non-zero exit aborts the run (clean failure handling). R and Python share state
ONLY through the DuckDB warehouse, never in-memory.

    uv run python run.py --season 2024        # full pipeline for a season
    uv run python run.py ingest               # one stage
    uv run python run.py build
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console

REPO_ROOT = Path(__file__).resolve().parent
console = Console()
app = typer.Typer(add_completion=False, help=__doc__)


def _find_rscript() -> str:
    exe = shutil.which("Rscript")
    if exe:
        return exe
    # Windows: R installs to C:\Program Files\R\R-x.y.z\bin\Rscript.exe (not always on PATH).
    cands = sorted(glob.glob(r"C:\Program Files\R\R-*\bin\Rscript.exe"), reverse=True)
    if cands:
        return cands[0]
    raise typer.Exit(console.print("[red]Rscript not found — install R or add it to PATH.[/red]") or 1)


def _find_quarto() -> str:
    exe = shutil.which("quarto")
    if exe:
        return exe
    cands = glob.glob(r"C:\Program Files\Quarto\bin\quarto.cmd") + glob.glob(r"C:\Program Files\Quarto\bin\quarto.exe")
    if cands:
        return cands[0]
    raise typer.Exit(console.print("[red]quarto not found — install Quarto or add it to PATH.[/red]") or 1)


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
    """CFBD -> DuckDB bronze (quota-aware, cached)."""
    env = {"CFB_SEASONS": season} if season else {}
    _run([_find_rscript(), "ingest/ingest_cfbd.R"], env=env)


@app.command()
def build() -> None:
    """dbt: staging -> silver -> gold (+ snapshot, tests, freshness)."""
    _run(_dbt("deps"))
    _run(_dbt("build"))


@app.command()
def models() -> None:
    """Run the book's statistical models (R), writing residuals/metrics back to gold."""
    scripts = [
        "analysis/R/stability.R",       # M1
        "analysis/R/ryoe.R",            # M2/M3
        "analysis/R/cpoe.R",            # M4
        "analysis/R/poisson.R",         # M5
        "analysis/R/game_model_train.R",
        "analysis/R/game_model_score.R",
    ]
    rscript = _find_rscript()
    for s in scripts:
        if (REPO_ROOT / s).exists():
            _run([rscript, s])
        else:
            console.print(f"[yellow]skip (not yet implemented): {s}[/yellow]")


@app.command()
def dashboard() -> None:
    """Render the Quarto dashboard to docs/."""
    _run([_find_quarto(), "render", "dashboard/dashboard.qmd"])


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context, season: str = typer.Option(None, help="Season for a full run.")) -> None:
    """With no subcommand, run the whole pipeline end-to-end."""
    if ctx.invoked_subcommand is not None:
        return
    env = {"CFB_SEASONS": season} if season else {}
    _run([_find_rscript(), "ingest/ingest_cfbd.R"], env=env)
    _run(_dbt("deps"))
    _run(_dbt("build"))
    models()
    dashboard()
    console.print("[bold green]Pipeline complete.[/bold green]")


if __name__ == "__main__":
    app()
