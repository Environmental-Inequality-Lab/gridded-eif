/* Number and label formatting. Centralised so tables, charts, and exports
 * cannot drift apart in how they render the same value. */

const int = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
const one = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 });

export function count(v) {
  if (v == null || Number.isNaN(v)) return '—';
  return int.format(Math.round(v));
}

export function pct(v) {
  if (v == null || Number.isNaN(v)) return '—';
  return one.format(v) + '%';
}

/** Compact form for axis ticks and stat tiles. Full precision belongs in the
 *  table and the CSV, never only in an abbreviation. */
export function compact(v) {
  if (v == null || Number.isNaN(v)) return '—';
  const a = Math.abs(v);
  if (a >= 1e9) return one.format(v / 1e9) + 'B';
  if (a >= 1e6) return one.format(v / 1e6) + 'M';
  if (a >= 1e3) return one.format(v / 1e3) + 'K';
  return int.format(v);
}

export function csvEscape(v) {
  const s = v == null ? '' : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function toCsv(rows, columns) {
  const cols = columns || (rows.length ? Object.keys(rows[0]) : []);
  const head = cols.map(csvEscape).join(',');
  const body = rows.map((r) => cols.map((c) => csvEscape(r[c])).join(',')).join('\n');
  return head + '\n' + body + '\n';
}

export function download(filename, text, mime = 'text/csv;charset=utf-8') {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
