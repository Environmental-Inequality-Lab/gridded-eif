/* Fetches and interprets catalog.json.
 *
 * Everything the UI knows about datasets, dimensions, geographies, and years
 * comes from here. No dataset name, category value, or year range is hardcoded
 * in a component — if it were, publishing new data would require a site
 * rebuild, which is exactly what this architecture avoids.
 */

import { CATALOG_URL } from './config.js';

let cached = null;

export async function loadCatalog() {
  if (cached) return cached;
  const res = await fetch(CATALOG_URL);
  if (!res.ok) throw new Error(`catalog unavailable (HTTP ${res.status})`);
  cached = await res.json();
  return cached;
}

/** Geography levels that actually have data, in a sensible coarse-to-fine order. */
export function geographies(cat) {
  const order = ['nation', 'state', 'county', 'cbsa', 'czone', 'puma', 'zcta', 'tract', 'cd'];
  const present = new Set(cat.entries.map((e) => e.geography));
  return order
    .filter((g) => present.has(g))
    .map((g) => ({ id: g, ...(cat.geographies[g] || { label: g }) }));
}

export function datasets(cat) {
  return Object.entries(cat.datasets).map(([id, d]) => ({ id, ...d }));
}

/** Dimension definition, with its declared values and labels. */
export function dimension(cat, name) {
  const d = cat.dimensions[name];
  if (!d) return null;
  return {
    id: name,
    label: d.label || name,
    note: d.note,
    footnote: d.footnote,
    values: (d.values || []).map((v) => ({
      code: v.code,
      label: v.label ?? String(v.code),
      residual: !!v.residual,
    })),
  };
}

export function yearsFor(cat, dataset, geography) {
  return cat.entries
    .filter((e) => e.dataset === dataset && e.geography === geography)
    .map((e) => e.year)
    .sort((a, b) => a - b);
}

export function isPreliminary(cat, dataset, year) {
  return (cat.datasets[dataset]?.preliminary_years || []).includes(year);
}

export function entryUrl(cat, dataset, geography, year) {
  return cat.entries.find(
    (e) => e.dataset === dataset && e.geography === geography && e.year === year
  )?.url;
}

/** All-years file for a (dataset, geography), when one is published.
 *  Multi-year queries should use this: reading 25 per-year files means 25
 *  round trips, which dominates latency on a cold CDN edge. */
export function combinedUrl(cat, dataset, geography) {
  return (cat.combined || []).find(
    (c) => c.dataset === dataset && c.geography === geography
  )?.url;
}

/** Which measure to default to, per the published guidance.
 *  Post-processed below the population threshold, raw above it. */
export function defaultMeasure(cat, population) {
  const threshold = cat.measure_selection_population_threshold;
  if (population == null || threshold == null) {
    return Object.entries(cat.measures).find(([, m]) => m.default)?.[0] || 'n_noise_postprocessed';
  }
  return population > threshold ? 'n_noise' : 'n_noise_postprocessed';
}
