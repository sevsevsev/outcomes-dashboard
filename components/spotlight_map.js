// The District indicators map, one indicator at a time: the SPOTlight indicators in a list on the left, and
// for the one picked there, the goals partners name, the program models and research associations that join
// them to it, and the indicator, joined by thin lines. Drawn in the browser so pointing costs no round trip to
// Python (see spotlight_component.py). Showing one indicator keeps the map on one screen; all of them at once
// ran to about 2,000 pixels.
//
// It follows the codebook wheel's habits: plain names, per-domain hues, pale at rest and full hue only for what
// is pointed at or picked, and a side panel that says what that is. The rows and model nodes are the targets,
// never the lines, so a pointer resting on the map never sits on something that moves. Line style says what kind
// of link it is (cause shown, correlation only, by definition, or research-associated), which the node and the
// panel also say in words. Tested links sit above a rule and research associations below it, never mixed.
//
// Lines are one width by default. The "Line width" switch can make a goal's line into its model as thick as the
// number of programs naming the goal; the lines from models to the indicator always stay one width, so nothing
// stacks up at the indicator into something that reads like a total.
//
// With `data.scope` (one program, or the partners at one school), the goals named there stay dark and the rest
// go pale, so the gaps stay in view; indicators none of whose links that scope names go pale in the list.
//
// Picking an indicator in the list redraws the map for it. In the map, a click (or Enter, or a tap) pins a row or
// node; clicking it again, clicking empty space or Escape unpins. While something is pinned, pointing elsewhere
// changes nothing, so the panel never flickers. Each pin goes to Python as the "selection" state, which filters
// the table below; with nothing pinned, the selection is the shown indicator. Every selection carries `focus`, the
// shown indicator, so a rerun reopens it. `data.sig` changes only when what is drawn changes, so reruns caused by
// a pick leave the map alone.

const SVG_NS = 'http://www.w3.org/2000/svg';
const NODE_GAP = 6;         // least space between two model nodes
const STUB = 34;            // length of the dotted stub beside a row with no link
const DASH = { cause: null, correlation: '6 4', definition: '1.5 4', associated: '9 3 2 3' };
const KIND = {
  cause: {
    word: 'Cause shown',
    explain: 'Studies that compared similar students or schools found that this kind of program, or this change ' +
      'in students, moves what the indicator measures. How sure that is depends on the evidence level.',
  },
  correlation: {
    word: 'Correlation only',
    explain: 'Students who do well on this goal tend to do well on the indicator, but no study shows that a ' +
      'program causes the change. It is a warning sign worth watching, not proof of an effect.',
  },
  associated: {
    word: 'Research-associated',
    explain: 'Long-term studies find that this outcome is associated with the indicator. They do not show that a ' +
      'program building it moves the indicator, so it never earns credit.',
  },
  definition: {
    word: 'By definition',
    explain: 'The indicator counts this outcome directly, so a program helps only if school records show the ' +
      "change for its own students. It says nothing about which kinds of program work.",
  },
};
const WIDTH = { min: 1.6, max: 9, zero: 1.1 };   // line widths when they follow program counts

const pale = h => (h === null || h === undefined ? '#cbd5e1' : `hsl(${h} 42% 74%)`);
const full = h => (h === null || h === undefined ? '#64748b' : `hsl(${h} 58% 40%)`);
const swatch = h => (h === null || h === undefined ? '#94a3b8' : `hsl(${h} 55% 52%)`);
let widthMode = 'same';     // outlives a fresh map (a new scope, a page revisit)

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function svgEl(tag, attrs) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) node.setAttribute(k, v);
  return node;
}

const plural = (n, one, many) => `${n.toLocaleString()} ${n === 1 ? one : many}`;
const programs = n => (n ? `${plural(n, 'program names', 'programs name')} this goal; model not confirmed`
  : 'No program names this goal');
const kindLine = l => (l.kind === 'definition' ? KIND.definition.word
  : l.kind === 'associated' ? `${KIND.associated.word} · no credit` : `${KIND[l.kind].word} · ${l.evidenceLabel}`);

export default function (component) {
  const { data, parentElement, setStateValue } = component;
  if (!data || !data.goals) return;
  let root = parentElement.querySelector('.sm');
  if (!root) {
    root = el('div', 'sm');
    parentElement.appendChild(root);
  }
  const sm = root.__sm || (root.__sm = { sig: null, hover: null, pick: null });
  sm.send = setStateValue;
  if (sm.sig !== data.sig) mount(root, sm, data);
}

// ---------------------------------------------------------------- model

