import { html, render, useState, useEffect } from './h.js';
import { loadCatalog, loadNames, placeIndex } from './catalog.js';
import { useUrlState } from './state.js';
import { warmUp } from './duck.js';
import { Header, Footer, Notice, Spinner } from './components/Chrome.js';
import { Landing } from './components/Landing.js';
import { Explore } from './components/Explore.js';
import { DataPage, DocsPage } from './components/Pages.js';
import { SITE } from './config.js';

function App() {
  const [state, go, toggleFacet] = useUrlState();
  const [cat, setCat] = useState(null);
  const [err, setErr] = useState(null);
  const [places, setPlaces] = useState([]);

  useEffect(() => {
    loadCatalog().then(setCat).catch((e) => setErr(String(e.message || e)));
  }, []);

  // Warm the engine as soon as the user shows intent to query, so the WASM
  // download overlaps with them choosing what to look at rather than blocking.
  useEffect(() => { if (state.v === 'explore') warmUp().catch(() => {}); }, [state.v]);

  /* Names for every level, loaded once from the published lookups. Not scoped
   * to the current selection: search has to reach a county while "state" is
   * selected, which the previous per-level load made impossible. */
  useEffect(() => {
    if (!cat) return;
    let cancelled = false;
    loadNames(cat)
      .then((names) => { if (!cancelled) setPlaces(placeIndex(cat, names)); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [cat]);

  const TITLES = { explore: 'Query', data: 'Data Downloads', docs: 'Documentation' };
  useEffect(() => {
    document.title = state.v === 'home' ? SITE.name
      : `${TITLES[state.v] || state.v} · ${SITE.name}`;
  }, [state.v]);

  if (err) {
    return html`
      <${Header} view=${state.v} go=${go} />
      <main class="wrap section">
        <p class="eyebrow">Something went wrong</p>
        <h1>Data unavailable</h1>
        <${Notice} kind="warn">
          <strong>Could not load the data catalog.</strong> ${err}
        <//>
        <p class="small muted" style="margin-top:16px">
          The data files themselves are unaffected and can be downloaded directly
          from the <a href=${SITE.repo}>repository</a> or the
          <a href="https://www2.census.gov/ces/gridded_eif/">Census file directory</a>.
        </p>
      </main>`;
  }
  if (!cat) {
    return html`<div class="wrap section"><${Spinner} label="Loading catalog…" /></div>`;
  }

  return html`
    <${Header} view=${state.v} go=${go} />
    <main>
      ${state.v === 'home' && html`<${Landing} cat=${cat} go=${go} places=${places} />`}
      ${state.v === 'explore' && html`<${Explore} cat=${cat} state=${state} go=${go}
                                        toggleFacet=${toggleFacet} places=${places} />`}
      ${state.v === 'data' && html`<${DataPage} cat=${cat} />`}
      ${state.v === 'docs' && html`<${DocsPage} cat=${cat} />`}
    </main>
    <${Footer} cat=${cat} />
  `;
}

/* Any unhandled failure degrades to a readable message rather than a blank
 * page. Also catches errors thrown outside the render path, which is where a
 * bad assumption about catalog shape tends to surface. */
function Boundary({ children }) {
  const [crash, setCrash] = useState(null);
  useEffect(() => {
    const onErr = (e) => setCrash(String(e.reason?.message || e.message || e.reason || e));
    window.addEventListener('unhandledrejection', onErr);
    window.addEventListener('error', onErr);
    return () => {
      window.removeEventListener('unhandledrejection', onErr);
      window.removeEventListener('error', onErr);
    };
  }, []);
  if (!crash) return children;
  return html`
    <main class="wrap section">
      <p class="eyebrow">Something went wrong</p>
      <h1>This page failed to load</h1>
      <${Notice} kind="warn">${crash}<//>
      <p class="small muted" style="margin-top:16px">
        Please <a href=${SITE.repo + '/issues'}>report this</a> with the page address.
        The underlying data files are unaffected.
      </p>
    </main>`;
}

render(html`<${Boundary}><${App} /><//>`, document.getElementById('app'));
