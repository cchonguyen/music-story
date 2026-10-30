# Genres

Weighted parent-genre and style distribution over 19.5 years, with an explicit **Epistemic Coverage Toggle** to inspect any unclassified/unenriched residual alongside the curated parent taxonomy (`blues -> jazz`, `hardcore -> metal`, `reggae/dub/ska -> world`).

```js
import {SPECIFICATION_BASELINE} from "./specificationBaseline.js";
const genreYear = await FileAttachment("data/genre_year.json").json();
const yearTotals = await FileAttachment("data/year.json").json();
```

## Share of plays by parent genre

Tracks with several genres are split by weight (`1.0` track tag, `0.7` album tag, `0.5` artist tag, filtered at $\ge 15\%$ share). Compare **Classified Genres (100% Share)** against **Share of All Plays (Including Unclassified Residual)** or **Weighted Play Counts**.

```js
const genreMode = view(Inputs.radio(
  [
    "Classified Genres Only (100% Share)",
    "Share of All Plays (Include Unclassified Band)",
    "Weighted Play Counts"
  ],
  {label: "Coverage & scale mode", value: "Classified Genres Only (100% Share)"}
));
```

```js
const totalPlaysByYear = new Map(yearTotals.map((d) => [d.year, d.plays]));
const byYearParent = d3.rollups(
  genreYear,
  (v) => d3.sum(v, (d) => d.plays_weighted),
  (d) => d.year,
  (d) => d.parent_genre
);

const parentSeries = byYearParent.flatMap(([year, ps]) => {
  const classifiedSum = d3.sum(ps, (p) => p[1]);
  const allPlays = Math.max(classifiedSum, totalPlaysByYear.get(year) ?? classifiedSum);
  const unclassified = Math.max(0, allPlays - classifiedSum);
  const rows = ps.map(([parent_genre, w]) => ({
    year,
    parent_genre,
    plays_weighted: w,
    share_classified: w / (classifiedSum || 1),
    share_all: w / (allPlays || 1)
  }));
  if (genreMode === "Share of All Plays (Include Unclassified Band)") {
    rows.push({
      year,
      parent_genre: "unclassified / pending enrichment",
      plays_weighted: unclassified,
      share_classified: 0,
      share_all: unclassified / (allPlays || 1)
    });
  }
  return rows;
});
```

```js
genreMode === "Classified Genres Only (100% Share)"
  ? Plot.plot({
      x: {label: "Year", tickFormat: "d"},
      y: {label: "Share of weighted plays", grid: true, tickFormat: "%"},
      color: {legend: true},
      marks: [Plot.areaY(parentSeries, {x: "year", y: "share_classified", fill: "parent_genre", tip: true}), Plot.ruleY([0])]
    })
  : genreMode === "Share of All Plays (Include Unclassified Band)"
  ? Plot.plot({
      x: {label: "Year", tickFormat: "d"},
      y: {label: "Share of total annual plays", grid: true, tickFormat: "%"},
      color: {legend: true},
      marks: [Plot.areaY(parentSeries, {x: "year", y: "share_all", fill: "parent_genre", tip: true}), Plot.ruleY([0])]
    })
  : Plot.plot({
      x: {label: "Year", tickFormat: "d"},
      y: {label: "Weighted plays", grid: true},
      color: {legend: true},
      marks: [Plot.areaY(parentSeries, {x: "year", y: "plays_weighted", fill: "parent_genre", tip: true}), Plot.ruleY([0])]
    })
```

<!-- story: genres -->

## Styles within a parent genre

Drill into any parent genre to inspect how its individual sub-styles shift over time.

```js
const parents = [...new Set(genreYear.map((d) => d.parent_genre))].sort();
const parent = view(Inputs.select(parents, {label: "Parent genre"}));
const styleScale = view(Inputs.radio(["Weighted Plays", "100% Share within Parent Genre"], {
  label: "Style scale",
  value: "Weighted Plays"
}));
```

```js
const rawStyles = genreYear.filter((d) => d.parent_genre === parent);
const styleYears = [...new Set(rawStyles.map((d) => d.year))].sort((a, b) => a - b);
const styleNames = [...new Set(rawStyles.map((d) => d.style))].sort();
const styleByYearMap = new Map(rawStyles.map((d) => [`${d.year}::${d.style}`, d.plays_weighted]));
const styles = styleYears.flatMap((year) => {
  const yearTotal = d3.sum(styleNames, (s) => styleByYearMap.get(`${year}::${s}`) ?? 0);
  return styleNames.map((style) => {
    const plays_weighted = styleByYearMap.get(`${year}::${style}`) ?? 0;
    return {
      year,
      parent_genre: parent,
      style,
      plays_weighted,
      share_parent: yearTotal > 0 ? plays_weighted / yearTotal : 0
    };
  });
});
```

```js
styleScale === "Weighted Plays"
  ? Plot.plot({
      x: {label: "Year", tickFormat: "d"},
      y: {label: "Weighted plays", grid: true},
      color: {legend: true},
      marks: [Plot.areaY(styles, {x: "year", y: "plays_weighted", fill: "style", tip: true}), Plot.ruleY([0])]
    })
  : Plot.plot({
      x: {label: "Year", tickFormat: "d"},
      y: {label: `Share of ${parent} plays`, domain: [0, 1], grid: true, tickFormat: "%"},
      color: {legend: true},
      marks: [
        Plot.areaY(styles, {x: "year", y: "share_parent", fill: "style", offset: "normalize", tip: true}),
        Plot.ruleY([0])
      ]
    })
```
