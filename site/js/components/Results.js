import { html, useState, useMemo } from '../h.js';
import { count, compact, toCsv, download } from '../format.js';

/* Results table.
 *
 * Small numbers are shown and marked rather than suppressed. Suppression trains
 * people to think data is missing; marking trains them to think about
 * uncertainty, which is the actual situation with privacy-infused counts.
 */
/* `valueLabels` maps a column to a code->label lookup, so the table can show
 * published wording while the underlying value stays the code the data uses.
 * The CSV deliberately keeps codes: an export exists to be joined back to the
 * source files, and a relabelled value would not match them. */
/* Shown on the flag itself, not the cell, so hovering the thing you are asking
 * about is what explains it. */
const SMALL_EXPLAINER =
  'Fewer than 100 people. Privacy noise of about ±3 per grid cell does not ' +
  'average out at this size, so treat the figure as approximate rather than exact.';

export function ResultsTable({ rows, columns, labels, valueLabels, valueOrder, onExport, note }) {
  const [compact_, setCompact] = useState(false);

  /* Rank lookups from the registry's declared order. Without these, dimension
   * columns sort alphabetically, which is meaningless for ordered categories:
   * age became "19-65, Missing Age, Over 65, Under 18" and income deciles
   * sorted 0, 1, 10, 2. */
  const ranks = useMemo(() => {
    const out = {};
    for (const [col, codes] of Object.entries(valueOrder || {})) {
      out[col] = new Map(codes.map((c, i) => [String(c), i]));
    }
    return out;
  }, [valueOrder]);

  /* Default sort. A ranking by value is the point when rows are places — the
   * question is which are biggest. But when rows are a demographic breakdown,
   * ordering by the rightmost column scrambles the columns people read first,
   * so the declared order of the leading dimension wins instead. */
  const dimensionCols = useMemo(
    () => columns.filter((c) => ranks[c] && c !== 'geo_id'),
    [columns, ranks]
  );
  const defaultSort = dimensionCols.length
    ? { col: dimensionCols[0], asc: true }
    : { col: 'value', asc: false };
  const [sort, setSort] = useState(defaultSort);

  const cmpOne = (col, a, b) => {
    const x = a[col];
    const y = b[col];
    const rank = ranks[col];
    if (rank) {
      // Unknown codes sort last rather than colliding at position 0.
      const rx = rank.has(String(x)) ? rank.get(String(x)) : Number.MAX_SAFE_INTEGER;
      const ry = rank.has(String(y)) ? rank.get(String(y)) : Number.MAX_SAFE_INTEGER;
      if (rx !== ry) return rx - ry;
      return String(x ?? '').localeCompare(String(y ?? ''));
    }
    if (typeof x === 'number' && typeof y === 'number') return x - y;
    return String(x ?? '').localeCompare(String(y ?? ''));
  };

  const sorted = useMemo(() => {
    const r = [...rows];
    r.sort((a, b) => {
      const cmp = cmpOne(sort.col, a, b);
      if (cmp !== 0) return sort.asc ? cmp : -cmp;
      // Tie-break down the remaining dimensions in column order, so the whole
      // table reads consistently left to right rather than arbitrarily.
      for (const c of dimensionCols) {
        if (c === sort.col) continue;
        const t = cmpOne(c, a, b);
        if (t !== 0) return t;
      }
      return (b.value ?? 0) - (a.value ?? 0);
    });
    return r;
  }, [rows, sort, ranks, dimensionCols]);

  if (!rows.length) {
    return html`<p class="muted small" style="padding:20px">
      No rows for this selection. Try clearing a filter.
    </p>`;
  }

  return html`
    <div>
      <div class="spread" style="padding:10px 4px">
        <span class="small muted">${count(rows.length)} rows${note ? ' · ' + note : ''}</span>
        <span class="row" style="gap:6px">
          <button class="btn btn-quiet btn-sm" onClick=${() => setCompact(!compact_)}>
            ${compact_ ? 'Comfortable' : 'Compact'}
          </button>
          <button class="btn btn-outline btn-sm" onClick=${onExport}>Download CSV</button>
        </span>
      </div>
      <div class=${'table-scroll' + (compact_ ? ' compact' : '')} style="max-height:460px;overflow-y:auto">
        <table class="data">
          <thead>
            <tr>${columns.map((c) => html`
              <th class=${sort.col === c ? 'sorted ' + (sort.asc ? 'asc' : '') : ''}
                  onClick=${() => setSort((s) =>
                    // A fresh click on a dimension starts in declared order;
                    // on a measure it starts with the largest. Defaulting
                    // everything to descending reversed the categories, so
                    // clicking Sex led with "Not reported".
                    s.col === c ? { col: c, asc: !s.asc } : { col: c, asc: !!ranks[c] })}>
                ${labels?.[c] || c}
              </th>`)}
            </tr>
          </thead>
          <tbody>
            ${sorted.slice(0, 500).map((r, i) => html`
              <tr key=${i}>
                ${columns.map((c) => {
                  const v = r[c];
                  const numeric = typeof v === 'number';
                  const shown = numeric ? v : (valueLabels?.[c]?.[v] ?? v);
                  const small = c === 'value' && numeric && Math.abs(v) < 100;
                  return html`<td class=${numeric ? 'n' : ''}>
                    ${numeric ? count(v) : (shown ?? '—')}${small
                      ? html` <span
                          class="tag tag-help"
                          tabindex="0"
                          title=${SMALL_EXPLAINER}
                          aria-label=${SMALL_EXPLAINER}>small</span>`
                      : ''}
                  </td>`;
                })}
              </tr>`)}
          </tbody>
        </table>
      </div>
      ${sorted.some((r) => typeof r.value === 'number' && Math.abs(r.value) < 100) && html`
        <p class="small muted" style="padding:8px 4px 0">
          <span class="tag">small</span> ${SMALL_EXPLAINER}
        </p>`}
      ${sorted.length > 500 && html`
        <p class="small muted" style="padding:8px 4px">
          Showing the first 500 of ${count(sorted.length)} rows. The CSV contains all of them.
        </p>`}
    </div>
  `;
}

