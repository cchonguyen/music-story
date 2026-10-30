# Explorer & Visual Remix Studio

Every play and skip across 19.5 years, queryable and remixable in the browser. Use the slicers below to cross-filter any artist, track, album, genre, or year range, then switch between **Insights & Visual Remix Tabs** to inspect the slice's monthly pulse, weekday $\times$ hour rhythm fingerprint, top entities, and skip behavior.

```js
import {SPECIFICATION_BASELINE} from "./specificationBaseline.js";
const rawEvents = await FileAttachment("data/explorer_events.json").json();
const tempoPulse = await FileAttachment("data/tempo_pulse.json").json();

const allEvents = rawEvents.map((d) => {
  const dt = new Date(d.ts);
  const utcDay = dt.getUTCDay();
  return {
    ...d,
    dateObj: dt,
    year: dt.getUTCFullYear(),
    monthDate: new Date(Date.UTC(dt.getUTCFullYear(), dt.getUTCMonth(), 1)),
    weekday: utcDay === 0 ? 7 : utcDay,
    hour: dt.getUTCHours(),
    dayStr: d.ts.slice(0, 10)
  };
});

const minYear = d3.min(allEvents, (d) => d.year) ?? 2007;
const maxYear = d3.max(allEvents, (d) => d.year) ?? 2026;
const yearList = d3.range(minYear, maxYear + 1);
const genreList = [...new Set(allEvents.map((d) => d.parent_genre).filter(Boolean))].sort();
```

```js
const search = view(Inputs.text({label: "Search", placeholder: "Artist, title or album (e.g. Mara, Beyonce, Harbor)", submit: false}));
const fromYear = view(Inputs.select(yearList, {label: "From", value: minYear, format: String}));
const toYear = view(Inputs.select(yearList, {label: "To", value: maxYear, format: String}));
const genre = view(Inputs.select([null, ...genreList], {label: "Parent genre", format: (d) => d ?? "all"}));
const eventMode = view(Inputs.select(
  new Map([
    ["Plays + Skips (Standard)", "all"],
    ["Completed Plays Only", "plays_only"],
    ["Skipped Events Only (<30s)", "skips_only"]
  ]),
  {label: "Event filter", value: "all"}
));
const groupBy = view(Inputs.select(new Map([
  ["Track", "track"], ["Artist", "artist"], ["Album", "album"], ["Style", "style"], ["Year", "year"],
  ["Platform", "platform"], ["Country", "country"]
]), {label: "Group by", value: "track"}));
```

```js
const loY = Math.min(fromYear, toYear);
const hiY = Math.max(fromYear, toYear);
const q = search.trim().toLowerCase();

const filteredEvents = allEvents.filter((d) => {
  if (d.year < loY || d.year > hiY) return false;
  if (genre && d.parent_genre !== genre) return false;
  if (eventMode === "plays_only" && d.is_skip) return false;
  if (eventMode === "skips_only" && !d.is_skip) return false;
  if (q) {
    const match =
      (d.artist && d.artist.toLowerCase().includes(q)) ||
      (d.title && d.title.toLowerCase().includes(q)) ||
      (d.album && d.album.toLowerCase().includes(q)) ||
      (d.artist_norm && d.artist_norm.toLowerCase().includes(q)) ||
      (d.title_norm && d.title_norm.toLowerCase().includes(q));
    if (!match) return false;
  }
  return true;
});

const slicePlays = filteredEvents.filter((d) => !d.is_skip);
const sliceSkips = filteredEvents.filter((d) => d.is_skip);
const sliceHours = Math.round(d3.sum(slicePlays, (d) => d.minutes) / 6) / 10;

const months = d3.rollups(
  eventMode === "skips_only" ? sliceSkips : slicePlays,
  (v) => v.length,
  (d) => +d.monthDate
)
  .map(([ms, plays]) => ({month: new Date(ms), plays}))
  .sort((a, b) => a.month - b.month);

const rhythmCells = d3.rollups(
  eventMode === "skips_only" ? sliceSkips : slicePlays,
  (v) => v.length,
  (d) => d.weekday,
  (d) => d.hour
).flatMap(([weekday, hs]) => hs.map(([hour, plays]) => ({weekday, hour, plays})));

const groupKeyFn = (d) => {
  if (groupBy === "track") return `${d.artist}|||${d.title}`;
  if (groupBy === "artist") return d.artist;
  if (groupBy === "album") return `${d.artist}|||${d.album ?? "(no album)"}`;
  if (groupBy === "style") return `${d.parent_genre ?? "(none)"}|||${d.style ?? "(none)"}`;
  if (groupBy === "year") return String(d.year);
  if (groupBy === "platform") return d.platform ?? "unknown";
  return d.country ?? "unknown";
};

const groupedMap = new Map();
for (const d of filteredEvents) {
  const k = groupKeyFn(d);
  let g = groupedMap.get(k);
  if (!g) {
    g = {
      key: k,
      sample: d,
      plays: 0,
      minutes: 0,
      skips: 0,
      sp_denom: 0,
      first_play: null,
      last_play: null
    };
    groupedMap.set(k, g);
  }
  if (d.is_skip) {
    g.skips += 1;
    g.sp_denom += 1;
  } else {
    g.plays += 1;
    g.minutes += d.minutes;
    if (d.source !== "lastfm") g.sp_denom += 1;
    if (!g.first_play || d.dayStr < g.first_play) g.first_play = d.dayStr;
    if (!g.last_play || d.dayStr > g.last_play) g.last_play = d.dayStr;
  }
}

const rows = Array.from(groupedMap.values())
  .filter((g) => (eventMode === "skips_only" ? g.skips > 0 : g.plays > 0))
  .map((g) => {
    const s = g.sample;
    const base =
      groupBy === "track"
        ? {artist: s.artist, title: s.title, label: `${s.title} — ${s.artist}`}
        : groupBy === "artist"
        ? {artist: s.artist, label: s.artist}
        : groupBy === "album"
        ? {artist: s.artist, album: s.album ?? "(no album)", label: `${s.album ?? "(no album)"} — ${s.artist}`}
        : groupBy === "style"
        ? {parent_genre: s.parent_genre ?? "(none)", style: s.style ?? "(none)", label: `${s.style ?? "(none)"} (${s.parent_genre ?? "none"})`}
        : groupBy === "year"
        ? {year: s.year, label: String(s.year)}
        : groupBy === "platform"
        ? {platform: s.platform ?? "unknown", label: s.platform ?? "unknown"}
        : {country: s.country ?? "unknown", label: s.country ?? "unknown"};
    return {
      ...base,
      plays: g.plays,
      hours: Math.round((g.minutes / 60) * 10) / 10,
      skips: g.skips,
      skip_rate: g.sp_denom > 0 ? g.skips / g.sp_denom : null,
      first_play: g.first_play,
      last_play: g.last_play
    };
  })
  .sort((a, b) => (eventMode === "skips_only" ? b.skips - a.skips : b.plays - a.plays) || String(a.label).localeCompare(String(b.label)))
  .slice(0, 500);
```

