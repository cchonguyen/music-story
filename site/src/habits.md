# Habits

```js
const clock = FileAttachment("data/clock.json").json();
const sessions = FileAttachment("data/sessions_year.json").json();
const skip = FileAttachment("data/skip_rate.json").json();
const platform = FileAttachment("data/platform_year.json").json();
const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
```

## Weekday and hour

Plays by local weekday and hour for the chosen year.

```js
const years = ["All", ...[...new Set(clock.map((d) => d.year))].sort((a, b) => b - a)];
const pickedYear = view(Inputs.select(years, {label: "Year"}));
```

```js
const cells = d3.rollups(clock.filter((d) => pickedYear === "All" || d.year === pickedYear), (v) => d3.sum(v, (d) => d.plays), (d) => d.weekday, (d) => d.hour)
  .flatMap(([weekday, hs]) => hs.map(([hour, plays]) => ({weekday, hour, plays})));
```

```js
Plot.plot({
  x: {label: "Hour", tickFormat: "d"},
  y: {label: null, domain: [1, 2, 3, 4, 5, 6, 7], tickFormat: (d) => days[d - 1]},
  color: {legend: true, label: "Plays"},
  marks: [Plot.cell(cells, {x: "hour", y: "weekday", fill: "plays", inset: 0.5})]
})
```

<!-- story: weekly rhythm -->

## Sessions per year

Number of sessions, then the median and 90th percentile length in minutes.

```js
Plot.plot({
  x: {label: "Year", tickFormat: "d"},
  y: {label: "Sessions", grid: true},
  marks: [Plot.barY(sessions, {x: "year", y: "sessions"}), Plot.ruleY([0])]
})
```

```js
Plot.plot({
  x: {label: "Year", tickFormat: "d"},
  y: {label: "Minutes", grid: true},
  color: {legend: true, domain: ["median", "p90"]},
  marks: [
    Plot.line(sessions, {x: "year", y: "median_minutes", stroke: () => "median", marker: "dot"}),
    Plot.line(sessions, {x: "year", y: "p90_minutes", stroke: () => "p90", marker: "dot"}),
    Plot.ruleY([0])
  ]
})
```

## Skip rate

Skips as a share of skips plus Spotify plays, from 2012 on.

```js
Plot.plot({
  x: {label: "Year", tickFormat: "d"},
  y: {label: "Skip rate", grid: true, tickFormat: "%"},
  marks: [Plot.lineY(skip, {x: "year", y: "skip_rate", marker: "dot"}), Plot.ruleY([0])]
})
```

## Platform share

```js
Plot.plot({
  x: {label: "Year", tickFormat: "d"},
  y: {label: "Share of plays", grid: true, tickFormat: "%"},
  color: {legend: true},
  marks: [Plot.barY(platform, Plot.normalizeY("sum", {x: "year", y: "plays", fill: "platform_family"})), Plot.ruleY([0])]
})
```
