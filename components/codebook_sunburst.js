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
// When the nodes include the codebook's categories (level "category"), the
// wheel rests on domains and categories: each category is one equal slice
// whose bar shows how many programs name any of its goals, and a row of dots
// at its base shows its goals: filled for a goal some program names, hollow
// for a gap. Pointing at a category lists its goals (the subcategories)
// beside the chart. Clicking a category opens its domain, where a
// thin category ring carries the category names and the goals are the bars,
// and narrows the table to that category's goals.
//
// The search box above the chart greys out every slice that doesn't contain
// what was typed, while the reader types, with no round trip to Python. A
// goal matches when its name or the codebook's description of it does (so
// "mentoring" finds Supportive adults), or when outcome statements under it
// do; then its colour fills only the share of it that matches. `data.search`
// carries the statements and codebook words (outcomes_data.chart_search_index).

const SIZE = 600;
const C = SIZE / 2;
const R_VALUE = { hole: 138, domain: 202, goal: 284 };
const R_EQUAL = { hole: 104, domain: 150, cat: 178, goal: 290 };   // a smaller centre leaves the bars room to grow
const STUB = 14;             // depth of a zero goal's dashed stub, and the shortest bar
const POP = 1.04;            // how far the active goal lifts out of the ring
const ANIM_MS = 520;         // zoom in / out
const LEAVE_MS = 70;         // grace period so moving between slices doesn't flash the resting readout
const MIN_LABEL_DEG = { domain: 9, goal: 8, category: 4.5, categoryName: 30 };
const FAN = false;           // fan a pointed-at category's goals out over the wheel (off: the side list shows them)
const DOT = { r: 2.5, gap: 5.8, at: 28, row: 6.5 };   // the goal dots at a category bar's base
const FAN_STEP = 9;          // degrees per goal when a category fans its goals out
const FAN_MAX = 84;          // widest a fan gets
const MIN_QUERY = 2;         // characters before the search starts greying slices
const GREY = { domain: '#cbd5e1', goal: '#e2e8f0', label: '#94a3b8' };
let lastQuery = '';          // the search outlives a fresh chart (a cleared selection, a page revisit)

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
  // Resting on categories, each category weighs the same instead, shared among its goals.
  const catSlices = model.equal && model.cats.length && !zoom;
  const goalWeight = g => (catSlices && g.category ? 1 / (model.goalsOf.get(g.category) || [g]).length : 1);
  const weight = n => (!model.equal ? n.value
    : n.level === 'domain' ? Math.max((model.children.get(n.id) || []).reduce((t, g) => t + goalWeight(g), 0), 1)
      : goalWeight(n));
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
  // A category spans its goals (they sit next to each other, in codebook order).
  for (const c of model.cats) {
    const spans = (model.goalsOf.get(c.id) || []).map(g => out.get(g.id)).filter(Boolean);
    if (spans.length) out.set(c.id, [Math.min(...spans.map(a => a[0])), Math.max(...spans.map(a => a[1]))]);
  }
  return out;
}

/** True while the wheel rests on categories (it has them, and no domain is open). */
const catBars = sb => sb.model.equal && sb.model.cats.length > 0 && !sb.zoom;
/** Where a bar starts: just outside the domain ring, or outside the category ring in an open domain. */
const barBase = sb => (sb.model.cats.length && sb.zoom && sb.R.cat ? sb.R.cat : sb.R.domain) + 3;
/** Is this goal folded into its category bar right now (resting on categories, its category not pointed at)? */
const folded = (sb, n, openCat) => n.level === 'goal' && catBars(sb) && !!n.category && (!FAN || n.category !== openCat);

// ---------------------------------------------------------------- colour

/** The resting look, then greyed or paled by the search when one is active. */
function fills(node, state) {
  const look = baseFills(node, state);
  const hits = state.hits;
  if (!hits) return look;
  if (node.level === 'domain' || (node.level === 'category' && !state.catBars)) {
    if (!(node.level === 'domain' ? hits.domains : hits.cats).has(node.id)) look.fill = GREY.domain;
    return look;
  }
  const hit = node.level === 'category' ? hits.cats.get(node.id) : hits.goals.get(node.id);
  if (!hit) {
    if (!(state.equal && node.count === 0)) look.fill = GREY.goal;
  } else if (hit.partial) {
    // The slice keeps a pale wash of its hue; the overlay (see draw) fills the share that matches.
    look.overlay = look.fill;
    look.fill = node.hue === null || node.hue === undefined ? '#eef0f3' : `hsl(${node.hue} 55% 90%)`;
  } else if (state.equal && node.count === 0) {
    look.fill = `hsl(${node.hue ?? 215} 50% 88%)`;
  }
  return look;
}

