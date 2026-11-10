// The Portrait of a Graduate wheel, after the District's own graphic: "Portrait of
// a Graduate" in the centre, six slices (one per group in the reference file,
// clockwise from the top left), a thin ring of the 14 competencies inside their
// slices, and an outer ring in two halves, "Prepared for individual success" on
// the left and "Prepared to build collective success" on the right.
//
// The wheel's shape never changes with the counts: every slice is 60 degrees and
// a slice's competencies share it equally. Each count is printed as a number on
// its slice or competency, and every number counts programs naming a goal there.
//
// Beside the wheel: on the left, "Results the Portrait does not name" (the
// codebook's own OUT codes, never drawn as a slice), with families, staff,
// programs or systems kept apart from the five youth codes; on the right, the
// side panel. At rest the panel lists every slice and competency with its count,
// so nothing on the wheel needs pointing at to be read. A click, Enter or a tap
// on a slice, competency, skill or outside code pins it, opens it in the panel
// and goes to Python as the "selection" state, which narrows the table below.
// Clicking it again, the centre, or Escape lets go. Pointing only tints what is
// under the pointer; nothing moves. `data.sig` changes only when counts change.

const SVG_NS = 'http://www.w3.org/2000/svg';
const SIZE = 720;
const C = SIZE / 2;
const R = { centre: 66, sliceIn: 76, sliceOut: 210, compIn: 215, compOut: 306, halfIn: 313, halfOut: 352 };
const RING_FONT = [12, 11];   // competency names: the normal size, then the size tried when a name won't fit
const RING_LINE = 1.22;          // line height, in ems
const RING_LINES = 5;            // a competency name wraps onto at most this many lines
const OUTCOME_CHARS = 200;       // longer sentences are cut around their coded part

// Lucide icons (ISC licence), drawn in the slice's label colour.
const ICONS = {
  bulb: ['M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5', 'M9 18h6', 'M10 22h4'],
  speech: ['M14 9a2 2 0 0 1-2 2H6l-4 4V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2z', 'M18 9h2a2 2 0 0 1 2 2v11l-4-4h-6a2 2 0 0 1-2-2v-1'],
  handshake: ['m11 17 2 2a1 1 0 1 0 3-3', 'm14 14 2.5 2.5a1 1 0 1 0 3-3l-3.88-3.88a3 3 0 0 0-4.24 0l-.88.88a1 1 0 1 1-3-3l2.81-2.81a5.79 5.79 0 0 1 7.06-.87l.47.28a2 2 0 0 0 1.42.25L21 4', 'm21 3 1 11h-2', 'M3 3 2 14l6.5 6.5a1 1 0 1 0 3-3', 'M3 4h8'],
  globe: ['M12 2a10 10 0 1 0 0 20 10 10 0 1 0 0-20', 'M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20', 'M2 12h20'],
  brain: ['M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z', 'M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z', 'M15 13a4.5 4.5 0 0 1-3-4 4.5 4.5 0 0 1-3 4', 'M17.599 6.5a3 3 0 0 0 .399-1.375', 'M6.003 5.125A3 3 0 0 0 6.401 6.5', 'M3.477 10.896a4 4 0 0 1 .585-.396', 'M19.938 10.5a4 4 0 0 1 .585.396', 'M6 18a4 4 0 0 1-1.967-.516', 'M19.967 17.484A4 4 0 0 1 18 18'],
  cap: ['M21.42 10.922a1 1 0 0 0-.019-1.838L12.83 5.18a2 2 0 0 0-1.66 0L2.6 9.08a1 1 0 0 0 0 1.832l8.57 3.908a2 2 0 0 0 1.66 0z', 'M22 10v6', 'M6 12.5V16a6 3 0 0 0 12 0v-3.5'],
};

let uid = 0;

// ---------------------------------------------------------------- helpers

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function svgEl(tag, attrs, text) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v !== null && v !== undefined) node.setAttribute(k, v);
  if (text !== undefined) node.textContent = text;
  return node;
}

const point = (r, deg) => {
  const rad = ((deg - 90) * Math.PI) / 180;
  return [C + r * Math.cos(rad), C + r * Math.sin(rad)];
};
const f = n => Number(n.toFixed(2));

