// Runtime ES module mirror of src/specificationBaseline.ts for Observable Framework pages
export const SPECIFICATION_BASELINE = {
  appName: "music-story",
  version: "1.1.0",
  port: 3000,
  seed: 20260422,
  eraRegimes: [
    { year: 2007, endYear: 2011, label: "Last.fm Only (2007–2010)" },
    { year: 2011, endYear: 2022, label: "Spotify Onboarding & Split Era (2011–2021)" },
    { year: 2022, endYear: 2026, label: "Matched Dual-Source Era (2022–2026)" }
  ],
  genreParentResolutions: {
    blues: "jazz",
    hardcore: "metal",
    reggae: "world",
    dub: "world",
    ska: "world"
  },
  featureManifest: [
    "W0-W10 Core DuckDB & Observable Framework 7-Chapter Story Pipeline",
    "Root Dev Server & Deterministic Loader Bridge on 0.0.0.0:3000",
    "Overview Era Regime Overlays (2007-2010 Last.fm, 2011 Spotify, 2022+ Twin Match) & Discovery Rates",
    "Artists Longitudinal Lifelines Matrix (Staples, Comebacks, Flashes) & Remixer Dual Comparison",
    "Songs Obsession Trajectory Scatter (14-Day Binge Rate Ratio vs Lifetime Plays) & Normalized Song Age",
    "Genres Coverage-Aware Streamgraph with Unclassified Enrichment Residual Toggle",
    "Habits 10m / 20m / 30m Session Gap Sensitivity Overlay & Weekday-Hour Rhythm Heatmap",
    "Places Direct vs Imputed Country Provenance Breakdown & Unknown Location Tracking",
    "Explorer Multi-View Remix Studio with Slice Rhythm Heatmap, Top Entities Pivot & Resilient Query Engine",
    "Case-Insensitive iOS / iPhone / iPad Platform Normalization in SQL Ingest"
  ],
  operationalRules: [
    "Serve Observable Framework preview on 0.0.0.0:3000 via root package.json scripts.",
    "Preserve exact site/src/data/*.sh loader filenames and mart schemas required by test_site_pages.py.",
    "Expose epistemic uncertainty (unclassified genre plays, unknown song ages, imputed countries, 10/20/30m session gaps).",
    "Lock parent genre mappings: blues -> jazz, hardcore -> metal, reggae/dub/ska -> world.",
    "Match ios, iphone, and ipad platform strings case-insensitively in sql/01_ingest.sql."
  ]
};
