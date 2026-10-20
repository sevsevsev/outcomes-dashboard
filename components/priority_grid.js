// The District priorities grid: the crosswalk's lanes as rows under the Board's
// three headings, the codebook's domains as columns. A dot sits only where the
// crosswalk puts goals of that domain in that lane; its area and its printed
// number are the programs naming one of those goals. Drawn in the browser so
// pointing costs no round trip to Python (see priority_component.py).
//
// The rules it keeps: lanes stay in the file's order and are never sorted,
// totalled or coloured by size; every number is printed, so dot size is never
// the only way to read it; an empty cell is structure (the codebook has no
// goal there), drawn as a faint point, never as a gap; a guardrail lane is a
// Board priority in its own right.
//
// Rows and dots are the targets. Pointing previews in the side panel; a click
// (or Enter, or a tap) pins, and clicking the same thing again, or Escape,
// unpins. While something is pinned, pointing elsewhere changes nothing. Each
// pin goes to Python as the "selection" state, which filters the table below.
// `data.sig` changes only when what is drawn changes.

const SVG_NS = 'http://www.w3.org/2000/svg';
const LABEL_W = 236;      // lane names, wrapped to two lines, and each lane's own count
const COL_W = 40;         // one domain
const HEAD_H = 178;       // room for the slanted domain names
const WRAP = 27;          // characters per line of a lane name
const ROW_H = 40;
const GROUP_H = 34;
const R_MIN = 4, R_MAX = 17;

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function svgEl(tag, attrs, text) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) node.setAttribute(k, v);
  if (text !== undefined) node.textContent = text;
  return node;
}

const plural = (n, one, many) => `${n.toLocaleString()} ${n === 1 ? one : many}`;
const laneLine = n => `${plural(n, 'program', 'programs')} naming a goal in this lane`;

export default function (component) {
  const { data, parentElement, setStateValue } = component;
  if (!data || !data.lanes) return;
  let root = parentElement.querySelector('.pg');
  if (!root) {
    root = el('div', 'pg');
    parentElement.appendChild(root);
  }
  const pg = root.__pg || (root.__pg = {});
  pg.send = setStateValue;
  if (pg.sig !== data.sig) mount(root, pg, data);
}

function mount(root, pg, data) {
  const firstMount = pg.sig === undefined;
  pg.sig = data.sig;
  pg.data = data;
  pg.lanes = new Map(data.lanes.map(l => [l.id, l]));
  pg.domains = new Map(data.domains.map(d => [d.code, d]));
  pg.cells = new Map(data.cells.map(c => [`${c.lane}|${c.domain}`, c]));
  pg.targets = new Map();
  if (firstMount && data.selected && data.selected.id) pg.pin = data.selected.id;
  if (pg.pin && !pg.lanes.has(pg.pin) && !pg.cells.has(pg.pin)) pg.pin = null;

  root.replaceChildren();
  const body = el('div', 'pg-body');
  const chart = el('div', 'pg-chart');
  const panel = el('div', 'pg-panel');
  panel.setAttribute('aria-live', 'polite');
  body.append(chart, panel);
  root.append(el('p', 'pg-title', 'District priorities'),
    el('p', 'pg-sub', 'The number beside each priority is the programs naming a goal in it. A dot shows the ' +
      'programs naming a goal from that domain in that priority.'), body);
  pg.panel = panel;

  const doms = data.domains;
  const W = LABEL_W + COL_W * doms.length + 8;
  const rows = [];
  let y = HEAD_H;
  for (const group of data.groups) {
    rows.push({ group, y });
    y += GROUP_H;
    for (const lane of data.lanes.filter(l => l.group === group)) {
      rows.push({ lane, y });
      y += ROW_H;
    }
    y += 6;
  }
  const H = y;
  const svg = svgEl('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'group',
    'aria-label': 'District priorities by domain' });
  chart.append(svg);

  // Domain names slant up to the left from their column, so the last ones never run off the right edge.
  doms.forEach((d, i) => {
    const x = LABEL_W + COL_W * i + COL_W / 2 + 4;
    svg.append(svgEl('text', { x, y: HEAD_H - 8, 'text-anchor': 'end', transform: `rotate(40 ${x} ${HEAD_H - 8})`,
      class: 'pg-dom' }, d.name));
  });

  const max = Math.max(1, ...data.cells.map(c => c.programs));
  const radius = n => (n ? R_MIN + (R_MAX - R_MIN) * Math.sqrt(n / max) : R_MIN);

  for (const r of rows) {
    if (r.group) {
      svg.append(svgEl('text', { x: 0, y: r.y + 21, class: 'pg-group' }, r.group.toUpperCase()));
      svg.append(svgEl('line', { x1: 0, x2: W, y1: r.y + 29, y2: r.y + 29, class: 'pg-rule' }));
      continue;
    }
    const lane = r.lane;
    const cy = r.y + ROW_H / 2;
    const row = svgEl('g', { class: 'pg-target pg-lane', tabindex: 0, role: 'button',
      'aria-label': `${lane.name}: ${laneLine(lane.programs)}` });
    row.append(svgEl('rect', { x: 0, y: r.y + 2, width: LABEL_W - 8, height: ROW_H - 4, rx: 6, class: 'pg-hit' }),
      nameText(lane.name, cy),
      svgEl('text', { x: LABEL_W - 16, y: cy + 4, 'text-anchor': 'end', class: 'pg-count' },
        lane.programs.toLocaleString()));
    svg.append(row);
    wire(pg, row, lane.id);
    pg.targets.set(lane.id, { node: row, lane: lane.id });

    doms.forEach((d, i) => {
      const cx = LABEL_W + COL_W * i + COL_W / 2;
      const cell = pg.cells.get(`${lane.id}|${d.code}`);
      if (!cell) {
        svg.append(svgEl('circle', { cx, cy, r: 1.5, class: 'pg-empty' }));
        return;
      }
      const id = `${lane.id}|${d.code}`;
      const rad = radius(cell.programs);
      const g = svgEl('g', { class: 'pg-target pg-cell', tabindex: 0, role: 'button',
        'aria-label': `${lane.name}, ${d.name}: ${plural(cell.programs, 'program names', 'programs name')} a goal here` });
      g.append(svgEl('rect', { x: cx - COL_W / 2 + 1, y: r.y + 1, width: COL_W - 2, height: ROW_H - 2, rx: 6,
        class: 'pg-hit' }));
      g.append(svgEl('circle', { cx, cy, r: rad, class: cell.programs ? 'pg-dot' : 'pg-dot pg-zero' }));
      if (rad >= 12) g.append(svgEl('text', { x: cx, y: cy + 4, 'text-anchor': 'middle', class: 'pg-in' },
        cell.programs.toLocaleString()));
      else g.append(svgEl('text', { x: cx, y: cy - rad - 3, 'text-anchor': 'middle', class: 'pg-out' },
        cell.programs.toLocaleString()));
      svg.append(g);
      wire(pg, g, id);
      pg.targets.set(id, { node: g, lane: lane.id });
    });
  }

  root.onkeydown = e => {
    if (e.key === 'Escape' && pg.pin) { pg.pin = null; paint(pg); send(pg); }
  };
  paint(pg);
}

