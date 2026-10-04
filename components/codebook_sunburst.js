// The codebook sunburst: domains on the inner ring, their goals on the outer
// ring, drawn as SVG in the browser so hovering costs no round trip to Python.
//
// Modeled on the codebook explorer's sunburst (the coder repo's
// components/CodebookSunburst.tsx): the hovered slice lifts out and darkens,
// the rest of the ring fades, and the centre says what the slice is. A side
// readout adds the counts and a few real outcome statements.
//
// Clicking a domain opens it (its goals fill the ring), clicking a goal picks
// it, and clicking the centre goes back. Each click sends the picked domain
// and goal to Python as the "selection" state, which filters the table below.
// Python sends `data` (see sunburst_component.py); `data.sig` changes only
// when the counts change, so reruns caused by a click leave the chart alone.
//
// With `data.layout === 'equal'` it is the equal-slice wheel instead: every
// goal gets the same angle, and its count sets how far its bar reaches out
// from the domain ring. A goal no program names keeps its place as a short
// dashed stub, so gaps stay visible instead of shrinking to a hairline.

const SIZE = 600;
const C = SIZE / 2;
const R_VALUE = { hole: 138, domain: 202, goal: 284 };
const R_EQUAL = { hole: 104, domain: 152, goal: 290 };   // a smaller centre leaves the bars room to grow
const STUB = 14;             // depth of a zero goal's dashed stub, and the shortest bar
const POP = 1.04;            // how far the active goal lifts out of the ring
const ANIM_MS = 520;         // zoom in / out
const LEAVE_MS = 70;         // grace period so moving between slices doesn't flash the resting readout
const MIN_LABEL_DEG = { domain: 9, goal: 8 };

const SVG_NS = 'http://www.w3.org/2000/svg';
const reducedMotion = () => !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

// ---------------------------------------------------------------- geometry

const point = (r, deg) => {
  const rad = ((deg - 90) * Math.PI) / 180;
  return [C + r * Math.cos(rad), C + r * Math.sin(rad)];
};
const f = n => Number(n.toFixed(2));

/** SVG path for a ring segment between two radii and two angles (degrees clockwise from 12 o'clock). */
function arcPath(r0, r1, start, end) {
  const sweep = end - start;
  if (sweep <= 0.001) return '';
  if (sweep >= 359.9) {
    // A full ring can't be one arc (its ends would meet): draw both circles and let
    // the even-odd rule (set on the slices) cut the hole.
    const circle = r => `M${C} ${C - r}A${r} ${r} 0 1 1 ${C} ${C + r}A${r} ${r} 0 1 1 ${C} ${C - r}Z`;
    return circle(r1) + circle(r0);
  }
  const large = sweep > 180 ? 1 : 0;
  const e = start + sweep;
  const [x0, y0] = point(r1, start);
  const [x1, y1] = point(r1, e);
  const [x2, y2] = point(r0, e);
  const [x3, y3] = point(r0, start);
  return `M${f(x0)} ${f(y0)}A${r1} ${r1} 0 ${large} 1 ${f(x1)} ${f(y1)}L${f(x2)} ${f(y2)}A${r0} ${r0} 0 ${large} 0 ${f(x3)} ${f(y3)}Z`;
}

/** Where every slice sits when `zoom` (a domain id, or null) is open. */
function targetAngles(model, zoom) {
  const out = new Map();
  // The wheel weighs every goal the same, so a domain's arc follows how many goals it has.
  const weight = n => (!model.equal ? n.value
    : n.level === 'domain' ? Math.max((model.children.get(n.id) || []).length, 1) : 1);
  const placeGoals = (domain, a0, a1) => {
    const goals = model.children.get(domain.id) || [];
    const total = goals.reduce((n, g) => n + weight(g), 0) || 1;
    let a = a0;
    for (const g of goals) {
      const span = ((a1 - a0) * weight(g)) / total;
      out.set(g.id, [a, a + span]);
      a += span;
    }
  };
  if (!zoom) {
    const total = model.domains.reduce((n, d) => n + weight(d), 0) || 1;
    let a = 0;
    for (const d of model.domains) {
      const span = (360 * weight(d)) / total;
      out.set(d.id, [a, a + span]);
      placeGoals(d, a, a + span);
      a += span;
    }
  } else {
    // The open domain fills the ring; the others fold away to either side of it.
    let edge = 0;
    for (const d of model.domains) {
      if (d.id === zoom) {
        out.set(d.id, [0, 360]);
        placeGoals(d, 0, 360);
        edge = 360;
      } else {
        out.set(d.id, [edge, edge]);
        placeGoals(d, edge, edge);
      }
    }
  }
  return out;
}

