/* DuckDB-WASM query layer.
 *
 * Real SQL runs in the browser against Parquet on a CDN, using HTTP range
 * requests. There is no server and no database.
 *
 * The engine is created lazily on first query so the landing page never pays
 * for it — the WASM bundle is several megabytes and most visitors to "/" never
 * run a query.
 */

import { DUCKDB_CDN } from './config.js';

let connPromise = null;

async function connect() {
  const duckdb = await import(/* @vite-ignore */ DUCKDB_CDN);
  const bundle = await duckdb.selectBundle(duckdb.getJsDelivrBundles());
  const workerUrl = URL.createObjectURL(
    new Blob([`importScripts("${bundle.mainWorker}");`], { type: 'text/javascript' })
  );
  const db = new duckdb.AsyncDuckDB(new duckdb.VoidLogger(), new Worker(workerUrl));
  await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
  URL.revokeObjectURL(workerUrl);
  return db.connect();
}

export function warmUp() {
  if (!connPromise) connPromise = connect();
  return connPromise;
}

/* Queries are serialised.
 *
 * A DuckDB-WASM connection is not safe for concurrent queries. Issuing two at
 * once — which the workbench does naturally, fetching a table and a time series
 * together — interleaves reads on the shared connection and surfaces as
 * "ZSTD Decompression failure", an error that points at the file format rather
 * than the real cause.
 *
 * This queue makes callers free to fire queries whenever they like without
 * knowing about the constraint.
 */
let tail = Promise.resolve();

const shape = (result) =>
  result.toArray().map((row) => {
    const o = {};
    for (const [k, v] of Object.entries(row)) o[k] = typeof v === 'bigint' ? Number(v) : v;
    return o;
  });

export function query(sql) {
  const run = tail.then(async () => {
    const conn = await warmUp();
    try {
      return shape(await conn.query(sql));
    } catch (e) {
      // A first request for a large file can fail while CloudFront is fetching
      // it from the origin — the edge has nothing cached and the range request
      // stalls. Observed on the 29 MB all-years county file. One retry after a
      // short pause is enough, and is far better than showing the user an error
      // for a file that is simply warming up.
      if (!/network|failed to (load|fetch|execute)/i.test(String(e.message || e))) throw e;
      await new Promise((r) => setTimeout(r, 900));
      return shape(await conn.query(sql));
    }
  });
  // Keep the chain alive even when a query rejects, or one failure would
  // permanently wedge every later query behind it.
  tail = run.catch(() => {});
  return run;
}

/** Single-quote a string for SQL. URLs come from the catalog rather than user
 *  input, but quoting is cheap and the alternative is a habit worth not having. */
export const q = (s) => `'${String(s).replace(/'/g, "''")}'`;

/** Build a filtered aggregation over one Parquet source.
 *
 * `filters` maps a dimension to selected codes; empty or absent means "all",
 * which is left unfiltered rather than expanded into a full IN list.
 */
export function buildQuery({ url, measure, groupBy = [], filters = {}, year = null, limit = null }) {
  const where = [];
  if (year != null) where.push(`year = ${Number(year)}`);
  for (const [dim, codes] of Object.entries(filters)) {
    if (!codes || codes.length === 0) continue;
    const list = codes
      .map((c) => (typeof c === 'number' ? String(c) : q(c)))
      .join(', ');
    where.push(`${dim} IN (${list})`);
  }
  const cols = groupBy.length ? groupBy.join(', ') : null;
  const sql = [
    // n_cells is deliberately not selected. Summing it across demographic rows
    // counts each grid cell once per group present in it — Wayne County reports
    // 42,159 against 1,693 actual populated cells. A corrected count would still
    // not be an area measure: cells are equal in degrees, not square kilometres
    // (~1.12 km² in Florida, ~0.40 km² in northern Alaska), and only populated
    // cells exist at all. Anyone who wants cell counts, density, or true area
    // can compute them from the published crosswalk.
    `SELECT ${cols ? cols + ', ' : ''}sum(${measure}) AS value`,
    `FROM read_parquet(${q(url)})`,
    where.length ? `WHERE ${where.join(' AND ')}` : '',
    cols ? `GROUP BY ${groupBy.map((_, i) => i + 1).join(', ')}` : '',
    cols ? `ORDER BY value DESC` : '',
    limit ? `LIMIT ${Number(limit)}` : '',
  ]
    .filter(Boolean)
    .join('\n');
  return sql;
}
