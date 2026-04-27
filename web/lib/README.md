# Pure Functions Library

Extracted pure functions from `session-viewer.html` and `21-sutra-map/index.html` for TDD.

## Modules

- **constellation.js** — Geometry builders, layout, key derivation, tool parsing, camera transforms
  - No side effects, no DOM, no canvas
  - Test: `constellation.test.js`

- **session.js** — Stats, formatting, tool classification, HTML escape
  - No side effects, no DOM
  - Test: `session.test.js`

## Running Tests

```bash
npm install  # if not done: adds vitest
npm run test  # runs all .test.js files
npm run test:watch  # watch mode
npm run test:coverage  # coverage report
```

Add to `package.json`:
```json
{
  "devDependencies": {
    "vitest": "^2.x",
    "jsdom": "^24.x"
  },
  "scripts": {
    "test": "vitest run",
    "test:watch": "vitest",
    "test:coverage": "vitest run --coverage"
  }
}
```

## Integration

These modules are **not yet wired into the HTML views** — they live as standalone, testable code.

To integrate:
1. Convert `session-viewer.html` and `21-sutra-map/index.html` to ES6 modules
2. Import functions from `lib/`
3. Remove inline function definitions

Or import only what you need for new features (e.g., chat view can import `constellation.js` and `session.js` directly).