// ---------------------------------------------------------------- colour

function fills(node, state) {
  const { activeDomain, activeId, hovering } = state;
  const h = node.hue;
  const grey = h === null || h === undefined;
  if (node.level === 'domain') {
    const on = activeDomain === node.id;
    return {
      fill: grey ? (on ? '#7c8492' : '#9aa1ad') : `hsl(${h} ${on ? 60 : 55}% ${on ? 42 : 52}%)`,
      opacity: hovering && !on ? 0.35 : 1,
    };
  }
  const on = activeId === node.id || state.pick === node.id;
  const inDomain = activeDomain === node.parent;
  if (state.equal) {
    return {
      fill: node.count === 0 ? '#fff' : grey ? (on ? '#7c8492' : '#cbd5e1')
        : on ? `hsl(${h} 62% 40%)` : `hsl(${h} 58% ${inDomain ? 52 : 60}%)`,
      opacity: hovering && !inDomain ? 0.3 : 1,
      lift: on && (activeId === node.id || !hovering),
    };
  }
  return {
    fill: grey
      ? (on ? '#9aa1ad' : '#e3e6ea')
      : on ? `hsl(${h} 62% 46%)` : `hsl(${h} 70% ${inDomain ? 72 : 80}%)`,
    opacity: hovering && !inDomain ? 0.3 : 1,
    lift: on && (activeId === node.id || !hovering),
  };
}

const swatchColor = node =>
  node.hue === null || node.hue === undefined ? '#9aa1ad' : `hsl(${node.hue} 55% 52%)`;

// ---------------------------------------------------------------- DOM helpers

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = text;
  return e;
}
function svgEl(tag, attrs) {
  const e = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v);
  return e;
}
const fmt = n => Number(n || 0).toLocaleString('en-US');
const plural = (n, one, many) => `${fmt(n)} ${n === 1 ? one : many}`;

// ---------------------------------------------------------------- component

export default function (component) {
  const { data, parentElement, setStateValue } = component;
  if (!data || !data.nodes) return;
  let root = parentElement.querySelector('.sb');
  if (!root) {
    root = el('div', 'sb');
    parentElement.appendChild(root);
  }
  const sb = root.__sb || (root.__sb = { sig: null, hover: null, zoom: null, pick: null, angles: new Map(), first: true });
  sb.send = setStateValue;
  if (sb.sig !== data.sig) mount(root, sb, data);
}

