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
- Alerts fire when a listing starts matching. A further price drop on a listing that already matched is not reported.
- Until the first real run, a dry-run counts as the baseline run, so it prints only recent matches, never old-listing alerts.
