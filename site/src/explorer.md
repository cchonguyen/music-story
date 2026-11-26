# Explorer

Every play, queryable in the browser with **Track Genre Lineage X-Ray** (`LEFT JOIN xray USING (artist_norm, title_norm, parent_genre, style)`) and multi-facet subfilters. DuckDB-Wasm and the Parquet file load only on this page; the first visit downloads about 9 MB of DuckDB from jsDelivr (see `docs/PROJECT.md`, decision 2026-10-27).

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
  const [playsBuf, xrayBuf] = await Promise.all([
    FileAttachment("data/plays_explorer.parquet").arrayBuffer(),
    FileAttachment("data/genre_xray.parquet").arrayBuffer()
  ]);
  const conn = await instance.connect();
  await instance.registerFileBuffer("plays.parquet", new Uint8Array(playsBuf));
  await conn.query("CREATE TABLE plays AS SELECT * FROM 'plays.parquet'");
  await instance.registerFileBuffer("genre_xray.parquet", new Uint8Array(xrayBuf));
  await conn.query(`
    CREATE TABLE xray AS
    SELECT CAST(track_id AS VARCHAR) AS track_id,
           CAST(artist_norm AS VARCHAR) AS artist_norm,
           CAST(title_norm AS VARCHAR) AS title_norm,
           CAST(parent_genre AS VARCHAR) AS parent_genre,
           CAST(style AS VARCHAR) AS style,
           CAST(primary_weight AS DOUBLE) AS primary_weight,
           CAST(level AS VARCHAR) AS genre_level,
           CAST(secondary_styles AS VARCHAR) AS secondary_styles,
           CAST(suppressed_umbrellas AS VARCHAR) AS suppressed_umbrellas
    FROM 'genre_xray.parquet'
  `);
  await conn.query(`
    CREATE VIEW plays_xray AS
    SELECT p.*,
           x.primary_weight,
           x.genre_level,
           x.secondary_styles,
           x.suppressed_umbrellas
    FROM plays p
    LEFT JOIN xray x USING (artist_norm, title_norm, parent_genre, style)
  `);
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

const db = await openExplorer();
```

```js
const [joinAudit] = await query(db, `
  SELECT (SELECT count(*) FROM plays) AS pre_join_rows,
         (SELECT count(*) FROM plays_xray) AS post_join_rows,
         (SELECT count(*) FILTER (WHERE NOT is_skip) FROM plays) AS pre_join_plays,
         (SELECT count(*) FILTER (WHERE NOT is_skip) FROM plays_xray) AS post_join_plays,
         (SELECT count(*) FILTER (WHERE NOT is_skip AND parent_genre IS NOT NULL) FROM plays_xray) AS classified_plays,
         (SELECT count(*) FILTER (WHERE NOT is_skip AND parent_genre IS NULL) FROM plays_xray) AS unclassified_plays,
         (SELECT count(*) FILTER (WHERE parent_genre IS NOT NULL AND primary_weight IS NULL) FROM plays_xray) AS unmatched_classified
`);
console.assert(
  joinAudit.post_join_rows === joinAudit.pre_join_rows && joinAudit.unmatched_classified === 0,
  "Explorer LEFT JOIN xray conservation check failed",
  joinAudit
);

const [bounds] = await query(db, "SELECT min(year(day)) AS lo, max(year(day)) AS hi FROM plays_xray");
const yearList = d3.range(bounds.lo, bounds.hi + 1);
const genreList = (await query(db, "SELECT DISTINCT parent_genre FROM plays_xray WHERE parent_genre IS NOT NULL ORDER BY 1"))
  .map((d) => d.parent_genre);
const styleListAll = (await query(db, "SELECT DISTINCT parent_genre, style FROM plays_xray WHERE style IS NOT NULL ORDER BY 1, 2"));
const countryList = (await query(db, "SELECT DISTINCT coalesce(country, 'unknown') AS c FROM plays_xray ORDER BY 1"))
  .map((d) => d.c);
const platformList = (await query(db, "SELECT DISTINCT coalesce(platform, 'unknown') AS p FROM plays_xray ORDER BY 1"))
  .map((d) => d.p);