function mount(root, sb, data) {
  const model = { byId: new Map(), domains: [], children: new Map(), root: null, data, equal: data.layout === 'equal' };
  for (const n of data.nodes) {
    model.byId.set(n.id, n);
    if (n.level === 'root') model.root = n;
    else if (n.level === 'domain') model.domains.push(n);
    else {
      if (!model.children.has(n.parent)) model.children.set(n.parent, []);
      model.children.get(n.parent).push(n);
    }
  }
  const firstMount = sb.sig === null;
  sb.sig = data.sig;
  sb.model = model;
  sb.R = model.equal ? R_EQUAL : R_VALUE;
  sb.maxCount = Math.max(1, ...data.nodes.filter(n => n.level === 'goal').map(n => n.count));

  // The pick comes from Python on the first draw (a page revisit); after that the chart owns it.
  if (firstMount && data.selected) {
    const d = data.selected.domain;
    const g = data.selected.goal;
    const goalId = g ? `${d}${data.sep}${g}` : null;
    if (model.byId.has(d)) {
      sb.zoom = d;
      sb.pick = goalId && model.byId.has(goalId) ? goalId : d;
    }
  }
  // New counts (another measure or filter) keep the open domain if it is still there.
  if (sb.zoom && !model.byId.has(sb.zoom)) sb.zoom = null;
  if (sb.pick && !model.byId.has(sb.pick)) {
    sb.pick = sb.zoom;
    sb.send('selection', selectionOf(model, sb.pick));
  }
  sb.hover = null;

  root.replaceChildren();
  root.classList.toggle('sb-equal', model.equal);
  const figure = el('div', 'sb-figure');
  const svg = svgEl('svg', {
    viewBox: `0 0 ${SIZE} ${SIZE}`, class: 'sb-svg', role: 'group',
    'aria-label': model.equal
      ? `${model.domains.length} domains and their goals, one equal slice per goal; bar length shows ${data.noun}. Each slice is a button.`
      : `${model.domains.length} domains and their goals, sized by ${data.noun}. Each slice is a button.`,
  });
  const trackLayer = svgEl('g');
  const goalLayer = svgEl('g');
  const domainLayer = svgEl('g');
  const labelLayer = svgEl('g');
  const hole = svgEl('circle', { cx: C, cy: C, r: sb.R.hole - 3, class: 'sb-hole' });
  svg.append(trackLayer, goalLayer, domainLayer, hole, labelLayer);
  const center = el('div', 'sb-center');
  figure.append(svg, center);
  const panel = el('div', 'sb-panel');
  root.append(figure, panel);

  sb.els = { svg, hole, center, panel, slices: new Map(), labels: new Map(), tracks: new Map() };
  const animate = firstMount && !reducedMotion();
  if (animate) svg.classList.add('sb-enter');

  let i = 0;
  for (const n of data.nodes) {
    if (n.level === 'root') continue;
    const gap = model.equal && n.level === 'goal' && n.count === 0;
    const path = svgEl('path', {
      class: 'sb-slice', stroke: gap ? '#94a3b8' : '#fff', 'fill-rule': 'evenodd',
      'stroke-width': n.level === 'domain' ? 2 : 1.25,
      tabindex: 0, role: 'button', 'aria-label': `${n.eyebrow}: ${n.title}, ${plural(n.count, data.noun_one, data.noun)}`,
    });
    if (gap) path.setAttribute('stroke-dasharray', '3 2');
    if (model.equal && n.level === 'goal') {
      // The pale track behind each bar shows how far the bar could reach.
      const track = svgEl('path', { class: 'sb-track', fill: '#f1f5f9', stroke: '#fff', 'stroke-width': 1.25 });
      trackLayer.appendChild(track);
      sb.els.tracks.set(n.id, track);
    }
    path.style.transformOrigin = `${C}px ${C}px`;
    if (animate) path.style.animationDelay = n.level === 'domain' ? `${i * 40}ms` : `${120 + i * 6}ms`;
    i += 1;
    (n.level === 'domain' ? domainLayer : goalLayer).appendChild(path);
    sb.els.slices.set(n.id, path);
    if (n.label) {
      const text = svgEl('text', {
        class: 'sb-label', 'text-anchor': 'middle', 'dominant-baseline': 'central',
        'font-size': n.level === 'domain' ? 17 : 14, 'font-weight': 600,
      });
      text.textContent = n.label;
      labelLayer.appendChild(text);
      sb.els.labels.set(n.id, text);
    }
    wire(path, n, sb);
  }
  if (animate) setTimeout(() => svg.classList.remove('sb-enter'), 1600);

  hole.addEventListener('click', () => { if (sb.zoom) choose(sb, null, null); });
  svg.addEventListener('pointerleave', () => setHover(sb, null));

  sb.angles = firstMount || !sb.angles.size ? targetAngles(model, sb.zoom) : sb.angles;
  // Slices that are new since the last draw grow from where their domain sits.
  const target = targetAngles(model, sb.zoom);
  for (const [id, t] of target) if (!sb.angles.has(id)) sb.angles.set(id, [t[0], t[0]]);
  sb.focusKey = null;
  draw(sb);
  if (!firstMount) tween(sb, target);
}

function wire(path, node, sb) {
  path.addEventListener('pointerenter', () => setHover(sb, node.id));
  path.addEventListener('pointerleave', () => setHover(sb, null));
  path.addEventListener('focus', () => setHover(sb, node.id, true));
  path.addEventListener('blur', () => setHover(sb, null, true));
  path.addEventListener('click', () => clickNode(sb, node));
  path.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); clickNode(sb, node); }
    if (e.key === 'Escape' && sb.zoom) { e.preventDefault(); choose(sb, null, null); }
  });
}

function setHover(sb, id, now) {
  clearTimeout(sb.leaveTimer);
  if (id === null && !now) {
    sb.leaveTimer = setTimeout(() => { sb.hover = null; paint(sb); }, LEAVE_MS);
    return;
  }
  if (sb.hover === id) return;
  sb.hover = id;
  paint(sb);
}

