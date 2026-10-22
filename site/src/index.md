# music-story

```js
const year = FileAttachment("data/year.json").json();
const clock = FileAttachment("data/clock.json").json();
```

## Plays per year

```js
Plot.plot({
  x: {label: "Year", tickFormat: "d"},
  y: {label: "Plays", grid: true},
  marks: [Plot.barY(year, {x: "year", y: "plays"}), Plot.ruleY([0])]
})
```

```js
Inputs.table(year)
```

## When I listen

```js
const byCell = d3.rollups(clock, (v) => d3.sum(v, (d) => d.plays), (d) => d.weekday, (d) => d.hour)
  .flatMap(([weekday, hours]) => hours.map(([hour, plays]) => ({weekday, hour, plays})));
const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
```

```js
Plot.plot({
  x: {label: "Hour", tickFormat: "d"},
  y: {label: null, domain: [1, 2, 3, 4, 5, 6, 7], tickFormat: (d) => days[d - 1]},
  color: {legend: true, label: "Plays"},
  marks: [Plot.cell(byCell, {x: "hour", y: "weekday", fill: "plays", inset: 0.5})]
})
```