```

```js
const search = view(Inputs.text({label: "Search", placeholder: "Artist, title, album, or secondary style", submit: false}));
const fromYear = view(Inputs.select(yearList, {label: "From year", value: bounds.lo, format: String}));
const toYear = view(Inputs.select(yearList, {label: "To year", value: bounds.hi, format: String}));
const genre = view(Inputs.select([null, "__UNCLASSIFIED__", ...genreList], {
  label: "Parent genre",
  format: (d) => (d === null ? "all (including unclassified)" : d === "__UNCLASSIFIED__" ? "unclassified (no genre tags)" : d)
}));
const styleOptions = [
  null,
  ...styleListAll
    .filter((d) => !genre || genre === "__UNCLASSIFIED__" || d.parent_genre === genre)
    .map((d) => d.style)
];
const styleFilter = view(Inputs.select([...new Set(styleOptions)], {
  label: "Sub-style",
  format: (d) => d ?? "all"
}));
const daypart = view(Inputs.select(
  new Map([
    ["All Hours (00–23)", "all"],
    ["Night (00–05)", "night"],
    ["Morning (06–11)", "morning"],
    ["Afternoon (12–17)", "afternoon"],
    ["Evening (18–23)", "evening"]
  ]),
  {label: "Local daypart", value: "all"}
));
const dayType = view(Inputs.select(
  new Map([
    ["All Days (Mon–Sun)", "all"],
    ["Weekdays (Mon–Fri)", "weekday"],
    ["Weekends (Sat–Sun)", "weekend"]
  ]),
  {label: "Weekday / weekend", value: "all"}
));
const countryFilter = view(Inputs.select([null, ...countryList], {
  label: "Country",
  format: (d) => d ?? "all"
}));
const platformFilter = view(Inputs.select([null, ...platformList], {
  label: "Platform",
  format: (d) => d ?? "all"
}));
const levelFilter = view(Inputs.select([null, "manual", "track", "album", "artist"], {
  label: "Genre tag level",
  format: (d) => d ?? "all"
}));
const groupBy = view(Inputs.select(
  new Map([
    ["Track (with Genre X-Ray)", "track"],
    ["Artist", "artist"],
    ["Album", "album"],
    ["Style", "style"],
    ["Year", "year"],
    ["Platform", "platform"],
    ["Country", "country"],
    ["Local Hour (0–23)", "hour"]
  ]),
  {label: "Group by", value: "track"}
));
```

```js
// Search matches the names as shown and the pipeline's normalised names, so "beyonce" finds "Beyoncé".
const pattern = `%${search.trim()}%`;
const daypartClause =
  daypart === "night"
    ? "hour BETWEEN 0 AND 5"
    : daypart === "morning"
    ? "hour BETWEEN 6 AND 11"
    : daypart === "afternoon"
    ? "hour BETWEEN 12 AND 17"
    : daypart === "evening"
    ? "hour BETWEEN 18 AND 23"
    : null;
const dayTypeClause =
  dayType === "weekday"
    ? "weekday BETWEEN 1 AND 5"
    : dayType === "weekend"
    ? "weekday IN (6, 7)"
    : null;

const whereParts = [
  "year(day) BETWEEN ? AND ?",
  "(artist ILIKE ? OR title ILIKE ? OR coalesce(album, '') ILIKE ? OR artist_norm ILIKE ? OR title_norm ILIKE ? OR coalesce(secondary_styles, '') ILIKE ?)"
];
const params = [
  Math.min(fromYear, toYear),
  Math.max(fromYear, toYear),
  ...Array(6).fill(pattern)
];

if (genre === "__UNCLASSIFIED__") {
  whereParts.push("parent_genre IS NULL");
} else if (genre) {
  whereParts.push("parent_genre = ?");
  params.push(genre);
}
if (styleFilter) {
  whereParts.push("style = ?");
  params.push(styleFilter);
}
if (daypartClause) whereParts.push(daypartClause);
if (dayTypeClause) whereParts.push(dayTypeClause);
if (countryFilter) {
  whereParts.push("coalesce(country, 'unknown') = ?");
  params.push(countryFilter);
}
if (platformFilter) {
  whereParts.push("coalesce(platform, 'unknown') = ?");
  params.push(platformFilter);
}
if (levelFilter) {
  whereParts.push("genre_level = ?");
  params.push(levelFilter);
}

const where = whereParts.join(" AND ");