function clickNode(sb, node) {
  if (node.level === 'domain') {
    if (sb.zoom === node.id) choose(sb, null, null);
    else choose(sb, node.id, node.id);
  } else if (sb.zoom !== node.parent) {
    choose(sb, node.parent, node.id);
  } else {
    choose(sb, node.parent, sb.pick === node.id ? node.parent : node.id);
  }
}

function selectionOf(model, pickId) {
  const n = pickId ? model.byId.get(pickId) : null;
  if (!n) return null;
  return n.level === 'domain' ? { domain: n.id, goal: null } : { domain: n.parent, goal: n.goal };
}

function choose(sb, zoom, pick) {
  const zoomChanged = zoom !== sb.zoom;
  sb.zoom = zoom;
  sb.pick = pick;
  sb.send('selection', selectionOf(sb.model, pick));
  if (zoomChanged) tween(sb, targetAngles(sb.model, zoom));
  else paint(sb);
}

// ---------------------------------------------------------------- drawing

function tween(sb, target) {
  cancelAnimationFrame(sb.frame);
  const from = new Map(sb.angles);
  if (reducedMotion()) {
    sb.angles = target;
    draw(sb);
    return;
  }
  const t0 = performance.now();
  const ease = t => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
  const step = now => {
    const k = ease(Math.min((now - t0) / ANIM_MS, 1));
    const next = new Map();
    for (const [id, [b0, b1]] of target) {
      const [a0, a1] = from.get(id) || [b0, b0];
      next.set(id, [a0 + (b0 - a0) * k, a1 + (b1 - a1) * k]);
    }
    sb.angles = next;
    draw(sb);
    if (k < 1) sb.frame = requestAnimationFrame(step);
  };
  sb.frame = requestAnimationFrame(step);
}

/** How far a goal's slice reaches: the full ring in the sunburst, its bar length on the wheel. */
function outerRadius(sb, n) {
  const R = sb.R;
  if (!sb.model.equal) return R.goal;
  const base = R.domain + 3;
  if (n.count === 0) return base + STUB;
  // Square root, so the bar's area (not its length) follows the count, and thin goals stay visible.
  return base + STUB + Math.sqrt(n.count / sb.maxCount) * (R.goal - base - STUB);
}

function draw(sb) {
  const { model, els } = sb;
  const R = sb.R;
  for (const [id, track] of els.tracks) {
    const [a0, a1] = sb.angles.get(id) || [0, 0];
    track.setAttribute('d', arcPath(R.domain + 3, R.goal, a0, a1));
  }
  for (const [id, path] of els.slices) {
    const n = model.byId.get(id);
    const [a0, a1] = sb.angles.get(id) || [0, 0];
    const d = n.level === 'domain' ? arcPath(R.hole, R.domain, a0, a1) : arcPath(R.domain + 3, outerRadius(sb, n), a0, a1);
    path.setAttribute('d', d);
    const hidden = !d;
    path.style.display = hidden ? 'none' : '';
    path.setAttribute('tabindex', hidden ? -1 : 0);
    const label = els.labels.get(id);
    if (label) {
      const span = a1 - a0;
      const show = n.level === 'domain'
        ? !sb.zoom && span >= MIN_LABEL_DEG.domain
        : !!sb.zoom && span >= MIN_LABEL_DEG.goal;
      const [x, y] = n.level === 'domain'
        ? point((R.hole + R.domain) / 2, (a0 + a1) / 2)
        : point(model.equal ? R.goal - 16 : (R.domain + R.goal) / 2 + 2, (a0 + a1) / 2);
      label.setAttribute('x', f(x));
      label.setAttribute('y', f(y));
      label.style.display = show ? '' : 'none';
    }
  }
  els.hole.classList.toggle('can-go-up', !!sb.zoom);
  paint(sb);
}

function paint(sb) {
  const { model, els } = sb;
  const hovered = sb.hover ? model.byId.get(sb.hover) : null;
  const picked = sb.pick ? model.byId.get(sb.pick) : null;
  const lead = hovered || picked;
  const activeDomain = lead ? (lead.level === 'domain' ? lead.id : lead.parent) : null;
  const state = { activeDomain, activeId: sb.hover, hovering: !!hovered, pick: sb.pick, equal: model.equal };
  for (const [id, path] of els.slices) {
    const n = model.byId.get(id);
    const look = fills(n, state);
    path.setAttribute('fill', look.fill);
    path.setAttribute('fill-opacity', look.opacity);
    path.style.transform = look.lift ? `scale(${POP})` : '';
    const label = els.labels.get(id);
    if (label) {
      label.setAttribute('fill', n.level === 'domain' ? '#fff' : (n.hue === null || n.hue === undefined
        ? '#334155' : model.equal ? `hsl(${n.hue} 45% 18%)` : `hsl(${n.hue} 55% ${look.lift ? 97 : 26}%)`));
      label.style.opacity = look.opacity < 1 ? 0.55 : 1;
    }
  }
  readout(sb, hovered);
}

