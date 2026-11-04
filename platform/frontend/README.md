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

## Testing

```bash
npm test             # run every test once (also: make test; make check runs lint + typecheck + test)
npm run test:watch   # rerun on save
```

Tests use [Vitest](https://vitest.dev) and sit next to the code they test:

- `*.test.ts` runs in Node, for logic: stores, parsers, formatters.
- `*.test.tsx` runs in jsdom with [React Testing Library](https://testing-library.com/docs/react-testing-library/intro/), for components. Find elements by role and accessible name and act through `@testing-library/user-event`. `src/components/ui/FilterChips.dom.test.tsx` is the example.

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
