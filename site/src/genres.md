# Genres

Weighted parent-genre and style distribution over 19.5 years, powered by the two-tier `W9b` umbrella disaggregation rule (continuous linear ramp $\alpha(\rho_P)$ on $[0.10, 0.30]$ and two-stage soft-hinge floor $g(x; 0.10, 0.20)$), with an explicit **Epistemic Coverage Toggle**, **Genre $\to$ Sub-Style $\to$ Artist Hierarchy**, **Local-Time Circadian Rhythm**, and **Song Genre X-Ray**.

```js
import {SPECIFICATION_BASELINE} from "./specificationBaseline.js";
const genreYear = await FileAttachment("data/genre_year.json").json();
const yearTotals = await FileAttachment("data/year.json").json();
const genreHierarchy = await FileAttachment("data/genre_hierarchy.json").json();
const genreClock = await FileAttachment("data/genre_clock.json").json();
const genreXray = await FileAttachment("data/genre_xray.json").json();
```

## Share of plays by parent genre

Tracks with several genres are split by weight (`1.0` track tag, `0.7` album tag, `0.5` artist tag, with umbrella self-tags disaggregated into co-occurring specific styles via $\alpha(\rho_P)$ and pruned via the two-stage $[0.10, 0.20]$ soft hinge). Compare **Classified Genres (100% Share)** against **Share of All Plays (Including Unclassified Residual)** or **Weighted Play Counts**.

```js
const genreMode = view(Inputs.radio(
  [
    "Classified Genres Only (100% Share)",
    "Share of All Plays (Include Unclassified Band)",
    "Weighted Play Counts"
  ],
  {label: "Coverage & scale mode", value: "Classified Genres Only (100% Share)"}
));
const parentYearBounds = d3.extent(genreYear, (d) => d.year);
const parentYearList = d3.range(parentYearBounds[0], parentYearBounds[1] + 1);
const parentFromYear = view(Inputs.select(parentYearList, {label: "From year", value: parentYearBounds[0], format: String}));
const parentToYear = view(Inputs.select(parentYearList, {label: "To year", value: parentYearBounds[1], format: String}));
```

```js
const loY = Math.min(parentFromYear, parentToYear);
const hiY = Math.max(parentFromYear, parentToYear);
const filteredGenreYear = genreYear.filter((d) => d.year >= loY && d.year <= hiY);
const filteredYearTotals = yearTotals.filter((d) => d.year >= loY && d.year <= hiY);
const totalPlaysByYear = new Map(filteredYearTotals.map((d) => [d.year, d.plays]));
const byYearParent = d3.rollups(
  filteredGenreYear,
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

const totalClassifiedWindow = d3.sum(filteredGenreYear, (d) => d.plays_weighted);
const totalAllWindow = Math.max(totalClassifiedWindow, d3.sum(filteredYearTotals, (d) => d.plays));
const parentSummaryTable = d3.rollups(
  filteredGenreYear,
  (v) => {
    const weighted = d3.sum(v, (d) => d.plays_weighted);
    const byY = d3.rollups(v, (vv) => d3.sum(vv, (x) => x.plays_weighted), (d) => d.year);
    const peak = d3.greatest(byY, (d) => d[1]);
    const stylesSet = new Set(v.map((d) => d.style));
    const specificWeight = d3.sum(v.filter((d) => d.style !== d.parent_genre), (d) => d.plays_weighted);
    return {
      weighted_plays: Math.round(weighted * 10) / 10,
      share_classified: `${((weighted / (totalClassifiedWindow || 1)) * 100).toFixed(1)}%`,
      share_all_plays: `${((weighted / (totalAllWindow || 1)) * 100).toFixed(1)}%`,
      sub_styles: stylesSet.size,
      specific_style_share: `${((specificWeight / (weighted || 1)) * 100).toFixed(1)}%`,
      peak_year: peak ? peak[0] : null
    };
  },
  (d) => d.parent_genre
)
  .map(([parent_genre, stats]) => ({parent_genre, ...stats}))
  .sort((a, b) => b.weighted_plays - a.weighted_plays);
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

```js
Inputs.table(parentSummaryTable, {
  format: {peak_year: (d) => (d == null ? "—" : String(d))},
  rows: 15
})
```

<!-- story: genres -->

## Styles within a parent genre

Drill into any parent genre to inspect how its individual sub-styles shift over time and how much listening resolves to specific sub-styles versus the residual parent umbrella.

```js
const parents = [...new Set(genreYear.map((d) => d.parent_genre))].sort();
const parent = view(Inputs.select(parents, {label: "Parent genre"}));
const styleScale = view(Inputs.radio(["Weighted Plays", "100% Share within Parent Genre"], {
  label: "Style scale",
  value: "Weighted Plays"
}));
```

```js
const rawStyles = filteredGenreYear.filter((d) => d.parent_genre === parent);
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

