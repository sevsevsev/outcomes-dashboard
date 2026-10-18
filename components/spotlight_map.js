// The District indicators map: the goals partners name on the left, the program
// models the studies tested in the middle, and the District's SPOTlight
// indicators on the right, joined by thin bands. Drawn in the browser so
// pointing costs no round trip to Python (see spotlight_component.py).
//
// It follows the codebook wheel's habits: plain names, per-domain hues, pale at
// rest and full hue only for what is pointed at or picked, and a side panel
// that says what that is. The rows and model nodes are the targets, never the
// bands, so a pointer resting on the map never sits on something that moves.
// Every band is the same width: program counts are text in the panel, never a
// length, so nothing adds up per indicator. Line style repeats the evidence
// level, which the node and the panel also say in words.
//
// A click (or Enter, or a tap) pins a row or node; clicking it again, clicking
// empty space or Escape unpins. While something is pinned, pointing elsewhere
// changes nothing, so the panel never flickers. Each pin goes to Python as the
// "selection" state, which filters the table below. `data.sig` changes only
// when what is drawn changes, so reruns caused by a pick leave the map alone.

const SVG_NS = 'http://www.w3.org/2000/svg';
const NODE_GAP = 10;        // least space between two model nodes
const STUB = 34;            // length of the dotted stub beside a row no study reaches
const DASH = { strong: null, good: null, suggestive: '6 4', definitional: '1.5 4', thin: '1.5 4' };

const pale = h => (h === null || h === undefined ? '#cbd5e1' : `hsl(${h} 42% 74%)`);
const full = h => (h === null || h === undefined ? '#64748b' : `hsl(${h} 58% 40%)`);
const swatch = h => (h === null || h === undefined ? '#94a3b8' : `hsl(${h} 55% 52%)`);

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
  return { data, goals, links, indicators, linksOfGoal, linksOfInd };
}

/** What a pick lights: the rows, nodes and band segments ("in" goal->link, "out" link->indicator). */
function litBy(model, item) {
  const lit = { goal: new Set(), link: new Set(), indicator: new Set(), other: false, seg: new Set() };
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
  } else if (item.kind === 'other') {
    lit.other = true;
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
  if (firstMount && data.selected && data.selected.kind) sm.pick = data.selected;
  root.replaceChildren();
  sm.rows = { goal: new Map(), link: new Map(), indicator: new Map(), other: null };

  const map = el('div', 'sm-map');
  const svg = svgEl('svg', { class: 'sm-bands', 'aria-hidden': 'true' });
  const cols = el('div', 'sm-cols');
  map.append(cols);
  sm.map = map;
  sm.cols = cols;
  sm.svg = svg;

  // Goals, in codebook order under their domains.
  const goalCol = el('div', 'sm-col sm-goals');
  goalCol.append(el('div', 'sm-head', 'Goals partners name'));
  let domain = null;
  for (const g of data.goals) {
    if (g.domain !== domain) {
      domain = g.domain;
      const head = el('div', 'sm-dom');
      const sw = el('span', 'sm-swatch');
      sw.style.background = swatch(g.hue);
      head.append(sw, el('span', null, g.domainName));
      goalCol.append(head);
    }
    const row = button('sm-row sm-goal', { kind: 'goal', id: g.id }, sm, `${g.name}. ${programs(g.programs)}.`);
    row.append(el('span', 'sm-name', g.name));
    sm.rows.goal.set(g.id, row);
    goalCol.append(row);
  }
  if (data.otherGoals) {
    const other = button('sm-row sm-other', { kind: 'other', id: 'other' }, sm);
    other.append(el('span', 'sm-name', `${data.otherGoals} other goals have no indicator link`),
      el('span', 'sm-note', "They count under the Board's guardrails: a well-rounded education and safe, welcoming schools."));
    sm.rows.other = other;
    goalCol.append(other);
  }

  // Program models: one node per recommended link, placed beside what it joins (see place).
  const linkCol = el('div', 'sm-col sm-links');
  linkCol.append(el('div', 'sm-head', 'Program model studied'));
  const stack = el('div', 'sm-stack');
  linkCol.append(stack);
  sm.stack = stack;
  for (const l of data.links) {
    const node = button('sm-node', { kind: 'link', id: l.id }, sm, `${l.name}. ${l.evidenceLabel}. Possible link only.`);
    node.style.setProperty('--hue-pale', pale(l.hue));
    node.style.setProperty('--hue-full', full(l.hue));
    node.append(el('span', 'sm-name', l.name), el('span', 'sm-ev', evidenceWords(l)));
    sm.rows.link.set(l.id, node);
    stack.append(node);
  }

  // Indicators, grouped as the SPOTlight groups them.
  const indCol = el('div', 'sm-col sm-inds');
  indCol.append(el('div', 'sm-head', `District indicators, ${data.year}`));
  let group = null;
  for (const i of data.indicators) {
    if (i.group !== group) {
      group = i.group;
      indCol.append(el('div', 'sm-group', group));
    }
    const row = button(`sm-row sm-ind${i.reached ? '' : ' is-unreached'}`, { kind: 'indicator', id: i.id }, sm,
      `${i.name}, ${data.year}: ${i.value}.${i.reached ? '' : ' No study the review checked reaches this indicator.'}`);
    const line = el('span', 'sm-line');
    const short = i.value.length <= 8;
    line.append(el('span', 'sm-name', i.name));
    if (short) line.append(el('span', 'sm-value', i.value));
    row.append(line);
    if (!short) row.append(el('span', 'sm-value sm-value-long', i.value));
    if (!i.reached) row.append(el('span', 'sm-note', "No study reaches this. Counts under the Board's guardrails."));
    sm.rows.indicator.set(i.id, row);
    indCol.append(row);
  }

  cols.append(svg, goalCol, el('div', 'sm-gutter'), linkCol, el('div', 'sm-gutter'), indCol);
  cols.addEventListener('click', e => { if (!e.target.closest('button')) setPick(sm, null); });

  const panel = el('aside', 'sm-panel');
  panel.setAttribute('aria-live', 'polite');
  sm.panel = panel;

  const legend = el('div', 'sm-legend');
  for (const [label, dash] of [['Strong or good evidence', null], ['Suggestive evidence', DASH.suggestive], ['By definition', DASH.definitional]]) {
    const item = el('span', 'sm-key');
    const s = svgEl('svg', { width: 28, height: 8, 'aria-hidden': 'true' });
    s.append(svgEl('line', { x1: 1, y1: 4, x2: 27, y2: 4, stroke: '#64748b', 'stroke-width': 2, 'stroke-dasharray': dash, 'stroke-linecap': 'round' }));
    item.append(s, el('span', null, label));
    legend.append(item);
  }
  legend.append(el('span', 'sm-key-note', 'Every band is a possible link only. Bands are all one width; they do not add up.'));

  const body = el('div', 'sm-body');
  body.append(map, panel);
  root.append(body, legend);

  if (!sm.keys) {
    sm.keys = true;
    root.addEventListener('keydown', e => { if (e.key === 'Escape') setPick(sm, null); });
  }
  const relayout = () => { place(sm); draw(sm); };
  if (sm.observer) sm.observer.disconnect();
  sm.observer = new ResizeObserver(relayout);
  sm.observer.observe(cols);
  document.fonts?.ready?.then(relayout);
  relayout();
  paint(sm);
}

