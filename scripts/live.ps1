# Refresh the in-progress season (the live lane) and publish it. From the repo root:
#     scripts\live.cmd                 # pull, refresh 2026, rebuild pages, commit, push
#     scripts\live.cmd --skip-ingest   # rebuild from the bronze already on disk (no API calls)
# Start it through live.cmd: Windows blocks running an unsigned .ps1 directly by default.
# Uses the project's uv environment; the global `python` does not have the dependencies.
Set-Location (Split-Path $PSScriptRoot -Parent)

Write-Host "== sync with origin (the scoreboard bot commits several times a day) ==" -ForegroundColor Cyan
git pull --rebase --autostash origin main
if ($LASTEXITCODE -ne 0) { Write-Host "git pull failed - resolve it and re-run." -ForegroundColor Red; exit 1 }

Write-Host "== live lane ==" -ForegroundColor Cyan
uv run python run.py live @args
if ($LASTEXITCODE -ne 0) { Write-Host "live lane failed - nothing committed." -ForegroundColor Red; exit 1 }

git add -A docs
git diff --cached --quiet
if ($LASTEXITCODE -eq 0) { Write-Host "pages unchanged - nothing to publish." -ForegroundColor Yellow; exit 0 }

git commit -m ("live: refresh 2026 team stats " + (Get-Date -Format "yyyy-MM-dd"))
git pull --rebase origin main
git push origin main
if ($LASTEXITCODE -ne 0) { Write-Host "push failed - run 'git pull --rebase origin main' then 'git push'." -ForegroundColor Red; exit 1 }
Write-Host "published." -ForegroundColor Green
