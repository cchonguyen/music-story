# Artists

Longitudinal artist trajectories, 20-year lifelines across Staples, Comebacks, and Flashes, plus the **Underground Obscurity Index** and **Early-Adopter Vanguard** powered by Last.fm global listener counts and MusicBrainz career start years.

```js
import {SPECIFICATION_BASELINE} from "./specificationBaseline.js";
const artistYear = await FileAttachment("data/artist_year.json").json();
const arc = await FileAttachment("data/artist_arc.json").json();
const remix = await FileAttachment("data/remixer_year.json").json();
const artistLabel = await FileAttachment("data/artist_label.json").json();
const obscurityYear = await FileAttachment("data/obscurity_year.json").json();
const vanguard = await FileAttachment("data/vanguard.json").json();

const names = new Map(artistLabel.map((d) => [d.artist_id, d.name]));
const nameOf = (id) => names.get(id) ?? `artist ${id}`;
```

## Top 10 per year

Most-played artists in the chosen year, ranked by play count and total listening hours.

```js
const years = [...new Set(artistYear.map((d) => d.year))].sort((a, b) => b - a);
const pickedYear = view(Inputs.select(years, {label: "Year"}));
```

```js
const top10Year = artistYear
  .filter((d) => d.year === pickedYear && d.rank <= 10)
  .sort((a, b) => a.rank - b.rank)
  .map((d) => ({
    rank: d.rank,
    artist: nameOf(d.artist_id),
    plays: d.plays,
    hours: Math.round(d.listen_hours * 10) / 10
  }));
```

```js
Plot.plot({
  marginLeft: 150,
  height: 290,
  x: {label: `Plays in ${pickedYear}`, grid: true},
  y: {label: null, domain: top10Year.map((d) => d.artist)},
  color: {legend: true, scheme: "Blues", label: "Listen hours"},
  marks: [
    Plot.barX(top10Year, {y: "artist", x: "plays", fill: "hours", tip: true}),
    Plot.text(top10Year, {y: "artist", x: "plays", text: (d) => `${d.plays} (${d.hours}h)`, dx: 6, textAnchor: "start", fontSize: 11}),
    Plot.ruleX([0])
  ]
})
```

```js
Inputs.table(top10Year)
```

<!-- story: top artists -->

## Artist Lifelines Matrix (2007–2026)

Instead of viewing flat start and end years, inspect the **Year $\times$ Artist intensity grid** across archetypes: **Staples** ($\ge 10$ active years), **Comebacks** (returned after a gap of $\ge 3$ silent years), and **Flashes** (single active year with $\ge 50$ plays).

```js
const cohortMode = view(Inputs.radio(
  ["Staples (10+ active years)", "Comebacks (3+ year hiatus)", "Flashes (1 active year, 50+ plays)", "Top 25 Overall"],
  {label: "Lifeline cohort", value: "Staples (10+ active years)"}
));
```

```js
const selectedArcRows = (
  cohortMode.startsWith("Staples")
    ? arc.filter((d) => d.years_active >= 10)
    : cohortMode.startsWith("Comebacks")
    ? arc.filter((d) => d.comeback_year != null)
    : cohortMode.startsWith("Flashes")
    ? arc.filter((d) => d.years_active === 1 && d.plays >= 50)
    : arc
)
  .slice()
  .sort((a, b) => b.plays - a.plays)
  .slice(0, 20);

const selectedArtistIds = new Set(selectedArcRows.map((d) => d.artist_id));
const orderedArtistNames = selectedArcRows.map((d) => nameOf(d.artist_id));
const matrixCells = artistYear
  .filter((d) => selectedArtistIds.has(d.artist_id))
  .map((d) => ({
    year: d.year,
    artist: nameOf(d.artist_id),
    plays: d.plays,
    hours: Math.round(d.listen_hours * 10) / 10
  }));
```

```js
Plot.plot({
  marginLeft: 155,
  height: Math.max(220, orderedArtistNames.length * 22 + 50),
  x: {label: "Year", tickFormat: "d", domain: d3.range(2007, 2027)},
  y: {label: null, domain: orderedArtistNames},
  color: {legend: true, scheme: "YlGnBu", label: "Plays in year (ranked top-50)"},
  marks: [
    Plot.cell(matrixCells, {x: "year", y: "artist", fill: "plays", inset: 1, tip: true})
  ]
})
```

```js
const arcRows = (rows) => rows.slice().sort((a, b) => b.plays - a.plays).slice(0, 25).map((d) => ({
  artist: nameOf(d.artist_id),
  plays: d.plays,
  first_year: d.first_year,
  last_year: d.last_year,
  years_active: d.years_active,
  longest_gap_years: d.longest_gap_years,
  comeback_year: d.comeback_year,
  peak_year: d.peak_year
}));
```

