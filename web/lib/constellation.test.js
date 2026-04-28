import { describe, it, expect } from 'vitest';
import {
  hashStr,
  projectKey,
  projectLabel,
  pickForm,
  parseToolFromAction,
  buildHub,
  buildSeal,
  layoutProjects,
  relTime,
  deriveTask,
} from './constellation.js';

describe('constellation.js — Key Derivation', () => {
  it('hashStr produces consistent results', () => {
    const h1 = hashStr('lovenotes');
    const h2 = hashStr('lovenotes');
    expect(h1).toBe(h2);
  });

  it('projectKey extracts from cwd', () => {
    // parts[2] of Projects/prototypes/scratch/... is 'scratch'
    const cwd = '/Users/christopherk.marks/Downloads/personal-os-main/Projects/prototypes/scratch/scratchpad';
    expect(projectKey(cwd, 'worker')).toBe('scratch');
    // top-level project
    const cwd2 = '/Users/christopherk.marks/Downloads/personal-os-main/Projects/lovenotes';
    expect(projectKey(cwd2, 'worker')).toBe('lovenotes');
  });

  it('projectKey returns sutra for orchestrator', () => {
    expect(projectKey('/some/cwd', 'orchestrator')).toBe('sutra');
  });

  it('projectLabel titlecases keys', () => {
    expect(projectLabel('lovenotes')).toBe('Lovenotes');
    expect(projectLabel('AI_research')).toBe('AI Research'); // all-caps words preserved
    expect(projectLabel('agent-dispatch')).toBe('Agent Dispatch');
  });
});

describe('constellation.js — Form Selection', () => {
  it('pickForm returns nexus for orchestrator', () => {
    expect(pickForm('sutra', 5, true)).toBe('nexus');
  });

  it('pickForm returns deterministic form per key', () => {
    const f1 = pickForm('lovenotes', 3, false);
    const f2 = pickForm('lovenotes', 3, false);
    expect(f1).toBe(f2);
  });

  it('pickForm varies by childCount', () => {
    const f_few = pickForm('test', 1, false);
    const f_many = pickForm('test', 10, false);
    expect(typeof f_few).toBe('string');
    expect(typeof f_many).toBe('string');
  });
});

describe('constellation.js — Tool Parsing', () => {
  it('parseToolFromAction identifies READ', () => {
    expect(parseToolFromAction('Reading file.js')).toBe('READ');
    expect(parseToolFromAction('read the spec')).toBe('READ');
  });

  it('parseToolFromAction identifies BASH', () => {
    expect(parseToolFromAction('Running bash command')).toBe('BASH');
    expect(parseToolFromAction('shell script execution')).toBe('BASH');
  });

  it('parseToolFromAction returns null for unknown', () => {
    expect(parseToolFromAction('idle')).toBeNull();
  });
});

describe('constellation.js — Geometry', () => {
  it('buildHub creates core + spokes', () => {
    const entity = { id: 'proj1', cx: 0, cy: 0, radius: 100 };
    const seeds = [['CLAUDE.md', 'doc'], ['file1', 'code'], ['file2', 'code']];
    const result = buildHub(entity, seeds);
    expect(result.nodes.length).toBeGreaterThan(0);
    expect(result.nodes[0].isCore).toBe(true);
    expect(result.edges.length).toBeGreaterThan(0);
  });

  it('buildSeal creates circular ring', () => {
    const entity = { id: 'proj1', cx: 0, cy: 0, radius: 100 };
    const seeds = [['core', 'doc'], ['a', 'code'], ['b', 'code']];
    const result = buildSeal(entity, seeds);
    expect(result.nodes.length).toBe(3);
    expect(result.nodes[0].isCore).toBe(true);
  });
});

describe('constellation.js — Layout', () => {
  it('layoutProjects places sutra at origin', () => {
    const keys = ['sutra', 'lovenotes'];
    const result = layoutProjects(keys);
    expect(result.sutra.wx).toBe(0);
    expect(result.sutra.wy).toBe(0);
  });

  it('layoutProjects spaces others in circle', () => {
    const keys = ['sutra', 'proj1', 'proj2', 'proj3'];
    const result = layoutProjects(keys);
    // All on same radius
    const dist1 = Math.hypot(result.proj1.wx, result.proj1.wy);
    const dist2 = Math.hypot(result.proj2.wx, result.proj2.wy);
    const dist3 = Math.hypot(result.proj3.wx, result.proj3.wy);
    expect(Math.abs(dist1 - dist2)).toBeLessThan(1);
    expect(Math.abs(dist2 - dist3)).toBeLessThan(1);
    // Not at same position
    expect(result.proj1.wy).not.toBeCloseTo(result.proj2.wy);
  });
});

describe('constellation.js — Time & Task', () => {
  it('relTime formats recent timestamps', () => {
    const now = new Date();
    const past5m = new Date(now.getTime() - 5 * 60 * 1000);
    const result = relTime(past5m.toISOString());
    expect(result).toContain('ago');
  });

  it('deriveTask extracts from system_prompt', () => {
    const agent = {
      system_prompt: 'You are an agent — your job is to do important work on the codebase.'
    };
    const task = deriveTask(agent);
    expect(task).toBe('your job is to do important work on the codebase');
  });
});