function buildModel(data) {
  const goals = new Map(data.goals.map(g => [g.id, g]));
  const links = new Map(data.links.map(l => [l.id, l]));
  const indicators = new Map(data.indicators.map(i => [i.id, i]));
  const linksOfGoal = new Map(data.goals.map(g => [g.id, data.links.filter(l => l.goals.includes(g.id))]));
  const linksOfInd = new Map(data.indicators.map(i => [i.id, data.links.filter(l => l.indicators.includes(i.id))]));
  // In a scoped view, what the program or school's partners name; everything is "in" without a scope.
  const scope = data.scope;
  const goalIn = g => !scope || (goals.get(g)?.here || 0) > 0;
  const linkIn = l => l.goals.some(goalIn);
  const indIn = i => !scope || (linksOfInd.get(i) || []).some(linkIn);
  const lanes = new Map((data.lanes || []).map(l => [l.id, l]));
  return { data, scope, goals, links, indicators, lanes, linksOfGoal, linksOfInd, goalIn, linkIn, indIn };
}

/** What a pick lights: the rows, nodes and line segments ("in" goal->link, "out" link->indicator). */
function litBy(model, item) {
  const lit = { goal: new Set(), link: new Set(), indicator: new Set(), seg: new Set() };
  if (!item) return null;
  const take = (l, goalIds, indIds) => {
    lit.link.add(l.id);
    for (const g of goalIds) { lit.goal.add(g); lit.seg.add(`in|${g}|${l.id}`); }
    for (const i of indIds) { lit.indicator.add(i); lit.seg.add(`out|${l.id}|${i}`); }
  };
  if (item.kind === 'goal') {
    lit.goal.add(item.id);
    for (const l of model.linksOfGoal.get(item.id) || []) take(l, [item.id], l.indicators);
  } else if (item.kind === 'link') {
    const l = model.links.get(item.id);
    if (l) take(l, l.goals, l.indicators);
  } else if (item.kind === 'indicator') {
    lit.indicator.add(item.id);
    for (const l of model.linksOfInd.get(item.id) || []) take(l, l.goals, [item.id]);
  }
  return lit;
}

// ---------------------------------------------------------------- mount

function mount(root, sm, data) {
  const model = buildModel(data);
  const firstMount = sm.sig === null;
  sm.sig = data.sig;
  sm.model = model;
  sm.hover = null;
  if (firstMount) {
    // The last pick carries the indicator it was made on, so a rerun reopens the same one.
    const sel = data.selected && data.selected.kind ? data.selected : null;
    sm.focus = (sel && (sel.focus || (sel.kind === 'indicator' ? sel.id : null))) || data.focus;
    sm.pick = sel && !(sel.kind === 'indicator' && sel.id === sm.focus) ? sel : null;
  }
  if (!model.indicators.has(sm.focus)) { sm.focus = data.focus; sm.pick = null; }
  root.replaceChildren();

  const map = el('div', 'sm-map');
  sm.map = map;
  const panel = el('aside', 'sm-panel');
  panel.setAttribute('aria-live', 'polite');
  sm.panel = panel;

  const body = el('div', 'sm-body');
  body.append(indicatorList(sm), map, panel);
  root.append(widthSwitch(sm, data.scope), body, howToRead());

  if (!sm.keys) {
    sm.keys = true;
    root.addEventListener('keydown', e => { if (e.key === 'Escape') setPick(sm, null); });
  }
  renderMap(sm);
}

/** The 13 indicators, grouped as the SPOTlight groups them; picking one redraws the map for it alone. */
function indicatorList(sm) {
  const { model } = sm;
  const { data } = model;
  const nav = el('nav', 'sm-picker');
  nav.setAttribute('aria-label', `District indicators, ${data.year}`);
  nav.append(el('div', 'sm-head', `District indicators, ${data.year}`));
  sm.listRows = new Map();
  let group = null;
  for (const i of data.indicators) {
    if (i.group !== group) {
      group = i.group;
      nav.append(el('div', 'sm-group', group));
    }
    const row = el('button', `sm-row sm-pickrow${i.reached || i.associated ? '' : ' is-unreached'}${model.indIn(i.id) ? '' : ' is-out'}`);
    row.type = 'button';
    row.setAttribute('aria-label', `${i.name}, ${data.year}: ${i.value}. ${noteOf(i) || 'Show its links.'}`);
    const line = el('span', 'sm-line');
    line.append(el('span', 'sm-name', i.name));
    if (i.value.length <= 8) line.append(el('span', 'sm-value', i.value));
    row.append(line);
    row.addEventListener('click', () => setFocus(sm, i.id));
    sm.listRows.set(i.id, row);
    nav.append(row);
  }
  return nav;
}

