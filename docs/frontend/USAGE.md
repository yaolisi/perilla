# Frontend Developer Onboarding

## 1. Install dependencies

```bash
cd frontend
npm install
```

## 2. Start development server

```bash
npm run dev
```

- uses `vite.config.dev.ts`
- sourcemap enabled for easier debugging

## 3. Build production bundle

```bash
npm run build
```

- uses `vite.config.prod.ts`
- minification enabled with production-oriented defaults

## 4. Unit tests (Vitest)

```bash
npm run test:unit
```

Watch mode:

```bash
npm run test:unit:watch
```

## 5. End-to-end tests (Cypress)

```bash
npm run test:e2e
```

Open Cypress UI:

```bash
npm run test:e2e:open
```

CI helper (start dev server then run e2e):

```bash
npm run test:e2e:ci
```

## 6. Recommended workflow

1. implement feature
2. run `npm run test:unit`
3. run targeted e2e flow (`npm run test:e2e`)
4. run `npm run build` before merge
