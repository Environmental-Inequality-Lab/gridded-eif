/* Runtime configuration.
 *
 * The data base URL comes from catalog.json itself, which is fetched at
 * runtime rather than baked into a build. That is what lets a data refresh be
 * "run the pipeline, upload" with no site redeploy — new years and geographies
 * appear here without a code change.
 */

// Pinned. Upgrading is a deliberate edit, not something that drifts.
export const DUCKDB_VERSION = '1.29.0';
export const DUCKDB_CDN = `https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@${DUCKDB_VERSION}/+esm`;

const DEFAULT_CATALOG = 'https://d2l6ob0rkxsi9o.cloudfront.net/catalog.json';

/* ?catalog=<url> points the site at a different catalog — a locally built one
 * during development, or a staging copy before publishing. The data URLs still
 * come from inside that catalog, so this swaps the manifest without touching
 * anything else. */
export const CATALOG_URL =
  new URLSearchParams(window.location.search).get('catalog') || DEFAULT_CATALOG;

/* Base path, derived from where the page is actually served.
 * The site lives at <org>.github.io/<repo>/ today and moves to a path under the
 * EIL domain later — both are subpaths, never a domain root. Deriving this at
 * runtime means the move needs no rebuild and no config edit. */
export const BASE = (() => {
  const p = window.location.pathname;
  return p.endsWith('/') ? p : p.slice(0, p.lastIndexOf('/') + 1);
})();

export const SITE = {
  name: 'Gridded EIF Data Explorer',
  org: 'Environmental Inequality Lab',
  orgUrl: 'https://environmental-inequality-lab.org',
  repo: 'https://github.com/Environmental-Inequality-Lab/gridded-eif',
  author: 'Grant M. Seiter',
  // TODO: replace with the real personal site before the next deploy.
  authorUrl: 'https://environmental-inequality-lab.org',
  // Public address of this site, used in the citation. Update if the site moves
  // to a path under the EIL domain.
  url: 'https://environmental-inequality-lab.github.io/gridded-eif/',
};
