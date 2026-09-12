# kirmya_project

A modern TypeScript & React web application designed for task management and serving as the target repository for the offline coding agent.

---

## Overview

**`kirmya_project`** is a lightweight frontend application demonstrating strict TypeScript typing, reactive state management with React hooks, and unit testing with Vitest.

### Key Features
- **Task Dashboard**: Interactive task management interface with completion toggling and state tracking.
- **Strict TypeScript**: Configured with strict compiler flags (`noEmit`, `strict: true`, `noUnusedLocals`).
- **Unit Testing**: Pre-configured test suite powered by [Vitest](https://vitest.dev/).
- **Vite Build System**: Ultra-fast development server and optimized production bundling.

---

## Tech Stack

| Technology | Purpose |
|------------|---------|
| **React 18** | UI Component Architecture |
| **TypeScript 5** | Static Type Safety |
| **Vite 5** | Bundler & Dev Server |
| **Vitest 1** | Unit & Component Testing |
| **ESLint 8** | Code Formatting & Linting |

---

## Repository Structure

```
kirmya_project/
├── src/
│   ├── App.tsx             # Main React application & task dashboard component
│   └── __tests__/
│       └── App.test.tsx    # Vitest unit test suite
├── package.json            # Dependencies and npm scripts
├── tsconfig.json           # Strict TypeScript compiler options
├── .gitignore              # Git ignore rules for node_modules and builds
└── README.md               # Project documentation
```

---

## Available Scripts

In the project root, you can run:

### `npm run typecheck` (or `yarn run typecheck`)
Runs the TypeScript compiler in verification mode without emitting files:
```bash
npm run typecheck
```

### `npm test` (or `yarn test`)
Runs all unit test suites using Vitest:
```bash
npm test
```

### `npm run lint` (or `yarn run lint`)
Lints the TypeScript source files with ESLint:
```bash
npm run lint
```

### `npm run build` (or `yarn run build`)
Compiles the React application into static production assets in `/dist`.

---

## Verification & Edit Protocol

When working on this repository, always adhere to the repository verification workflow:
1. Make targeted component or utility edits.
2. Run `npm run typecheck` and resolve any type mismatches.
3. Run `npm test` on affected test suites.
4. Run `npm run lint` to confirm formatting conventions.
