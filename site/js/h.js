/* Single place where the view layer is bound.
 * Preact + htm are vendored, so the site has no external runtime dependency
 * for its framework and no build step. Swapping either happens here. */
import { h, render, Fragment } from './vendor/preact.module.js';
import { useState, useEffect, useMemo, useRef, useCallback } from './vendor/hooks.module.js';
import htm from './vendor/htm.module.js';

export const html = htm.bind(h);
export { h, render, Fragment, useState, useEffect, useMemo, useRef, useCallback };
