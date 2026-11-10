# React + TypeScript + Vite

This template provides a minimal setup to get React working in Vite with HMR and some ESLint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react/README.md) uses [Babel](https://babeljs.io/) for Fast Refresh
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react-swc) uses [SWC](https://swc.rs/) for Fast Refresh

## Expanding the ESLint configuration

If you are developing a production application, we recommend updating the configuration to enable type aware lint rules:

- Configure the top-level `parserOptions` property like this:

```js
   parserOptions: {
    ecmaVersion: 'latest',
    sourceType: 'module',
    project: ['./tsconfig.json', './tsconfig.node.json'],
    tsconfigRootDir: __dirname,
   },
```

- Replace `plugin:@typescript-eslint/recommended` to `plugin:@typescript-eslint/recommended-type-checked` or `plugin:@typescript-eslint/strict-type-checked`
- Optionally add `plugin:@typescript-eslint/stylistic-type-checked`
- Install [eslint-plugin-react](https://github.com/jsx-eslint/eslint-plugin-react) and add `plugin:react/recommended` & `plugin:react/jsx-runtime` to the `extends` list

## Where code and tests go

Code is grouped by the product area it belongs to, so the work for one screen or flow stays in one folder:

```
src/
  app shell   App.tsx, main.tsx, layouts/ (persistent shell), pages/ (PageX.tsx, what a route renders)
  features/   one folder per product area: chat, artifacts (with every viewer), workflows,
              approval-queue, agent-registry, data-management, project-management, auth, admin,
              dashboard, shell (header, sidebar, nav)
  components/ui/<Name>/   shared design-system components, one folder each
  lib/        code with no UI that several features use: api/, highlight/, mime, table/, useTheme
  test/       Vitest setup and the tests that check rules across the app
e2e/          Playwright end-to-end tests, by user flow
```

- **A feature folder holds everything for its area:** components, hooks, helpers and tests. Stores go in a `store/` subfolder, as in `features/chat/store/chat.ts`. A new screen gets a feature folder and a `pages/PageX.tsx` that renders it.
- **Other code imports a feature only through its `index.ts`.** Write `import { Chat } from "@/features/chat"`, not `@/features/chat/Chat`. The index names what the feature shares; everything else in the folder is internal to it, so it can change without touching other features. When another feature needs something new, export it from the index. Inside a feature, import its own files directly.
- **Import anything outside your own folder with `@/`**, never `../`, so a file can move without its imports breaking. Use `./` only within the same folder or below it.
- **A shared component gets its own folder** in `components/ui/`, holding the component, its helpers, its tests and an `index.ts` that re-exports it: `components/ui/Button/` has `Button.tsx`, `buttonStyle.ts`, `Button.test.ts`, `Button.dom.test.tsx` and `index.ts`. Import it as `@/components/ui/Button`.
- **Code moves to `lib/` or `components/ui/` once a second feature needs it**, not before.

`npm run lint` enforces the import rules: it fails a deep import into another feature and any `../` import.

## Testing

```bash
npm test             # run every test once (also: make test; make check runs lint + typecheck + test)
npm run test:watch   # rerun on save
```

Tests use [Vitest](https://vitest.dev) and sit next to the code they test, in the same folder:

- `*.test.ts` runs in Node, for logic: stores, parsers, formatters. `features/chat/store/chat.test.ts` sits beside `chat.ts`.
- `*.test.tsx` runs in jsdom with [React Testing Library](https://testing-library.com/docs/react-testing-library/intro/), for components. Name it `<Component>.dom.test.tsx`. Find elements by role and accessible name and act through `@testing-library/user-event`. `src/components/ui/FilterChips/FilterChips.dom.test.tsx` is the example.
- A test for a screen as a whole sits beside the screen's main component, such as `features/workflows/NodeInspector.dom.test.tsx` beside `NodeInspector.tsx`.
- A test that checks a rule across the app, rather than one file, goes in `src/test/`.

A test file named any other way never runs, so `src/test/testFiles.test.ts` fails if a file under `src/` imports Vitest or Testing Library without a `.test.ts` or `.test.tsx` name. CI runs every test in `src/` through `npm run test:coverage`, wherever it sits.

Not every change needs tests. Test shared components, non-trivial logic and flows that would hurt to break.

### End-to-end tests

```bash
npm run test:e2e      # build the app, serve it on port 5160 and run e2e/ in headless Chromium (also: make test-e2e)
npm run test:e2e:ui   # Playwright's UI mode, to step through a test and watch it run
```

The first run needs a browser: `npx playwright install chromium`.

End-to-end tests use [Playwright](https://playwright.dev) and live in `e2e/` as `*.spec.ts`, apart from the Vitest suite, so `npm test` stays fast and never runs them. They load the built app in a real browser. Nothing runs behind it, so each test answers the `/api` calls it needs with `page.route`. Find elements by role and accessible name, the same way the component tests do. `e2e/login.spec.ts` is the example. Import `test` and `expect` from `e2e/fixtures.ts`, not from `@playwright/test`: each test then starts as a signed-out visitor with the sign-in calls stubbed, and fails if the app makes an `/api` call that no stub answers.

Use only made-up credentials and data in these tests. CI uploads a failed test's screenshots and trace, including what the page showed and every request and response, and the repo is public, so anyone signed in to GitHub can download them.

Playwright builds and starts the app itself on every run, so the tests always check your current code. If something is already using port 5160, the run fails instead of testing it; stop that server first. When a test fails it keeps a trace and a screenshot in `test-results/`; open a trace with `npx playwright show-trace <path>/trace.zip`. In CI, the `platform: frontend e2e` job uploads them with the HTML report as the `frontend-e2e-report` artifact.

#### Against the full platform

The tests in `e2e/full/` run against the e2e stack: the whole platform, served by nginx, with nothing faked. They check what the faked tests can't: nginx's `/api` proxy, the real backend and its database.

```bash
make up-e2e              # in platform/: start the e2e stack, nginx on http://localhost:8090
npm run test:e2e:full    # in frontend/: run e2e/full/ against it (also: make test-e2e-full)
make down-e2e            # in platform/: stop it and delete its data
```

The e2e stack is its own compose project on its own ports, so it runs beside a dev stack without touching it. Rebuild it with `make up-e2e` after changing the frontend, since it serves the production build. The first run creates a test admin, `e2e-admin`, which only exists in the e2e stack. Each test starts signed in as it; a test that signs in itself starts from an empty `storageState`, as `e2e/full/sign-in.spec.ts` does.

Import `test` and `expect` from `e2e/full/fixtures.ts`. Nothing is faked there, but a test fails if the page throws or an `/api` call fails or returns a server error. Failed tests keep their trace in `test-results-full/`, and CI's `platform: frontend e2e full` job uploads them as `frontend-e2e-full-report`. That job reports on every pull request but isn't a required check yet.
