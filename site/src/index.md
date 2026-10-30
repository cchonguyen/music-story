# music-story

19.5 years of personal listening telemetry across Last.fm (Apr 2007–Oct 2026) and Spotify (Jul 2011–Oct 2026).

```js
import {SPECIFICATION_BASELINE} from "./specificationBaseline.js";
const year = await FileAttachment("data/year.json").json();
const clock = await FileAttachment("data/clock.json").json();

const totalPlays = d3.sum(year, (d) => d.plays);
const totalHours = Math.round(d3.sum(year, (d) => d.listen_hours));
const totalSessions = d3.sum(year, (d) => d.sessions);
const peakYearRow = d3.greatest(year, (d) => d.plays);
```

<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 1rem; padding: 0.85rem 0; border-top: 1px solid rgba(128,128,128,0.22); border-bottom: 1px solid rgba(128,128,128,0.22); margin-bottom: 1.5rem; font-variant-numeric: tabular-nums;">
  <div>
    <div style="font-size: 0.75rem; opacity: 0.68;">Total Verified Plays</div>
    <div style="font-size: 1.45rem; font-weight: 600;">${totalPlays.toLocaleString()}</div>
    <div style="font-size: 0.75rem; opacity: 0.65;">2007–2026 · v${SPECIFICATION_BASELINE.version}</div>
  </div>
  <div>
    <div style="font-size: 0.75rem; opacity: 0.68;">Cumulative Listening Time</div>
    <div style="font-size: 1.45rem; font-weight: 600;">${totalHours.toLocaleString()} hrs</div>
    <div style="font-size: 0.75rem; opacity: 0.65;">${(totalHours / 24).toFixed(1)} full 24h days</div>
  </div>
  <div>
    <div style="font-size: 0.75rem; opacity: 0.68;">Listening Sessions (20m gap)</div>
    <div style="font-size: 1.45rem; font-weight: 600;">${totalSessions.toLocaleString()}</div>
    <div style="font-size: 0.75rem; opacity: 0.65;">${(totalPlays / totalSessions).toFixed(1)} plays / session</div>
  </div>
  <div>
    <div style="font-size: 0.75rem; opacity: 0.68;">Peak Volume Year</div>
    <div style="font-size: 1.45rem; font-weight: 600;">${peakYearRow?.year ?? "—"}</div>
    <div style="font-size: 0.75rem; opacity: 0.65;">${(peakYearRow?.plays ?? 0).toLocaleString()} plays (${Math.round(peakYearRow?.listen_hours ?? 0)} hrs)</div>
  </div>
</div>

## Longitudinal Volume & Era Coverage Lens

 Because raw play counts mix **Last.fm-only years (2007–2010)**, **Spotify onboarding (Jul 2011)**, and **matched dual-source years (2022–2026)**, use the lens below to compare raw volume against normalized discovery rates and skip volume.

```js
const overviewLens = view(Inputs.radio(
  [
    "Plays & Era Regimes",
    "Listening Hours",
    "Discovery Velocity (per 1,000 Plays)",
    "Plays vs. Skips Stacked"
  ],
  {label: "View lens", value: "Plays & Era Regimes"}
));
const showRegimes = view(Inputs.toggle({label: "Show logging regime boundaries (2011 Spotify, 2022 Dual-Source)", value: true}));
```

```js
const regimeRules = showRegimes
  ? [
      Plot.ruleX([2010.5], {stroke: "#d97706", strokeDasharray: "4,4", strokeWidth: 1.5}),
      Plot.ruleX([2021.5], {stroke: "#0284c7", strokeDasharray: "4,4", strokeWidth: 1.5}),
      Plot.text(
        [
          {x: 2008.7, label: "Last.fm Only (2007–10)"},
          {x: 2016.0, label: "Spotify + Sparse LFM (2011–21)"},
          {x: 2024.0, label: "Dual-Source Twin Era (2022–26)"}
        ],
        {x: "x", y: () => 0, text: "label", dy: -8, frameAnchor: "top", fontSize: 10, fill: "currentColor", fillOpacity: 0.72}
      )
    ]
  : [];

const discoveryData = year.flatMap((d) => [
  {year: d.year, metric: "New artists / 1k plays", rate: (d.new_artists / d.plays) * 1000, raw: d.new_artists},
  {year: d.year, metric: "New tracks / 1k plays", rate: (d.new_tracks / d.plays) * 1000, raw: d.new_tracks}
]);

const playSkipStack = year.flatMap((d) => [
  {year: d.year, type: "Completed Plays", count: d.plays},
  {year: d.year, type: "Skips (<30s Spotify)", count: d.skips}
]);
```