function evidenceWords(l) {
  const words = l.predicts ? `${l.evidenceLabel}; predicts, not shown to cause` : l.evidenceLabel;
  return words;
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

function setPick(sm, item) {
  const was = sm.pick;
  sm.pick = item;
  for (const [kind, rows] of Object.entries(sm.rows)) {
    if (!rows) continue;
    const list = rows instanceof Map ? rows : new Map([['other', rows]]);
    for (const [id, row] of list) row.setAttribute('aria-pressed', String(!!item && item.kind === kind && item.id === id));
  }
  paint(sm);
  if ((was && was.kind) !== (item && item.kind) || (was && was.id) !== (item && item.id)) sm.send('selection', item);
}

// ---------------------------------------------------------------- layout

const rel = (box, base) => ({ top: box.top - base.top, bottom: box.bottom - base.top, left: box.left - base.left, right: box.right - base.left });

/** Sets each model node's height beside the rows it joins, keeping them in order and apart. */
function place(sm) {
  const { model, stack } = sm;
  const base = stack.getBoundingClientRect();
  const centre = row => { const r = rel(row.getBoundingClientRect(), base); return (r.top + r.bottom) / 2; };
  const nodes = model.data.links.map(l => {
    const ends = [...l.goals.map(g => sm.rows.goal.get(g)), ...l.indicators.map(i => sm.rows.indicator.get(i))].filter(Boolean);
    const want = ends.reduce((s, r) => s + centre(r), 0) / Math.max(1, ends.length);
    const node = sm.rows.link.get(l.id);
    return { node, want, h: node.offsetHeight };
  }).sort((a, b) => a.want - b.want);
  const colH = Math.max(...[...sm.rows.goal.values(), ...sm.rows.indicator.values(), sm.rows.other].filter(Boolean)
    .map(r => rel(r.getBoundingClientRect(), base).bottom));
  let y = 0;
  for (const n of nodes) { n.top = Math.max(n.want - n.h / 2, y); y = n.top + n.h + NODE_GAP; }
  let limit = colH;
  for (let k = nodes.length - 1; k >= 0; k--) {
    const n = nodes[k];
    n.top = Math.max(0, Math.min(n.top, limit - n.h));
    limit = n.top - NODE_GAP;
  }
  for (const n of nodes) n.node.style.top = `${Math.round(n.top)}px`;
  stack.style.height = `${Math.ceil(Math.max(colH, y))}px`;
}

function curve(x0, y0, x1, y1) {
  const dx = (x1 - x0) / 2;
  return `M${x0.toFixed(1)},${y0.toFixed(1)} C${(x0 + dx).toFixed(1)},${y0.toFixed(1)} ${(x1 - dx).toFixed(1)},${y1.toFixed(1)} ${x1.toFixed(1)},${y1.toFixed(1)}`;
}

/** Draws the bands from the rows' and nodes' current places. */
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
  const bands = svgEl('g', { class: 'sm-bandset' });
  const ends = svgEl('g', { class: 'sm-ends' });
  for (const l of model.data.links) {
    const n = box(sm.rows.link.get(l.id));
    const add = (key, d, hue, endAt) => {
      const path = svgEl('path', { d, class: 'sm-band', 'stroke-dasharray': DASH[l.evidence] ?? null });
      bands.append(path);
      const dot = svgEl('circle', { cx: endAt[0], cy: endAt[1], r: 2.6, class: 'sm-end' });
      ends.append(dot);
      sm.segs.push({ key, path, dot, hue });
    };
    for (const g of l.goals) {
      const row = sm.rows.goal.get(g);
      if (!row) continue;
      const r = box(row);
      add(`in|${g}|${l.id}`, curve(r.right + 3, mid(r), n.left, mid(n)), model.goals.get(g)?.hue, [r.right + 3, mid(r)]);
    }
    for (const i of l.indicators) {
      const row = sm.rows.indicator.get(i);
      if (!row) continue;
      const r = box(row);
      add(`out|${l.id}|${i}`, curve(n.right, mid(n), r.left - 3, mid(r)), l.hue, [r.left - 3, mid(r)]);
    }
  }
  // A short dotted stub beside each row no study reaches, so the gap is drawn, not left blank.
  const stubs = svgEl('g', { class: 'sm-stubs' });
  for (const i of model.data.indicators) {
    if (i.reached) continue;
    const r = box(sm.rows.indicator.get(i.id));
    stubs.append(svgEl('line', { x1: r.left - 3 - STUB, y1: mid(r), x2: r.left - 3, y2: mid(r), class: 'sm-stub' }));
  }
  if (sm.rows.other) {
    const r = box(sm.rows.other);
    stubs.append(svgEl('line', { x1: r.right + 3, y1: mid(r), x2: r.right + 3 + STUB, y2: mid(r), class: 'sm-stub' }));
  }
  svg.append(stubs, bands, ends);
  paint(sm);
}

