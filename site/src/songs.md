# Songs

Annual top recordings, 14-day obsession binges, the **Earworm Half-Life** (distinguishing short-lived burnouts from canonized anthems), and the **Musical Biological Clock** (song age at the moment of play).

```js
import {SPECIFICATION_BASELINE} from "./specificationBaseline.js";
const trackYear = await FileAttachment("data/track_year.json").json();
const binge = await FileAttachment("data/binge.json").json();
const earworm = await FileAttachment("data/earworm_halflife.json").json();
const songAge = await FileAttachment("data/song_age.json").json();
const trackLabel = await FileAttachment("data/track_label.json").json();
const artistLabel = await FileAttachment("data/artist_label.json").json();

const titles = new Map(trackLabel.map((d) => [d.track_id, d]));
const artistNames = new Map(artistLabel.map((d) => [d.artist_id, d.name]));
const trackName = (id) => titles.get(id)?.title ?? `track ${id}`;
const artistOf = (id) => artistNames.get(titles.get(id)?.artist_id) ?? "";
```

## Top tracks per year

```js
const years = [...new Set(trackYear.map((d) => d.year))].sort((a, b) => b - a);
const pickedYear = view(Inputs.select(years, {label: "Year"}));
```

```js
const topTracksYear = trackYear
  .filter((d) => d.year === pickedYear && d.rank <= 10)
  .sort((a, b) => a.rank - b.rank)
  .map((d) => ({
    rank: d.rank,
    track: trackName(d.track_id),
    artist: artistOf(d.track_id),
    label: `${trackName(d.track_id)} — ${artistOf(d.track_id)}`,
    plays: d.plays,
    hours: Math.round(d.listen_hours * 10) / 10
  }));
```

```js
Plot.plot({
  marginLeft: 220,
  height: 290,
  x: {label: `Plays in ${pickedYear}`, grid: true},
  y: {label: null, domain: topTracksYear.map((d) => d.label)},
  marks: [
    Plot.barX(topTracksYear, {y: "label", x: "plays", fill: "#2563eb", tip: true}),
    Plot.ruleX([0])
  ]
})
```

```js
Inputs.table(topTracksYear.map(({rank, track, artist, plays, hours}) => ({rank, track, artist, plays, hours})))
```

<!-- story: top tracks -->

## Binges & The Earworm Half-Life: Burnout vs. Canonization

Tracks whose busiest 14-day window ran far above their baseline rate ($\ge 15$ plays in 14 days). By measuring **what happened after day 14** (`later_plays / lifetime_plays`), each binge separates into:
- **Canonized Anthems**: A 14-day obsession that became a permanent, multi-year favorite ($\ge 1.25\times$ more plays *after* the binge than during it).
- **Steady Rotation**: Moderate post-binge replay.
- **Flash Burnouts**: Overplayed in a single 14-day fever with minimal replay afterward ($\le 0.35\times$ post-window plays).

```js
const archetypeFilter = view(Inputs.radio(
  ["All Archetypes", "Canonized Anthem", "Steady Rotation", "Flash Burnout"],
  {label: "Earworm archetype", value: "All Archetypes"}
));
```

```js
const earwormRows = earworm
  .filter((d) => archetypeFilter === "All Archetypes" || d.archetype === archetypeFilter)
  .map((d) => ({
    ...d,
    track: trackName(d.track_id),
    artist: artistOf(d.track_id),
    survival_pct: d.post_survival_share * 100
  }))
  .sort((a, b) => b.rate_ratio - a.rate_ratio);
```

```js
Plot.plot({
  height: 320,
  x: {label: "14-Day Burst Intensity (Rate Ratio vs. Lifetime Baseline)", grid: true},
  y: {label: "Post-Binge Survival Share (% of Lifetime Plays After Day 14)", grid: true},
  r: {range: [5, 16], label: "14-Day Window Plays"},
  color: {
    legend: true,
    domain: ["Canonized Anthem", "Steady Rotation", "Flash Burnout"],
    range: ["#16a34a", "#0284c7", "#dc2626"]
  },
  marks: [
    Plot.ruleY([50], {strokeDasharray: "4,4", strokeOpacity: 0.4}),
    Plot.dot(earwormRows, {
      x: "rate_ratio",
      y: "survival_pct",
      r: "window_plays",
      fill: "archetype",
      fillOpacity: 0.8,
      stroke: "currentColor",
      strokeWidth: 0.6,
      title: (d) => `${d.track} — ${d.artist}\nArchetype: ${d.archetype}\n14d Window (${d.window_start}): ${d.window_plays} plays\nAfter Binge: ${d.later_plays} plays (${d.survival_pct.toFixed(1)}% of ${d.lifetime_plays} lifetime)`,
      tip: true
    })
  ]
})
```