const noteOf = i => (i.reached ? '' : i.associated ? 'No tested program model yet; some goals are associated with it.'
  : 'No strong study links a partner goal to this yet.');

/** The pick that stands for the shown indicator when nothing in the map is picked. */
const focusPick = sm => ({ kind: 'indicator', id: sm.focus, focus: sm.focus });

function setFocus(sm, id) {
  if (sm.focus === id && !sm.pick) return;
  sm.focus = id;
  sm.pick = null;
  sm.hover = null;
  renderMap(sm);
  sm.send('selection', focusPick(sm));
}

/** Draws the map for the shown indicator: its goals, the links that join them to it, and the indicator. */
function renderMap(sm) {
  const { model, map } = sm;
  const { data } = model;
  const scope = data.scope;
  for (const [id, row] of sm.listRows) row.setAttribute('aria-pressed', String(id === sm.focus));
  const ind = model.indicators.get(sm.focus);
  const all = ind ? model.linksOfInd.get(ind.id) || [] : [];
  // Tested links first, research associations after a rule of their own, never mixed.
  sm.links = [...all.filter(l => !l.associated), ...all.filter(l => l.associated)];
  const shown = new Set(sm.links.flatMap(l => l.goals));
  const goals = data.goals.filter(g => shown.has(g.id));
  sm.rows = { goal: new Map(), link: new Map(), indicator: new Map() };

  const svg = svgEl('svg', { class: 'sm-bands', 'aria-hidden': 'true' });
  const cols = el('div', 'sm-cols');
  sm.cols = cols;
  sm.svg = svg;

  // Goals, grouped by the District priority (lane) they serve, from the outcome crosswalk; without it, under
  // their domains. Only the goals a link joins to this indicator: the rest live in the Priority grid above.
  const goalCol = el('div', 'sm-col sm-goals');
  goalCol.append(el('div', 'sm-head', 'Goals partners name'));
  const goalRow = g => {
    const here = scope ? hereWords(scope, g.here || 0) : '';
    const row = button(`sm-row sm-goal${model.goalIn(g.id) ? '' : ' is-out'}`, { kind: 'goal', id: g.id }, sm,
      `${g.name}. ${scope ? `${here || 'Not named here'}.` : `${programs(g.programs)}.`}`);
    const line = el('span', 'sm-line');
    const name = el('span', 'sm-name', g.name);
    if (model.lanes.size) {
      const sw = el('span', 'sm-swatch sm-goal-hue');
      sw.style.background = swatch(g.hue);
      sw.title = g.domainName;
      name.prepend(sw);
    }
    line.append(name);
    if (scope && g.here) line.append(el('span', 'sm-value', here));
    row.append(line);
    sm.rows.goal.set(g.id, row);
    goalCol.append(row);
  };
  if (model.lanes.size) {
    for (const lane of model.lanes.values()) {
      const inLane = goals.filter(g => g.lane === lane.id);
      if (!inLane.length) continue;
      goalCol.append(el('div', 'sm-dom sm-lane', lane.name));
      inLane.forEach(goalRow);
    }
    goals.filter(g => !model.lanes.has(g.lane)).forEach(goalRow);
  } else {
    let domain = null;
    for (const g of goals) {
      if (g.domain !== domain) {
        domain = g.domain;
        const head = el('div', 'sm-dom');
        const sw = el('span', 'sm-swatch');
        sw.style.background = swatch(g.hue);
        head.append(sw, el('span', null, g.domainName));
        goalCol.append(head);
      }
      goalRow(g);
    }
  }

  // Program models and research associations: one node per link, placed beside the goals it joins (see place).
  const linkCol = el('div', 'sm-col sm-links');
  linkCol.append(el('div', 'sm-head', 'Model or association'));
  const stack = el('div', 'sm-stack');
  linkCol.append(stack);
  sm.stack = stack;
  for (const l of sm.links) {
    const node = button(`sm-node${l.associated ? ' sm-node-assoc' : ''}${model.linkIn(l) ? '' : ' is-out'}`,
      { kind: 'link', id: l.id }, sm,
      `${l.name}. ${kindLine(l)}. ${l.associated ? 'Associated only, never credit.' : 'A possible link only.'}`);
    node.style.setProperty('--hue-pale', pale(l.hue));
    node.style.setProperty('--hue-full', full(l.hue));
    node.append(el('span', 'sm-name', l.name), el('span', 'sm-ev', kindLine(l)));
    sm.rows.link.set(l.id, node);
    stack.append(node);
  }
  sm.divider = null;
  if (sm.links.some(l => l.associated)) {
    sm.divider = el('div', 'sm-divider', sm.links.some(l => !l.associated)
      ? 'Research associations · never credit' : 'Research associations only · never credit');
    stack.append(sm.divider);
  }
  if (!sm.links.length && ind) linkCol.append(el('p', 'sm-empty', 'The research review found no study strong enough to link a partner goal to this indicator.'));

  // The one indicator, beside the middle of the links that reach it.
  const indCol = el('div', 'sm-col sm-inds');
  indCol.append(el('div', 'sm-head', 'Indicator'));
  sm.indRow = null;
  if (ind) {
    const row = button(`sm-row sm-ind${ind.reached || ind.associated ? '' : ' is-unreached'}${model.indIn(ind.id) ? '' : ' is-out'}`,
      { kind: 'indicator', id: ind.id }, sm, `${ind.name}, ${data.year}: ${ind.value}.`);
    row.append(el('span', 'sm-name', ind.name), el('span', 'sm-value sm-value-long', `${data.year}: ${ind.value}`));
    sm.rows.indicator.set(ind.id, row);
    sm.indRow = row;
    indCol.append(row);
  }

  cols.append(svg, goalCol, el('div', 'sm-gutter'), linkCol, el('div', 'sm-gutter'), indCol);
  cols.addEventListener('click', e => { if (!e.target.closest('button')) setPick(sm, null); });
  map.replaceChildren(cols);
  markPick(sm);

  const relayout = () => { place(sm); draw(sm); };
  if (sm.observer) sm.observer.disconnect();
  sm.observer = new ResizeObserver(relayout);
  sm.observer.observe(cols);
  document.fonts?.ready?.then(relayout);
  relayout();
}

