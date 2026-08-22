/* Application state lives in the URL query string.
 *
 * Every selection — view, dataset, geography, place, year, measure, facets —
 * serialises here. That makes a view shareable, bookmarkable, citable, and
 * makes a bug report reproducible by pasting a link. It also means the back
 * button behaves the way people expect.
 *
 * Query params rather than paths: GitHub Pages has no server-side rewrite, so
 * path routing needs a 404.html redirect hack. A query string works at any base
 * path with no configuration, which matters because this site moves from
 * <org>.github.io/<repo>/ to a path under the EIL domain.
 */

import { useState, useEffect, useCallback } from './h.js';

export const DEFAULTS = {
  v: 'home',        // view
  d: 'ageracesex',  // dataset
  g: 'county',      // geography
  y: null,          // year (null = latest)
  m: null,          // measure (null = auto by population)
  p: null,          // place (geo_id)
  tab: 'table',
  mapMode: 'count',  // 'count' | 'share' — map colouring only
};

function read() {
  const sp = new URLSearchParams(window.location.search);
  const s = { ...DEFAULTS };
  for (const k of Object.keys(DEFAULTS)) if (sp.has(k)) s[k] = sp.get(k);
  if (s.y != null) s.y = Number(s.y);
  // Facet selections arrive as f_<dimension>=code,code
  s.facets = {};
  for (const [k, val] of sp.entries()) {
    if (!k.startsWith('f_') || !val) continue;
    s.facets[k.slice(2)] = val.split(',').map((c) => (/^-?\d+$/.test(c) ? Number(c) : c));
  }
  return s;
}

function write(s, replace) {
  const sp = new URLSearchParams();
  for (const k of Object.keys(DEFAULTS)) {
    const v = s[k];
    if (v == null || v === DEFAULTS[k]) continue;
    sp.set(k, String(v));
  }
  for (const [dim, codes] of Object.entries(s.facets || {})) {
    if (codes && codes.length) sp.set('f_' + dim, codes.join(','));
  }
  const qs = sp.toString();
  const url = window.location.pathname + (qs ? '?' + qs : '');
  window.history[replace ? 'replaceState' : 'pushState']({}, '', url);
}

export function useUrlState() {
  const [state, setState] = useState(read);

  useEffect(() => {
    const onPop = () => setState(read());
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  const update = useCallback((patch, { replace = false } = {}) => {
    setState((prev) => {
      const next = { ...prev, ...patch };
      if (patch.facets) next.facets = patch.facets;
      write(next, replace);
      return next;
    });
  }, []);

  const toggleFacet = useCallback((dim, code) => {
    setState((prev) => {
      const cur = prev.facets[dim] || [];
      const has = cur.includes(code);
      const next = has ? cur.filter((c) => c !== code) : [...cur, code];
      const facets = { ...prev.facets };
      if (next.length) facets[dim] = next;
      else delete facets[dim];
      const s = { ...prev, facets };
      write(s, false);
      return s;
    });
  }, []);

  return [state, update, toggleFacet];
}
