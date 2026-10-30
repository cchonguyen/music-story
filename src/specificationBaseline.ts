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
  version: "1.5.0",
  port: 3000,
  seed: 20260422,
  featureManifest: [
    "W0-W10 Core DuckDB & Observable Framework 7-Chapter Story Pipeline",
    "Root Dev Server & Single-Pass Cached Loader Bridge on 0.0.0.0:3000",
    "Overview Era Regime Overlays (2007-2010 Last.fm, 2011 Spotify, 2022+ Twin Match) & Discovery Velocity",
    "Artists Longitudinal Lifelines Matrix (Staples, Comebacks, Flashes), Underground Obscurity Index & Vanguard Score",
    "Songs Earworm Half-Life (Post-Binge Burnout vs. Canonized Anthems) & Normalized Song Age Nostalgia Lens",
    "Genres Coverage-Aware Streamgraph with Unclassified Enrichment Residual Toggle & Style Anatomy",
    "Habits Intentionality vs. Shuffle Autopilot, Skip Survival Curve, Circadian BPM Heartbeat & 10/20/30m Session Sensitivity",
    "Places Direct vs. Imputed Country Provenance & Musical Passport (Artist Origin Country vs. Travel Resonance)",
    "Explorer Multi-Tab Insights & Visual Remix Studio (Timeline & Slice Rhythm Heatmap, Top 15 & Intent, Sonic & Obscurity Scatter)",
    "Primary-URI-First Spotify Queue Ranking & Cross-Source ISRC Tail Pruning in pipeline/enrich_queue.py",
    "Case-Insensitive iOS / iPhone / iPad Platform Normalization in sql/01_ingest.sql",
    "Seamless subshell directory execution for Observable preview and build scripts",
    "Non-Destructive Invariant & Additive Data Association Protocol (preserves all raw telemetry while enabling additive merges, recalculations, and associations)",
    "AI Studio iframe WebSocket URL compatibility patch (URL.prototype.startsWith and WebSocket string URL normalization)"
  ],
  operationalRules: [
    "Data Preservation Invariant: Never destructively edit or delete any ingested listening data or historical raw records; all data transformations, normalizations, deduplications, and associations must be additive or non-destructive views/marts to maximize analytical fidelity.",
    "Serve Observable Framework preview on 0.0.0.0:3000 via root package.json scripts (cd site && npm run dev).",
    "Preserve exact site/src/data/*.sh loader filenames and mart schemas required by test_site_pages.py.",
    "Expose epistemic uncertainty (unclassified genre plays, unknown song ages, imputed countries, 10/20/30m session gaps).",
    "Propagate octave-corrected Deezer BPM/gain, Last.fm global listeners, MusicBrainz artist country/begin_year, and Spotify intent/shuffle signals without breaking core schema contracts.",
    "Prioritize Tier-1 primary URIs per (artist_norm, full_norm) in Spotify queue and anti-join resolved ISRCs from tail searches.",
    "Lock parent genre mappings: blues -> jazz, hardcore -> metal, reggae/dub/ska -> world.",
    "Match ios, iphone, and ipad platform strings case-insensitively in sql/01_ingest.sql.",
    "Normalize all client WebSocket instantiations to string URLs (and polyfill URL.prototype.startsWith/indexOf) to prevent iframe proxy TypeError."
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
      summary: "Initial baseline specification registration and case-insensitive iOS platform normalization.",
      affectedFiles: [
        "src/specificationBaseline.ts",
        "site/src/specificationBaseline.js",
        "sql/01_ingest.sql"
      ]
    },
    {
      version: "1.2.0",
      timestamp: "2026-10-30T06:45:00Z",
      summary: "Add 5 non-hallucinated visual insights (Earworm Half-Life, Intentionality & Skip Survival, Circadian BPM & Session Energy Arc, Underground Obscurity Index & Vanguard Score, Musical Passport), 4 pipeline/fetch optimizations (Primary-URI-first Spotify ranking, Cross-source ISRC tail pruning, Zero-cost telemetry propagation, Single-pass mart caching), and multi-tab Explorer Remix Studio on port 3000.",
      affectedFiles: [
        "src/specificationBaseline.ts",
        "site/src/specificationBaseline.js",
        "package.json",
        "site/package.json",
        "pipeline/enrich_queue.py",
        "pipeline/site_data.py",
        "sql/marts/10_simple.sql",
        "sql/marts/20_trap.sql",
        "sql/marts/40_explorer.sql",
        "scripts/generate_fixture_marts.py",
        "site/src/index.md",
        "site/src/artists.md",
        "site/src/songs.md",
        "site/src/genres.md",
        "site/src/habits.md",
        "site/src/places.md",
        "site/src/explorer.md"
      ]
    },
    {
      version: "1.3.0",
      timestamp: "2026-10-30T10:48:00Z",
      summary: "Update root package.json dev and build scripts to cd site && npm run dev/build for flawless observable CLI path resolution.",
      affectedFiles: [
        "src/specificationBaseline.ts",
        "site/src/specificationBaseline.js",
        "package.json"
      ]
    },
    {
      version: "1.4.0",
      timestamp: "2026-10-30T10:49:00Z",
      summary: "Formally enshrine the Non-Destructive Invariant and Additive Association Protocol in SPECIFICATION_BASELINE, ensuring raw listening telemetry is never destructively altered while permitting additive associations and recalculations.",
      affectedFiles: [
        "src/specificationBaseline.ts",
        "site/src/specificationBaseline.js",
        "docs/PROJECT.md"
      ]
    },
    {
      version: "1.5.0",
      timestamp: "2026-10-30T10:53:00Z",
      summary: "Polyfill URL.prototype.startsWith and normalize WebSocket constructor URLs to prevent TypeError in AI Studio iframe proxy.",
      affectedFiles: [
        "src/specificationBaseline.ts",
        "site/src/specificationBaseline.js",
        "site/observablehq.config.js",
        "scripts/uv_shim.sh",
        "site/node_modules/@observablehq/framework/dist/client/preview.js"
      ]
    }
  ]
};
