# Genres

```js
const genreYear = await FileAttachment("data/genre_year.json").json();
const parentShare = d3.rollups(genreYear, (v) => d3.sum(v, (d) => d.plays_weighted), (d) => d.year, (d) => d.parent_genre)
  .flatMap(([year, ps]) => { const tot = d3.sum(ps, (p) => p[1]); return ps.map(([parent_genre, w]) => ({year, parent_genre, share: w / tot})); });
```

## Share of plays by parent genre

Each year sums to 100%. Tracks with several genres are split by weight.

```js
Plot.plot({
  x: {label: "Year", tickFormat: "d"},
  y: {label: "Share of weighted plays", grid: true, tickFormat: "%"},
  color: {legend: true},
  marks: [Plot.areaY(parentShare, {x: "year", y: "share", fill: "parent_genre"}), Plot.ruleY([0])]
})
```

<!-- story: genres -->

## Styles within a parent genre

```js
const parents = [...new Set(genreYear.map((d) => d.parent_genre))].sort();
const parent = view(Inputs.select(parents, {label: "Parent genre"}));
```

```js
const styles = genreYear.filter((d) => d.parent_genre === parent);
```

```js
Plot.plot({
  x: {label: "Year", tickFormat: "d"},
  y: {label: "Weighted plays", grid: true},
  color: {legend: true},
  marks: [Plot.areaY(styles, {x: "year", y: "plays_weighted", fill: "style"}), Plot.ruleY([0])]
})
```