function baseFills(node, state) {
  const { activeDomain, activeId, hovering } = state;
  if (node.level === 'category') {
    const grey = node.hue === null || node.hue === undefined;
    const on = state.activeCat === node.id || state.pick === node.id;
    const dim = hovering && (state.activeCat ? state.activeCat !== node.id : activeDomain !== node.parent);
    if (state.catBars) {
      // Resting on categories, a category is a bar like a goal's; pointed at, it pales so its goals show through.
      return {
        fill: node.count === 0 ? '#fff' : grey ? (on ? '#7c8492' : '#cbd5e1')
          : on ? `hsl(${node.hue} 62% 40%)` : `hsl(${node.hue} 58% ${activeDomain === node.parent ? 52 : 60}%)`,
        opacity: FAN && state.activeCat === node.id ? 0.18 : dim ? 0.3 : 1,
      };
    }
    return {
      fill: grey ? (on ? '#7c8492' : '#b6bcc6') : `hsl(${node.hue} ${on ? 55 : 45}% ${on ? 48 : 72}%)`,
      opacity: dim ? 0.35 : 1,
    };
  }
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
  const inDomain = activeDomain === node.parent && (!state.activeCat || node.category === state.activeCat);
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
  const sb = root.__sb || (root.__sb = { sig: null, hover: null, zoom: null, pick: null, angles: new Map(), first: true, query: lastQuery });
  sb.send = setStateValue;
  if (!sb.searchBar) sb.searchBar = searchBar(parentElement, root, sb);
  if (sb.sig !== data.sig) mount(root, sb, data);
}

// ---------------------------------------------------------------- search

const norm = s => String(s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
const words = q => {
  const w = norm(q).split(/\s+/).filter(Boolean);
  return w.join('').length >= MIN_QUERY ? w : [];
};

function searchBar(parentElement, root, sb) {
  const bar = el('div', 'sb-search');
  const box = el('label', 'sb-search-box');
  const icon = svgEl('svg', { viewBox: '0 0 20 20', width: 16, height: 16, 'aria-hidden': 'true', class: 'sb-search-icon' });
  icon.append(svgEl('circle', { cx: 8.5, cy: 8.5, r: 5.5, fill: 'none', stroke: 'currentColor', 'stroke-width': 1.8 }),
    svgEl('path', { d: 'M13 13l4 4', stroke: 'currentColor', 'stroke-width': 1.8, 'stroke-linecap': 'round' }));
  const input = el('input');
  Object.assign(input, { type: 'text', value: sb.query || '', placeholder: 'Search goals and outcomes, e.g. mentoring',
    autocomplete: 'off', spellcheck: false });
  input.setAttribute('aria-label', 'Search the chart: slices without the word turn grey');
  const clear = el('button', 'sb-search-clear', '×');
  Object.assign(clear, { type: 'button', title: 'Clear search' });
  clear.setAttribute('aria-label', 'Clear search');
  const note = el('span', 'sb-search-note');
  note.setAttribute('aria-live', 'polite');
  box.append(icon, input, clear);
  bar.append(box, note);
  parentElement.insertBefore(bar, root);

  let frame = 0;
  const update = () => {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => {
      sb.query = lastQuery = input.value;
      if (sb.model) { runSearch(sb); draw(sb); }
    });
  };
  input.addEventListener('input', update);
  input.addEventListener('keydown', e => { if (e.key === 'Escape' && input.value) { e.preventDefault(); input.value = ''; update(); } });
  clear.addEventListener('click', () => { input.value = ''; update(); input.focus(); });
  return { bar, input, clear, note };
}

/** Normalized text for the search, worked out once per drawing. */
function prepareSearch(model, data) {
  const s = data.search || {};
  const terms = s.terms || {};
  const names = new Map();
  for (const n of data.nodes) {
    if (n.level === 'root') continue;
    names.set(n.id, { title: norm(`${n.eyebrow} ${n.title}`), terms: norm(terms[n.id]) });
  }
  return { texts: (s.texts || []).map(norm), raw: s.texts || [], rows: s.rows || {}, names };
}

/** Which slices hold the query, and how much of each. Sets sb.hits (null when the box is empty). */
function runSearch(sb) {
  const { model, search } = sb;
  const w = words(sb.query);
  sb.hits = null;
  sb.focusKey = null;
  if (!w.length || !search) return updateNote(sb);
  // Each word must start a word in the text: "mentor" finds "mentoring", "reading" doesn't find "spreading".
  const res = w.map(x => new RegExp('(?:^|[^a-z0-9])' + escapeRe(x)));
  const has = t => res.every(r => r.test(t));
  const textHit = search.texts.map(has);
  const col = model.data.noun.startsWith('program') ? 1 : model.data.noun.startsWith('organization') ? 2 : -1;
  const goals = new Map();
  const domains = new Set();
  const all = [];
  const domainRows = new Map();
  for (const d of model.domains) {
    const dn = search.names.get(d.id);
    const titleHit = has(dn.title);
    if (titleHit || has(dn.terms)) domains.add(d.id);
    const dRows = [];
    for (const g of model.children.get(d.id) || []) {
      const gn = search.names.get(g.id);
      const rows = search.rows[g.id] || [];
      const named = titleHit || has(gn.title) || has(gn.terms);
      const matched = named ? rows : rows.filter(r => textHit[r[0]]);
      if (!named && !matched.length) continue;
      const count = named ? g.count : measure(matched, col);
      goals.set(g.id, { named, rows: matched, count, partial: !named && count < g.count && g.count > 0 });
      domains.add(d.id);
      dRows.push(...matched);
    }
    domainRows.set(d.id, dRows);
    all.push(...dRows);
  }
  // A category holds what its goals hold, or all of itself when its own name matches.
  const cats = new Map();
  for (const c of model.cats) {
    const titleHit = has(search.names.get(c.id).title) || has(search.names.get(c.parent).title);
    const members = model.goalsOf.get(c.id) || [];
    const rows = titleHit ? members.flatMap(g => search.rows[g.id] || [])
      : members.flatMap(g => (goals.get(g.id) || { rows: [] }).rows);
    if (!titleHit && !members.some(g => goals.has(g.id))) continue;
    const count = titleHit ? c.count : Math.min(measure(rows, col), c.count);
    cats.set(c.id, { named: titleHit, rows, count, partial: !titleHit && count < c.count && c.count > 0 });
    domains.add(c.parent);
    if (titleHit) {
      // Its goals light up with it, and count toward the totals.
      for (const g of members) {
        if (goals.has(g.id)) continue;
        const gRows = search.rows[g.id] || [];
        goals.set(g.id, { named: true, rows: gRows, count: g.count, partial: false });
        all.push(...gRows);
        domainRows.get(c.parent).push(...gRows);
      }
    }
  }
  const count = rows => ({ programs: measure(rows, 1), organizations: measure(rows, 2), outcomes: rows.length });
  sb.hits = { words: w, textHit, goals, cats, domains, domainRows, col, total: count(all), all };
  updateNote(sb);
}

