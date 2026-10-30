export interface SpecificationMutationEntry {
  readonly version: string;
  readonly timestamp: string;
  readonly summary: string;
  readonly affectedFiles: readonly string[];
}

export interface SpecificationBaseline {
  readonly appName: string;
  readonly version: string;
  readonly port: number;
  readonly seed: number;
  readonly featureManifest: readonly string[];
  readonly operationalRules: readonly string[];
  readonly genreParentResolutions: Readonly<Record<string, string>>;
  readonly mutationAuditLog: readonly SpecificationMutationEntry[];
}

export const SPECIFICATION_BASELINE: SpecificationBaseline = {
  appName: "music-story",
  version: "1.1.0",
  port: 3000,
  seed: 20260422,
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
  ],
  genreParentResolutions: {
    blues: "jazz",
    hardcore: "metal",
    reggae: "world",
    dub: "world",
    ska: "world"
  },
  mutationAuditLog: [
    {
      version: "1.0.0",
      timestamp: "2026-10-27T00:00:00Z",
      summary: "Initial repository import of cchonguyen/music-story (W0-W10b).",
      affectedFiles: [
        "pipeline/build_pipeline.py",
        "pipeline/site_data.py",
        "site/observablehq.config.js"
      ]
    },
    {
      version: "1.1.0",
      timestamp: "2026-10-30T06:34:00Z",
      summary: "Configure root package.json dev server on port 3000, add deterministic data loader runtime bridge, normalize iOS/iPhone/iPad platform strings case-insensitively, and upgrade all 7 Observable Framework chapters with coverage overlays, artist lifeline matrices, binge scatter plots, sensitivity toggles, and the Explorer multi-view Remix Studio.",
      affectedFiles: [
        "src/specificationBaseline.ts",
        "site/src/specificationBaseline.js",
        "package.json",
        "site/package.json",
        "scripts/site_data_node.mjs",
        "sql/01_ingest.sql",
        "site/src/index.md",
        "site/src/artists.md",
        "site/src/songs.md",
        "site/src/genres.md",
        "site/src/habits.md",
        "site/src/places.md",
        "site/src/explorer.md"
      ]
    }
  ]
};
