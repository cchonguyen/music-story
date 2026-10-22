# Places

```js
const country = FileAttachment("data/country_year.json").json();
const known = country.filter((d) => d.country !== "unknown");
const unknown = country.filter((d) => d.country === "unknown");
```

## Plays per country per year

Countries with a known location: the 8 most played overall, the rest grouped as "other".

```js
const top = d3.groupSort(known, (v) => -d3.sum(v, (d) => d.plays), (d) => d.country).slice(0, 8);
const grouped = d3.rollups(known, (v) => d3.sum(v, (d) => d.plays), (d) => d.year, (d) => top.includes(d.country) ? d.country : "other")
  .flatMap(([year, cs]) => cs.map(([c, plays]) => ({year, country: c, plays})));
```

```js
Plot.plot({
  x: {label: "Year", tickFormat: "d"},
  y: {label: "Plays", grid: true},
  color: {legend: true},
  marks: [Plot.barY(grouped, {x: "year", y: "plays", fill: "country"}), Plot.ruleY([0])]
})
```

<!-- story: places -->

## Unknown location

Plays with no country on record, shown separately.

```js
Plot.plot({
  x: {label: "Year", tickFormat: "d"},
  y: {label: "Plays with unknown country", grid: true},
  marks: [Plot.barY(unknown, {x: "year", y: "plays"}), Plot.ruleY([0])]
})
```