const escapeRe = x => x.replace(/[.*+?^$()|[\]{}\\]/g, '\\$&');

function measure(rows, col) {
  if (col < 0) return rows.length;
  const seen = new Set();
  for (const r of rows) if (r[col] >= 0) seen.add(r[col]);
  return seen.size;
}

function updateNote(sb) {
  const ui = sb.searchBar;
  if (!ui) return;
  const hits = sb.hits;
  ui.bar.classList.toggle('has-query', !!sb.query);
  if (!hits) {
    ui.note.textContent = sb.query && words(sb.query).length === 0 ? 'Keep typing…' : '';
    return;
  }
  const g = hits.goals.size;
  ui.note.textContent = g
    ? `${plural(g, 'goal', 'goals')} in ${plural(hits.domains.size, 'domain', 'domains')} match`
    : 'No goal or outcome matches';
}

/** Up to `n` distinct statements among `rows` that contain the query, with the words marked. */
function matchingSamples(sb, rows, n = 3) {
  const out = [];
  const seen = new Set();
  for (const r of rows) {
    if (!sb.hits.textHit[r[0]] || seen.has(r[0])) continue;
    seen.add(r[0]);
    out.push(sb.search.raw[r[0]]);
    if (out.length >= n) break;
  }
  return out;
}

function marked(text, w) {
  const li = el('li');
  const pattern = new RegExp('\\b(' + w.map(escapeRe).join('|') + ')', 'gi');
  const clipped = text.length > 220 ? text.slice(0, 217).trimEnd() + '…' : text;
  li.append('“');
  clipped.split(pattern).forEach((part, i) => li.append(i % 2 ? el('mark', '', part) : document.createTextNode(part)));
  li.append('”');
  return li;
}