// A lane name on one line, or two when it is long, centred on the row.
function nameText(name, cy) {
  const lines = [];
  for (const word of name.split(' ')) {
    const last = lines.length - 1;
    if (last >= 0 && (lines[last] + ' ' + word).length <= WRAP) lines[last] += ' ' + word;
    else lines.push(word);
  }
  const text = svgEl('text', { x: 8, y: cy + 4 - (lines.length - 1) * 8, class: 'pg-name' });
  lines.forEach((line, i) => text.append(svgEl('tspan', { x: 8, dy: i ? 16 : 0 }, line)));
  return text;
}

function wire(pg, node, id) {
  node.addEventListener('pointerenter', () => { if (!pg.pin) { pg.hover = id; paint(pg); } });
  node.addEventListener('pointerleave', () => { if (pg.hover === id) { pg.hover = null; paint(pg); } });
  const toggle = () => { pg.pin = pg.pin === id ? null : id; pg.hover = null; paint(pg); send(pg); };
  node.addEventListener('click', toggle);
  node.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
  });
}

function send(pg) {
  if (pg.send) pg.send('selection', pg.pin ? { kind: pg.pin.includes('|') ? 'cell' : 'lane', id: pg.pin } : null);
}

function paint(pg) {
  const focus = pg.pin || pg.hover;
  const focusLane = focus ? focus.split('|')[0] : null;
  for (const [id, t] of pg.targets) {
    const on = !!focus && (id === focus || (!focus.includes('|') && t.lane === focusLane));
    t.node.classList.toggle('is-on', on);
    t.node.classList.toggle('is-pinned', id === pg.pin);
    t.node.setAttribute('aria-pressed', id === pg.pin ? 'true' : 'false');
  }
  describe(pg, focus);
}

function describe(pg, focus) {
  const p = pg.panel;
  p.replaceChildren();
  const data = pg.data;
  if (!focus) {
    p.append(el('p', 'pg-k', 'How to read this'),
      el('p', null, 'Each goal in the codebook serves one District priority. A dot shows how many programs name a ' +
        'goal from that domain in that priority. Point at a dot or a priority to see its goals; click to keep it ' +
        'open and narrow the table below.'),
      el('p', 'pg-muted', 'A program counts everywhere it names a goal, so the numbers never add up to a total. ' +
        'They say what programs work toward, not what they achieve. Programs that share one logic model count once.'));
    if (data.bylaw) p.append(bylaw(data.bylaw));
    return;
  }
  const [laneId, domain] = focus.split('|');
  const lane = pg.lanes.get(laneId);
  let goals;
  if (domain) {
    const cell = pg.cells.get(focus);
    goals = cell.goals;
    p.append(el('p', 'pg-k', lane.name), el('h4', null, pg.domains.get(domain).name),
      el('p', null, `${plural(cell.programs, 'program names', 'programs name')} a goal from this domain in this lane.`));
  } else {
    goals = data.cells.filter(c => c.lane === laneId).flatMap(c => c.goals);
    p.append(el('p', 'pg-k', 'District priority'), el('h4', null, lane.name));
    if (lane.description) p.append(el('p', null, lane.description));
    if (lane.quote) p.append(el('p', 'pg-quote', `“${lane.quote}”`));
    p.append(el('p', 'pg-strong', laneLine(lane.programs)));
  }
  p.append(el('p', 'pg-k', 'Its goals, and programs naming each'));
  const list = el('ul', 'pg-goals');
  for (const g of goals) {
    const li = el('li', g.programs ? null : 'pg-none');
    li.append(el('span', null, g.name), el('span', 'pg-n', g.programs ? g.programs.toLocaleString() : 'none'));
    list.append(li);
  }
  p.append(list);
  if (!domain && lane.quote && data.bylaw) p.append(bylaw(data.bylaw));
}

function bylaw(url) {
  const a = el('a', null, 'Board of Education Bylaw 003.1, Goals and Guardrails');
  a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer';
  const p = el('p', 'pg-muted');
  p.append(a);
  return p;
}