// Group keys come from the fixed list above, never from typed text.
const groups = {
  track: [
    "artist, title, coalesce(parent_genre, '(unclassified)') AS parent_genre, coalesce(style, '(unclassified)') AS style, round(avg(primary_weight), 2) AS weight, any_value(coalesce(genre_level, 'none')) AS tag_level, any_value(coalesce(secondary_styles, '')) AS secondary_styles",
    "artist, title, parent_genre, style"
  ],
  artist: [
    "artist, any_value(coalesce(parent_genre, '(unclassified)')) AS top_parent_genre, any_value(coalesce(style, '(unclassified)')) AS top_style",
    "artist"
  ],
  album: ["artist, coalesce(album, '(no album)') AS album", "artist, album"],
  style: [
    "coalesce(parent_genre, '(unclassified)') AS parent_genre, coalesce(style, '(unclassified)') AS style",
    "parent_genre, style"
  ],
  year: ["year(day) AS year", "year"],
  platform: ["coalesce(platform, 'unknown') AS platform", "platform"],
  country: ["coalesce(country, 'unknown') AS country", "country"],
  hour: ["hour AS local_hour", "local_hour"]
};
const [groupCols, groupKeys] = groups[groupBy];
```

```js
const [filteredKpis] = await query(
  db,
  `SELECT count(*) FILTER (WHERE NOT is_skip) AS plays,
          count(*) FILTER (WHERE is_skip) AS skips,
          round(coalesce(sum(minutes) FILTER (WHERE NOT is_skip), 0) / 60.0, 1) AS hours,
          count(*) FILTER (WHERE NOT is_skip AND parent_genre IS NOT NULL) AS classified_plays,
          count(*) FILTER (WHERE NOT is_skip AND parent_genre IS NULL) AS unclassified_plays
   FROM plays_xray
   WHERE ${where}`,
  params
);
const months = await query(
  db,
  `SELECT date_trunc('month', day) AS month, count(*) AS plays FROM plays_xray WHERE NOT is_skip AND ${where} GROUP BY 1 ORDER BY 1`,
  params
);
const rows = await query(
  db,
  `SELECT ${groupCols}, count(*) FILTER (NOT is_skip) AS plays,
          round(sum(minutes) FILTER (NOT is_skip) / 60, 1) AS hours,
          count(*) FILTER (is_skip) AS skips,
          count(*) FILTER (is_skip) / nullif(count(*) FILTER (is_skip OR source <> 'lastfm'), 0) AS skip_rate,
          min(day) FILTER (NOT is_skip) AS first_play, max(day) FILTER (NOT is_skip) AS last_play
   FROM plays_xray WHERE ${where} GROUP BY ${groupKeys} HAVING count(*) FILTER (NOT is_skip) > 0
   ORDER BY plays DESC, ${groupKeys} LIMIT 500`,
  params
);
```

<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(175px, 1fr)); gap: 0.9rem; padding: 0.75rem 0; border-top: 1px solid rgba(128,128,128,0.22); border-bottom: 1px solid rgba(128,128,128,0.22); margin: 0.75rem 0 1.25rem; font-variant-numeric: tabular-nums;">
  <div>
    <div style="font-size: 0.75rem; opacity: 0.68;">Filtered Plays</div>
    <div style="font-size: 1.35rem; font-weight: 600;">${(filteredKpis?.plays ?? 0).toLocaleString()}</div>
    <div style="font-size: 0.75rem; opacity: 0.65;">${(filteredKpis?.hours ?? 0).toLocaleString()} hrs · ${(filteredKpis?.skips ?? 0).toLocaleString()} skips</div>
  </div>
  <div>
    <div style="font-size: 0.75rem; opacity: 0.68;">Classified Plays</div>
    <div style="font-size: 1.35rem; font-weight: 600;">${(filteredKpis?.classified_plays ?? 0).toLocaleString()}</div>
    <div style="font-size: 0.75rem; opacity: 0.65;">${filteredKpis?.plays ? ((filteredKpis.classified_plays / filteredKpis.plays) * 100).toFixed(1) : "0.0"}% of filtered plays</div>
  </div>
  <div>
    <div style="font-size: 0.75rem; opacity: 0.68;">Unclassified Plays (no genre tags)</div>
    <div style="font-size: 1.35rem; font-weight: 600;">${(filteredKpis?.unclassified_plays ?? 0).toLocaleString()}</div>
    <div style="font-size: 0.75rem; opacity: 0.65;">Preserved via LEFT JOIN</div>
  </div>
  <div>
    <div style="font-size: 0.75rem; opacity: 0.68;">Join Conservation Audit</div>
    <div style="font-size: 1.35rem; font-weight: 600;">${joinAudit.post_join_rows === joinAudit.pre_join_rows && joinAudit.unmatched_classified === 0 ? "1:1 Verified" : "Mismatch"}</div>
    <div style="font-size: 0.75rem; opacity: 0.65;">${joinAudit.post_join_rows.toLocaleString()} events · ${joinAudit.unmatched_classified} unmatched</div>
  </div>
</div>

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

Up to 500 rows, grouped by the picker above, most played first. Hours and dates count plays only. Skip rate is skips over skips plus Spotify plays, as on the Habits page (Last.fm-only plays cannot be skips). When grouped by **Track (with Genre X-Ray)**, each song also shows its primary style weight, dominant tag specificity level (`track` / `album` / `artist`), and co-occurring secondary styles.

```js
const day = d3.utcFormat("%Y-%m-%d");
display(Inputs.table(rows, {
  format: {
    skip_rate: (d) => (d == null ? "" : d3.format(".0%")(d)),
    weight: (d) => (d == null ? "—" : d3.format(".0%")(d)),
    year: String,
    local_hour: (d) => (d == null ? "" : `${String(d).padStart(2, "0")}:00`),
    first_play: day,
    last_play: day
  },
  rows: 20
}));
```

<!-- story: explorer -->