/** "3 statements" for a program, "2 partners" for a school; '' when nobody there names the goal. */
function hereWords(scope, n) {
  if (!n) return '';
  return scope.kind === 'school' ? plural(n, 'partner', 'partners') : plural(n, 'statement', 'statements');
}

/** The "Line width" switch: one width for all lines, or a goal's line as thick as its count. */
function widthSwitch(sm, scope) {
  const bar = el('div', 'sm-switch');
  bar.append(el('span', 'sm-switch-label', 'Line width'));
  const group = el('div', 'sm-seg');
  group.setAttribute('role', 'radiogroup');
  group.setAttribute('aria-label', 'Line width');
  const counted = !scope ? 'Programs naming the goal' : scope.kind === 'school' ? 'Partners naming the goal'
    : 'Statements naming the goal';
  for (const [mode, label] of [['same', 'Same for all'], ['count', counted]]) {
    const b = el('button', 'sm-seg-btn', label);
    b.type = 'button';
    b.setAttribute('role', 'radio');
    b.setAttribute('aria-checked', String(widthMode === mode));
    b.addEventListener('click', () => {
      widthMode = mode;
      for (const other of group.children) other.setAttribute('aria-checked', String(other === b));
      draw(sm);
    });
    group.append(b);
  }
  bar.append(group,
    el('span', 'sm-switch-note', 'Only the lines from goals to program models change; lines into the indicator stay one width, so they never add up.'));
  return bar;
}

/** How to read a link: the line styles, each with what it means in a sentence. */
function howToRead() {
  const box = el('div', 'sm-legend');
  box.append(el('div', 'sm-legend-head', 'How to read a link'));
  for (const kind of ['cause', 'correlation', 'definition', 'associated']) {
    const item = el('div', 'sm-key');
    const s = svgEl('svg', { width: 30, height: 10, 'aria-hidden': 'true' });
    s.append(svgEl('line', { x1: 1, y1: 5, x2: 29, y2: 5, stroke: '#64748b', 'stroke-width': 2, 'stroke-dasharray': DASH[kind], 'stroke-linecap': 'round' }));
    const text = el('div');
    text.append(el('b', null, KIND[kind].word), el('span', null, ` ${KIND[kind].explain}`));
    item.append(s, text);
    box.append(item);
  }
  box.append(el('p', 'sm-key-note', 'Every tested line is a possible link. It holds for a program only after someone confirms the program runs the model the study tested. A research-associated line never earns credit.'));
  return box;
}

function button(cls, item, sm, label) {
  const b = el('button', cls);
  b.type = 'button';
  if (label) b.setAttribute('aria-label', label);
  b.addEventListener('pointerenter', () => setHover(sm, item));
  b.addEventListener('pointerleave', () => setHover(sm, null));
  b.addEventListener('focus', () => setHover(sm, item));
  b.addEventListener('blur', () => setHover(sm, null));
  b.addEventListener('click', () => {
    const same = sm.pick && sm.pick.kind === item.kind && sm.pick.id === item.id;
    setPick(sm, same ? null : item);
  });
  return b;
}

