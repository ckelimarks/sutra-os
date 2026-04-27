import { describe, it, expect } from 'vitest';
import {
  computeStats,
  formatDuration,
  formatBytes,
  formatTokens,
  getToolPillClass,
  getToolDescription,
  getToolInput,
  summarizeSystemEvent,
  escapeHtml,
} from './session.js';

describe('session.js — Stats Computation', () => {
  it('computeStats aggregates turns', () => {
    const entries = [
      { type: 'user', message: { content: 'hello' }, timestamp: new Date().toISOString() },
      { type: 'assistant', message: { content: 'hi', model: 'claude-4.6' }, timestamp: new Date().toISOString() },
    ];
    const stats = computeStats(entries);
    expect(stats.userTurns).toBe(1);
    expect(stats.assistantTurns).toBe(1);
    expect(stats.totalTurns).toBe(2);
  });

  it('computeStats tracks tokens', () => {
    const entries = [
      {
        type: 'assistant',
        message: {
          usage: { input_tokens: 100, output_tokens: 50 }
        },
        timestamp: new Date().toISOString()
      },
    ];
    const stats = computeStats(entries);
    expect(stats.inputTokens).toBe(100);
    expect(stats.outputTokens).toBe(50);
  });

  it('computeStats calculates duration', () => {
    const now = new Date();
    const past = new Date(now.getTime() - 5000);
    const entries = [
      { type: 'user', timestamp: past.toISOString() },
      { type: 'assistant', timestamp: now.toISOString() },
    ];
    const stats = computeStats(entries);
    expect(stats.durationMs).toBeGreaterThan(4900);
    expect(stats.durationMs).toBeLessThan(5100);
  });
});

describe('session.js — Formatting', () => {
  it('formatDuration converts ms', () => {
    expect(formatDuration(30000)).toBe('30s');
    expect(formatDuration(90000)).toBe('1m 30s');
    expect(formatDuration(3600000)).toBe('1h 0m');
  });

  it('formatBytes scales correctly', () => {
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(1024)).toBe('1.0 KB');
    expect(formatBytes(1024 * 1024)).toBe('1.0 MB');
  });

  it('formatTokens uses k/M notation', () => {
    expect(formatTokens(500)).toBe('500');
    expect(formatTokens(5000)).toBe('5.0k');
    expect(formatTokens(5000000)).toBe('5.00M');
  });
});

describe('session.js — Tool Classification', () => {
  it('getToolPillClass maps tool names', () => {
    expect(getToolPillClass('bash')).toBe('bash');
    expect(getToolPillClass('read')).toBe('read');
    expect(getToolPillClass('Write')).toBe('write');
    expect(getToolPillClass('unknown')).toBe('default');
  });

  it('getToolDescription extracts from input', () => {
    const block = { name: 'read', input: { file_path: '/test.js' } };
    expect(getToolDescription(block)).toBe('/test.js');
  });

  it('getToolInput formats parameters', () => {
    const block = { name: 'bash', input: { command: 'ls -la' } };
    expect(getToolInput(block)).toBe('ls -la');

    const block2 = { name: 'read', input: { file_path: '/test.js', offset: 10, limit: 50 } };
    const result = getToolInput(block2);
    expect(result).toContain('/test.js');
    expect(result).toContain('offset: 10');
  });
});

describe('session.js — System Events', () => {
  it('summarizeSystemEvent extracts text', () => {
    const entry = { message: { content: 'This is a long system event message that should be truncated' } };
    const summary = summarizeSystemEvent(entry);
    expect(summary.length).toBeLessThanOrEqual(120);
  });

  it('summarizeSystemEvent handles arrays', () => {
    const entry = { message: { content: [{ text: 'hello' }, { text: 'world' }] } };
    const summary = summarizeSystemEvent(entry);
    expect(summary).toContain('hello');
  });
});

describe('session.js — HTML Escape', () => {
  it('escapeHtml encodes entities', () => {
    expect(escapeHtml('<div>test</div>')).toBe('&lt;div&gt;test&lt;/div&gt;');
    expect(escapeHtml('a & b')).toBe('a &amp; b');
    expect(escapeHtml('hello "world"')).toBe('hello &quot;world&quot;');
  });

  it('escapeHtml handles null/empty', () => {
    expect(escapeHtml(null)).toBe('');
    expect(escapeHtml('')).toBe('');
  });
});
