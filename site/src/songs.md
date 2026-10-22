# Songs

```js
const trackYear = FileAttachment("data/track_year.json").json();
const binge = FileAttachment("data/binge.json").json();
const songAge = FileAttachment("data/song_age.json").json();
const trackLabel = FileAttachment("data/track_label.json").json();
const artistLabel = FileAttachment("data/artist_label.json").json();
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
Inputs.table(
  trackYear.filter((d) => d.year === pickedYear && d.rank <= 10).sort((a, b) => a.rank - b.rank)
    .map((d) => ({rank: d.rank, track: trackName(d.track_id), artist: artistOf(d.track_id), plays: d.plays}))
)
```

<!-- story: top tracks -->

## Binges

Tracks whose busiest 14 days ran far above their usual rate (at least 15 plays in that window).

```js
Inputs.table(
  binge.filter((d) => d.window_plays >= 15).sort((a, b) => b.rate_ratio - a.rate_ratio).slice(0, 20)
    .map((d) => ({track: trackName(d.track_id), artist: artistOf(d.track_id), window_start: d.window_start,
      window_plays: d.window_plays, lifetime_plays: d.lifetime_plays, rate_ratio: Math.round(d.rate_ratio * 10) / 10}))
)
```

<!-- story: binges -->

## Song age

Plays per year by song age (play year minus the song's first release year).

```js
Plot.plot({
  x: {label: "Year", tickFormat: "d"},
  y: {label: "Plays", grid: true},
  color: {legend: true, label: "Age in years", domain: ["0", "1-2", "3-5", "6-10", "11-20", "21+", "unknown"]},
  marks: [Plot.barY(songAge, {x: "year", y: "plays", fill: "age_bucket"}), Plot.ruleY([0])]
})
```