```js
overviewLens === "Plays & Era Regimes"
  ? Plot.plot({
      marginTop: 28,
      x: {label: "Year", tickFormat: "d"},
      y: {label: "Plays", grid: true},
      marks: [
        Plot.barY(year, {x: "year", y: "plays", fill: "#2563eb", tip: true}),
        ...regimeRules,
        Plot.ruleY([0])
      ]
    })
  : overviewLens === "Listening Hours"
  ? Plot.plot({
      marginTop: 28,
      x: {label: "Year", tickFormat: "d"},
      y: {label: "Listening hours", grid: true},
      marks: [
        Plot.barY(year, {x: "year", y: "listen_hours", fill: "#0d9488", tip: true}),
        ...regimeRules,
        Plot.ruleY([0])
      ]
    })
  : overviewLens === "Discovery Velocity (per 1,000 Plays)"
  ? Plot.plot({
      marginTop: 28,
      x: {label: "Year", tickFormat: "d"},
      y: {label: "New entities per 1,000 plays", grid: true},
      color: {legend: true, domain: ["New artists / 1k plays", "New tracks / 1k plays"], range: ["#7c3aed", "#0284c7"]},
      marks: [
        Plot.lineY(discoveryData, {x: "year", y: "rate", stroke: "metric", strokeWidth: 2.2, marker: "dot", tip: true}),
        ...regimeRules,
        Plot.ruleY([0])
      ]
    })
  : Plot.plot({
      marginTop: 28,
      x: {label: "Year", tickFormat: "d"},
      y: {label: "Events (Plays + Skips)", grid: true},
      color: {legend: true, domain: ["Completed Plays", "Skips (<30s Spotify)"], range: ["#2563eb", "#f59e0b"]},
      marks: [
        Plot.barY(playSkipStack, {x: "year", y: "count", fill: "type", tip: true}),
        ...regimeRules,
        Plot.ruleY([0])
      ]
    })
```

## New artists & catalog breadth per year

Artists whose first play falls in that year alongside total distinct artists heard that year.

```js
const artistBreadth = year.flatMap((d) => [
  {year: d.year, kind: "First-time artists (New)", count: d.new_artists},
  {year: d.year, kind: "Returning artists", count: Math.max(0, d.artists - d.new_artists)}
]);
```

```js
Plot.plot({
  x: {label: "Year", tickFormat: "d"},
  y: {label: "Distinct artists heard", grid: true},
  color: {legend: true, domain: ["First-time artists (New)", "Returning artists"], range: ["#0ea5e9", "#64748b"]},
  marks: [
    Plot.barY(artistBreadth, {x: "year", y: "count", fill: "kind", tip: true}),
    Plot.ruleY([0])
  ]
})
```

<!-- story: overview narrative -->

## When I listen (19.5-Year Circadian Fingerprint)

```js
const byCell = d3.rollups(clock, (v) => d3.sum(v, (d) => d.plays), (d) => d.weekday, (d) => d.hour)
  .flatMap(([weekday, hours]) => hours.map(([hour, plays]) => ({weekday, hour, plays})));
const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
```

```js
Plot.plot({
  x: {label: "Local Hour (0–23)", tickFormat: "d"},
  y: {label: null, domain: [1, 2, 3, 4, 5, 6, 7], tickFormat: (d) => days[d - 1]},
  color: {legend: true, scheme: "YlGnBu", label: "Plays"},
  marks: [Plot.cell(byCell, {x: "hour", y: "weekday", fill: "plays", inset: 0.5, tip: true})]
})
```
