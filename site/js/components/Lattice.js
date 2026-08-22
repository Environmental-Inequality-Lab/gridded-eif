/* Abstract lattice mark.
 *
 * The Gridded EIF is a lattice of 0.01-degree cells, so a lattice is what the
 * product looks like. The points are generated from the published nation
 * boundary at a coarse spacing — a mark, not a rendering of the data, and
 * deliberately not readable as a map of anything.
 *
 * Motion is a slow, staggered opacity drift. It reads as something alive
 * without asking to be watched, and it stops entirely under
 * `prefers-reduced-motion`.
 */
import { html } from '../h.js';
import { LATTICE, LATTICE_W, LATTICE_H } from '../us-lattice.js';

export function Lattice() {
  return html`
    <svg
      class="lattice"
      viewBox=${`0 0 ${LATTICE_W} ${LATTICE_H}`}
      role="presentation"
      aria-hidden="true"
      preserveAspectRatio="xMidYMid meet"
    >
      ${LATTICE.map(([x, y], i) => {
        // Deterministic from the index, so the pattern is stable across
        // renders. A pseudo-random phase avoids a visible sweep.
        const phase = ((i * 2654435761) % 1000) / 1000;
        const r = 2.4 + ((i * 97) % 7) * 0.22;
        return html`<circle
          cx=${x}
          cy=${y}
          r=${r}
          style=${`animation-delay:${(phase * 9).toFixed(2)}s`}
        />`;
      })}
    </svg>`;
}
