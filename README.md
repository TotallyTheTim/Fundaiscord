# Funda Watch

Polls Funda every 30 minutes via GitHub Actions and posts new matching listings to a Discord channel.

## Setup

1. Push this repo to GitHub.
2. Discord: create a channel, then *Edit channel → Integrations → Webhooks → New webhook* and copy the URL.
3. Repo *Settings → Secrets and variables → Actions*, add:
   - `DISCORD_WEBHOOK_URL` (required)
   - `DISCORD_USER_ID` (optional, the user to @mention; enable Developer Mode in Discord, right-click yourself → Copy User ID)
4. *Actions → Funda Watch → Run workflow* to test without waiting for the schedule (tick `dry_run` to only print).

The webhook URL must only ever live in the secret, never in the repo.

## Configuration

Everything you'd want to change is in [config.yaml](config.yaml): price, surface, bedrooms, energy labels, the listing age window, and which wijken to search per city. `data/buurt-wijk.json` maps Funda's buurt names to wijken and is regenerated with `python scripts/build_buurt_map.py`.

## Local use

```
pip install -r requirements-dev.txt
python src/main.py --dry-run   # fetches live, prints alerts, saves nothing
pytest
```

## Notes

- `pyfunda` is unofficial and uses undocumented Funda endpoints, which may break and may conflict with Funda's terms. `funda_client.py` works around a fingerprint block in pyfunda 3.1.5; see the comment there.
- pyfunda is AGPL-3.0. It is used as a dependency only, none of its code is copied here.
- State lives in `data/seen-listings.json`, committed by the workflow whenever it changes.
