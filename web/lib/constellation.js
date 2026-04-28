/**
 * constellation.js — Pure geometry, layout, and key derivation for agent dispatch UI
 * No side effects, no DOM, no canvas, no globals.
 */

// Stable hash of a string → integer (DJB2)
export function hashStr(s) {
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = ((h * 33) ^ s.charCodeAt(i)) >>> 0;
  return h;
}

// Derive project cluster key from cwd + role
export function projectKey(cwd, role) {
  if (role === 'orchestrator') return 'sutra';
  if (!cwd) return 'sutra';
  const baseRe = /^\/Users\/christopherk\.marks\/Downloads\/personal-os-main\/?/;
  const rel = cwd.replace(baseRe, '');
  if (!rel) return 'sutra';
  const parts = rel.split('/').filter(Boolean);
  if (parts[0] === 'Projects') {
    if (parts[2]) return parts[2];
    if (parts[1]) return parts[1];
  }
  return parts[0] || 'sutra';
}

// Titlecase project key ("lovenotes" → "Lovenotes", "AI_research" → "Ai Research")
export function projectLabel(key) {
  return key.replace(/[-_]/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

// Pick a constellation form based on project key + file count
export function pickForm(key, childCount, isOrchestrator) {
  if (isOrchestrator) return 'nexus';
  const h = hashStr(key);
  if (childCount <= 1) return ['seal', 'stream', 'pair'][h % 3];
  if (childCount <= 4) return ['stream', 'pair', 'seal', 'hub'][h % 4];
  if (childCount <= 8) return ['pair', 'hub', 'branching', 'seal', 'stream'][h % 5];
  return ['hub', 'branching', 'nexus', 'pair', 'stream'][h % 5];
}

// File kind colors (for rendering context)
export const KIND_COLOR = {
  doc: 'hsla(45, 50%, 60%, 0.55)',
  code: 'hsla(200, 50%, 60%, 0.55)',
  note: 'hsla(280, 30%, 65%, 0.45)',
  folder: 'hsla(160, 35%, 55%, 0.50)',
};

export function kindColor(k) {
  return KIND_COLOR[k] || KIND_COLOR.note;
}

// ---- Constellation form builders ----
// Each takes { cx, cy, id, radius } and seeds array [['name', 'kind'], ...]
// Returns { nodes: [], edges: [] } in world space

export function buildHub(entity, seeds) {
  const out = { nodes: [], edges: [] };
  const cx = entity.cx, cy = entity.cy;
  const spokes = Math.min(8, seeds.length - 1);
  const ringR = entity.radius * 0.62;
  out.nodes.push({ id: entity.id + ':core', label: seeds[0][0], kind: seeds[0][1], x: cx, y: cy, isCore: true });
  for (let i = 0; i < spokes; i++) {
    const angle = -Math.PI / 2 + (i / spokes) * Math.PI * 2;
    const seed = seeds[1 + i];
    const nid = entity.id + ':spoke-' + i;
    out.nodes.push({ id: nid, label: seed[0], kind: seed[1], x: cx + Math.cos(angle) * ringR, y: cy + Math.sin(angle) * ringR });
    out.edges.push({ a: entity.id + ':core', b: nid });
  }
  return out;
}

export function buildBranching(entity, seeds) {
  const out = { nodes: [], edges: [] };
  const cx = entity.cx, cy = entity.cy;
  const rootY = cy + entity.radius * 0.55;
  out.nodes.push({ id: entity.id + ':root', label: seeds[0][0], kind: seeds[0][1], x: cx, y: rootY, isCore: true });
  const branchSeeds = seeds.slice(1);
  const layout = [
    { parent: 'root', ang: -Math.PI / 2 - 0.4, len: 0.34 },
    { parent: 'root', ang: -Math.PI / 2 + 0.4, len: 0.34 },
    { parent: 'b0', ang: -Math.PI / 2 - 0.75, len: 0.28 },
    { parent: 'b0', ang: -Math.PI / 2 - 0.15, len: 0.28 },
    { parent: 'b1', ang: -Math.PI / 2 + 0.15, len: 0.26 },
    { parent: 'b1', ang: -Math.PI / 2 + 0.75, len: 0.26 },
  ];
  const coords = { root: { x: cx, y: rootY } };
  layout.forEach((l, i) => {
    const seed = branchSeeds[i]; if (!seed) return;
    const pp = coords[l.parent]; if (!pp) return;
    const len = entity.radius * l.len;
    const x = pp.x + Math.cos(l.ang) * len;
    const y = pp.y + Math.sin(l.ang) * len;
    coords['b' + i] = { x, y };
    const nid = entity.id + ':b' + i;
    out.nodes.push({ id: nid, label: seed[0], kind: seed[1], x, y });
    out.edges.push({ a: entity.id + ':' + (l.parent === 'root' ? 'root' : l.parent), b: nid });
  });
  return out;
}

export function buildPair(entity, seeds) {
  const out = { nodes: [], edges: [] };
  const cx = entity.cx, cy = entity.cy;
  const span = entity.radius * 0.55;
  out.nodes.push({ id: entity.id + ':anchor-a', label: seeds[0][0], kind: seeds[0][1], x: cx - span, y: cy, isCore: true });
  out.nodes.push({ id: entity.id + ':anchor-b', label: seeds[1] ? seeds[1][0] : seeds[0][0], kind: seeds[1] ? seeds[1][1] : 'folder', x: cx + span, y: cy, isCore: true });
  out.edges.push({ a: entity.id + ':anchor-a', b: entity.id + ':anchor-b', isBridge: true });
  const sats = seeds.slice(2);
  sats.forEach((s, i) => {
    const side = i % 2 === 0 ? 'a' : 'b';
    const anchorX = side === 'a' ? cx - span : cx + span;
    const baseAngle = side === 'a' ? Math.PI : 0;
    const idxInSide = Math.floor(i / 2);
    const ang = baseAngle + (idxInSide - 0.5) * 0.7 + (i * 0.13);
    const r = entity.radius * 0.42;
    const nid = entity.id + ':sat-' + i;
    out.nodes.push({ id: nid, label: s[0], kind: s[1], x: anchorX + Math.cos(ang) * r, y: cy + Math.sin(ang) * r });
    out.edges.push({ a: entity.id + (side === 'a' ? ':anchor-a' : ':anchor-b'), b: nid });
  });
  return out;
}

export function buildSeal(entity, seeds) {
  const out = { nodes: [], edges: [] };
  const cx = entity.cx, cy = entity.cy;
  const r = entity.radius * 0.48;
  out.nodes.push({ id: entity.id + ':core', label: seeds[0][0], kind: seeds[0][1], x: cx, y: cy, isCore: true });
  const companions = seeds.slice(1, 6);
  const n = Math.max(4, companions.length);
  companions.forEach((s, i) => {
    const angle = -Math.PI / 2 + (i / n) * Math.PI * 2;
    const nid = entity.id + ':comp-' + i;
    out.nodes.push({ id: nid, label: s[0], kind: s[1], x: cx + Math.cos(angle) * r, y: cy + Math.sin(angle) * r });
    out.edges.push({ a: entity.id + ':core', b: nid });
    if (i > 0) out.edges.push({ a: entity.id + ':comp-' + (i - 1), b: nid });
  });
  if (companions.length >= 3) {
    out.edges.push({ a: entity.id + ':comp-0', b: entity.id + ':comp-' + (companions.length - 1) });
  }
  return out;
}

export function buildStream(entity, seeds) {
  const out = { nodes: [], edges: [] };
  const cx = entity.cx, cy = entity.cy;
  const n = seeds.length;
  const startX = cx - entity.radius * 0.72;
  const startY = cy - entity.radius * 0.5;
  const endX = cx + entity.radius * 0.72;
  const endY = cy + entity.radius * 0.5;
  const dx = endX - startX, dy = endY - startY;
  const len = Math.hypot(dx, dy) || 1;
  const px = -dy / len, py = dx / len;
  seeds.forEach((s, i) => {
    const t = n <= 1 ? 0.5 : i / (n - 1);
    const wave = Math.sin(i * 1.3) * entity.radius * 0.08;
    const x = startX + dx * t + px * wave;
    const y = startY + dy * t + py * wave;
    const nid = entity.id + ':link-' + i;
    out.nodes.push({ id: nid, label: s[0], kind: s[1], x, y, isCore: i === 0 });
    if (i > 0) out.edges.push({ a: entity.id + ':link-' + (i - 1), b: nid });
  });
  return out;
}

export function buildNexus(entity, seeds) {
  const out = { nodes: [], edges: [] };
  const cx = entity.cx, cy = entity.cy;
  const coreSeed = seeds[0];
  const rest = seeds.slice(1);
  const innerCount = Math.min(6, Math.ceil(rest.length / 2));
  const inner = rest.slice(0, innerCount);
  const outer = rest.slice(innerCount);
  const r1 = entity.radius * 0.42;
  const r2 = entity.radius * 0.82;
  out.nodes.push({ id: entity.id + ':core', label: coreSeed[0], kind: coreSeed[1], x: cx, y: cy, isCore: true });
  inner.forEach((s, i) => {
    const angle = -Math.PI / 2 + (i / inner.length) * Math.PI * 2;
    const nid = entity.id + ':in-' + i;
    out.nodes.push({ id: nid, label: s[0], kind: s[1], x: cx + Math.cos(angle) * r1, y: cy + Math.sin(angle) * r1 });
    out.edges.push({ a: entity.id + ':core', b: nid });
  });
  outer.forEach((s, i) => {
    const angle = -Math.PI / 2 + (i / outer.length) * Math.PI * 2 + 0.3;
    const nid = entity.id + ':out-' + i;
    out.nodes.push({ id: nid, label: s[0], kind: s[1], x: cx + Math.cos(angle) * r2, y: cy + Math.sin(angle) * r2 });
    if (inner.length) {
      const nearest = Math.round((i / outer.length) * inner.length) % inner.length;
      out.edges.push({ a: entity.id + ':in-' + nearest, b: nid });
    } else {
      out.edges.push({ a: entity.id + ':core', b: nid });
    }
  });
  return out;
}

export const BUILDERS = {
  hub: buildHub,
  branching: buildBranching,
  pair: buildPair,
  seal: buildSeal,
  stream: buildStream,
  nexus: buildNexus,
};

// Assign world positions to project clusters in circular layout
export function layoutProjects(keys, existingProjects = {}) {
  const newProjects = {};
  keys.sort((a, b) => {
    if (a === 'sutra') return -1;
    if (b === 'sutra') return 1;
    return a.localeCompare(b);
  });
  const outerKeys = keys.filter(k => k !== 'sutra');
  keys.forEach((key, i) => {
    if (existingProjects[key]) {
      newProjects[key] = existingProjects[key];
    } else {
      let wx = 0, wy = 0;
      if (key !== 'sutra') {
        const idx = outerKeys.indexOf(key);
        const r = 800;
        const angle = (idx / outerKeys.length) * Math.PI * 2 - Math.PI / 2;
        wx = Math.cos(angle) * r;
        wy = Math.sin(angle) * r;
      }
      newProjects[key] = {
        name: projectLabel(key),
        wx, wy,
        hue: key === 'sutra' ? 280 : (i * 53) % 360,
        agents: [],
        radius: 0,
      };
    }
    newProjects[key].agents = [];
  });
  return newProjects;
}

// Camera coordinate transforms
export function toScreen(wx, wy, cam, W, H) {
  return { x: W/2 + (wx + cam.x) * cam.scale, y: H/2 + (wy + cam.y) * cam.scale };
}

export function fromScreen(sx, sy, cam, W, H) {
  return { x: (sx - W/2) / cam.scale - cam.x, y: (sy - H/2) / cam.scale - cam.y };
}

// Relative time formatting (ISO → "5m ago")
export function relTime(isoStr) {
  if (!isoStr) return '';
  const ts = new Date(isoStr).getTime();
  const now = Date.now();
  const elapsedMs = now - ts;
  if (elapsedMs < 0) return 'future';
  const secs = Math.floor(elapsedMs / 1000);
  if (secs < 60) return secs + 's ago';
  const mins = Math.floor(secs / 60);
  if (mins < 60) return mins + 'm ago';
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return hrs + 'h ago';
  const days = Math.floor(hrs / 24);
  return days + 'd ago';
}

// Extract task description from agent system_prompt
export function deriveTask(agent) {
  if (!agent.system_prompt) return null;
  const sp = agent.system_prompt;
  const parts = sp.split('—');
  if (parts.length > 1) {
    const afterDash = parts.slice(1).join('—').trim();
    const firstSentence = afterDash.match(/[^.!?]+/)?.[0]?.trim();
    if (firstSentence && firstSentence.length > 0) {
      return firstSentence.length > 60 ? firstSentence.slice(0, 60) + '…' : firstSentence;
    }
  }
  return null;
}

// Parse tool name from last_action string
export const TOOL_PATTERNS = [
  [/\bRead\b|\breading\b/i,   'READ'],
  [/\bWrite\b|\bwriting\b/i,  'WRITE'],
  [/\bEdit\b|\bediting\b/i,   'EDIT'],
  [/\bBash\b|\bshell\b|\brunning\b/i, 'BASH'],
  [/\bGrep\b|\bsearch\b|\bsearching\b/i, 'GREP'],
  [/\bGlob\b|\bfind\b/i,      'GLOB'],
  [/\bfetch\b|\bweb\b/i,      'FETCH'],
  [/\bthink\b|\bplan\b/i,     'THINK'],
];

export function parseToolFromAction(action) {
  if (!action) return null;
  for (const [re, label] of TOOL_PATTERNS) {
    if (re.test(action)) return label;
  }
  return null;
}

// Status → hex color
export function statusColor(status) {
  if (status === 'busy') return '#6fe1b1';
  if (status === 'online') return '#6fe1b1';
  if (status === 'offline') return '#303850';
  return '#6fe1b1';
}

// Insert thin space between characters
export function spaced(s) {
  return s.split('').join('\u202f');
}

// Seeded PRNG
export function seededRandom(seed) {
  let s = seed;
  return function() {
    s = (s * 9301 + 49297) % 233280;
    return s / 233280;
  };
}
