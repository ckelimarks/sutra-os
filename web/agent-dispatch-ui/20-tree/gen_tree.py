#!/usr/bin/env python3
"""
Generates tree.js from the real Projects/ folder.
Filters noise, caps depth, keeps meaningful organizational structure.

Run: python gen_tree.py
"""
import os
import json

PROJECTS_ROOT = '/Users/christopherk.marks/Downloads/personal-os-main/Projects'
OUTPUT = os.path.join(os.path.dirname(__file__), 'tree.js')
OUTPUT_21 = os.path.join(os.path.dirname(__file__), '..', '21-sutra-map', 'tree.js')

EXCLUDE_DIRS = {
    'node_modules', '.git', '.next', '.vercel', '.turbo', 'dist', 'build',
    'target', '__pycache__', '.pytest_cache', '.venv', 'venv', 'env',
    '.DS_Store', '.idea', '.vscode', 'coverage', '.cache', '.parcel-cache',
    'out', '.svelte-kit', '.nuxt', 'public', 'assets', 'static',
}

EXCLUDE_FILES = {
    '.DS_Store', 'package-lock.json', 'yarn.lock', 'poetry.lock',
    'Pipfile.lock', '.env', '.env.local', '.gitignore',
}

# Files worth showing at depth 1 (signal files)
KEEP_FILES_DEPTH_1 = {
    'CLAUDE.md', 'INFRA.md', 'README.md', 'TASKS.md', 'TODO.md',
    'package.json', 'pyproject.toml', 'Cargo.toml',
}

MAX_DEPTH = 2  # depth 0 = entity, depth 1-2 = sub-structure

KIND_BY_EXT = {
    '.md': 'doc',
    '.ts': 'code', '.tsx': 'code', '.js': 'code', '.jsx': 'code',
    '.py': 'code', '.go': 'code', '.rs': 'code', '.html': 'code',
    '.css': 'code', '.json': 'note', '.yaml': 'note', '.yml': 'note',
    '.txt': 'note',
}

def kind_for(name, is_dir):
    if is_dir:
        return 'folder'
    ext = os.path.splitext(name)[1].lower()
    return KIND_BY_EXT.get(ext, 'note')

def build_tree(path, depth=0):
    """Walk directory, return dict of {name: {kind, depth, children?}}"""
    if depth > MAX_DEPTH:
        return None
    try:
        entries = sorted(os.listdir(path))
    except (PermissionError, FileNotFoundError):
        return {}

    result = {}
    for name in entries:
        if name.startswith('.'):
            continue
        if name in EXCLUDE_DIRS or name in EXCLUDE_FILES:
            continue
        full = os.path.join(path, name)
        is_dir = os.path.isdir(full)

        # Files: only keep at depth 1, and only if they're signal files
        if not is_dir:
            if depth == 1 and name in KEEP_FILES_DEPTH_1:
                result[name] = {'kind': kind_for(name, False), 'depth': depth}
            elif depth == 0:
                # skip top-level loose files
                continue
            continue

        # Directories: recurse
        children = build_tree(full, depth + 1) if depth < MAX_DEPTH else None
        node = {'kind': 'folder', 'depth': depth}
        if children:
            node['children'] = children
        result[name] = node

    return result

def main():
    print(f'Walking {PROJECTS_ROOT}...')
    if not os.path.isdir(PROJECTS_ROOT):
        print(f'ERROR: {PROJECTS_ROOT} not found')
        return

    tree = {}
    for entry in sorted(os.listdir(PROJECTS_ROOT)):
        full = os.path.join(PROJECTS_ROOT, entry)
        if not os.path.isdir(full):
            continue
        if entry.startswith('.') or entry in EXCLUDE_DIRS:
            continue
        children = build_tree(full, depth=1)
        tree[entry] = {'kind': 'folder', 'depth': 0, 'path': full, 'children': children or {}}

    js = 'const REAL_TREE = ' + json.dumps(tree, indent=2) + ';\n'
    for out in [OUTPUT, OUTPUT_21]:
        with open(out, 'w') as f:
            f.write(js)
        print(f'Wrote {out}')
    print(f'Top-level entities: {len(tree)}')
    for name, node in tree.items():
        n_children = len(node.get('children', {}))
        print(f'  {name}: {n_children} sub-items')

if __name__ == '__main__':
    main()
