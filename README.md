# Funda Watch

Polls Funda every 30 minutes via GitHub Actions and posts new matching listings to a Discord channel.

- **Every 30 min:** reads the newest result pages, so new listings show up quickly.
- **Every 12 h:** one run reads all pages. A listing that was published long ago but only now matches (price drop, new energy label, ...) gets a red `ALERT - OLD LISTING ADDED SINCE LISTING CHANGED` message.
- **First run:** records everything that matches today. Only listings from the last few days alert; older ones are stored silently.

## Setup

1. Push this repo to GitHub.
2. Discord: create a channel, then *Edit channel → Integrations → Webhooks → New webhook* and copy the URL.
3. Repo *Settings → Secrets and variables → Actions*, add:
   - `DISCORD_WEBHOOK_URL` (required)
   - `DISCORD_USER_ID` (optional, the user to @mention; enable Developer Mode in Discord, right-click yourself → Copy User ID)
4. *Actions → Funda Watch → Run workflow* to test without waiting for the schedule (tick `dry_run` to only print).

The webhook URL must only ever live in the secret, never in the repo.

## Reliable scheduling

GitHub's own `schedule` trigger is best-effort: on a new repo it can fire only a few times a day. The dependable way is an external cron service calling the `workflow_dispatch` API, which starts within seconds. The workflow's own cron stays as a backup; overlapping runs are harmless because the state file deduplicates alerts.

1. GitHub → *Settings → Developer settings → Personal access tokens → Fine-grained tokens*: repository access **only this repo**, permission **Actions: Read and write**, and an expiry date (renew it then).
2. On [cron-job.org](https://cron-job.org) create a job: URL `https://api.github.com/repos/TotallyTheTim/Fundaiscord/actions/workflows/funda-watch.yml/dispatches`, every 30 minutes, method **POST**, body `{"ref":"main"}`, headers `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`, `Content-Type: application/json`. A success is HTTP 204.

## Configuration

Everything you'd want to change is in [config.yaml](config.yaml): price, surface, bedrooms, energy labels, what counts as an old listing, the sweep interval, and which wijken to search per city. `data/buurt-wijk.json` maps Funda's buurt names to wijken and is regenerated with `python scripts/build_buurt_map.py`.

## Local use

```
pip install -r requirements-dev.txt
python src/main.py --dry-run   # fetches live, prints alerts, saves nothing
python src/main.py --dry-run --full   # same, but reads every result page
pytest
```

## Notes

- `pyfunda` is unofficial and uses undocumented Funda endpoints, which may break and may conflict with Funda's terms. `funda_client.py` works around a fingerprint block in pyfunda 3.1.5; see the comment there.
- pyfunda is AGPL-3.0. It is used as a dependency only, none of its code is copied here.
- State lives in `data/seen-listings.json`, committed by the workflow whenever it changes (at least twice a day, when a full sweep is recorded).
- Each result page is retried up to 3 times. If a search still only partly loads, the pages that did load are processed, the run logs a GitHub warning (it stays green), and the full sweep is retried on the next run.
- Alerts fire when a listing starts matching. A further price drop on a listing that already matched is not reported.
- Until the first real run, a dry-run counts as the baseline run, so it prints only recent matches, never old-listing alerts.
