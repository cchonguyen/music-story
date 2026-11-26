# Habits

Weekly listening rhythms, **10m / 20m / 30m session gap sensitivity**, **Intentionality vs. Shuffle Autopilot**, the **Skip Survival & Impatience Curve**, and the **Circadian BPM Heartbeat** powered by octave-corrected Deezer tempo and loudness telemetry.

```js
const clock = await FileAttachment("data/clock.json").json();
const sessions = await FileAttachment("data/sessions_year.json").json();
const skip = await FileAttachment("data/skip_rate.json").json();
const platform = await FileAttachment("data/platform_year.json").json();
const intentSkip = await FileAttachment("data/intent_skip.json").json();
const tempoPulse = await FileAttachment("data/tempo_pulse.json").json();
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
  color: {legend: true, scheme: "YlGnBu", label: "Plays"},
  marks: [Plot.cell(cells, {x: "hour", y: "weekday", fill: "plays", inset: 0.5, tip: true})]
})
```

```js
const habitDayRows = d3.rollups(
  cells,
  (v) => {
    const plays = d3.sum(v, (d) => d.plays);
    const peak = d3.greatest(v, (d) => d.plays);
    return {
      plays,
      peak_hour: peak ? `${String(peak.hour).padStart(2, "0")}:00` : "—",
      peak_hour_plays: peak ? peak.plays : 0
    };
  },
  (d) => d.weekday
)
  .sort((a, b) => a[0] - b[0])
  .map(([w, s]) => ({weekday: days[w - 1], ...s}));
```

```js
Inputs.table(habitDayRows, {rows: 7})
```

<!-- story: weekly rhythm -->

## Sessions per year & Gap Threshold Sensitivity (10m vs. 20m vs. 30m)

The baseline pipeline defines a new session after a **20-minute inactivity gap**, while also recording sensitivity flags for **10-minute** (`sessions_10`) and **30-minute** (`sessions_30`) gaps. Toggle the sensitivity overlay to see how session volume shifts under stricter or looser gap assumptions.

```js
const sessionViewMode = view(Inputs.radio(
  ["Compare 10m / 20m / 30m Gap Thresholds", "20m Baseline Bars Only"],
  {label: "Session gap view", value: "Compare 10m / 20m / 30m Gap Thresholds"}
));
```

```js
const sessionSensitivityLines = sessions.flatMap((d) => [
  {year: d.year, threshold: "10-min gap (strict)", count: d.sessions_10},
  {year: d.year, threshold: "20-min gap (baseline)", count: d.sessions},
  {year: d.year, threshold: "30-min gap (relaxed)", count: d.sessions_30}
]);
```

```js
sessionViewMode === "20m Baseline Bars Only"
  ? Plot.plot({
      x: {label: "Year", tickFormat: "d"},
      y: {label: "Sessions", grid: true},
      marks: [Plot.barY(sessions, {x: "year", y: "sessions", fill: "#2563eb", tip: true}), Plot.ruleY([0])]
    })
  : Plot.plot({
      x: {label: "Year", tickFormat: "d"},
      y: {label: "Sessions", grid: true},
      color: {
        legend: true,
        domain: ["10-min gap (strict)", "20-min gap (baseline)", "30-min gap (relaxed)"],
        range: ["#f59e0b", "#2563eb", "#0d9488"]
      },
      marks: [
        Plot.barY(sessions, {x: "year", y: "sessions", fill: "#2563eb", fillOpacity: 0.18}),
        Plot.lineY(sessionSensitivityLines, {x: "year", y: "count", stroke: "threshold", strokeWidth: 2.2, marker: "dot", tip: true}),
        Plot.ruleY([0])
      ]
    })
```