function sector(r0, r1, a0, a1) {
  const [x0, y0] = point(r1, a0), [x1, y1] = point(r1, a1);
  const [x2, y2] = point(r0, a1), [x3, y3] = point(r0, a0);
  const large = a1 - a0 > 180 ? 1 : 0;
  return `M${f(x0)},${f(y0)}A${r1},${r1} 0 ${large} 1 ${f(x1)},${f(y1)}L${f(x2)},${f(y2)}A${r0},${r0} 0 ${large} 0 ${f(x3)},${f(y3)}Z`;
}

/** An arc for text: clockwise (letters upright in the top half, or reading outward on the sides), or
 *  counter-clockwise, which keeps letters upright in the bottom half. */
function arc(r, a0, a1, clockwise = true) {
  const [s, e] = clockwise ? [a0, a1] : [a1, a0];
  const [x0, y0] = point(r, s), [x1, y1] = point(r, e);
  return `M${f(x0)},${f(y0)}A${r},${r} 0 0 ${clockwise ? 1 : 0} ${f(x1)},${f(y1)}`;
}

const upper = deg => Math.cos((deg * Math.PI) / 180) > 0;

let measureCtx = null;
function textWidth(text, px, weight = 600) {
  measureCtx = measureCtx || document.createElement('canvas').getContext('2d');
  measureCtx.font = `${weight} ${px}px Inter, "Source Sans", -apple-system, "Segoe UI", sans-serif`;
  return measureCtx.measureText(text).width;
}

/** Leads without one that repeats another's words (as on the codebook wheel). */
function dropRepeats(leads) {
  const n = leads.map(x => x.replace(/[\s.,;:!?]+$/, '').toLowerCase().split(/\s+/).join(' '));
  return leads.filter((_, i) => !n.some((y, j) => j !== i && y.includes(n[i]) && (y.length > n[i].length || j < i)));
}

/** One example statement, by the dashboard's split rule: a split sentence leads with its coded part (the
 *  partner's words when they are in the sentence word for word, else the coder's wording), then the whole
 *  sentence on a quieter "From:" line. A part is never shown alone, and the partner's words are never rewritten. */
function outcomeItem(p) {
  const t = p.t || '';
  const marks = (p.m || []).slice().sort((x, y) => x[0] - y[0]);
  const reworded = p.c || [];
  const split = marks.length > 0 || reworded.length > 0;
  let start = 0, end = t.length;
  if (t.length > OUTCOME_CHARS) {
    const focus = marks.length ? marks[0][0] : 0;
    if (focus > OUTCOME_CHARS * 0.4) start = t.lastIndexOf(' ', Math.max(0, focus - 30)) + 1;
    end = Math.min(t.length, start + OUTCOME_CHARS);
    if (end < t.length) {
      const space = t.lastIndexOf(' ', end);
      if (space > start) end = space;
    }
  }
  const li = el('li', 'pw-outcome');
  if (split) for (const x of dropRepeats([...marks.map(([s, e]) => t.slice(s, e)), ...reworded])) li.append(el('span', 'pw-lead', x));
  li.append(el('span', split ? 'pw-from' : 'pw-quote',
    (split ? 'From: ' : '') + '“' + (start ? '…' : '') + t.slice(start, end) + (end < t.length ? '…' : '') + '”'));
  return li;
}

const programs = n => `${n.toLocaleString()} ${n === 1 ? 'program' : 'programs'}`;
const sameSel = (a, b) => !!a && !!b && a.kind === b.kind && a.id === b.id;

function activate(node, handler) {
  node.addEventListener('click', handler);
  node.addEventListener('keydown', ev => {
    if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); handler(ev); }
  });
}

// ---------------------------------------------------------------- component

export default function (component) {
  const { data, parentElement, setStateValue } = component;
  if (!data || !data.slices) return;
  let root = parentElement.querySelector('.pw');
  if (!root) {
    root = el('div', 'pw');
    parentElement.appendChild(root);
  }
  const pw = root.__pw || (root.__pw = { sig: null, sel: null, uid: ++uid });
  pw.send = setStateValue;
  if (pw.sig !== data.sig) {
    pw.sig = data.sig;
    pw.data = data;
    if (pw.sel === null && data.selected) pw.sel = data.selected;
    mount(root, pw);
    if (!pw.fontsHooked && document.fonts && document.fonts.status !== 'loaded') {
      // Names are fitted by measuring them; measure again once Inter has loaded.
      pw.fontsHooked = true;
      document.fonts.ready.then(() => mount(root, pw));
    }
  }
}

