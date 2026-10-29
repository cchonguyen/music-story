# Explorer

Every play, queryable in the browser. DuckDB-Wasm and the Parquet file load only on this page; the first
visit downloads about 9 MB of DuckDB from jsDelivr (see docs/PROJECT.md, decision 2026-10-27).

```js
// Not Framework's DuckDBClient: that self-hosts duckdb-*.wasm (34-39 MiB), over the 25 MiB file limit of
// Workers static assets. Only the library comes from the CDN; the data stays behind Access.
import * as ddb from "https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@1.29.0/+esm";

async function openExplorer() {
  const bundle = await ddb.selectBundle(ddb.getJsDelivrBundles());
  const workerUrl = URL.createObjectURL(new Blob([`importScripts("${bundle.mainWorker}");`], {type: "text/javascript"}));
  const instance = new ddb.AsyncDuckDB(new ddb.ConsoleLogger(ddb.LogLevel.WARNING), new Worker(workerUrl));
  await instance.instantiate(bundle.mainModule, bundle.pthreadWorker);
  URL.revokeObjectURL(workerUrl);
  const file = await FileAttachment("data/plays_explorer.parquet").arrayBuffer();
  await instance.registerFileBuffer("plays.parquet", new Uint8Array(file));
  const conn = await instance.connect();
  await conn.query("CREATE TABLE plays AS SELECT * FROM 'plays.parquet'");
  return conn;
}

// Arrow rows -> plain objects; BIGINT counts become numbers, TIMESTAMP and DATE (epoch ms) become Dates.
async function query(conn, sql, params = []) {
  const stmt = await conn.prepare(sql);
  try {
    const table = await stmt.query(...params);
    const dates = table.schema.fields.filter((f) => /^(Timestamp|Date)/.test(String(f.type))).map((f) => f.name);
    return table.toArray().map((r) => {
      const o = {};
      for (const f of table.schema.fields) {
        const v = r[f.name];
        o[f.name] = v == null ? v : dates.includes(f.name) ? new Date(Number(v)) : typeof v === "bigint" ? Number(v) : v;
      }
      return o;
    });
  } finally {
    await stmt.close();
  }
}

const db = openExplorer();
```

```js
const [bounds] = await query(db, "SELECT min(year(day)) AS lo, max(year(day)) AS hi FROM plays");
const yearList = d3.range(bounds.lo, bounds.hi + 1);
const genreList = (await query(db, "SELECT DISTINCT parent_genre FROM plays WHERE parent_genre IS NOT NULL ORDER BY 1"))
  .map((d) => d.parent_genre);
```

```js
const search = view(Inputs.text({label: "Search", placeholder: "Artist, title or album", submit: false}));
const fromYear = view(Inputs.select(yearList, {label: "From", value: bounds.lo, format: String}));
const toYear = view(Inputs.select(yearList, {label: "To", value: bounds.hi, format: String}));
const genre = view(Inputs.select([null, ...genreList], {label: "Parent genre", format: (d) => d ?? "all"}));
const groupBy = view(Inputs.select(new Map([
  ["Track", "track"], ["Artist", "artist"], ["Album", "album"], ["Style", "style"], ["Year", "year"],
  ["Platform", "platform"], ["Country", "country"]
]), {label: "Group by", value: "track"}));
```

```js
// Search matches the names as shown and the pipeline's normalised names, so "beyonce" finds "Beyoncé".
const pattern = `%${search.trim()}%`;
const where = [
  "year(day) BETWEEN ? AND ?",
  "(artist ILIKE ? OR title ILIKE ? OR album ILIKE ? OR artist_norm ILIKE ? OR title_norm ILIKE ?)",
  genre ? "parent_genre = ?" : null
].filter(Boolean).join(" AND ");
const params = [Math.min(fromYear, toYear), Math.max(fromYear, toYear), ...Array(5).fill(pattern), ...(genre ? [genre] : [])];
// Group keys come from the fixed list above, never from typed text.
const groups = {
  track: ["artist, title", "artist, title"],
  artist: ["artist", "artist"],
  album: ["artist, coalesce(album, '(no album)') AS album", "artist, album"],
  style: ["coalesce(parent_genre, '(none)') AS parent_genre, coalesce(style, '(none)') AS style", "parent_genre, style"],
  year: ["year(day) AS year", "year"],
  platform: ["platform", "platform"],
  country: ["country", "country"]
};
const [groupCols, groupKeys] = groups[groupBy];
```

```js
const months = query(db,
  `SELECT date_trunc('month', day) AS month, count(*) AS plays FROM plays WHERE NOT is_skip AND ${where} GROUP BY 1 ORDER BY 1`,
  params);
const rows = query(db,
  `SELECT ${groupCols}, count(*) FILTER (NOT is_skip) AS plays,
          round(sum(minutes) FILTER (NOT is_skip) / 60, 1) AS hours,
          count(*) FILTER (is_skip) AS skips,
          count(*) FILTER (is_skip) / nullif(count(*) FILTER (is_skip OR source <> 'lastfm'), 0) AS skip_rate,
          min(day) FILTER (NOT is_skip) AS first_play, max(day) FILTER (NOT is_skip) AS last_play
   FROM plays WHERE ${where} GROUP BY ${groupKeys} HAVING count(*) FILTER (NOT is_skip) > 0
   ORDER BY plays DESC, ${groupKeys} LIMIT 500`, params);
```

## Plays per month

```js
Plot.plot({
  height: 220,
  x: {label: "Month"},
  y: {label: "Plays", grid: true},
  marks: [Plot.rectY(months, {x1: "month", x2: (d) => d3.utcMonth.offset(d.month, 1), y: "plays", tip: true}), Plot.ruleY([0])]
})
```

## Most played

Up to 500 rows, grouped by the picker above, most played first. Hours and dates count plays only. Skip rate is skips over skips plus
Spotify plays, as on the Habits page (Last.fm-only plays cannot be skips).

```js
const day = d3.utcFormat("%Y-%m-%d");
display(Inputs.table(rows, {
  format: {skip_rate: (d) => d == null ? "" : d3.format(".0%")(d), year: String, first_play: day, last_play: day},
  rows: 20
}));
```

<!-- story: explorer -->
