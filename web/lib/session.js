/**
 * session.js — Pure functions for session parsing, formatting, and tool classification
 * No side effects, no DOM, no globals.
 */

// Compute aggregate stats from session entries
export function computeStats(entries) {
  let userTurns = 0;
  let assistantTurns = 0;
  let inputTokens = 0;
  let outputTokens = 0;
  let cacheReadTokens = 0;
  let cacheCreateTokens = 0;
  let totalCost = 0;
  let model = '';
  let sessionId = '';
  let firstTs = null;
  let lastTs = null;

  for (const entry of entries) {
    const ts = entry.timestamp ? new Date(entry.timestamp) : null;
    if (ts) {
      if (!firstTs || ts < firstTs) firstTs = ts;
      if (!lastTs || ts > lastTs) lastTs = ts;
    }

    if (entry.type === 'user') userTurns++;
    if (entry.type === 'assistant') {
      assistantTurns++;
      const msg = entry.message;
      if (msg?.model && !model) model = msg.model;
      if (msg?.usage) {
        inputTokens += msg.usage.input_tokens || 0;
        outputTokens += msg.usage.output_tokens || 0;
        cacheReadTokens += msg.usage.cache_read_input_tokens || 0;
        cacheCreateTokens += msg.usage.cache_creation_input_tokens || 0;
      }
    }
    if (entry.type === 'result') {
      if (entry.costUSD) totalCost += entry.costUSD;
      if (entry.totalCostUSD) totalCost = entry.totalCostUSD;
      if (entry.model && !model) model = entry.model;
    }
    if (entry.sessionId && !sessionId) sessionId = entry.sessionId;
  }

  const durationMs = firstTs && lastTs ? (lastTs - firstTs) : 0;

  return {
    userTurns,
    assistantTurns,
    totalTurns: userTurns + assistantTurns,
    inputTokens,
    outputTokens,
    cacheReadTokens,
    cacheCreateTokens,
    totalCost,
    model,
    sessionId,
    durationMs,
    firstTs,
    lastTs,
    totalEntries: entries.length
  };
}

// Format milliseconds as human-readable duration
export function formatDuration(ms) {
  if (!ms) return '--';
  const secs = Math.floor(ms / 1000);
  if (secs < 60) return secs + 's';
  const mins = Math.floor(secs / 60);
  const remSecs = secs % 60;
  if (mins < 60) return mins + 'm ' + remSecs + 's';
  const hrs = Math.floor(mins / 60);
  const remMins = mins % 60;
  return hrs + 'h ' + remMins + 'm';
}

// Format bytes as B/KB/MB
export function formatBytes(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

// Format large numbers with k/M suffixes
export function formatTokens(n) {
  if (n < 1000) return String(n);
  if (n < 1000000) return (n / 1000).toFixed(1) + 'k';
  return (n / 1000000).toFixed(2) + 'M';
}

// Map tool name to CSS class
export function getToolPillClass(name) {
  const n = name.toLowerCase();
  if (n === 'bash') return 'bash';
  if (n === 'read') return 'read';
  if (n === 'write') return 'write';
  if (n === 'edit') return 'edit';
  if (n === 'glob') return 'glob';
  if (n === 'grep') return 'grep';
  if (n === 'webfetch') return 'webfetch';
  if (n === 'websearch') return 'websearch';
  if (n === 'skill') return 'skill';
  if (n === 'toolsearch') return 'toolsearch';
  if (n === 'notebookedit') return 'notebookedit';
  return 'default';
}

// Extract brief description from tool block metadata
export function getToolDescription(block) {
  const input = block.input || {};
  const name = (block.name || '').toLowerCase();

  if (name === 'bash') return input.description || input.command || '';
  if (name === 'read') return input.file_path || '';
  if (name === 'write') return input.file_path || '';
  if (name === 'edit') return input.file_path || '';
  if (name === 'glob') return input.pattern || '';
  if (name === 'grep') return input.pattern || '';
  if (name === 'webfetch') return input.url || '';
  if (name === 'websearch') return input.query || '';
  if (name === 'skill') return input.skill || '';
  if (name === 'toolsearch') return input.query || '';

  return '';
}

// Format tool input parameters into display string
export function getToolInput(block) {
  const input = block.input || {};
  const name = (block.name || '').toLowerCase();

  if (name === 'bash') {
    return input.command || '';
  }
  if (name === 'read') {
    let s = input.file_path || '';
    if (input.offset) s += ` (offset: ${input.offset})`;
    if (input.limit) s += ` (limit: ${input.limit})`;
    return s;
  }
  if (name === 'write') {
    const path = input.file_path || '';
    const content = input.content || '';
    const preview = content.length > 500 ? content.slice(0, 500) + '\n... (' + content.length + ' chars total)' : content;
    return path + '\n\n' + preview;
  }
  if (name === 'edit') {
    let s = input.file_path || '';
    if (input.old_string) s += '\n\n--- old ---\n' + input.old_string;
    if (input.new_string) s += '\n\n--- new ---\n' + input.new_string;
    return s;
  }
  if (name === 'grep') {
    let s = 'pattern: ' + (input.pattern || '');
    if (input.path) s += '\npath: ' + input.path;
    if (input.glob) s += '\nglob: ' + input.glob;
    if (input.type) s += '\ntype: ' + input.type;
    return s;
  }
  if (name === 'glob') {
    let s = 'pattern: ' + (input.pattern || '');
    if (input.path) s += '\npath: ' + input.path;
    return s;
  }

  const keys = Object.keys(input);
  if (keys.length === 0) return '';
  return JSON.stringify(input, null, 2);
}

// Extract summary from system event
export function summarizeSystemEvent(entry) {
  if (entry.message?.content) {
    const c = entry.message.content;
    if (typeof c === 'string') return c.slice(0, 120);
    if (Array.isArray(c)) return c.map(b => (b.text || b.type || '')).join(' ').slice(0, 120);
  }
  if (entry.data?.type) return entry.data.type;
  return 'system event';
}

// HTML entity encoding
export function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// Markdown to HTML (requires marked.parse available globally)
export function renderMarkdown(text) {
  try {
    if (typeof marked !== 'undefined' && marked.parse) {
      return marked.parse(text);
    }
    return escapeHtml(text);
  } catch (e) {
    return escapeHtml(text);
  }
}
