import { html, render, useState, useEffect } from './h.js';
import { loadCatalog } from './catalog.js';
import { useUrlState } from './state.js';
import { warmUp, query, q } from './duck.js';
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

  /* Place names come from the data itself. The pipeline does not publish a
   * separate name lookup yet, so geo_ids are labelled from a small built-in map
   * for states and shown as codes elsewhere. Replacing this with a published
   * lookup is a pipeline change, not a UI one. */
  useEffect(() => {
    if (!cat || state.v !== 'explore') return;
    let cancelled = false;
    const entry = cat.entries.find(
      (e) => e.dataset === state.d && e.geography === state.g
    );
    if (!entry) return;
    query(`SELECT DISTINCT geo_id FROM read_parquet(${q(entry.url)}) ORDER BY 1`)
      .then((rows) => {
        if (cancelled) return;
        setPlaces(rows.map((r) => ({
          geo_id: r.geo_id,
          name: labelFor(r.geo_id, state.g),
          level: state.g,
          levelLabel: cat.geographies[state.g]?.label || state.g,
        })));
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [cat, state.g, state.d, state.v]);

  useEffect(() => {
    const v = state.v;
    document.title = v === 'home' ? SITE.name
      : `${v[0].toUpperCase()}${v.slice(1)} · ${SITE.name}`;
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

const STATES = {
  '01':'Alabama','02':'Alaska','04':'Arizona','05':'Arkansas','06':'California','08':'Colorado',
  '09':'Connecticut','10':'Delaware','11':'District of Columbia','12':'Florida','13':'Georgia',
  '15':'Hawaii','16':'Idaho','17':'Illinois','18':'Indiana','19':'Iowa','20':'Kansas','21':'Kentucky',
  '22':'Louisiana','23':'Maine','24':'Maryland','25':'Massachusetts','26':'Michigan','27':'Minnesota',
  '28':'Mississippi','29':'Missouri','30':'Montana','31':'Nebraska','32':'Nevada','33':'New Hampshire',
  '34':'New Jersey','35':'New Mexico','36':'New York','37':'North Carolina','38':'North Dakota',
  '39':'Ohio','40':'Oklahoma','41':'Oregon','42':'Pennsylvania','44':'Rhode Island',
  '45':'South Carolina','46':'South Dakota','47':'Tennessee','48':'Texas','49':'Utah','50':'Vermont',
  '51':'Virginia','53':'Washington','54':'West Virginia','55':'Wisconsin','56':'Wyoming',
};

function labelFor(id, level) {
  if (level === 'nation') return 'United States';
  if (level === 'state') return STATES[id] || id;
  if (level === 'county') return `${id} (${STATES[id.slice(0, 2)] || '—'})`;
  return id;
}

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