<div style="display: flex; flex-wrap: wrap; gap: 1.5rem; padding: 0.75rem 0; border-top: 1px solid rgba(128,128,128,0.22); border-bottom: 1px solid rgba(128,128,128,0.22); margin: 0.75rem 0 1.25rem; font-variant-numeric: tabular-nums; font-size: 0.9rem;">
  <span><strong>Active Slice Plays:</strong> ${slicePlays.length.toLocaleString()}</span>
  <span>·</span>
  <span><strong>Listening Hours:</strong> ${sliceHours.toLocaleString()} hrs</span>
  <span>·</span>
  <span><strong>Skips:</strong> ${sliceSkips.length.toLocaleString()}</span>
  <span>·</span>
  <span><strong>Grouped Entities:</strong> ${rows.length.toLocaleString()}</span>
</div>

## Insights & Visual Remix Tabs

Switch between visual lenses for your active filter slice:

```js
const remixTab = view(Inputs.radio(
  [
    "Tab 1: Monthly Pulse & Slice Rhythm Heatmap",
    "Tab 2: Top 15 Ranked Entities & Skip Rate",
    "Tab 3: Circadian Tempo & Session Energy Reference"
  ],
  {label: "Remix Studio tab", value: "Tab 1: Monthly Pulse & Slice Rhythm Heatmap"}
));
```

```js
const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const top15 = rows.slice(0, 15);
const hrTempo = tempoPulse.filter((d) => d.bucket_type === "hour");
```

```js
remixTab.startsWith("Tab 1")
  ? html`<div>
      <h3 style="margin-top:0.5rem;">Plays per month (Active Slice)</h3>
      ${Plot.plot({
        height: 210,
        x: {label: "Month"},
        y: {label: eventMode === "skips_only" ? "Skips" : "Plays", grid: true},
        marks: [
          Plot.rectY(months, {x1: "month", x2: (d) => d3.utcMonth.offset(d.month, 1), y: "plays", fill: "#2563eb", tip: true}),
          Plot.ruleY([0])
        ]
      })}
      <h3 style="margin-top:1.25rem;">Slice Rhythm Fingerprint (Weekday × Local Hour)</h3>
      ${Plot.plot({
        height: 240,
        x: {label: "Local Hour (0–23)", tickFormat: "d", domain: d3.range(0, 24)},
        y: {label: null, domain: [1, 2, 3, 4, 5, 6, 7], tickFormat: (d) => days[d - 1]},
        color: {legend: true, scheme: "YlGnBu", label: eventMode === "skips_only" ? "Skips" : "Plays"},
        marks: [Plot.cell(rhythmCells, {x: "hour", y: "weekday", fill: "plays", inset: 0.5, tip: true})]
      })}
    </div>`
  : remixTab.startsWith("Tab 2")
  ? Plot.plot({
      marginLeft: 210,
      height: Math.max(240, top15.length * 24 + 50),
      x: {label: eventMode === "skips_only" ? "Skips" : "Plays", grid: true},
      y: {label: null, domain: top15.map((d) => d.label)},
      color: {legend: true, scheme: "Warm", label: "Skip rate"},
      marks: [
        Plot.barX(top15, {
          y: "label",
          x: eventMode === "skips_only" ? "skips" : "plays",
          fill: (d) => d.skip_rate ?? 0,
          tip: true
        }),
        Plot.ruleX([0])
      ]
    })
  : Plot.plot({
      height: 260,
      x: {label: "Local Hour of Day (0–23)", tickFormat: "d"},
      y: {label: "Tempo (BPM, octave-corrected)", grid: true},
      marks: [
        Plot.areaY(hrTempo, {x: "bucket", y1: "p25_bpm", y2: "p75_bpm", fill: "#0d9488", fillOpacity: 0.2}),
        Plot.lineY(hrTempo, {x: "bucket", y: "avg_bpm", stroke: "#0d9488", strokeWidth: 2.4, marker: "dot", tip: true})
      ]
    })
```

## Most played

Up to 500 rows, grouped by the picker above, most played first. Hours and dates count plays only. Skip rate is skips over skips plus Spotify plays, as on the Habits page (Last.fm-only plays cannot be skips).

```js
const tableRows = rows.map(({label, ...rest}) => rest);
display(Inputs.table(tableRows, {
  format: {skip_rate: (d) => d == null ? "" : d3.format(".0%")(d), year: String},
  rows: 20
}));
```

<!-- story: explorer -->
