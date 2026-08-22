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
export function ResultsTable({ rows, columns, labels, valueLabels, onExport, note }) {
  const [sort, setSort] = useState({ col: 'value', asc: false });
  const [compact_, setCompact] = useState(false);

  const sorted = useMemo(() => {
    const r = [...rows];
    r.sort((a, b) => {
      const x = a[sort.col], y = b[sort.col];
      const n = typeof x === 'number' && typeof y === 'number';
      const cmp = n ? x - y : String(x ?? '').localeCompare(String(y ?? ''));
      return sort.asc ? cmp : -cmp;
    });
    return r;
  }, [rows, sort]);

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
                  onClick=${() => setSort((s) => ({ col: c, asc: s.col === c ? !s.asc : false }))}>
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
                  return html`<td class=${numeric ? 'n' : ''}
                                  title=${small ? 'Small count — privacy noise is large relative to this value' : ''}>
                    ${numeric ? count(v) : (shown ?? '—')}${small ? html` <span class="tag">small</span>` : ''}
                  </td>`;
                })}
              </tr>`)}
          </tbody>
        </table>
      </div>
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
