# Artists

```js
const artistYear = await FileAttachment("data/artist_year.json").json();
const arc = await FileAttachment("data/artist_arc.json").json();
const remix = await FileAttachment("data/remixer_year.json").json();
const artistLabel = await FileAttachment("data/artist_label.json").json();
const names = new Map(artistLabel.map((d) => [d.artist_id, d.name]));
const nameOf = (id) => names.get(id) ?? `artist ${id}`;
```

## Top 10 per year

Most-played artists in the chosen year.

```js
const years = [...new Set(artistYear.map((d) => d.year))].sort((a, b) => b - a);
const pickedYear = view(Inputs.select(years, {label: "Year"}));
```

```js
Inputs.table(
  artistYear.filter((d) => d.year === pickedYear && d.rank <= 10).sort((a, b) => a.rank - b.rank)
    .map((d) => ({rank: d.rank, artist: nameOf(d.artist_id), plays: d.plays, hours: Math.round(d.listen_hours * 10) / 10}))
)
```

<!-- story: top artists -->

## Arcs

Each table lists the 25 most-played artists in the group.

```js
const arcRows = (rows) => rows.sort((a, b) => b.plays - a.plays).slice(0, 25).map((d) => ({
  artist: nameOf(d.artist_id), plays: d.plays, first_year: d.first_year, last_year: d.last_year,
  years_active: d.years_active, peak_year: d.peak_year
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

## Remixers

Plays of tracks each artist remixed, next to plays of the original versions.

```js
const remixTotals = d3.rollups(remix, (v) => ({remix_plays: d3.sum(v, (d) => d.remix_plays), original_plays: d3.sum(v, (d) => d.original_plays)}), (d) => d.artist_id)
  .map(([id, t]) => ({remixer: nameOf(id), ...t}))
  .sort((a, b) => b.remix_plays - a.remix_plays).slice(0, 25);
```

```js
Inputs.table(remixTotals)
```