/* Time series. Plain inline SVG — no charting library to keep current.
 *
 * Deliberately renders points as well as a line: with privacy-infused counts a
 * smooth line can imply more precision than the data supports. */
export function TimeSeries({ series, label, preliminaryYears = [] }) {
  const [hover, setHover] = useState(null);
  if (!series.length) return html`<p class="muted small" style="padding:20px">No data for this selection.</p>`;

  const W = 720, H = 300, P = { t: 16, r: 18, b: 34, l: 66 };
  const xs = series.map((d) => d.year);
  const ys = series.map((d) => d.value);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  const y1 = Math.max(...ys);
  const y0 = Math.min(0, Math.min(...ys));   // anchor counts at zero
  const px = (x) => P.l + ((x - x0) / Math.max(1, x1 - x0)) * (W - P.l - P.r);
  const py = (y) => H - P.b - ((y - y0) / Math.max(1, y1 - y0)) * (H - P.t - P.b);

  const ticks = 4;
  const yTicks = Array.from({ length: ticks + 1 }, (_, i) => y0 + ((y1 - y0) * i) / ticks);
  const xTicks = xs.filter((_, i) => i % Math.ceil(xs.length / 8) === 0);
  const path = series.map((d, i) => `${i ? 'L' : 'M'}${px(d.year)},${py(d.value)}`).join('');

  return html`
    <div style="padding:12px 4px">
      <svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto"
           role="img" aria-label=${`${label} by year`}>
        ${yTicks.map((t) => html`
          <g>
            <line x1=${P.l} x2=${W - P.r} y1=${py(t)} y2=${py(t)}
                  stroke="var(--line)" stroke-width="1" />
            <text x=${P.l - 8} y=${py(t) + 4} text-anchor="end"
                  font-size="11" fill="var(--ink-faint)">${compact(t)}</text>
          </g>`)}
        ${xTicks.map((t) => html`
          <text x=${px(t)} y=${H - 12} text-anchor="middle"
                font-size="11" fill="var(--ink-faint)">${t}</text>`)}
        <path d=${path} fill="none" stroke="var(--data-1)" stroke-width="2"
              stroke-linejoin="round" stroke-linecap="round" />
        ${series.map((d) => html`
          <circle cx=${px(d.year)} cy=${py(d.value)} r=${hover === d.year ? 5 : 3.2}
                  fill=${preliminaryYears.includes(d.year) ? 'var(--warn)' : 'var(--data-1)'}
                  stroke="var(--surface)" stroke-width="1.5"
                  onMouseEnter=${() => setHover(d.year)} onMouseLeave=${() => setHover(null)}>
            <title>${d.year}: ${count(d.value)}</title>
          </circle>`)}
      </svg>
      <div class="spread small muted" style="padding:0 4px">
        <span>${label}</span>
        ${hover != null && html`<span class="num">
          <strong>${hover}</strong> · ${count(series.find((d) => d.year === hover)?.value)}
        </span>`}
      </div>
    </div>
  `;
}

/* Emits both the code and the published label for any dimension where they
 * differ. Codes alone would confuse anyone comparing the file to the screen —
 * the site shows "18-64" where the data stores "19-65". Labels alone would
 * break a join back to the source Parquet, which is the point of publishing
 * stable file URLs. Both columns costs a little width and cannot be wrong. */
export function exportCsv(rows, columns, filename, valueLabels) {
  const cols = [];
  for (const c of columns) {
    cols.push(c);
    const map = valueLabels?.[c];
    if (map && rows.some((r) => map[r[c]] !== undefined && map[r[c]] !== r[c])) {
      cols.push(`${c}_label`);
    }
  }
  const expanded = rows.map((r) => {
    const out = { ...r };
    for (const c of cols) {
      if (c.endsWith('_label')) {
        const base = c.slice(0, -'_label'.length);
        out[c] = valueLabels?.[base]?.[r[base]] ?? r[base];
      }
    }
    return out;
  });
  download(filename, toCsv(expanded, cols));
}