function setHover(sm, item) {
  sm.hover = item;
  if (!sm.pick) paint(sm);
}

function markPick(sm) {
  const item = sm.pick;
  for (const [kind, rows] of Object.entries(sm.rows)) {
    for (const [id, row] of rows) row.setAttribute('aria-pressed', String(!!item && item.kind === kind && item.id === id));
  }
  paint(sm);
}

/** Pins a goal, link or the indicator; null unpins, which leaves the shown indicator as the pick. */
function setPick(sm, item) {
  const was = sm.pick;
  sm.pick = item;
  markPick(sm);
  if ((was && was.kind) !== (item && item.kind) || (was && was.id) !== (item && item.id)) {
    sm.send('selection', item ? { ...item, focus: sm.focus } : focusPick(sm));
  }
}

// ---------------------------------------------------------------- layout

const rel = (box, base) => ({ top: box.top - base.top, bottom: box.bottom - base.top, left: box.left - base.left, right: box.right - base.left });

/** Sets each node's height beside the goals it joins, tested ones first, then the associations under their rule;
 * then sets the indicator beside the middle of the column. */
function place(sm) {
  const { stack } = sm;
  const base = stack.getBoundingClientRect();
  const centre = row => { const r = rel(row.getBoundingClientRect(), base); return (r.top + r.bottom) / 2; };
  const nodes = sm.links.map(l => {
    const ends = l.goals.map(g => sm.rows.goal.get(g)).filter(Boolean);
    const want = ends.reduce((s, r) => s + centre(r), 0) / Math.max(1, ends.length);
    const node = sm.rows.link.get(l.id);
    return { node, want, h: node.offsetHeight, assoc: !!l.associated };
  });
  const sorted = [...nodes.filter(n => !n.assoc).sort((a, b) => a.want - b.want),
    ...nodes.filter(n => n.assoc).sort((a, b) => a.want - b.want)];
  const colH = Math.max(0, ...[...sm.rows.goal.values()].map(r => rel(r.getBoundingClientRect(), base).bottom));
  let y = 0;
  let ruled = false;
  for (const n of sorted) {
    let least = y;
    if (n.assoc && !ruled && sm.divider) {
      ruled = true;
      const dh = sm.divider.offsetHeight;
      least = y + (y ? 8 : 0) + dh + 4;
      n.top = Math.max(n.want - n.h / 2, least);
      sm.divider.style.top = `${Math.round(n.top - dh - 4)}px`;
    } else {
      n.top = Math.max(n.want - n.h / 2, least);
    }
    y = n.top + n.h + NODE_GAP;
  }
  for (const n of sorted) n.node.style.top = `${Math.round(n.top)}px`;
  const h = Math.ceil(Math.max(colH, y - NODE_GAP, 0));
  stack.style.height = `${h}px`;
  if (sm.indRow) sm.indRow.style.marginTop = `${Math.max(0, Math.round(h / 2 - sm.indRow.offsetHeight / 2))}px`;
}

function curve(x0, y0, x1, y1) {
  const dx = (x1 - x0) / 2;
  return `M${x0.toFixed(1)},${y0.toFixed(1)} C${(x0 + dx).toFixed(1)},${y0.toFixed(1)} ${(x1 - dx).toFixed(1)},${y1.toFixed(1)} ${x1.toFixed(1)},${y1.toFixed(1)}`;
}

/** A goal's count in view: statements or partners in a scoped view, programs otherwise. */
const countOf = (model, g) => (model.scope ? g.here || 0 : g.programs);

