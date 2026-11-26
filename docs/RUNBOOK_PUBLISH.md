# Publish the site (Mac runbook)

Run each block in Terminal, one at a time, and check the expected result before the next.
Repo folder: `/Users/charliechonguyen/Projects/music-story/music-story`

## Stage 1: Get the latest code

Run only if `git status` shows changes you want to keep. Otherwise skip to Stage 2.

```
cd /Users/charliechonguyen/Projects/music-story/music-story && git status
```

Expected result: a branch line and the list of changed files.

```
cd /Users/charliechonguyen/Projects/music-story/music-story && git stash && git pull --ff-only && git stash pop
```

Expected result: "Fast-forward" or "Already up to date", then your files restored. If `git pull --ff-only` says "divergent branches", stop and paste the output. Do not force anything.

## Stage 2: Rebuild the data from step 05

```
cd /Users/charliechonguyen/Projects/music-story/music-story && uv run python -m pipeline.build_pipeline --from 05
```

Expected result: the step list includes "step 05", and the final counts include `plays` above 0 (about 145,000 last run). If `plays` is 0, the build skipped step 05. Rerun this block.

## Stage 3: Build the site

```
cd /Users/charliechonguyen/Projects/music-story/music-story/site && SITE_DB=/Users/charliechonguyen/Projects/music-story/music-story/build/music.duckdb npm run build
```

Expected result: the build lists seven pages (artists, explorer, genres, habits, index, places, songs) and ends without an error.

## Stage 4: Deploy

```
cd /Users/charliechonguyen/Projects/music-story/music-story && npx wrangler deploy
```

Expected result: "Success! Uploaded..." and `music.charliechonguyen.com (custom domain)`.

## Stage 5: Check

Open https://music.charliechonguyen.com/artists, scroll to the bottom, and click Export CSV. Expected result: the row and artist count line appears (last run: 31,761 rows, 3,815 artists).

## Known traps

- Run every block from the repo folder that contains `.git`. Running from another folder gives "not a git repository".
- Do not run `npm run build` from the repo root. Its `prebuild` step copies a file into `/usr/local/bin` and fails without admin rights. Stage 3 builds from `site/` instead.
- Do not use `git pull --rebase` or force options in Stage 1.
- If a stage fails, paste the error text, not a screenshot of the terminal.
