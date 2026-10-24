# NHL EDGE V3 — Free NHL data collector + forward-test dashboard

## What is actually implemented
- **Verified NHL public API ingestion** for regular-season schedules, final scores, and full-game winners, stored in `data/edge.sqlite` with update timestamps.
- **Free GitHub Actions scheduled collection**, with 11 AM **America/Toronto** pregame forecast snapshots. Workflow may run late: it refuses forecasts after puck drop.
- **SQLite permanent persistence** by committing database changes back to your GitHub repository.
- **Append-only daily prediction snapshots** with model ID, UTC capture time, features and `NO BET` decision; actual final scores settle the records without rewriting predictions.
- **Streamlit phone-friendly dashboard**, tracking number of forecasts, winner accuracy and Brier score once real predictions settle.
- **Reproducible V2 research artifacts** (`train_v2.py`, `metrics.json`, `walkforward_predictions.csv`), preserved separately. V2 requires your original MoneyPuck ZIPs, **not included** in this small GitHub project.

### Critical model distinction
V3 live forecasts currently use a **provisional Elo baseline** (K=18, 35 home advantage) because the V2 model depends on large MoneyPuck shot/goalie ZIPs and has no production-ready feature pipeline. **V3 Elo is NOT the trained V2 baseline and has not been calibrated or validated for profitability.** It uses *only previous dates' completed NHL regular-season results*; no sportsbook odds or goalie confirmations are invented. All recommendations are `NO BET`. Future work is to integrate MoneyPuck pregame rolling features and validate them before promoting a new model.

## GitHub setup from Android or desktop
1. Create a **new empty GitHub repository** named `nhl-edge-v3` at https://github.com/new. A public repo is simplest for free Streamlit deployment; **do not upload private betting account details**. If you want private storage, check the current Streamlit deployment options first.
2. Extract `nhl_edge_v3.zip`. Upload **the contents of the `nhl_edge_v3` folder** to the repository, preserving `.github/workflows/edge.yml`, `edge.py`, `app.py`, `requirements.txt`, and `data/edge.sqlite`. GitHub's browser uploader may omit hidden folders or not preserve structure easily on mobile; a desktop Git client or GitHub web editor may be easier. An alternative is to upload the ZIP through GitHub Codespaces and run `unzip` then `git add . && git commit && git push`.
3. Go to **Settings → Actions → General → Workflow permissions**, select **Read and write permissions** and Save. The workflow needs this to commit the database. On a new repository, enable Actions if GitHub prompts you.
4. Open **Actions → NHL EDGE V3 Collector → Run workflow**. Tick **bootstrap = true** once to fetch recent seasons (roughly 96 public team-season requests, may take several minutes). Check the run log for `Ingested` and `summary`. Later runs use `bootstrap = false`.
5. Confirm the `data/edge.sqlite` file changed in the repo. Scheduled runs collect automatically. GitHub cron jobs are best-effort and can be delayed or skipped; monitor the last collection time.
6. Open https://share.streamlit.io/ , sign in with GitHub, choose your repository and `app.py` as the entrypoint, then deploy. In **Advanced settings → Secrets**, enter `EDGE_DB_URL = "https://raw.githubusercontent.com/YOUR_USERNAME/nhl-edge-v3/main/data/edge.sqlite"` (replace `YOUR_USERNAME` and branch if different). This is for **public repositories only**. The dashboard then downloads the latest committed SQLite database, cached for five minutes. Without that secret, the dashboard may display only the database packaged at deployment time.

## Local commands
```bash
python -m unittest discover -s tests -v
python edge.py bootstrap     # Requires internet; fetches recent seasons, first run only
python edge.py collect       # Fetches recent and upcoming NHL games
python edge.py forecast      # Creates today's pregame forecasts, once per day
python edge.py summary
pip install -r requirements.txt
streamlit run app.py
```

## Data integrity and limitations
- Game IDs are official NHL IDs. Regular season only (`gameType == 2`); full-game winner includes overtime/shootout.
- A score is final only if `gameState` is `FINAL` or `OFF`, both scores are present and unequal.
- NHL API data is subject to endpoint/schema changes and outages; see https://github.com/pseudo-r/Public-NHL-API . No guaranteed service-level agreement.
- Collection retries transient failures. Workflow failures must be investigated; never silently backfill forecasts after a game begins.
- Elo updates use **scheduled start ordering** for prior completed games, excluding all games on the forecast date; this conservative rule avoids same-day leakage but is not equivalent to actual final-result publication timestamps.
- `odds` table is intentionally empty unless a verified bookmaker, timestamp, source and actual quoted price are provided. No EV, ROI, or BetMGM prices are claimed.
- SQLite is committed to Git history and can grow; this is fine for an initial prototype but not ideal long-term. For scale or privacy, migrate to a managed DB.
- GitHub free Actions minutes/availability and Streamlit free tier may change; check current terms. Public repositories expose stored game/prediction data.

## Next development milestone
Connect historical MoneyPuck data to an inference-safe live feature pipeline, backtest chronologically against V2, add confirmed goalies when sourceable, then only upgrade the production model if it demonstrably improves held-out Brier/log loss. Track actual sportsbook odds independently.

## Actual provisional Elo backtest (2025–26)
Run `python backtest_elo.py` to reproduce `elo_holdout_metrics.json` and `elo_holdout_predictions.csv`. On 1,312 2025–26 holdout games, provisional Elo achieved **53.05% winner accuracy, Brier 0.25179, log loss 0.69762**. The V2 Base model previously achieved **55.03%, Brier 0.24619**, respectively, on its 2025–26 holdout. **Elo is worse and is not promoted as an improvement.** The Elo historical warmup uses the 2024–25 games available in V2 predictions; it does not prove profitability or real-world odds availability.