/** Draws the lines from the rows' and nodes' current places. */
function draw(sm) {
  const { svg, cols, model } = sm;
  const base = cols.getBoundingClientRect();
  svg.setAttribute('width', base.width);
  svg.setAttribute('height', base.height);
  svg.setAttribute('viewBox', `0 0 ${base.width} ${base.height}`);
  svg.replaceChildren();
  sm.segs = [];
  const box = row => rel(row.getBoundingClientRect(), base);
  const mid = r => (r.top + r.bottom) / 2;
  const maxCount = Math.max(1, ...model.data.goals.map(g => countOf(model, g)));
  const widthOf = g => {
    if (widthMode !== 'count') return null;
    const n = countOf(model, g);
    return n ? WIDTH.min + (WIDTH.max - WIDTH.min) * Math.sqrt(n / maxCount) : WIDTH.zero;
  };
  const bands = svgEl('g', { class: 'sm-bandset' });
  const ends = svgEl('g', { class: 'sm-ends' });
  for (const l of sm.links) {
    const n = box(sm.rows.link.get(l.id));
    const add = (key, d, hue, endAt, width, out) => {
      const path = svgEl('path', { d, class: 'sm-band', 'stroke-dasharray': DASH[l.kind] ?? null });
      if (width) path.style.strokeWidth = `${width}px`;
      bands.append(path);
      const dot = svgEl('circle', { cx: endAt[0], cy: endAt[1], r: 2.6, class: 'sm-end' });
      ends.append(dot);
      sm.segs.push({ key, path, dot, hue, width, out });
    };
    for (const g of l.goals) {
      const row = sm.rows.goal.get(g);
      if (!row) continue;
      const r = box(row);
      const goal = model.goals.get(g);
      add(`in|${g}|${l.id}`, curve(r.right + 3, mid(r), n.left, mid(n)), goal?.hue, [r.right + 3, mid(r)],
        goal ? widthOf(goal) : null, !model.goalIn(g));
    }
    if (sm.indRow) {
      const r = box(sm.indRow);
      add(`out|${l.id}|${sm.focus}`, curve(n.right, mid(n), r.left - 3, mid(r)), l.hue, [r.left - 3, mid(r)], null,
        !model.linkIn(l));
    }
  }
  // A short dotted stub beside an indicator no link reaches, so the gap is drawn, not left blank.
  const stubs = svgEl('g', { class: 'sm-stubs' });
  if (sm.indRow && !sm.links.length) {
    const r = box(sm.indRow);
    stubs.append(svgEl('line', { x1: r.left - 3 - STUB, y1: mid(r), x2: r.left - 3, y2: mid(r), class: 'sm-stub' }));
  }
  svg.append(stubs, bands, ends);
  paint(sm);
}

// ---------------------------------------------------------------- paint

function paint(sm) {
  const item = sm.pick || sm.hover;
  const lit = litBy(sm.model, item);
  sm.map.classList.toggle('is-focus', !!lit);
  for (const [kind, rows] of [['goal', sm.rows.goal], ['link', sm.rows.link], ['indicator', sm.rows.indicator]]) {
    for (const [id, row] of rows) {
      const on = !!lit && lit[kind].has(id);
      row.classList.toggle('is-on', on);
      row.classList.toggle('is-dim', !!lit && !on);
      row.classList.toggle('is-self', !!item && item.kind === kind && item.id === id);
    }
  }
  const front = [];
  for (const s of sm.segs || []) {
    const on = !!lit && lit.seg.has(s.key);
    s.path.style.stroke = on ? full(s.hue) : pale(s.hue);
    s.path.classList.toggle('is-on', on);
    s.path.classList.toggle('is-dim', !!lit && !on);
    s.path.classList.toggle('is-out', s.out && !on);
    s.dot.style.fill = on ? full(s.hue) : pale(s.hue);
    s.dot.classList.toggle('is-dim', (!!lit && !on) || (s.out && !on));
    if (on) front.push(s.path);
  }
  for (const p of front) p.parentNode.appendChild(p);   // lit lines on top of the pale ones
  readout(sm, item);
}

// ---------------------------------------------------------------- panel