// ---------------------------------------------------------------- paint

function paint(sm) {
  const item = sm.pick || sm.hover;
  const lit = litBy(sm.model, item);
  const map = sm.map;
  map.classList.toggle('is-focus', !!lit);
  for (const [kind, rows] of [['goal', sm.rows.goal], ['link', sm.rows.link], ['indicator', sm.rows.indicator]]) {
    for (const [id, row] of rows) {
      const on = !!lit && lit[kind].has(id);
      row.classList.toggle('is-on', on);
      row.classList.toggle('is-dim', !!lit && !on);
      row.classList.toggle('is-self', !!item && item.kind === kind && item.id === id);
    }
  }
  if (sm.rows.other) {
    sm.rows.other.classList.toggle('is-on', !!lit && lit.other);
    sm.rows.other.classList.toggle('is-dim', !!lit && !lit.other);
    sm.rows.other.classList.toggle('is-self', !!lit && lit.other);
  }
  const front = [];
  for (const s of sm.segs || []) {
    const on = !!lit && lit.seg.has(s.key);
    s.path.style.stroke = on ? full(s.hue) : pale(s.hue);
    s.path.classList.toggle('is-on', on);
    s.path.classList.toggle('is-dim', !!lit && !on);
    s.dot.style.fill = on ? full(s.hue) : pale(s.hue);
    s.dot.classList.toggle('is-dim', !!lit && !on);
    if (on) front.push(s.path);
  }
  for (const p of front) p.parentNode.appendChild(p);   // lit bands on top of the pale ones
  readout(sm, item);
}

// ---------------------------------------------------------------- panel