```js
Plot.plot({
  x: {label: "Year", tickFormat: "d"},
  y: {label: "Minutes", grid: true},
  color: {legend: true, domain: ["median", "p90"]},
  marks: [
    Plot.line(sessions, {x: "year", y: "median_minutes", stroke: () => "median", marker: "dot", tip: true}),
    Plot.line(sessions, {x: "year", y: "p90_minutes", stroke: () => "p90", marker: "dot", tip: true}),
    Plot.ruleY([0])
  ]
})
```

```js
Inputs.table(
  sessions
    .slice()
    .sort((a, b) => b.year - a.year)
    .map((d) => ({
      year: d.year,
      sessions_10m: d.sessions_10,
      sessions_20m: d.sessions,
      sessions_30m: d.sessions_30,
      median_min: Math.round(d.median_minutes * 10) / 10,
      p90_min: Math.round(d.p90_minutes * 10) / 10
    })),
  {format: {year: String}, rows: 10}
)
```

## Intentionality vs. Algorithmic Autopilot & The Skip Survival Curve

Using `plays.shuffle`, `plays.reason_start` (`clickrow` / `playbtn`), and `skips.ms_played`, inspect how much of your listening is deliberately hand-picked versus shuffle autopilot, and at what exact second (`0–5s`, `5–15s`, `15–30s`) skips occur.

```js
const intentLens = view(Inputs.radio(
  [
    "Intentionality Share (Hand-Picked vs. Flow vs. Shuffle)",
    "Skip Timing & Impatience Breakdown (0–5s vs. 5–15s vs. 15–30s)"
  ],
  {label: "Behavioral lens", value: "Intentionality Share (Hand-Picked vs. Flow vs. Shuffle)"}
));
```

```js
const skipTimingByYear = d3.rollups(
  intentSkip,
  (v) => ({
    under5: d3.sum(v, (d) => d.skip_under_5s),
    mid5_15: d3.sum(v, (d) => d.skip_5_to_15s),
    late15_30: d3.sum(v, (d) => d.skip_15_to_30s)
  }),
  (d) => d.year
).flatMap(([year, s]) => [
  {year, window: "Instant Rejection (0–5s)", skips: s.under5},
  {year, window: "Intro Check (5–15s)", skips: s.mid5_15},
  {year, window: "Verse Bailout (15–30s)", skips: s.late15_30}
]);
```

```js
intentLens.startsWith("Intentionality")
  ? Plot.plot({
      x: {label: "Year", tickFormat: "d"},
      y: {label: "Share of Spotify plays", grid: true, tickFormat: "%"},
      color: {
        legend: true,
        domain: ["Hand-Picked (Click/Play)", "Album / Queue Flow", "Shuffle Autopilot"],
        range: ["#2563eb", "#0d9488", "#f59e0b"]
      },
      marks: [
        Plot.barY(intentSkip, Plot.normalizeY("sum", {x: "year", y: "plays", fill: "intent_mode", tip: true})),
        Plot.ruleY([0])
      ]
    })
  : Plot.plot({
      x: {label: "Year", tickFormat: "d"},
      y: {label: "Skipped events", grid: true},
      color: {
        legend: true,
        domain: ["Instant Rejection (0–5s)", "Intro Check (5–15s)", "Verse Bailout (15–30s)"],
        range: ["#dc2626", "#f59e0b", "#6366f1"]
      },
      marks: [
        Plot.barY(skipTimingByYear, {x: "year", y: "skips", fill: "window", tip: true}),
        Plot.ruleY([0])
      ]
    })
```

```js
Inputs.table(
  intentSkip
    .slice()
    .sort((a, b) => b.year - a.year || b.plays - a.plays)
    .map((d) => ({
      year: d.year,
      intent_mode: d.intent_mode,
      plays: d.plays,
      skips: d.skips,
      skip_0_5s: d.skip_under_5s,
      skip_5_15s: d.skip_5_to_15s,
      skip_15_30s: d.skip_15_to_30s,
      avg_completion: `${(d.avg_completion * 100).toFixed(1)}%`
    })),
  {format: {year: String}, rows: 10}
)
```