function pick(pw, sel) {
  pw.sel = sameSel(pw.sel, sel) ? null : sel;
  pw.refresh();
  pw.send('selection', pw.sel);
}

function mount(root, pw) {
  const data = pw.data;
  pw.burstFor = null;   // the opened competency's rays are drawn again on the new wheel
  root.replaceChildren();
  const comps = data.competencies;
  const sliceOf = new Map();
  for (const s of data.slices) for (const id of s.competencies) sliceOf.set(id, s);

  // ---- left: results the Portrait does not name
  const out = el('aside', 'pw-out');
  const outHead = el('div', 'pw-out-head');
  outHead.append(el('div', 'pw-head', 'Results the Portrait does not name'), el('span', 'pw-out-unit', 'programs'));
  out.append(outHead);
  out.append(el('p', 'pw-note', 'Real results partners name that no Portrait skill covers. They stay off the wheel because they are not part of the Portrait.'));
  const outRows = new Map();
  const outRow = o => {
    const b = el('button', 'pw-row');
    b.type = 'button';
    b.append(el('span', 'pw-row-name', o.name), el('span', 'pw-row-n', o.programs.toLocaleString()));
    b.setAttribute('aria-label', `${o.name}: ${programs(o.programs)} naming a goal of this kind`);
    activate(b, () => pick(pw, { kind: 'outside', id: o.id }));
    outRows.set(o.id, b);
    return b;
  };
  const youth = data.outside.filter(o => o.youth);
  const adults = data.outside.filter(o => !o.youth);
  const youthList = el('div', 'pw-rows');
  youth.forEach(o => youthList.append(outRow(o)));
  out.append(el('div', 'pw-sub', 'For young people'), youthList);
  if (adults.length) {
    const adultList = el('div', 'pw-rows');
    adults.forEach(o => adultList.append(outRow(o)));
    out.append(el('div', 'pw-sub pw-sub-apart', 'For adults and organizations, left out of every figure about young people'), adultList);
  }

  // ---- middle: the wheel
  const figure = el('div', 'pw-figure');
  const svg = svgEl('svg', { viewBox: `0 0 ${SIZE} ${SIZE}`, class: 'pw-svg', role: 'group',
    'aria-label': 'Portrait of a Graduate wheel: six slices and their competencies, with the number of programs naming a goal in each' });
  const defs = svgEl('defs');
  svg.append(defs);
  // Everything that shrinks and steps aside when a competency opens (see openBurst).
  const wheel = svgEl('g', { class: 'pw-wheel' });
  const burst = svgEl('g', { class: 'pw-burst' });
  const pathId = name => `pw${pw.uid}-${name}`;

  // Outer ring: two halves, with their words along the arc.
  const halves = [
    { key: 'individual', a0: 181.5, a1: 358.5, fill: '#e2e4f1', text: [196, 344] },
    { key: 'collective', a0: 1.5, a1: 178.5, fill: '#fde6d4', text: [16, 164] },
  ];
  for (const h of halves) {
    wheel.append(svgEl('path', { d: sector(R.halfIn, R.halfOut, h.a0, h.a1), fill: h.fill, class: 'pw-half' }));
    const id = pathId(`half-${h.key}`);
    defs.append(svgEl('path', { id, d: arc((R.halfIn + R.halfOut) / 2 - 5.5, h.text[0], h.text[1]) }));
    const t = svgEl('text', { class: 'pw-half-text', fill: data.navy });
    const tp = svgEl('textPath', { href: `#${id}`, startOffset: '50%', 'text-anchor': 'middle' }, data.halves[h.key]);
    t.append(tp);
    wheel.append(t);
  }

  const sliceNodes = new Map(), compNodes = new Map();
  data.slices.forEach((s, i) => {
    const a0 = -60 + 60 * i, a1 = a0 + 60, mid = a0 + 30;
    const g = svgEl('g', { class: 'pw-slice', tabindex: 0, role: 'button',
      'aria-label': `${s.name}: ${programs(s.programs)} naming a goal in this slice` });
    g.append(svgEl('path', { d: sector(R.sliceIn, R.sliceOut, a0, a1), fill: s.color, class: 'pw-slice-shape' }));
    // The slice's icon, name and count, centred in the slice.
    const [cx, cy] = point(143, mid);
    const w = Math.abs(Math.cos((mid * Math.PI) / 180)) < 0.1 ? 118 : 136, hgt = 132;   // side slices are narrower
    const fo = svgEl('foreignObject', { x: f(cx - w / 2), y: f(cy - hgt / 2), width: w, height: hgt, class: 'pw-fo' });
    const box = el('div', 'pw-slice-label');
    box.style.color = s.ink;
    const icon = svgEl('svg', { viewBox: '0 0 24 24', width: 26, height: 26, fill: 'none', stroke: s.ink,
      'stroke-width': 1.8, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true' });
    for (const d of ICONS[s.icon] || []) icon.append(svgEl('path', { d }));
    const title = el('div', 'pw-slice-title');
    s.title.forEach((part, k) => title.append(k % 2 ? el('b', '', part) : document.createTextNode(part)));
    box.append(icon, title, el('div', 'pw-slice-n', programs(s.programs)));
    fo.append(box);
    g.append(fo);
    activate(g, () => pick(pw, { kind: 'slice', id: s.id }));
    sliceNodes.set(s.id, g);
    wheel.append(g);

    // The competency ring: each of the slice's competencies gets an equal share of its 60 degrees.
    const step = 60 / s.competencies.length;
    s.competencies.forEach((cid, k) => {
      const c = comps[cid];
      const b0 = a0 + step * k, b1 = b0 + step, bm = (b0 + b1) / 2;
      const cg = svgEl('g', { class: 'pw-comp', tabindex: 0, role: 'button',
        'aria-label': `${c.name} (${c.num}): ${programs(c.programs)} naming a goal in this competency` });
      const shape = svgEl('path', { d: sector(R.compIn, R.compOut, b0, b1), class: 'pw-comp-shape' });
      cg.append(shape);
      cg.append(svgEl('title', {}, `${c.name} (${c.num})`));
      ringLabel(cg, defs, pathId(`c-${cid}`), `${c.name} (${c.num})`, programs(c.programs), b0, b1, upper(bm));
      activate(cg, ev => { ev.stopPropagation(); pick(pw, { kind: 'competency', id: cid }); });
      compNodes.set(cid, { g: cg, shape, slice: s, mid: bm });
      wheel.append(cg);
    });
  });

  // Centre: "Portrait of a Graduate". Clicking it lets go of whatever is picked.
  const centre = svgEl('g', { class: 'pw-centre' });
  centre.append(svgEl('circle', { cx: C, cy: C, r: R.centre, fill: data.navy }));
  const cfo = svgEl('foreignObject', { x: C - 56, y: C - 30, width: 112, height: 60, class: 'pw-fo' });
  cfo.append(el('div', 'pw-centre-text', 'Portrait of a Graduate'));
  centre.append(cfo);
  centre.addEventListener('click', () => { if (pw.sel) pick(pw, pw.sel); });
  wheel.append(centre);
  svg.append(wheel, burst);
  figure.append(svg);
  figure.append(el('p', 'pw-key', 'Each number counts programs naming a goal in that slice or competency; a program counts once in each place. Slice sizes are fixed and do not show counts.'));

  // ---- right: the side panel
  const panel = el('aside', 'pw-panel');
  panel.setAttribute('aria-live', 'polite');

  const side = el('div', 'pw-side');
  side.append(out, panel);
  root.append(figure, side);

  root.onkeydown = ev => { if (ev.key === 'Escape' && pw.sel) pick(pw, pw.sel); };

  pw.refresh = () => {
    const sel = pw.sel;
    let litSlice = null, litComp = null;
    if (sel?.kind === 'slice') litSlice = sel.id;
    if (sel?.kind === 'competency' || sel?.kind === 'only') litComp = sel.id;
    if (sel?.kind === 'skill') litComp = sel.id.split('.').slice(0, 2).join('.');
    if (litComp) litSlice = sliceOf.get(litComp)?.id;
    const any = !!(litSlice || sel?.kind === 'outside');
    for (const [id, g] of sliceNodes) {
      g.classList.toggle('is-dim', any && id !== litSlice);
      g.classList.toggle('is-on', id === litSlice);
      g.setAttribute('aria-pressed', String(sel?.kind === 'slice' && sel.id === id));
    }
    for (const [id, n] of compNodes) {
      const on = litComp ? id === litComp : (litSlice ? n.slice.id === litSlice : false);
      n.shape.setAttribute('fill', on && litComp ? n.slice.color : tint(n.slice.color));
      n.g.classList.toggle('is-picked', !!litComp && id === litComp);
      n.g.style.setProperty('--ink', on && litComp ? n.slice.ink : data.navy);
      n.g.classList.toggle('is-dim', any && !(litComp ? id === litComp || n.slice.id === litSlice : n.slice.id === litSlice));
      n.g.setAttribute('aria-pressed', String(!!litComp && id === litComp));
    }
    for (const [id, b] of outRows) b.classList.toggle('is-on', sel?.kind === 'outside' && sel.id === id);
    if (litComp) openBurst(pw, wheel, burst, compNodes.get(litComp), comps[litComp], sel);
    else closeBurst(pw, wheel, burst);
    drawPanel(panel, pw, sliceOf);
  };
  pw.refresh();
}

// ---------------------------------------------------------------- the opened competency
// Clicking a competency never turns the wheel. The wheel shrinks and steps aside, away from the side the
// competency faces; everything else fades; the competency's skills fan out as rays from its own spot on the
// ring, each ray as long as its program count, with a line to the skill's name in a list on that side.

const OPEN = { scale: 0.46, shift: 185, column: 232, columnWidth: 300, rayFrom: 4, rayMin: 16, rayMax: 52, ms: 320 };

function reducedMotion() {
  return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/** Tween the wheel to scale k, shifted dx to the side, about its own centre. */
function moveWheel(pw, wheel, k, dx) {
  const set = (kk, xx) => wheel.setAttribute('transform', kk === 1 && xx === 0 ? '' :
    `translate(${f(C * (1 - kk) + xx)} ${f(C * (1 - kk))}) scale(${f(kk)})`);
  cancelAnimationFrame(pw.raf);
  const from = pw.at || { k: 1, dx: 0 };
  if (from.k === k && from.dx === dx) return set(k, dx);
  const t0 = performance.now(), ms = reducedMotion() ? 0 : OPEN.ms;
  const step = now => {
    const p = ms ? Math.min(1, (now - t0) / ms) : 1, e = 1 - Math.pow(1 - p, 3);
    pw.at = { k: from.k + (k - from.k) * e, dx: from.dx + (dx - from.dx) * e };
    set(pw.at.k, pw.at.dx);
    if (p < 1) pw.raf = requestAnimationFrame(step);
  };
  if (ms) pw.raf = requestAnimationFrame(step); else step(t0);
}

function closeBurst(pw, wheel, burst) {
  pw.burstFor = null;
  burst.replaceChildren();
  burst.classList.remove('is-open');
  wheel.parentNode?.classList.remove('is-open');
  moveWheel(pw, wheel, 1, 0);
}

function openBurst(pw, wheel, burst, node, c, sel) {
  if (!node || !c) return closeBurst(pw, wheel, burst);
  const right = Math.sin((node.mid * Math.PI) / 180) >= 0;     // the list goes on the side the competency faces
  const dx = right ? -OPEN.shift : OPEN.shift, cx = C + dx, k = OPEN.scale;
  wheel.parentNode?.classList.add('is-open');
  moveWheel(pw, wheel, k, dx);
  const picked = sel?.kind === 'skill' ? sel.id : null;
  if (pw.burstFor === c.id) {
    // Same competency: only the picked skill changes.
    burst.querySelectorAll('[data-skill]').forEach(n => n.classList.toggle('is-on', n.dataset.skill === picked));
    return;
  }
  pw.burstFor = c.id;
  burst.replaceChildren();
  burst.classList.remove('is-open');

  // The list: the competency's name and count, then one row per skill.
  const x = right ? cx + OPEN.column : cx - OPEN.column - OPEN.columnWidth;
  const fo = svgEl('foreignObject', { x: f(x), y: 0, width: OPEN.columnWidth, height: SIZE, class: 'pw-burst-fo' });
  const col = el('div', 'pw-burst-list' + (right ? '' : ' is-left'));
  const head = el('div', 'pw-burst-head');
  head.append(el('div', 'pw-burst-title', `${c.name} (${c.num})`),
    el('div', 'pw-burst-n', `${programs(c.programs)} naming a goal in this competency`));
  col.append(head);
  const rows = c.skills.map(sk => {
    const b = el('button', 'pw-burst-row' + (sk.programs ? '' : ' is-zero') + (sk.id === picked ? ' is-on' : ''));
    b.type = 'button';
    b.dataset.skill = sk.id;
    b.append(el('span', 'pw-burst-name', `${sk.name} (${sk.num})`),
      el('span', 'pw-burst-count', sk.programs ? programs(sk.programs) : 'none yet'));
    b.setAttribute('aria-label', `${sk.name} (${sk.num}): ${sk.programs ? programs(sk.programs) : 'no programs yet'} naming a goal in this skill`);
    activate(b, () => pick(pw, { kind: 'skill', id: sk.id }));
    col.append(b);
    return b;
  });
  fo.append(col);
  burst.append(fo);

  // Rays and leader lines need the rows' heights, so they are drawn once the list has been laid out.
  requestAnimationFrame(() => {
    if (pw.burstFor !== c.id) return;
    const ys = rows.map(r => r.offsetTop + 10);
    const n = c.skills.length, spread = Math.min(11, 66 / n);
    const lean = right ? 90 : 270, turn = ((lean - node.mid + 540) % 360) - 180;
    const centre = node.mid + Math.max(-40, Math.min(40, turn * 0.5));
    const at = (r, deg) => { const [px, py] = point(r, deg); return [px + dx, py]; };
    const r0 = R.compOut * k + OPEN.rayFrom;
    // The topmost ray goes to the topmost row, so leader lines never cross.
    const angles = c.skills.map((_, i) => centre + (i - (n - 1) / 2) * spread)
      .sort((a, b) => at(100, a)[1] - at(100, b)[1]);
    const max = Math.max(1, ...c.skills.map(sk => sk.programs));
    const lx = right ? x - 6 : x + OPEN.columnWidth + 6;
    c.skills.forEach((sk, i) => {
      const deg = angles[i];
      const len = sk.programs ? OPEN.rayMin + OPEN.rayMax * Math.sqrt(sk.programs / max) : 10;
      const [x0, y0] = at(r0, deg), [x1, y1] = at(r0 + len, deg), ty = ys[i];
      const g = svgEl('g', { class: 'pw-ray' + (sk.programs ? '' : ' is-zero') + (sk.id === picked ? ' is-on' : ''),
        'data-skill': sk.id, 'aria-hidden': 'true' });
      g.append(svgEl('path', { class: 'pw-leader',
        d: `M${f(x1)},${f(y1)} C${f((x1 + lx) / 2)},${f(y1)} ${f((x1 + lx) / 2)},${f(ty)} ${f(lx)},${f(ty)}` }));
      g.append(svgEl('line', { class: 'pw-ray-line', x1: f(x0), y1: f(y0), x2: f(x1), y2: f(y1),
        stroke: sk.programs ? node.slice.color : '#94a3b8' }));
      g.addEventListener('click', () => pick(pw, { kind: 'skill', id: sk.id }));
      burst.insertBefore(g, fo);
    });
    burst.classList.add('is-open');
  });
}

/** A pale tint of a slice colour for its competency ring, so navy names read on it. */
function tint(hex, amount = 0.22) {
  const n = parseInt(hex.slice(1), 16);
  const mix = c => Math.round(255 - (255 - c) * amount);
  return `rgb(${mix(n >> 16)}, ${mix((n >> 8) & 255)}, ${mix(n & 255)})`;
}

/** Greedy wrap where line k may be at most widths[k] wide; null when the words need more lines. */
function wrapTo(text, widths, px) {
  const lines = [];
  let line = '';
  for (const word of text.split(/\s+/)) {
    const next = line ? `${line} ${word}` : word;
    const room = widths[lines.length];
    if (room === undefined) return null;
    if (!line || textWidth(next, px) <= room) line = next;
    else { lines.push(line); line = word; }
  }
  if (line) lines.push(line);
  return lines.length <= widths.length && lines.every((l, k) => textWidth(l, px) <= widths[k]) ? lines : null;
}

/** A competency's name and count along its arc of the ring, wrapped to fit, reading left to right.
 *  Each line is measured at its own radius, since the outer lines have more room than the inner ones. */
function ringLabel(g, defs, idBase, name, count, a0, a1, isUpper) {
  const thick = R.compOut - R.compIn;
  const widthAt = r => (r * (a1 - a0) * Math.PI) / 180 - 14;
  // Baseline radii for a block of n lines, centred across the ring; line 0 is the one read first.
  const radii = (n, px) => {
    const lh = px * RING_LINE, cap = px * 0.72;
    const offset = Math.max(4, (thick - ((n - 1) * lh + cap)) / 2);
    return Array.from({ length: n }, (_, k) =>
      isUpper ? R.compOut - offset - cap - k * lh : R.compIn + offset + cap + k * lh);
  };
  // The tightest line of a glyph is where its letters reach nearest the centre.
  const room = (r, px) => widthAt(isUpper ? r : r - px * 0.72);
  let lines = null, px = RING_FONT[0];
  search:
  for (const size of RING_FONT) {
    px = size;
    for (let n = 1; n <= RING_LINES; n++) {
      const rs = radii(n + 1, size);
      lines = wrapTo(name, rs.slice(0, n).map(r => room(r, size)), size);
      if (lines) break search;
    }
  }
  if (!lines) {   // still too long: cut the last line (the full name is in the panel and the tooltip)
    const rs = radii(RING_LINES + 1, px);
    const widths = rs.slice(0, RING_LINES).map(r => room(r, px));
    lines = [];
    let rest = name.split(/\s+/);
    for (let k = 0; k < RING_LINES; k++) {
      let line = '';
      while (rest.length && (!line || textWidth(`${line} ${rest[0]}`, px) <= widths[k])) line = line ? `${line} ${rest.shift()}` : rest.shift();
      lines.push(line);
    }
    if (rest.length) {
      let last = lines[RING_LINES - 1];
      while (last.length > 1 && textWidth(last + '…', px) > widths[RING_LINES - 1]) last = last.slice(0, -1);
      lines[RING_LINES - 1] = last.trimEnd() + '…';
    }
  }
  const all = [...lines, count];
  radii(all.length, px).forEach((r, k) => {
    const id = `${idBase}-${k}`;
    defs.append(svgEl('path', { id, d: arc(r, a0 + 0.5, a1 - 0.5, isUpper) }));
    const t = svgEl('text', { class: k === all.length - 1 ? 'pw-ring-n' : 'pw-ring-text', 'font-size': px });
    t.append(svgEl('textPath', { href: `#${id}`, startOffset: '50%', 'text-anchor': 'middle' }, all[k]));
    g.append(t);
  });
}

// ---------------------------------------------------------------- side panel

function drawPanel(panel, pw, sliceOf) {
  const data = pw.data, sel = pw.sel;
  const inner = el('div', 'pw-panel-inner');
  const swatchRow = (color, text) => {
    const row = el('div', 'pw-eyebrow');
    const sw = el('span', 'pw-swatch');
    sw.style.background = color;
    row.append(sw, el('span', '', text));
    return row;
  };
  const link = (text, sel2, cls = 'pw-link') => {
    const b = el('button', cls, text);
    b.type = 'button';
    activate(b, () => pick(pw, sel2));
    return b;
  };
  const examples = list => {
    const ul = el('ul', 'pw-examples');
    list.forEach(p => ul.append(outcomeItem(p)));
    return ul;
  };

  if (!sel) {
    inner.append(el('div', 'pw-eyebrow', 'Portrait of a Graduate'),
      el('div', 'pw-title', 'Pick a slice or a competency'),
      el('p', 'pw-statement', 'Its skills, their “I can” statements and example partner goals open here. Every number counts programs naming a goal there.'));
    for (const s of data.slices) {
      const block = el('div', 'pw-index');
      const head = link('', { kind: 'slice', id: s.id }, 'pw-index-slice');
      const sw = el('span', 'pw-swatch');
      sw.style.background = s.color;
      head.append(sw, el('span', 'pw-index-name', s.name), el('span', 'pw-index-n', programs(s.programs)));
      block.append(head);
      for (const cid of s.competencies) {
        const c = data.competencies[cid];
        const row = link('', { kind: 'competency', id: cid }, 'pw-index-comp');
        row.append(el('span', 'pw-index-name', `${c.name} (${c.num})`), el('span', 'pw-index-n', String(c.programs)));
        block.append(row);
      }
      inner.append(block);
    }
  } else if (sel.kind === 'slice') {
    const s = data.slices.find(x => x.id === sel.id);
    inner.append(swatchRow(s.color, data.halves[s.half]), el('div', 'pw-title', s.name),
      el('p', 'pw-count', `${programs(s.programs)} naming a goal in this slice`));
    for (const cid of s.competencies) {
      const c = data.competencies[cid];
      const block = el('div', 'pw-comp-block');
      block.append(link(`${c.name} (${c.num})`, { kind: 'competency', id: cid }, 'pw-comp-name'),
        el('p', 'pw-statement', c.statement),
        el('p', 'pw-count', `${programs(c.programs)} naming a goal in this competency`));
      const ul = el('ul', 'pw-skill-index');
      for (const sk of c.skills) {
        const li = el('li');
        li.append(el('span', '', `${sk.name} (${sk.num})`), el('span', 'pw-index-n', sk.programs ? String(sk.programs) : 'none'));
        ul.append(li);
      }
      block.append(ul);
      inner.append(block);
    }
    inner.append(el('p', 'pw-hint', 'Open a competency to see its skills’ “I can” statements and example partner goals.'));
  } else if (sel.kind === 'outside') {
    const o = data.outside.find(x => x.id === sel.id);
    inner.append(el('div', 'pw-eyebrow', 'Results the Portrait does not name'), el('div', 'pw-title', o.name),
      el('p', 'pw-count', `${programs(o.programs)} naming a goal of this kind`),
      el('p', 'pw-statement', o.youth
        ? 'A result for young people that no Portrait skill names. This group is the codebook’s own; it is not part of the Portrait.'
        : 'A result for families, staff, programs or systems rather than for young people, so it is left out of every figure about young people. This group is the codebook’s own; it is not part of the Portrait.'));
    if (o.examples.length) inner.append(el('div', 'pw-sub', 'Example partner goals'), examples(o.examples));
  } else {
    const cid = sel.kind === 'skill' ? sel.id.split('.').slice(0, 2).join('.') : sel.id;
    const c = data.competencies[cid];
    const s = sliceOf.get(cid);
    if (!c || !s) { panel.replaceChildren(inner); return; }
    const back = link('', { kind: 'slice', id: s.id }, 'pw-eyebrow pw-back');
    const sw = el('span', 'pw-swatch');
    sw.style.background = s.color;
    back.append(sw, el('span', '', s.name));
    inner.append(back, el('div', 'pw-title', `${c.name} (${c.num})`), el('p', 'pw-statement', c.statement),
      el('p', 'pw-count', `${programs(c.programs)} naming a goal in this competency`));
    if (c.onlyPrograms) {
      const only = el('div', 'pw-skill' + (sel.kind === 'only' ? ' is-on' : ''));
      only.append(link('Named the competency but no single skill', { kind: 'only', id: cid }, 'pw-skill-name'),
        el('p', 'pw-count', `${programs(c.onlyPrograms)} naming a goal in this competency without a single skill`),
        examples(c.onlyExamples));
      inner.append(only);
    }
    const named = c.skills.filter(x => x.programs > 0);
    const unnamed = c.skills.filter(x => x.programs === 0);
    if (named.length) inner.append(el('div', 'pw-sub', 'Skills'));
    let focus = null;
    for (const sk of named) {
      const on = sel.kind === 'skill' && sel.id === sk.id;
      const box = el('div', 'pw-skill' + (on ? ' is-on' : ''));
      box.append(link(`${sk.name} (${sk.num})`, { kind: 'skill', id: sk.id }, 'pw-skill-name'),
        el('p', 'pw-statement', sk.statement),
        el('p', 'pw-count', `${programs(sk.programs)} naming a goal in this skill`),
        examples(sk.examples));
      if (on) focus = box;
      inner.append(box);
    }
    if (unnamed.length) {
      inner.append(el('div', 'pw-sub', 'Skills no partner program names yet'));
      const ul = el('ul', 'pw-plain');
      for (const sk of unnamed) {
        const li = el('li');
        li.append(el('span', 'pw-plain-name', `${sk.name} (${sk.num})`), el('span', 'pw-plain-statement', sk.statement));
        ul.append(li);
      }
      inner.append(ul);
    }
    panel.replaceChildren(inner);
    // Scroll only the panel, never the page, so nothing moves under the pointer.
    panel.scrollTop = focus ? Math.max(0, focus.offsetTop - inner.offsetTop - 8) : 0;
    return;
  }
  panel.replaceChildren(inner);
  panel.scrollTop = 0;
}