const parentTotalWeight = d3.sum(rawStyles, (d) => d.plays_weighted);
const styleSummaryRows = d3.rollups(
  rawStyles,
  (v) => {
    const w = d3.sum(v, (d) => d.plays_weighted);
    const peak = d3.greatest(v, (d) => d.plays_weighted);
    return {
      weighted_plays: Math.round(w * 10) / 10,
      share_of_parent: `${((w / (parentTotalWeight || 1)) * 100).toFixed(1)}%`,
      tier: v[0].style === parent ? "Umbrella Residual" : "Specific Sub-Style",
      first_year: d3.min(v, (d) => d.year),
      last_year: d3.max(v, (d) => d.year),
      peak_year: peak ? peak.year : null
    };
  },
  (d) => d.style
)
  .map(([style, stats]) => ({parent_genre: parent, style, ...stats}))
  .sort((a, b) => b.weighted_plays - a.weighted_plays);
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

```js
Inputs.table(styleSummaryRows, {
  format: {
    first_year: String,
    last_year: String,
    peak_year: (d) => (d == null ? "—" : String(d))
  },
  rows: 15
})
```

## Genre $\to$ Sub-Style $\to$ Artist Hierarchy Breakdown

Explore which artists anchor each sub-style within the selected parent genre (`mart_genre_hierarchy`).

```js
const hierarchyStylesForParent = [
  "All Sub-Styles",
  ...[...new Set(genreHierarchy.filter((d) => d.parent_genre === parent).map((d) => d.style))].sort()
];
const pickedHierarchyStyle = view(Inputs.select(hierarchyStylesForParent, {
  label: `Sub-style in ${parent}`,
  value: "All Sub-Styles"
}));
```

```js
const hierarchyFiltered = genreHierarchy
  .filter((d) => d.parent_genre === parent && (pickedHierarchyStyle === "All Sub-Styles" || d.style === pickedHierarchyStyle))
  .sort((a, b) => b.plays_weighted - a.plays_weighted);

const topHierarchyChartRows = hierarchyFiltered.slice(0, 18).map((d) => ({
  ...d,
  artist_label: `${d.artist} (${d.style})`
}));
```

```js
Plot.plot({
  marginLeft: 210,
  height: Math.max(220, topHierarchyChartRows.length * 24 + 50),
  x: {label: "Weighted plays", grid: true},
  y: {label: null, domain: topHierarchyChartRows.map((d) => d.artist_label)},
  color: {legend: true, label: "Sub-style"},
  marks: [
    Plot.barX(topHierarchyChartRows, {
      y: "artist_label",
      x: "plays_weighted",
      fill: "style",
      tip: true
    }),
    Plot.ruleX([0])
  ]
})
```

```js
Inputs.table(
  hierarchyFiltered.map((d) => ({
    parent_genre: d.parent_genre,
    style: d.style,
    rank_in_style: d.artist_rank_in_style,
    artist: d.artist,
    plays: d.plays,
    plays_weighted: d.plays_weighted,
    listen_hours: d.listen_hours,
    tracks: d.tracks,
    style_share_of_parent: `${(d.style_share_of_parent * 100).toFixed(1)}%`,
    artist_share_of_style: `${(d.artist_share_of_style * 100).toFixed(1)}%`
  })),
  {rows: 15}
)
```

