# Cloud Automation Setup (\$0/month)

Run enrichment, DuckDB pipeline builds, and Cloudflare Workers deploys from GitHub Actions without running commands on your Mac.

## Architecture

```text
Private Cloudflare R2 Bucket          GitHub Actions (ubuntu-latest)        Cloudflare Workers + Access
┌───────────────────────────┐         ┌────────────────────────────┐        ┌──────────────────────────┐
│ raw/                      │ ──pull─▶│ 1. sync raw, cache, db     │        │                          │
│   Streaming_History_*.json│         │ 2. pipeline.enrich fetch   │─deploy▶│ Static site behind       │
│   recenttracks-*.csv      │         │ 3. pipeline.build_pipeline │        │ Cloudflare Access        │
│   *_genre_overrides.csv   │         │ 4. site build + wrangler   │        │                          │
│ cache/http_cache.sqlite   │ ◀─push──│                            │        └──────────────────────────┘
│ build/music.duckdb        │         └────────────────────────────┘
└───────────────────────────┘
```

- **Storage:** Cloudflare R2 free tier (10 GB storage, \$0 egress). Your exports, cache, and overrides stay private in R2 and never enter Git.
- **Compute:** GitHub Actions (unlimited free minutes on public repositories; 2,000 min/month on private repositories).
- **Hosting:** Cloudflare Workers Static Assets behind Cloudflare Access.

---

## 1. Create the Private R2 Bucket & API Token

1. In the Cloudflare dashboard, open **R2 Object Storage** and create a private bucket (e.g. `music-story-private`).
2. Go to **R2 → Manage R2 API Tokens → Create API Token**:
   - Permissions: **Object Read & Write** scoped to `music-story-private`.
   - Save the **Access Key ID**, **Secret Access Key**, and your **Cloudflare Account ID**.

## 2. Create a Cloudflare Workers Deploy Token

1. In the Cloudflare dashboard, go to **My Profile → API Tokens → Create Token**.
2. Use the **Edit Cloudflare Workers** template (or custom token with `Workers Scripts: Edit`, `Account Settings: Read`, and `Zone: Read` for your custom domain).

## 3. Add GitHub Repository Secrets

In your GitHub repository: **Settings → Secrets and variables → Actions → New repository secret**.

| Secret | Required | Purpose |
|---|---|---|
| `R2_ACCOUNT_ID` | Yes | Cloudflare Account ID for R2 endpoint |
| `R2_BUCKET` | Yes | Private R2 bucket name |
| `R2_ACCESS_KEY_ID` | Yes | R2 S3-compatible access key |
| `R2_SECRET_ACCESS_KEY` | Yes | R2 S3-compatible secret key |
| `CLOUDFLARE_API_TOKEN` | For deploy | Wrangler deploy token |
| `CLOUDFLARE_ACCOUNT_ID` | For deploy | Cloudflare Account ID |
| `CLOUDFLARE_SITE_DOMAIN` | For deploy | Custom domain (e.g. `music.yourdomain.com`) |
| `LASTFM_API_KEY` | For enrich | Last.fm API key |
| `LASTFM_USER` | Optional | Last.fm username |
| `SPOTIFY_CLIENT_ID` | For enrich | Spotify app client ID |
| `SPOTIFY_CLIENT_SECRET` | For enrich | Spotify app client secret |
| `SPOTIFY_DAILY_BUDGET` | Optional | Rolling 24h request cap (default `500`) |
| `MUSICBRAINZ_CONTACT` | For enrich | Contact email/URL for MusicBrainz User-Agent |
| `GEMINI_API_KEY` | Optional | Gemini API key for LLM genre classification |

## 4. One-Time Upload from Your Mac

Install the AWS CLI if needed (`brew install awscli`), add the four `R2_*` variables to your local `.env`, and push your existing raw exports, HTTP cache, and DuckDB:

```bash
bash scripts/r2_sync.sh push
```

## 5. Run in the Cloud

1. Open your GitHub repository → **Actions → Cloud Pipeline & Deploy → Run workflow**.
2. Choose a mode:
   - `build-and-deploy`: rebuild DuckDB from cached data + deploy site (fast, ~2–3 min).
   - `enrich-build-deploy`: fetch new API data (`enrich_max_minutes` cap), rebuild DuckDB, and deploy.
   - `enrich-only`: fetch and push `http_cache.sqlite` back to R2.
   - `build-only`: rebuild DuckDB and push `music.duckdb` back to R2.
3. Once verified, uncomment the `schedule` block in `.github/workflows/cloud-pipeline.yml` to run automatically every night.

## Updating Exports or Genre Overrides Later

- **New Spotify/Last.fm export or edited `*_genre_overrides.csv`:** drop the file into your local `DATA_DIR` and run:
  ```bash
  bash scripts/r2_sync.sh push --raw
  ```
  Then trigger **Cloud Pipeline & Deploy** (`build-and-deploy`) from GitHub.
- **Inspecting the cloud database locally:**
  ```bash
  bash scripts/r2_sync.sh pull --db
  ```
