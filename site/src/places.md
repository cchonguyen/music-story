# Places

Physical listening footprint (`plays.country` and 48-hour neighbor imputation) alongside your **Musical Passport** (`dim_artist.country` from MusicBrainz, tracking where the artists you listen to originate).

```js
const country = await FileAttachment("data/country_year.json").json();
const passport = await FileAttachment("data/artist_passport.json").json();
const known = country.filter((d) => d.country !== "unknown");
const unknown = country.filter((d) => d.country === "unknown");
```

## Plays per country per year & Imputation Provenance

Countries with a known location: the 8 most played overall, the rest grouped as "other". Toggle **Direct vs. Imputed Provenance** to inspect plays where a redacted `ZZ` country code was recovered from matching known neighbors within 48 hours (`imputed_plays`).

```js
const placeMode = view(Inputs.radio(
  ["By Country (Top 8 + Other)", "Direct vs. Imputed Provenance"],
  {label: "Location view", value: "By Country (Top 8 + Other)"}
));
```

```js
const top = d3.groupSort(known, (v) => -d3.sum(v, (d) => d.plays), (d) => d.country).slice(0, 8);
const grouped = d3.rollups(known, (v) => d3.sum(v, (d) => d.plays), (d) => d.year, (d) => top.includes(d.country) ? d.country : "other")
  .flatMap(([year, cs]) => cs.map(([c, plays]) => ({year, country: c, plays})));

const provenanceByYear = d3.rollups(
  known,
  (v) => ({
    direct: d3.sum(v, (d) => d.plays - (d.imputed_plays ?? 0)),
    imputed: d3.sum(v, (d) => d.imputed_plays ?? 0)
  }),
  (d) => d.year
).flatMap(([year, p]) => [
  {year, provenance: "Directly Reported Country", plays: p.direct},
  {year, provenance: "Imputed from 48h Neighbors (ZZ)", plays: p.imputed}
]);
```

```js
placeMode === "By Country (Top 8 + Other)"
  ? Plot.plot({
      x: {label: "Year", tickFormat: "d"},
      y: {label: "Plays", grid: true},
      color: {legend: true},
      marks: [Plot.barY(grouped, {x: "year", y: "plays", fill: "country", tip: true}), Plot.ruleY([0])]
    })
  : Plot.plot({
      x: {label: "Year", tickFormat: "d"},
      y: {label: "Plays with known country", grid: true},
      color: {
        legend: true,
        domain: ["Directly Reported Country", "Imputed from 48h Neighbors (ZZ)"],
        range: ["#2563eb", "#f59e0b"]
      },
      marks: [Plot.barY(provenanceByYear, {x: "year", y: "plays", fill: "provenance", tip: true}), Plot.ruleY([0])]
    })
```

```js
const countrySummaryRows = d3.rollups(
  known,
  (v) => ({
    plays: d3.sum(v, (d) => d.plays),
    direct_plays: d3.sum(v, (d) => d.plays - (d.imputed_plays ?? 0)),
    imputed_plays: d3.sum(v, (d) => d.imputed_plays ?? 0),
    active_years: v.length,
    first_year: d3.min(v, (d) => d.year),
    last_year: d3.max(v, (d) => d.year)
  }),
  (d) => d.country
)
  .map(([country, s]) => ({country, ...s}))
  .sort((a, b) => b.plays - a.plays);
```

```js
Inputs.table(countrySummaryRows, {format: {first_year: String, last_year: String}, rows: 10})
```

<!-- story: places -->

## Musical Passport: Where the Music Comes From (`dim_artist.country`)

While `plays.country` records where you physically were when listening, MusicBrainz records each artist's home country (`dim_artist.country`: `US`, `GB`, `DE`, `KR`, `JP`, `VN`...). Compare how the geographic origin of your artists evolved over 19.5 years.

```js
const passportScale = view(Inputs.radio(["100% Share of Known-Origin Plays", "Absolute Plays (Including Unknown Origin)"], {
  label: "Artist origin scale",
  value: "100% Share of Known-Origin Plays"
}));
```

```js
const artistOriginRows = d3.rollups(
  passport.filter((d) => passportScale.startsWith("Absolute") || d.artist_country !== "unknown"),
  (v) => d3.sum(v, (d) => d.plays),
  (d) => d.year,
  (d) => d.artist_country
).flatMap(([year, cs]) => cs.map(([artist_country, plays]) => ({year, artist_country, plays})));

const totalPassportPlays = d3.sum(artistOriginRows, (d) => d.plays);
const passportOriginTable = d3.rollups(
  artistOriginRows,
  (v) => {
    const plays = d3.sum(v, (d) => d.plays);
    return {
      plays,
      share: `${((plays / (totalPassportPlays || 1)) * 100).toFixed(1)}%`,
      active_years: v.length
    };
  },
  (d) => d.artist_country
)
  .map(([artist_country, s]) => ({artist_country, ...s}))
  .sort((a, b) => b.plays - a.plays);
```

```js
passportScale.startsWith("100%")
  ? Plot.plot({
      x: {label: "Year", tickFormat: "d"},
      y: {label: "Share of plays by artist home country", grid: true, tickFormat: "%"},
      color: {legend: true},
      marks: [
        Plot.barY(artistOriginRows, Plot.normalizeY("sum", {x: "year", y: "plays", fill: "artist_country", tip: true})),
        Plot.ruleY([0])
      ]
    })
  : Plot.plot({
      x: {label: "Year", tickFormat: "d"},
      y: {label: "Plays by artist home country", grid: true},
      color: {legend: true},
      marks: [
        Plot.barY(artistOriginRows, {x: "year", y: "plays", fill: "artist_country", tip: true}),
        Plot.ruleY([0])
      ]
    })
```

```js
Inputs.table(passportOriginTable, {rows: 10})
```

### Travel Resonance (International Trips vs. Artist Origins)

Plays recorded while physically outside the US (`JP`, `FR`, `CA`), broken down by the artist's origin country.

```js
const travelRows = d3.rollups(
  passport.filter((d) => d.listener_country !== "US" && d.listener_country !== "unknown"),
  (v) => d3.sum(v, (d) => d.plays),
  (d) => `${d.listener_country} (${d.year})`,
  (d) => d.artist_country
).flatMap(([trip, origins]) => {
  const total = d3.sum(origins, (o) => o[1]);
  return origins
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4)
    .map(([artist_country, plays]) => ({
      trip,
      artist_origin: artist_country,
      plays,
      share_of_trip: `${((plays / (total || 1)) * 100).toFixed(1)}%`
    }));
});
```

```js
Inputs.table(travelRows)
```

## Unknown location

Plays with no country on record (such as Last.fm-only years and unrecoverable `ZZ` blocks), shown separately.

```js
Plot.plot({
  x: {label: "Year", tickFormat: "d"},
  y: {label: "Plays with unknown country", grid: true},
  marks: [Plot.barY(unknown, {x: "year", y: "plays", fill: "#64748b", tip: true}), Plot.ruleY([0])]
})
```

```js
Inputs.table(
  unknown
    .slice()
    .sort((a, b) => b.year - a.year)
    .map((d) => ({year: d.year, unknown_country_plays: d.plays})),
  {format: {year: String}, rows: 10}
)
```