```js
Inputs.table(
  earwormRows.slice(0, 25).map((d) => ({
    track: d.track,
    artist: d.artist,
    archetype: d.archetype,
    window_start: d.window_start,
    window_plays: d.window_plays,
    post_30d: d.post_30d_plays,
    later_plays: d.later_plays,
    lifetime_plays: d.lifetime_plays,
    rate_ratio: Math.round(d.rate_ratio * 10) / 10
  }))
)
```

<!-- story: binges -->

## Song age & The Musical Biological Clock

Plays per year by song age (`play_year - work_year` of the underlying composition, so a 2021 remaster of a 2008 track counts as a 2008 song). Toggle between **Absolute Plays** and **100% Share of Annual Listening**.

```js
const ageMode = view(Inputs.radio(["Absolute Plays", "100% Share of Year"], {
  label: "Display scale",
  value: "Absolute Plays"
}));
const includeUnknownAge = view(Inputs.toggle({label: "Include tracks with unknown work_year", value: true}));
```

```js
const ageDomain = ["0", "1-2", "3-5", "6-10", "11-20", "21+", ...(includeUnknownAge ? ["unknown"] : [])];
const filteredAge = songAge.filter((d) => includeUnknownAge || d.age_bucket !== "unknown");
```

```js
ageMode === "Absolute Plays"
  ? Plot.plot({
      x: {label: "Year", tickFormat: "d"},
      y: {label: "Plays", grid: true},
      color: {legend: true, label: "Age in years", domain: ageDomain},
      marks: [Plot.barY(filteredAge, {x: "year", y: "plays", fill: "age_bucket", tip: true}), Plot.ruleY([0])]
    })
  : Plot.plot({
      x: {label: "Year", tickFormat: "d"},
      y: {label: "Share of plays", grid: true, tickFormat: "%"},
      color: {legend: true, label: "Age in years", domain: ageDomain},
      marks: [
        Plot.barY(filteredAge, Plot.normalizeY("sum", {x: "year", y: "plays", fill: "age_bucket", tip: true})),
        Plot.ruleY([0])
      ]
    })
```

```js
const totalFilteredAgePlays = d3.sum(filteredAge, (d) => d.plays);
const songAgeSummaryTable = d3.rollups(
  filteredAge,
  (v) => {
    const plays = d3.sum(v, (d) => d.plays);
    const peak = d3.greatest(v, (d) => d.plays);
    return {
      plays,
      share_of_plays: `${((plays / (totalFilteredAgePlays || 1)) * 100).toFixed(1)}%`,
      peak_year: peak ? peak.year : null,
      peak_year_plays: peak ? peak.plays : 0
    };
  },
  (d) => d.age_bucket
).map(([age_bucket, s]) => ({age_bucket, ...s}));
```

```js
Inputs.table(songAgeSummaryTable, {
  format: {peak_year: (d) => (d == null ? "—" : String(d))},
  rows: 8
})
```

## Track genre sheet

Every track with at least 3 plays, with its title, artist, genres and share. Export the CSV, edit it outside the site, then import it on the Mac with `uv run python -m pipeline.track_sheet import <file>`. Imported genres replace the automatic genres for those tracks.

```js
const trackSheetRows = await FileAttachment("data/track_genre_sheet.json").json();

const csvCellT = (v) => {
  if (v == null) return "";
  const s = String(v);
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

const trackSheetCsv = (rows) => {
  const head = ["track_id", "title", "artist", "plays", "parent_genre", "style", "share", "source"];
  const lines = rows.map((r) =>
    [r.track_id, r.title, r.artist, r.plays, r.parent_genre, r.style, r.share, r.source].map(csvCellT).join(",")
  );
  return [head.join(","), ...lines].join("\n") + "\n";
};

const trackSheetButton = Inputs.button("Export track CSV", {
  reduce: () => {
    const blob = new Blob([trackSheetCsv(trackSheetRows)], {type: "text/csv;charset=utf-8"});
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "track_genre_sheet.csv";
    a.click();
    URL.revokeObjectURL(url);
  }
});
display(trackSheetButton);
```

```js
display(html`<p>${trackSheetRows.length.toLocaleString()} rows, ${new Set(trackSheetRows.map((r) => r.track_id)).size.toLocaleString()} tracks.</p>`);
```