### Staples (active in 10 or more years)

```js
Inputs.table(arcRows(arc.filter((d) => d.years_active >= 10)))
```

### Comebacks (returned after a gap of 3 or more years)

```js
Inputs.table(arcRows(arc.filter((d) => d.comeback_year != null)))
```

### Flashes (one active year, 50 or more plays)

```js
Inputs.table(arcRows(arc.filter((d) => d.years_active === 1 && d.plays >= 50)))
```

<!-- story: arcs -->

## The Underground Obscurity Index & Early-Adopter Vanguard

Using global Last.fm listener counts (`dim_artist.lastfm_listeners`) and MusicBrainz career start years (`dim_artist.begin_year`) already stored in the database, we can see how your listening distributes between underground acts (`<25k` global listeners) and mainstream headliners (`750k+`), and identify artists you started listening to right as their career began.

```js
const obscurityScale = view(Inputs.radio(["100% Share of Plays", "Absolute Plays"], {
  label: "Obscurity display",
  value: "100% Share of Plays"
}));
```

```js
const tierOrder = [
  "Deep Underground (<25k)",
  "Indie & Niche (25k–150k)",
  "Mid-Tier (150k–750k)",
  "Global Mainstream (750k+)",
  "Unranked"
].filter((t) => obscurityYear.some((d) => d.tier === t));
```

```js
obscurityScale === "100% Share of Plays"
  ? Plot.plot({
      x: {label: "Year", tickFormat: "d"},
      y: {label: "Share of plays", grid: true, tickFormat: "%"},
      color: {legend: true, domain: tierOrder, range: ["#0f766e", "#0284c7", "#6366f1", "#f59e0b", "#94a3b8"]},
      marks: [
        Plot.barY(obscurityYear, Plot.normalizeY("sum", {x: "year", y: "plays", fill: "tier", tip: true})),
        Plot.ruleY([0])
      ]
    })
  : Plot.plot({
      x: {label: "Year", tickFormat: "d"},
      y: {label: "Plays", grid: true},
      color: {legend: true, domain: tierOrder, range: ["#0f766e", "#0284c7", "#6366f1", "#f59e0b", "#94a3b8"]},
      marks: [
        Plot.barY(obscurityYear, {x: "year", y: "plays", fill: "tier", tip: true}),
        Plot.ruleY([0])
      ]
    })
```

```js
const obscurityTableRows = d3.rollups(
  obscurityYear,
  (v) => ({
    plays: d3.sum(v, (d) => d.plays),
    listen_hours: Math.round(d3.sum(v, (d) => d.listen_hours) * 10) / 10,
    distinct_artists_sum: d3.sum(v, (d) => d.artists),
    active_years: v.length
  }),
  (d) => d.tier
).map(([tier, s]) => ({tier, ...s}));
```

```js
Inputs.table(obscurityTableRows, {rows: 6})
```

### Early-Adopter Vanguard (First Listen Relative to Artist Career Start)

Artists where your first recorded play was closest to (or right at) their MusicBrainz career `begin_year`.

```js
Inputs.table(
  vanguard.slice(0, 25).map((d) => ({
    artist: d.name,
    career_begin: d.begin_year,
    first_listen: d.first_play_year,
    lag_years: d.discovery_lag_years,
    plays: d.plays,
    years_active: d.years_active,
    global_listeners: d.lastfm_listeners,
    origin: d.country
  })),
  {format: {career_begin: String, first_listen: String}}
)
```

## Remixers

Plays of tracks each artist remixed, next to plays of the original versions (`bridge_track_artist.role = 'remixer'`).

```js
const remixTotals = d3.rollups(remix, (v) => ({remix_plays: d3.sum(v, (d) => d.remix_plays), original_plays: d3.sum(v, (d) => d.original_plays)}), (d) => d.artist_id)
  .map(([id, t]) => ({remixer: nameOf(id), ...t}))
  .sort((a, b) => b.remix_plays - a.remix_plays).slice(0, 25);

const remixByYearBars = remix.flatMap((d) => [
  {year: d.year, remixer: nameOf(d.artist_id), version: "Remixed Version Plays", plays: d.remix_plays},
  {year: d.year, remixer: nameOf(d.artist_id), version: "Original Composition Plays", plays: d.original_plays}
]);
```

```js
Plot.plot({
  height: 240,
  x: {label: "Year", tickFormat: "d"},
  y: {label: "Plays", grid: true},
  color: {legend: true, domain: ["Remixed Version Plays", "Original Composition Plays"], range: ["#7c3aed", "#94a3b8"]},
  marks: [
    Plot.barY(remixByYearBars, {x: "year", y: "plays", fill: "version", tip: true}),
    Plot.ruleY([0])
  ]
})
```

```js
Inputs.table(remixTotals)
```