## Circadian BPM Heartbeat & Session Energy Arc

Using octave-corrected Deezer `bpm` (`bpm > 175` halved to correct beat-detector double-time outliers) and audio `gain` from `enr_deezer_track`, trace how your average musical tempo and interquartile range (`P25–P75`) shift across the 24-hour clock or across track depth within a session (`Opener #1` to `Track #15+`).

```js
const tempoAxis = view(Inputs.radio(
  ["Circadian Clock (Hour 0–23)", "Session Choreography (Track Index 1–15)", "Longitudinal Tempo by Year"],
  {label: "Tempo dimension", value: "Circadian Clock (Hour 0–23)"}
));
```

```js
const activeTempoType = tempoAxis.startsWith("Circadian")
  ? "hour"
  : tempoAxis.startsWith("Session")
  ? "session_index"
  : "year";
const tempoRows = tempoPulse.filter((d) => d.bucket_type === activeTempoType);
```

```js
Plot.plot({
  height: 270,
  x: {
    label:
      activeTempoType === "hour"
        ? "Local Hour of Day (0–23)"
        : activeTempoType === "session_index"
        ? "Track Position in Session (1 = Opener, 15 = 15+)"
        : "Year",
    tickFormat: "d"
  },
  y: {label: "Tempo (BPM, octave-corrected)", grid: true},
  marks: [
    Plot.areaY(tempoRows, {x: "bucket", y1: "p25_bpm", y2: "p75_bpm", fill: "#0284c7", fillOpacity: 0.2}),
    Plot.lineY(tempoRows, {x: "bucket", y: "avg_bpm", stroke: "#0284c7", strokeWidth: 2.5, marker: "dot", tip: true})
  ]
})
```

```js
Inputs.table(
  tempoRows.map((d) => ({
    bucket: activeTempoType === "hour" ? `${String(d.bucket).padStart(2, "0")}:00` : String(d.bucket),
    plays: d.plays,
    avg_bpm: d.avg_bpm,
    p25_bpm: d.p25_bpm,
    p75_bpm: d.p75_bpm,
    avg_gain_db: d.avg_gain
  })),
  {rows: 10}
)
```

## Skip rate

Skips as a share of skips plus Spotify plays, from 2012 on.

```js
Plot.plot({
  x: {label: "Year", tickFormat: "d"},
  y: {label: "Skip rate", grid: true, tickFormat: "%"},
  marks: [Plot.lineY(skip, {x: "year", y: "skip_rate", marker: "dot", tip: true}), Plot.ruleY([0])]
})
```

```js
Inputs.table(
  skip
    .slice()
    .sort((a, b) => b.year - a.year)
    .map((d) => ({
      year: d.year,
      spotify_plays: d.spotify_plays,
      skips: d.skips,
      skip_rate: `${(d.skip_rate * 100).toFixed(1)}%`
    })),
  {format: {year: String}, rows: 10}
)
```

## Platform share

```js
Plot.plot({
  x: {label: "Year", tickFormat: "d"},
  y: {label: "Share of plays", grid: true, tickFormat: "%"},
  color: {legend: true},
  marks: [Plot.barY(platform, Plot.normalizeY("sum", {x: "year", y: "plays", fill: "platform_family", tip: true})), Plot.ruleY([0])]
})
```

```js
const platformTableRows = d3.rollups(
  platform,
  (v) => ({
    plays: d3.sum(v, (d) => d.plays),
    active_years: v.length,
    first_year: d3.min(v, (d) => d.year),
    last_year: d3.max(v, (d) => d.year)
  }),
  (d) => d.platform_family
)
  .map(([platform_family, s]) => ({platform_family, ...s}))
  .sort((a, b) => b.plays - a.plays);
```

```js
Inputs.table(platformTableRows, {format: {first_year: String, last_year: String}, rows: 8})
```
