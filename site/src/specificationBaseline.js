// Runtime ES module mirror of src/specificationBaseline.ts for Observable Framework pages
export const SPECIFICATION_BASELINE = {
  appName: "music-story",
  version: "1.5.0",
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
  ]
};