function readout(sm, item) {
  const { panel, model } = sm;
  const { data } = model;
  const inner = el('div', 'sm-panel-inner');
  const eyebrow = (text, hue) => {
    const e = el('div', 'sm-eyebrow');
    if (hue !== undefined) { const s = el('span', 'sm-swatch'); s.style.background = swatch(hue); e.append(s); }
    e.append(el('span', null, text));
    return e;
  };
  const section = (title, ...kids) => { const s = el('div', 'sm-sec'); s.append(el('div', 'sm-sec-head', title), ...kids); return s; };
  const guardrail = () => {
    const g = data.guardrail || {};
    const p = el('p', 'sm-text', g.summary);
    const q = el('p', 'sm-quote', g.quote ? `“${g.quote}”` : '');
    const kids = [p];
    if (g.quote) kids.push(q);
    if (g.url) {
      const a = el('a', 'sm-link', 'Board of Education Bylaw 003.1, Goals and Guardrails');
      a.href = g.url; a.target = '_blank'; a.rel = 'noopener noreferrer';
      kids.push(a);
    }
    return kids;
  };
  const linkLine = l => {
    const li = el('li');
    li.append(el('b', null, l.name), el('span', 'sm-muted', ` · ${evidenceWords(l)}`));
    return li;
  };

  if (!item) {
    inner.append(eyebrow('District indicators'),
      el('div', 'sm-title', 'Which goals may reach the District’s indicators'),
      el('p', 'sm-text', `${data.goals.length} goals reach ${data.indicators.filter(i => i.reached).length} of ${data.indicators.length} indicators through ${data.links.length} program models the studies tested.`),
      el('p', 'sm-text sm-caution', data.possible),
      el('p', 'sm-hint', 'Point at or pick a goal, a program model or an indicator to see the evidence and what a program must run.'));
  } else if (item.kind === 'goal') {
    const g = model.goals.get(item.id);
    const ls = model.linksOfGoal.get(item.id) || [];
    const list = el('ul', 'sm-list');
    for (const l of ls) {
      const li = linkLine(l);
      li.append(el('div', 'sm-sub', `may reach ${l.indicators.map(i => model.indicators.get(i)?.name).join('; ')}`));
      list.append(li);
    }
    inner.append(eyebrow(`Goal · ${g.domainName}`, g.hue), el('div', 'sm-title', g.name));
    if (g.definition) inner.append(el('p', 'sm-text', g.definition));
    inner.append(el('p', 'sm-count', programs(g.programs)),
      section(ls.length === 1 ? 'Program model that may connect it' : 'Program models that may connect it', list),
      el('p', 'sm-text sm-caution', 'Naming this goal earns no credit on its own: a link holds for a program only once someone confirms it runs the model.'));
  } else if (item.kind === 'link') {
    const l = model.links.get(item.id);
    const goals = el('ul', 'sm-list');
    for (const id of l.goals) {
      const g = model.goals.get(id);
      if (!g) continue;
      const li = el('li');
      li.append(el('b', null, g.name), el('div', 'sm-sub', programs(g.programs)));
      goals.append(li);
    }
    const inds = el('ul', 'sm-list');
    for (const id of l.indicators) {
      const i = model.indicators.get(id);
      const li = el('li');
      li.append(el('b', null, i.name), el('span', 'sm-muted', ` · ${data.year}: ${i.value}`));
      inds.append(li);
    }
    inner.append(eyebrow('Program model · possible link only', l.hue), el('div', 'sm-title', l.name),
      section('The program must run', el('p', 'sm-text sm-strong', l.model)),
      section('Evidence', el('p', 'sm-text', `${evidenceWords(l)}${l.scope ? `, ${l.scope}` : ''}. ${l.pathway}`)));
    if (l.conditions) inner.append(section('Holds only when', el('p', 'sm-text', l.conditions)));
    inner.append(section('Goals it joins', goals), section('Indicators it may reach', inds));
  } else if (item.kind === 'indicator') {
    const i = model.indicators.get(item.id);
    const ls = model.linksOfInd.get(item.id) || [];
    inner.append(eyebrow(`District indicator · ${i.group}`), el('div', 'sm-title', i.name), el('p', 'sm-text', i.wording),
      el('p', 'sm-count', `${data.year}: ${i.value}`));
    if (!ls.length) {
      inner.append(section('No study the review checked reaches this indicator', ...guardrail()));
    } else {
      const list = el('ul', 'sm-list');
      for (const l of ls) {
        const li = linkLine(l);
        li.append(el('div', 'sm-sub', l.goals.map(g => model.goals.get(g)?.name).filter(Boolean).join('; ')));
        list.append(li);
      }
      inner.append(section('Program models that may reach it, and the goals they join', list),
        el('p', 'sm-text sm-caution', 'Program counts are per goal and never add up per indicator: one program can name several of these goals.'));
    }
  } else if (item.kind === 'other') {
    inner.append(eyebrow('Goals with no indicator link'),
      el('div', 'sm-title', `${data.otherGoals} other goals`),
      el('p', 'sm-text', 'Goals with no indicator link are not worth less.'),
      ...guardrail());
  }
  panel.replaceChildren(inner);
}