function readout(sb, hovered) {
  const { model, els } = sb;
  const data = model.data;
  const zoomed = sb.zoom ? model.byId.get(sb.zoom) : null;
  const picked = sb.pick ? model.byId.get(sb.pick) : null;
  const focus = hovered || picked || zoomed || model.root;
  const key = `${focus.id}|${sb.zoom}|${sb.pick}|${!!hovered}`;
  if (key === sb.focusKey) return;
  const focusChanged = !sb.focusKey || sb.focusKey.split('|')[0] !== focus.id;
  sb.focusKey = key;

  // Centre
  const inner = el('div', 'sb-center-inner' + (focusChanged ? ' sb-fade' : ''));
  if (focus.level === 'root') {
    inner.append(el('div', 'sb-big', fmt(focus.count)), el('div', 'sb-meta', `${data.noun} in ${data.n_domains} domains`));
  } else {
    inner.append(
      el('div', 'sb-eyebrow', focus.eyebrow),
      el('div', 'sb-title', focus.title),
      el('div', 'sb-meta', plural(focus.count, data.noun_one, data.noun)),
    );
    if (zoomed && !hovered) inner.append(el('div', 'sb-back', '‹ All domains'));
  }
  els.center.replaceChildren(inner);

  // Side panel
  const panel = els.panel;
  const box = el('div', 'sb-panel-inner' + (focusChanged ? ' sb-fade' : ''));
  const eyebrow = el('div', 'sb-eyebrow');
  if (focus.level !== 'root') {
    const sw = el('span', 'sb-swatch');
    sw.style.background = swatchColor(focus);
    eyebrow.append(sw);
  }
  eyebrow.append(document.createTextNode(focus.level === 'root' ? 'The whole portfolio' : focus.eyebrow));
  const title = el('div', 'sb-title', focus.level === 'root' ? 'All domains' : focus.title);
  const counts = el('ul', 'sb-counts');
  for (const [n, one, many] of [[focus.programs, 'program', 'programs'], [focus.organizations, 'organization', 'organizations'],
    [focus.outcomes, 'outcome statement', 'outcome statements']]) {
    const li = el('li');
    li.append(el('b', '', fmt(n)), document.createTextNode(n === 1 ? one : many));
    counts.append(li);
  }
  const children = [eyebrow, title, counts];
  if (focus.level !== 'root') {
    const share = model.root.count ? focus.count / model.root.count : 0;
    const bar = el('div', 'sb-share');
    const fill = el('span');
    fill.style.width = focus.count ? `${Math.max(share * 100, 1.5)}%` : '0';
    fill.style.background = swatchColor(focus);
    bar.append(fill);
    children.push(bar, el('div', 'sb-share-note', focus.level === 'goal' && focus.count === 0
      ? 'No program in this view names this goal yet.'
      : `${Math.round(share * 100)}% of all ${data.noun}`));
  }
  if (focus.samples && focus.samples.length) {
    const list = el('ul', 'sb-samples');
    for (const s of focus.samples) list.append(el('li', '', `“${s}”`));
    children.push(el('div', 'sb-eyebrow sb-samples-head', 'Sample outcomes'), list);
  }
  children.push(el('div', 'sb-hint', hint(sb, hovered)));
  box.append(...children);
  panel.replaceChildren(box);
}

function hint(sb, hovered) {
  if (hovered) {
    if (hovered.level === 'domain') return sb.zoom === hovered.id ? 'Click to go back to all domains.' : 'Click to open its goals.';
    if (sb.pick === hovered.id) return 'Click again to show the whole domain.';
    return hovered.count ? 'Click to list its outcomes in the table below.' : 'Nothing to list yet.';
  }
  if (sb.zoom) return 'Click the center to go back to all domains.';
  return 'Point at a slice to read it. Click a domain to open its goals.';
}