function readout(sm, item) {
  const { panel, model } = sm;
  const { data, scope } = model;
  const inner = el('div', 'sm-panel-inner');
  const eyebrow = (text, hue) => {
    const e = el('div', 'sm-eyebrow');
    if (hue !== undefined) { const s = el('span', 'sm-swatch'); s.style.background = swatch(hue); e.append(s); }
    e.append(el('span', null, text));
    return e;
  };
  const section = (title, ...kids) => { const s = el('div', 'sm-sec'); s.append(el('div', 'sm-sec-head', title), ...kids); return s; };
  const text = (t, cls = '') => el('p', `sm-text ${cls}`.trim(), t);
  const laneLines = (name, serves) => {
    const dl = el('dl', 'sm-lane-lines');
    if (name) dl.append(el('dt', null, 'District priority'), el('dd', 'sm-strong', name));
    if (serves) dl.append(el('dt', null, 'Serves'), el('dd', null, serves));
    return dl;
  };
  const linkLine = l => {
    const li = el('li');
    li.append(el('b', null, l.name), el('span', 'sm-muted', ` · ${kindLine(l)}`));
    return li;
  };
  const goalName = id => {
    const g = model.goals.get(id);
    if (!g) return null;
    const span = el('span', scope && !model.goalIn(id) ? 'sm-muted' : null, g.name);
    if (scope && !model.goalIn(id)) span.textContent += ' (not named here)';
    return span;
  };
  const joined = ids => {
    const div = el('div', 'sm-sub');
    ids.map(goalName).filter(Boolean).forEach((s, k) => { if (k) div.append('; '); div.append(s); });
    return div;
  };
  const who = scope ? (scope.kind === 'school' ? 'No partner there' : scope.label) : '';
  // Research associations always come with the review's caution, and in a list of their own.
  const assocSection = (title, ls, line) => {
    const list = el('ul', 'sm-list');
    for (const l of ls) list.append(line(l));
    return section(title, list, text(data.associatedCaution, 'sm-caution'), text(data.associatedNote, 'sm-caution'));
  };

  // With nothing picked or pointed at, the panel reads out the indicator the map shows.
  const atRest = !item;
  if (atRest) item = focusPick(sm);
  if (item.kind === 'goal') {
    const g = model.goals.get(item.id);
    const all = model.linksOfGoal.get(item.id) || [];
    const ls = all.filter(l => !l.associated);
    const assocLs = all.filter(l => l.associated);
    // "Model not confirmed" belongs to tested links only; a research association has no model to confirm.
    const fit = s => (ls.length ? s : s.replace(/; model not confirmed/, ''));
    const list = el('ul', 'sm-list');
    for (const l of ls) {
      const li = linkLine(l);
      li.append(el('div', 'sm-sub', `could help move ${l.indicators.map(i => model.indicators.get(i)?.name).join('; ')}`));
      list.append(li);
    }
    inner.append(eyebrow(`Goal · ${g.domainName}`, g.hue), el('div', 'sm-title', g.name));
    if (g.definition) inner.append(text(g.definition));
    if (g.laneName) inner.append(laneLines(g.laneName, g.serves));
    if (scope) {
      if (scope.kind === 'school') {
        inner.append(el('p', 'sm-count', g.here
          ? fit(`${plural(g.here, 'partner here names', 'partners here name')} this goal; model not confirmed`)
          : `${who} names this goal.`));
        if (g.hereNames?.length) inner.append(el('p', 'sm-sub', g.hereNames.join('; ')));
      } else {
        inner.append(el('p', 'sm-count', g.here
          ? fit(`${scope.label} names this goal in ${plural(g.here, 'statement', 'statements')}; model not confirmed`)
          : `${scope.label} does not name this goal.`));
        if (g.hereSamples?.length) {
          const quotes = el('ul', 'sm-quotes');
          for (const t of g.hereSamples) quotes.append(el('li', null, t));
          inner.append(quotes);
        }
      }
      inner.append(el('p', 'sm-sub', `Across all partners: ${fit(programs(g.programs)).toLowerCase()}.`));
    } else {
      inner.append(el('p', 'sm-count', fit(programs(g.programs))));
    }
    if (ls.length) {
      inner.append(section(ls.length === 1 ? 'Program model that could connect it' : 'Program models that could connect it', list),
        text('Naming this goal earns no credit on its own. A link holds for a program only once someone confirms it runs the model.', 'sm-caution'));
    }
    if (assocLs.length) {
      inner.append(assocSection('Research associations', assocLs, l => {
        const li = el('li');
        li.append(el('b', null, l.name), el('div', 'sm-sub', l.pathway));
        return li;
      }));
    }
  } else if (item.kind === 'link' && model.links.get(item.id)?.associated) {
    const l = model.links.get(item.id);
    const goals = el('ul', 'sm-list');
    for (const id of l.goals) {
      const g = model.goals.get(id);
      if (!g) continue;
      const li = el('li');
      li.append(el('b', null, g.name), el('div', 'sm-sub', scope
        ? (g.here ? `${hereWords(scope, g.here)} here` : 'Not named here') : programs(g.programs).replace(/; model not confirmed$/, '')));
      goals.append(li);
    }
    const inds = el('ul', 'sm-list');
    for (const id of l.indicators) {
      const i = model.indicators.get(id);
      const li = el('li');
      li.append(el('b', null, i.name), el('span', 'sm-muted', ` · ${data.year}: ${i.value}`));
      inds.append(li);
    }
    inner.append(eyebrow('Research association · never credit', l.hue), el('div', 'sm-title', l.name),
      section('What the research says', text(l.pathway, 'sm-strong')),
      text(data.associatedCaution, 'sm-caution'), text(data.associatedNote, 'sm-caution'),
      section('What kind of link: research-associated', text(data.associatedRule || KIND.associated.explain)));
    if (l.basis) inner.append(section('The studies behind it', text(l.basis)));
    if (l.effect) inner.append(section('What the studies found', text(l.effect)));
    if (l.caveats) inner.append(section('Limits of the evidence', text(l.caveats)));
    if (l.philadelphia) inner.append(section('In Philadelphia', text(l.philadelphia)));
    inner.append(section('Goals it is about', goals), section('Indicators it is associated with', inds));
    if (l.studies?.length) {
      const details = el('details', 'sm-studies');
      details.append(el('summary', null, `The ${plural(l.studies.length, 'study', 'studies')} behind it`));
      const ol = el('ol', 'sm-list');
      for (const c of l.studies) ol.append(el('li', null, c));
      details.append(ol);
      inner.append(details);
    }
  } else if (item.kind === 'link') {
    const l = model.links.get(item.id);
    const inds = el('ul', 'sm-list');
    for (const id of l.indicators) {
      const i = model.indicators.get(id);
      const li = el('li');
      li.append(el('b', null, i.name), el('span', 'sm-muted', ` · ${data.year}: ${i.value}`));
      inds.append(li);
    }
    const goals = el('ul', 'sm-list');
    for (const id of l.goals) {
      const g = model.goals.get(id);
      if (!g) continue;
      const li = el('li');
      li.append(el('b', null, g.name), el('div', 'sm-sub', scope
        ? (g.here ? `${hereWords(scope, g.here)} here; model not confirmed` : 'Not named here')
        : programs(g.programs)));
      goals.append(li);
    }
    inner.append(eyebrow('Program model · a possible link', l.hue), el('div', 'sm-title', l.name),
      section('The program must run', text(l.model, 'sm-strong')),
      section(`What kind of link: ${KIND[l.kind].word.toLowerCase()}`, text(KIND[l.kind].explain),
        text(`Evidence: ${l.evidenceLabel}${l.scope ? `, ${l.scope}` : ''}.`, 'sm-caution')),
      section('Why the link makes sense', text(l.pathway)));
    if (l.effect) inner.append(section('What the studies found', text(l.effect)));
    if (l.size) inner.append(section('What it could mean for a school', text(l.size)));
    if (l.caveats) inner.append(section('Limits of the evidence', text(l.caveats)));
    if (l.philadelphia) inner.append(section('In Philadelphia', text(l.philadelphia)));
    if (l.conditions) inner.append(section('Holds only when', text(l.conditions)));
    inner.append(section('Goals it joins', goals), section('Indicators it could help move', inds));
    if (l.studies?.length) {
      const details = el('details', 'sm-studies');
      details.append(el('summary', null, `The ${plural(l.studies.length, 'study', 'studies')} behind it`));
      const ol = el('ol', 'sm-list');
      for (const c of l.studies) ol.append(el('li', null, c));
      details.append(ol);
      inner.append(details);
    }
  } else if (item.kind === 'indicator') {
    const i = model.indicators.get(item.id);
    const all = model.linksOfInd.get(item.id) || [];
    const ls = all.filter(l => !l.associated);
    const assocLs = all.filter(l => l.associated);
    inner.append(eyebrow(`District indicator · ${i.group}`), el('div', 'sm-title', i.name), text(i.wording),
      el('p', 'sm-count', `${data.year}: ${i.value}`));
    if (!ls.length && !assocLs.length) {
      inner.append(section('No link yet', text('The research review found no study strong enough to link a partner goal to this indicator.')));
    } else if (!ls.length) {
      inner.append(section('No tested program model yet', text('No study has tested a program model that moves this indicator.')));
    } else {
      const list = el('ul', 'sm-list');
      for (const l of ls) {
        const li = linkLine(l);
        li.append(joined(l.goals));
        list.append(li);
      }
      inner.append(section('Program models that could help move it, and the goals they join', list),
        text('Counts are per goal and never add up per indicator: one program can name several of these goals.', 'sm-caution'));
    }
    if (assocLs.length) {
      inner.append(assocSection('Goals research associates with it', assocLs, l => {
        const li = el('li');
        li.append(el('b', null, l.name), el('span', 'sm-muted', ' · is associated with this indicator'), joined(l.goals));
        return li;
      }));
    }
    if (atRest) {
      if (scope) {
        inner.append(text(`Goals in dark type are the linked goals ${scope.kind === 'school' ? 'these partners name' : 'this program names'}. ` +
          `Pale goals are linked goals ${scope.kind === 'school' ? 'no partner there names' : 'it does not name'}, so the gaps stay in view.`));
      }
      if (all.length) inner.append(text(data.possible, 'sm-caution'));
      inner.append(el('p', 'sm-hint', 'Point at or pick a goal or a program model to see why it is linked and what a program would have to run. Pick another indicator from the list to see its links.'));
    }
  }
  panel.replaceChildren(inner);
}