function mount(root, sb, data) {
  const model = { byId: new Map(), domains: [], cats: [], goalsOf: new Map(), children: new Map(), root: null, data, equal: data.layout === 'equal' };
  for (const n of data.nodes) {
    model.byId.set(n.id, n);
    if (n.level === 'root') model.root = n;
    else if (n.level === 'domain') model.domains.push(n);
    else if (n.level === 'category') model.cats.push(n);
    else {
      if (n.category) {
        if (!model.goalsOf.has(n.category)) model.goalsOf.set(n.category, []);
        model.goalsOf.get(n.category).push(n);
      }
      if (!model.children.has(n.parent)) model.children.set(n.parent, []);
      model.children.get(n.parent).push(n);
    }
  }
  const firstMount = sb.sig === null;
  sb.sig = data.sig;
  sb.model = model;
  sb.R = model.equal ? R_EQUAL : R_VALUE;
  sb.maxCount = Math.max(1, ...data.nodes.filter(n => n.level === 'goal').map(n => n.count));
  // Resting on categories, bars are categories (and any goal outside one), on one scale of their own.
  sb.maxUnit = Math.max(1, ...data.nodes.filter(n => n.level === 'category' || (n.level === 'goal' && !n.category)).map(n => n.count));
  sb.search = prepareSearch(model, data);
  runSearch(sb);

  // The pick comes from Python on the first draw (a page revisit); after that the chart owns it.
  if (firstMount && data.selected) {
    const d = data.selected.domain;
    const g = data.selected.goal;
    const goalId = g ? `${d}${data.sep}${g}` : null;
    const catId = data.selected.category ? `${d}\x1e${data.selected.category}` : null;
    if (model.byId.has(d)) {
      sb.zoom = d;
      sb.pick = goalId && model.byId.has(goalId) ? goalId : catId && model.byId.has(catId) ? catId : d;
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
  const hitLayer = svgEl('g', { class: 'sb-hits' });   // the matching share of each goal, while searching
  const catLayer = svgEl('g');
  // Resting on categories, a pointed-at category fans its goals out over its neighbours, on this backdrop.
  const fan = svgEl('path', { class: 'sb-fan', fill: '#f8fafc', stroke: '#e2e8f0', 'stroke-width': 1 });
  goalLayer.appendChild(fan);
  const defs = svgEl('defs');                          // arcs the open domain's category names run along
  const domainLayer = svgEl('g');
  const labelLayer = svgEl('g');
  const hole = svgEl('circle', { cx: C, cy: C, r: sb.R.hole - 3, class: 'sb-hole' });
  svg.append(defs, trackLayer, catLayer, goalLayer, hitLayer, domainLayer, hole, labelLayer);
  const center = el('div', 'sb-center');
  figure.append(svg, center);
  const panel = el('div', 'sb-panel');
  root.append(figure, panel);

  sb.els = { svg, hole, center, panel, slices: new Map(), labels: new Map(), tracks: new Map(), hits: new Map(), catNames: new Map(), dots: new Map(), fan };
  const uid = `sb${Math.random().toString(36).slice(2, 8)}`;
  const animate = firstMount && !reducedMotion();
  if (animate) svg.classList.add('sb-enter');

  let i = 0;
  for (const n of data.nodes) {
    if (n.level === 'root') continue;
    const gap = model.equal && (n.level === 'goal' || n.level === 'category') && n.count === 0;
    const path = svgEl('path', {
      class: 'sb-slice', stroke: gap ? '#94a3b8' : '#fff', 'fill-rule': 'evenodd',
      'stroke-width': n.level === 'domain' ? 2 : 1.25,
      tabindex: 0, role: 'button', 'aria-label': `${n.eyebrow}: ${n.title}, ${plural(n.count, data.noun_one, data.noun)}`,
    });
    if (gap) path.setAttribute('stroke-dasharray', '3 2');
    if (model.equal && (n.level === 'goal' || n.level === 'category')) {
      // The pale track behind each bar shows how far the bar could reach.
      const track = svgEl('path', { class: 'sb-track', fill: '#f1f5f9', stroke: '#fff', 'stroke-width': 1.25 });
      trackLayer.appendChild(track);
      sb.els.tracks.set(n.id, track);
    }
    path.style.transformOrigin = `${C}px ${C}px`;
    if (animate) path.style.animationDelay = n.level === 'domain' ? `${i * 40}ms` : `${120 + i * 6}ms`;
    i += 1;
    (n.level === 'domain' ? domainLayer : n.level === 'category' ? catLayer : goalLayer).appendChild(path);
    sb.els.slices.set(n.id, path);
    if ((n.level === 'goal' || (model.equal && n.level === 'category')) && n.count > 0) {
      const hit = svgEl('path', { class: 'sb-hit', stroke: '#fff', 'stroke-width': 1.25 });
      hit.style.transformOrigin = `${C}px ${C}px`;
      hitLayer.appendChild(hit);
      sb.els.hits.set(n.id, hit);
    }
    if (n.label) {
      const text = svgEl('text', {
        class: 'sb-label', 'text-anchor': 'middle', 'dominant-baseline': 'central',
        'font-size': n.level === 'domain' ? 17 : n.level === 'category' ? 12 : 14, 'font-weight': 600,
      });
      text.textContent = n.label;
      labelLayer.appendChild(text);
      sb.els.labels.set(n.id, text);
    }
    if (n.level === 'category' && model.equal) {
      // One dot per goal at the bar's base: filled when a program names it, hollow for a gap.
      const dots = svgEl('g', { class: 'sb-dots' });
      for (const g of model.goalsOf.get(n.id) || []) dots.appendChild(svgEl('circle', { r: DOT.r, 'data-on': g.count > 0 ? '1' : '' }));
      labelLayer.appendChild(dots);
      sb.els.dots.set(n.id, dots);
    }
    if (n.level === 'category') {
      // The open domain's categories carry their names along the ring.
      const arc = svgEl('path', { id: `${uid}-${i}`, fill: 'none' });
      defs.appendChild(arc);
      const name = svgEl('text', { class: 'sb-label sb-cat-name', 'font-size': 12, 'font-weight': 600, 'dominant-baseline': 'central' });
      const tp = svgEl('textPath', { href: `#${uid}-${i}`, startOffset: '50%', 'text-anchor': 'middle' });
      tp.textContent = n.title;
      name.appendChild(tp);
      labelLayer.appendChild(name);
      sb.els.catNames.set(n.id, { arc, name });
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
  if (node.level === 'category') {
    choose(sb, node.parent, sb.pick === node.id && sb.zoom === node.parent ? node.parent : node.id);
  } else if (node.level === 'domain') {
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
  if (n.level === 'category') return { domain: n.parent, goal: null, category: n.label + '. ' + n.title };
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
function outerRadius(sb, n, count = n.count) {
  const R = sb.R;
  const base = barBase(sb);
  if (!sb.model.equal) {
    // While searching, the matching share of a sunburst slice fills it from the inside out.
    return count === n.count ? R.goal : base + Math.max(count / n.count, 0.06) * (R.goal - base);
  }
  if (count === 0) return base + STUB;
  // Square root, so the bar's area (not its length) follows the count, and thin goals stay visible.
  // Resting on categories, revealed goals share the categories' scale, so they read against them.
  const max = catBars(sb) ? sb.maxUnit : sb.maxCount;
  return base + STUB + Math.sqrt(count / max) * (R.goal - base - STUB);
}

function draw(sb) {
  const { model, els } = sb;
  const R = sb.R;
  const resting = catBars(sb);
  for (const [id, track] of els.tracks) {
    const n = model.byId.get(id);
    const [a0, a1] = sb.angles.get(id) || [0, 0];
    // Resting on categories, the tracks belong to the category bars (and goals outside a category).
    const shown = n.level === 'category' ? resting : !(resting && n.category);
    track.style.display = shown ? '' : 'none';
    if (shown) track.setAttribute('d', arcPath(barBase(sb), R.goal, a0, a1));
  }
  for (const [id, path] of els.slices) {
    const n = model.byId.get(id);
    const [a0, a1] = sb.angles.get(id) || [0, 0];
    const d = n.level === 'domain' ? arcPath(R.hole, R.domain, a0, a1)
      : n.level === 'category' ? (resting ? arcPath(barBase(sb), outerRadius(sb, n), a0, a1) : arcPath(R.domain + 2, R.cat, a0, a1))
        : arcPath(barBase(sb), outerRadius(sb, n), a0, a1);
    path.setAttribute('d', d);
    path.dataset.empty = d ? '' : '1';
    if (n.level === 'category' && model.equal) {
      // An empty category is a dashed stub while it is a bar, a plain band on the open domain's ring.
      path.setAttribute('stroke', resting && n.count === 0 ? '#94a3b8' : '#fff');
      if (resting && n.count === 0) path.setAttribute('stroke-dasharray', '3 2');
      else path.removeAttribute('stroke-dasharray');
    }
    const hitPath = els.hits.get(id);
    if (hitPath) {
      const hit = sb.hits && (n.level === 'category' ? sb.hits.cats.get(id) : sb.hits.goals.get(id));
      const usable = !!(hit && hit.partial && d) && (n.level !== 'category' || resting);
      hitPath.dataset.usable = usable ? '1' : '';
      if (usable) hitPath.setAttribute('d', arcPath(barBase(sb), outerRadius(sb, n, Math.max(hit.count, 1)), a0, a1));
    }
    const label = els.labels.get(id);
    const named = n.level === 'category' && categoryName(sb, n, a0, a1, d);
    if (label) {
      const span = a1 - a0;
      const show = !!d && (n.level === 'domain' ? !sb.zoom && span >= MIN_LABEL_DEG.domain
        : n.level === 'category' ? !named && span >= MIN_LABEL_DEG.category
          : !!sb.zoom && span >= MIN_LABEL_DEG.goal);
      const [x, y] = n.level === 'domain' ? point((R.hole + R.domain) / 2, (a0 + a1) / 2)
        : n.level === 'category' ? point(resting ? R.domain + 13 : (R.domain + 2 + R.cat) / 2, (a0 + a1) / 2)
          : point(model.equal ? R.goal - 16 : (barBase(sb) + R.goal) / 2 - 1, (a0 + a1) / 2);
      label.setAttribute('x', f(x));
      label.setAttribute('y', f(y));
      label.dataset.show = show ? '1' : '';
    }
  }
  for (const [id, dots] of els.dots) placeDots(sb, model.byId.get(id), dots, resting);
  els.hole.classList.toggle('can-go-up', !!sb.zoom);
  paint(sb);
}

/** Lay a category's goal dots along its arc, in as many short rows as its width needs. */
function placeDots(sb, n, dots, resting) {
  const [a0, a1] = sb.angles.get(n.id) || [0, 0];
  const circles = [...dots.children];
  const r0 = sb.R.domain + DOT.at;
  const perRow = Math.max(1, Math.floor(((r0 * (a1 - a0) * Math.PI) / 180 - 4) / DOT.gap));
  const show = resting && a1 - a0 >= MIN_LABEL_DEG.category && circles.length > 0;
  dots.style.display = show ? '' : 'none';
  if (!show) return;
  const rows = Math.ceil(circles.length / perRow);
  circles.forEach((c, k) => {
    const row = Math.floor(k / perRow);
    const inRow = row === rows - 1 ? circles.length - row * perRow : perRow;
    const r = r0 + row * DOT.row;
    const step = (DOT.gap / r) * (180 / Math.PI);
    const a = (a0 + a1) / 2 + (k - row * perRow - (inRow - 1) / 2) * step;
    const [x, y] = point(r, a);
    c.setAttribute('cx', f(x));
    c.setAttribute('cy', f(y));
  });
}

/** What is drawn right now: folded goals stay hidden until their category is pointed at. */
function reveal(sb, openCat) {
  const { model, els } = sb;
  const fanned = fanOut(sb, openCat);
  // Category letters under an open fan would sit on its goals' bars.
  const underFan = n => {
    if (!fanned || n.level !== 'category') return false;
    const [a0, a1] = sb.angles.get(n.id) || [0, 0];
    const mid = (a0 + a1) / 2;
    return [mid, mid - 360, mid + 360].some(m => m > fanned[0] && m < fanned[1]);
  };
  for (const [id, path] of els.slices) {
    const n = model.byId.get(id);
    const hidden = path.dataset.empty === '1' || folded(sb, n, openCat);
    path.style.display = hidden ? 'none' : '';
    path.setAttribute('tabindex', hidden ? -1 : 0);
    // Revealed goals sit over their category's bar; the pointer stays with the category underneath.
    path.style.pointerEvents = n.level === 'goal' && catBars(sb) && n.category ? 'none' : '';
    const hitPath = els.hits.get(id);
    if (hitPath) {
      const covered = FAN && n.level === 'category' && openCat === id;
      hitPath.style.display = hitPath.dataset.usable && !hidden && !covered ? '' : 'none';
    }
    const label = els.labels.get(id);
    if (label) label.style.display = label.dataset.show && !hidden && !underFan(n) ? '' : 'none';
  }
}

/** In an open domain, write a category's name along its arc if it fits; returns whether it does. */
function fanOut(sb, openCat) {
  const { model, els } = sb;
  const goals = FAN && openCat && catBars(sb) ? model.goalsOf.get(openCat) || [] : [];
  els.fan.style.display = goals.length ? '' : 'none';
  if (!goals.length) return null;
  // The fan is centred on the category, at least as wide as it, so each goal gets a readable bar.
  const [c0, c1] = sb.angles.get(openCat) || [0, 0];
  const span = Math.max(c1 - c0, Math.min(goals.length * FAN_STEP, FAN_MAX));
  const f0 = (c0 + c1) / 2 - span / 2;
  const step = span / goals.length;
  const base = barBase(sb);
  els.fan.setAttribute('d', arcPath(base - 1, sb.R.goal + 2, f0, f0 + span));
  goals.forEach((g, k) => {
    const a0 = f0 + k * step;
    els.slices.get(g.id).setAttribute('d', arcPath(base, outerRadius(sb, g), a0, a0 + step));
    const hitPath = els.hits.get(g.id);
    const hit = sb.hits && sb.hits.goals.get(g.id);
    if (hitPath && hit && hit.partial) hitPath.setAttribute('d', arcPath(base, outerRadius(sb, g, Math.max(hit.count, 1)), a0, a0 + step));
    const label = els.labels.get(g.id);
    if (label) {
      const [x, y] = point(sb.R.goal - 16, a0 + step / 2);
      label.setAttribute('x', f(x));
      label.setAttribute('y', f(y));
      label.dataset.show = step >= 7 ? '1' : '';
    }
  });
  return [f0, f0 + span];
}

function categoryName(sb, n, a0, a1, d) {
  const item = sb.els.catNames.get(n.id);
  if (!item) return false;
  const r = (sb.R.domain + 2 + sb.R.cat) / 2;
  const room = (r * (a1 - a0) * Math.PI) / 180 - 12;
  const fits = !!sb.zoom && !!d && a1 - a0 >= MIN_LABEL_DEG.categoryName && n.title.length * 6.6 <= room;
  item.name.style.display = fits ? '' : 'none';
  if (!fits) return false;
  // Clockwise along the top half, counter-clockwise along the bottom, so the name never reads upside down.
  const mid = ((a0 + a1) / 2) % 360;
  const flip = mid > 90 && mid < 270;
  const [s0, e0] = flip ? [a1, a0] : [a0, a1];
  const [x0, y0] = point(r, s0);
  const [x1, y1] = point(r, e0);
  item.arc.setAttribute('d', `M${f(x0)} ${f(y0)}A${r} ${r} 0 ${a1 - a0 > 180 ? 1 : 0} ${flip ? 0 : 1} ${f(x1)} ${f(y1)}`);
  return true;
}

function paint(sb) {
  const { model, els } = sb;
  const hovered = sb.hover ? model.byId.get(sb.hover) : null;
  const picked = sb.pick ? model.byId.get(sb.pick) : null;
  const lead = hovered || picked;
  const activeDomain = lead ? (lead.level === 'domain' ? lead.id : lead.parent) : null;
  const activeCat = lead && lead.level === 'category' ? lead.id : null;
  const state = { activeDomain, activeCat, activeId: sb.hover, hovering: !!hovered, pick: sb.pick, equal: model.equal, hits: sb.hits,
    catBars: catBars(sb) };
  // Resting on categories, only a pointed-at category opens to show its goals.
  reveal(sb, hovered && hovered.level === 'category' ? hovered.id : null);
  for (const [id, path] of els.slices) {
    const n = model.byId.get(id);
    const look = fills(n, state);
    path.setAttribute('fill', look.fill);
    path.setAttribute('fill-opacity', look.opacity);
    path.style.transform = look.lift ? `scale(${POP})` : '';
    const hitPath = els.hits.get(id);
    if (hitPath && look.overlay) {
      hitPath.setAttribute('fill', look.overlay);
      hitPath.setAttribute('fill-opacity', look.opacity);
      hitPath.style.transform = path.style.transform;
    }
    const label = els.labels.get(id);
    const missed = sb.hits && !(n.level === 'goal' ? sb.hits.goals : n.level === 'category' ? sb.hits.cats : sb.hits.domains).has(id);
    const ink = n.level === 'domain' ? (missed ? '#64748b' : '#fff') : missed ? GREY.label : (n.hue === null || n.hue === undefined
      ? '#334155' : n.level === 'category' ? `hsl(${n.hue} 45% ${state.pick === id || activeCat === id ? 97 : 20}%)`
        : model.equal ? `hsl(${n.hue} 45% 18%)` : `hsl(${n.hue} 55% ${look.lift && !look.overlay ? 97 : 26}%)`);
    const dots = els.dots.get(id);
    if (dots) {
      const lit = state.pick === id || activeCat === id;   // on the darker picked or pointed-at bar, the dots turn white
      const dark = lit ? '#fff' : n.hue === null || n.hue === undefined ? '#475569' : `hsl(${n.hue} 45% 24%)`;
      for (const c of dots.children) {
        c.setAttribute('fill', c.dataset.on ? (missed ? GREY.label : dark) : lit ? 'none' : '#fff');
        c.setAttribute('stroke', missed ? GREY.label : dark);
        c.setAttribute('stroke-width', 1);
      }
      dots.style.opacity = look.opacity < 1 ? 0.55 : 1;
    }
    for (const text of [label, els.catNames.get(id)?.name]) {
      if (!text) continue;
      text.setAttribute('fill', ink);
      text.style.opacity = look.opacity < 1 ? 0.55 : 1;
    }
  }
  readout(sb, hovered);
}

function readout(sb, hovered) {
  const { model, els } = sb;
  const data = model.data;
  const hits = sb.hits;
  const zoomed = sb.zoom ? model.byId.get(sb.zoom) : null;
  const picked = sb.pick ? model.byId.get(sb.pick) : null;
  const focus = hovered || picked || zoomed || model.root;
  const key = `${focus.id}|${sb.zoom}|${sb.pick}|${!!hovered}|${hits ? hits.words.join(' ') : ''}`;
  if (key === sb.focusKey) return;
  const focusChanged = !sb.focusKey || sb.focusKey.split('|')[0] !== focus.id;
  sb.focusKey = key;
  const query = hits ? `“${sb.query.trim()}”` : '';
  // While searching: the rows of this slice that match, and how many of the chart's measure they make.
  const match = !hits ? null : focus.level === 'root' ? { rows: hits.all, count: hits.total[data.noun.startsWith('program') ? 'programs' : data.noun.startsWith('organization') ? 'organizations' : 'outcomes'], named: false }
    : focus.level === 'domain' ? { rows: hits.domainRows.get(focus.id) || [], count: measure(hits.domainRows.get(focus.id) || [], hits.col), named: false, lit: hits.domains.has(focus.id) }
    : focus.level === 'category' ? (hits.cats.get(focus.id) || { rows: [], count: 0, named: false })
    : (hits.goals.get(focus.id) || { rows: [], count: 0, named: false });

  // Centre
  const inner = el('div', 'sb-center-inner' + (focusChanged ? ' sb-fade' : ''));
  if (focus.level === 'root' && hits) {
    inner.append(el('div', 'sb-big', fmt(match.count)), el('div', 'sb-meta', `${match.count === 1 ? data.noun_one : data.noun} match ${query}`));
  } else if (focus.level === 'root') {
    inner.append(el('div', 'sb-big', fmt(focus.count)), el('div', 'sb-meta', `${data.noun} in ${data.n_domains} domains`));
  } else {
    inner.append(
      el('div', 'sb-eyebrow', focus.eyebrow),
      el('div', 'sb-title', focus.title),
      el('div', 'sb-meta', hits ? matchLine(focus, match, data, true) : plural(focus.count, data.noun_one, data.noun)),
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
  eyebrow.append(document.createTextNode(focus.level === 'root' ? (hits ? 'Search' : 'The whole portfolio') : focus.eyebrow));
  const title = el('div', 'sb-title', focus.level === 'root' ? (hits ? query : 'All domains') : focus.title);
  const counts = el('ul', 'sb-counts');
  const shown = focus.level === 'root' && hits ? hits.total : focus;
  for (const [n, one, many] of [[shown.programs, 'program', 'programs'], [shown.organizations, 'organization', 'organizations'],
    [shown.outcomes, 'outcome statement', 'outcome statements']]) {
    const li = el('li');
    li.append(el('b', '', fmt(n)), document.createTextNode(n === 1 ? one : many));
    counts.append(li);
  }
  const children = [eyebrow, title, counts];
  if (focus.level === 'root' && hits) {
    children.push(el('div', 'sb-share-note sb-match-note', hits.goals.size
      ? `${plural(hits.goals.size, 'goal', 'goals')} in ${plural(hits.domains.size, 'domain', 'domains')} hold ${query}. Grey slices don't.`
      : `Nothing in this view mentions ${query}. Try a shorter word.`));
  } else if (focus.level !== 'root') {
    const share = hits ? (focus.count ? match.count / focus.count : 0) : model.root.count ? focus.count / model.root.count : 0;
    const bar = el('div', 'sb-share');
    const fill = el('span');
    fill.style.width = (hits ? match.count : focus.count) ? `${Math.max(share * 100, 1.5)}%` : '0';
    fill.style.background = swatchColor(focus);
    bar.append(fill);
    children.push(bar, el('div', 'sb-share-note', hits ? matchLine(focus, match, data, false)
      : focus.level === 'goal' && focus.count === 0
        ? 'No program in this view names this goal yet.'
        : `${Math.round(share * 100)}% of all ${data.noun}`));
  }
  if (focus.level === 'root' && hits && hits.goals.size) {
    // Which goals lit up, most first, so a goal found only through the codebook's words still shows why.
    const top = [...hits.goals.entries()].sort((x, y) => y[1].count - x[1].count).slice(0, 4);
    const list = el('ul', 'sb-goals');
    for (const [id, hit] of top) {
      const g = model.byId.get(id);
      const li = el('li');
      const sw = el('span', 'sb-swatch');
      sw.style.background = swatchColor(g);
      li.append(sw, el('span', 'sb-goal-name', `${g.label ? g.label + ' ' : ''}${g.title}`), el('span', 'sb-goal-n', fmt(hit.count)));
      list.append(li);
    }
    children.push(el('div', 'sb-eyebrow sb-samples-head', hits.goals.size > top.length ? `Top goals of ${hits.goals.size}` : 'Goals that match'), list);
  }
  if (focus.level === 'category') {
    // The subcategories: every goal in the category with its count, as the wheel shows them on hover.
    const list = el('ul', 'sb-goals sb-subs');
    const members = model.goalsOf.get(focus.id) || [];
    const top = Math.max(1, ...members.map(g => g.count));
    for (const g of members) {
      const n = hits ? (hits.goals.get(g.id) || { count: 0 }).count : g.count;
      const li = el('li', hits && !hits.goals.has(g.id) ? 'sb-goal-miss' : '');
      const bar = el('span', 'sb-mini');
      const fill = el('span');
      // Square root, as on the wheel, so a goal's bar here matches its bar there.
      fill.style.width = n ? `${Math.max(Math.sqrt(n / top) * 100, 4)}%` : '0';
      fill.style.background = swatchColor(g);
      bar.append(fill);
      li.append(el('span', 'sb-goal-name', `${g.label ? g.label + ' ' : ''}${g.title}`), bar, el('span', 'sb-goal-n', fmt(n)));
      list.append(li);
    }
    children.push(el('div', 'sb-eyebrow sb-samples-head', hits ? `Subcategories (${data.noun} that match)` : `Subcategories (${data.noun})`), list);
  }
  const found = hits ? matchingSamples(sb, match.rows, focus.level === 'root' || focus.level === 'category' ? 2 : 3) : [];
  if (found.length) {
    const list = el('ul', 'sb-samples');
    for (const s of found) list.append(marked(s, hits.words));
    children.push(el('div', 'sb-eyebrow sb-samples-head', 'Outcomes that match'), list);
  } else if (focus.samples && focus.samples.length && !(focus.level === 'root' && hits) && focus.level !== 'category') {
    const list = el('ul', 'sb-samples');
    for (const s of focus.samples) list.append(el('li', '', `“${s}”`));
    children.push(el('div', 'sb-eyebrow sb-samples-head', 'Sample outcomes'), list);
  }
  children.push(el('div', 'sb-hint', hint(sb, hovered)));
  box.append(...children);
  panel.replaceChildren(box);
}

/** What the search found in one slice, for the centre (short) or the side panel. */
function matchLine(node, match, data, short) {
  if (match.named) return short ? 'Its name or description matches'
    : `The codebook names or describes this ${node.level === 'category' ? 'category' : 'goal'} with these words, so all of it counts.`;
  if (node.level === 'domain' && !match.count && match.lit) return short ? 'Its description matches' : "The codebook's description of this domain matches; none of its goals do.";
  if (!match.count) return short ? 'No match' : 'Nothing here matches the search.';
  return short
    ? `${fmt(match.count)} of ${plural(node.count, data.noun_one, data.noun)} match`
    : `${fmt(match.count)} of ${plural(node.count, data.noun_one, data.noun)} here have an outcome that matches.`;
}

function hint(sb, hovered) {
  if (hovered) {
    if (hovered.level === 'domain') return sb.zoom === hovered.id ? 'Click to go back to all domains.'
      : sb.model.cats.length ? 'Point at a category to see its subcategories. Click to open the domain.' : 'Click to open its goals.';
    if (hovered.level === 'category') return sb.pick === hovered.id ? 'Click again to show the whole domain.' : 'Click to list its outcomes in the table below.';
    if (sb.pick === hovered.id) return 'Click again to show the whole domain.';
    return hovered.count ? 'Click to list its outcomes in the table below.' : 'Nothing to list yet.';
  }
  if (sb.zoom) return 'Click the center to go back to all domains.';
  if (sb.hits) return 'Point at a slice to see what matched. Clicking still opens it.';
  return sb.model.cats.length ? 'Point at a category to see its subcategories. Click one to list its outcomes.'
    : 'Point at a slice to read it. Click a domain to open its goals.';
}