## Local-Time Circadian Rhythm by Genre (`started_at_local`)

How genre and sub-style preferences shift across the 24-hour local clock (`0..23` in the listener's local timezone at the moment of play), split by **All Days**, **Weekdays (Mon–Fri)**, and **Weekends (Sat–Sun)**.

```js
const clockDayType = view(Inputs.radio(
  new Map([
    ["All Days", "all"],
    ["Weekdays (Mon–Fri)", "weekday"],
    ["Weekends (Sat–Sun)", "weekend"]
  ]),
  {label: "Day type", value: "all"}
));
const clockLevel = view(Inputs.radio(
  ["All Parent Genres", `Sub-Styles in ${parent}`],
  {label: "Row dimension", value: "All Parent Genres"}
));
const clockNorm = view(Inputs.radio(
  ["Share of Genre's Daily Plays (%)", "Share of Each Hour's Plays (%)", "Weighted Play Counts"],
  {label: "Cell metric", value: "Share of Genre's Daily Plays (%)"}
));
```

```js
const clockRaw = genreClock.filter((d) => d.weekday_type === clockDayType);
const clockGrouped = d3.rollups(
  clockLevel === "All Parent Genres" ? clockRaw : clockRaw.filter((d) => d.parent_genre === parent),
  (v) => ({
    plays: d3.sum(v, (d) => d.plays),
    plays_weighted: d3.sum(v, (d) => d.plays_weighted),
    listen_hours: d3.sum(v, (d) => d.listen_hours)
  }),
  (d) => (clockLevel === "All Parent Genres" ? d.parent_genre : d.style),
  (d) => d.hour
);

const hourTotals = new Map();
for (const [, hrList] of clockGrouped) {
  for (const [hr, stats] of hrList) {
    hourTotals.set(hr, (hourTotals.get(hr) ?? 0) + stats.plays_weighted);
  }
}

const clockCells = clockGrouped.flatMap(([label, hrList]) => {
  const rowTotal = d3.sum(hrList, ([, s]) => s.plays_weighted);
  return hrList.map(([hour, s]) => ({
    label,
    hour,
    plays: s.plays,
    plays_weighted: s.plays_weighted,
    listen_hours: s.listen_hours,
    share_of_genre: rowTotal > 0 ? s.plays_weighted / rowTotal : 0,
    share_of_hour: (hourTotals.get(hour) ?? 0) > 0 ? s.plays_weighted / hourTotals.get(hour) : 0
  }));
});

const clockTableRows = clockGrouped
  .map(([label, hrList]) => {
    const rowTotal = d3.sum(hrList, ([, s]) => s.plays_weighted);
    const byHr = new Map(hrList.map(([h, s]) => [h, s.plays_weighted]));
    const sumRange = (lo, hi) => d3.sum(d3.range(lo, hi + 1), (h) => byHr.get(h) ?? 0);
    const peak = d3.greatest(hrList, ([, s]) => s.plays_weighted);
    return {
      genre_or_style: label,
      weighted_plays: Math.round(rowTotal * 10) / 10,
      peak_local_hour: peak ? `${String(peak[0]).padStart(2, "0")}:00` : "—",
      night_00_05: `${((sumRange(0, 5) / (rowTotal || 1)) * 100).toFixed(1)}%`,
      morning_06_11: `${((sumRange(6, 11) / (rowTotal || 1)) * 100).toFixed(1)}%`,
      afternoon_12_17: `${((sumRange(12, 17) / (rowTotal || 1)) * 100).toFixed(1)}%`,
      evening_18_23: `${((sumRange(18, 23) / (rowTotal || 1)) * 100).toFixed(1)}%`
    };
  })
  .sort((a, b) => b.weighted_plays - a.weighted_plays);
```

```js
Plot.plot({
  marginLeft: 135,
  height: Math.max(240, clockGrouped.length * 26 + 60),
  x: {label: "Local Hour of Day (0–23)", domain: d3.range(0, 24), tickFormat: "d"},
  y: {label: null, domain: clockTableRows.map((d) => d.genre_or_style)},
  color: {
    legend: true,
    scheme: "YlGnBu",
    label: clockNorm,
    tickFormat: clockNorm.includes("(%)") ? "%" : undefined
  },
  marks: [
    Plot.cell(clockCells, {
      x: "hour",
      y: "label",
      fill:
        clockNorm === "Share of Genre's Daily Plays (%)"
          ? "share_of_genre"
          : clockNorm === "Share of Each Hour's Plays (%)"
          ? "share_of_hour"
          : "plays_weighted",
      inset: 0.5,
      tip: true
    })
  ]
})
```

```js
Inputs.table(clockTableRows, {rows: 15})
```

## Song Genre X-Ray & Tag Lineage Inspector

Inspect how individual songs are classified (`mart_genre_xray`), including their dominant tag specificity level (`track` vs. `album` vs. `artist`), primary style weight, co-occurring secondary styles, and whether broad umbrella tags (`electronic`, `edm`, `rock`, `indie`, `hip hop`, `rap`) were disaggregated into specific micro-styles.

```js
const xraySearch = view(Inputs.text({
  label: "Search song or artist",
  placeholder: "Title, artist, or secondary style...",
  submit: false
}));
const xrayParent = view(Inputs.select(["All", ...parents], {label: "Parent genre", value: "All"}));
const xrayStyleOptions = [
  "All",
  ...[
    ...new Set(
      genreXray
        .filter((d) => xrayParent === "All" || d.parent_genre === xrayParent)
        .map((d) => d.style)
    )
  ].sort()
];
const xrayStyle = view(Inputs.select(xrayStyleOptions, {label: "Primary sub-style", value: "All"}));
const xrayLevel = view(Inputs.select(["All", "track", "album", "artist"], {
  label: "Tag specificity level",
  value: "All"
}));
const xrayUmbrellaMode = view(Inputs.select(
  ["All Tracks", "Disaggregated to Specific Sub-Style", "Umbrella Retained (No Specific Sibling)"],
  {label: "Umbrella disaggregation status", value: "All Tracks"}
));
```

```js
const xrayQuery = xraySearch.trim().toLowerCase();
const filteredXray = genreXray
  .filter((d) => {
    if (xrayParent !== "All" && d.parent_genre !== xrayParent) return false;
    if (xrayStyle !== "All" && d.style !== xrayStyle) return false;
    if (xrayLevel !== "All" && d.level !== xrayLevel) return false;
    if (xrayUmbrellaMode === "Disaggregated to Specific Sub-Style" && d.style === d.parent_genre) return false;
    if (xrayUmbrellaMode === "Umbrella Retained (No Specific Sibling)" && d.style !== d.parent_genre) return false;
    if (!xrayQuery) return true;
    return (
      (d.title ?? "").toLowerCase().includes(xrayQuery) ||
      (d.artist ?? "").toLowerCase().includes(xrayQuery) ||
      (d.artist_norm ?? "").toLowerCase().includes(xrayQuery) ||
      (d.title_norm ?? "").toLowerCase().includes(xrayQuery) ||
      (d.secondary_styles ?? "").toLowerCase().includes(xrayQuery)
    );
  })
  .sort((a, b) => b.plays - a.plays || b.listen_hours - a.listen_hours);
```

```js
Inputs.table(
  filteredXray.slice(0, 500).map((d) => ({
    title: d.title,
    artist: d.artist,
    parent_genre: d.parent_genre,
    style: d.style,
    weight: `${(d.primary_weight * 100).toFixed(0)}%`,
    level: d.level,
    secondary_styles: d.secondary_styles || "—",
    umbrella_lineage: d.suppressed_umbrellas,
    plays: d.plays,
    hours: d.listen_hours,
    skip_rate: `${(d.skip_rate * 100).toFixed(1)}%`,
    peak_hour: `${String(d.peak_local_hour).padStart(2, "0")}:00`,
    country: d.top_country,
    active_years: `${d.first_year}–${d.last_year}`
  })),
  {rows: 20}
)
```
