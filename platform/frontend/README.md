# Prometheus frontend

The React app for the Prometheus platform: chat with the agents, view the
artifacts they produce, and manage workflows, agents, data and projects. It's
built with React, TypeScript, Vite, Tailwind and DaisyUI, and talks to the
FastAPI backend over its JSON/SSE contract
([`../backend/CONTRACT.md`](../backend/CONTRACT.md); the TypeScript side is
described in [`AGENT-CONTRACT.md`](AGENT-CONTRACT.md)).

## Running it

The dev server proxies `/api` to the backend at `VITE_BACKEND_URL`
(default `http://localhost:8600`), so start the backend first, for example
with `make up` in `platform/`.

```bash
make install     # npm install
make dev         # Vite dev server with hot reload, on port 5150
make build       # production bundle in dist/
make check       # lint, type-check and the Vitest tests
make test-e2e    # the Playwright end-to-end tests
```

In Docker, the `frontend-dev` service (compose profile `dev`) runs the dev
server with this folder mounted, and `frontend-prod` serves the production
build with nginx.

## Formatting

Code is formatted with [Prettier](https://prettier.io) (settings in `.prettierrc.json`, skipped files in `.prettierignore`). It installs with the other dev dependencies, so there's nothing extra to set up.

```bash
npm run format        # format everything (also: make format)
npm run format:check  # fail if anything isn't formatted (also: make format-check)
```

CI runs `make format-check` in the `platform: frontend npm` job (that job calls the Makefile for each check, so the targets stay working), so an unformatted file fails the PR; `npm run format` fixes it. `make check` runs it too. To format on save, install the Prettier extension for your editor (VS Code: `esbenp.prettier-vscode` with "Format On Save"; JetBrains: Settings, Prettier, "On save"). It picks up the project settings and version.

Markdown is not formatted, so docs keep their hand-written line breaks and tables. ESLint's style rules that would conflict are turned off (`eslint-config-prettier`), so ESLint checks code and Prettier checks layout.

## Where code and tests go

Code is grouped by the product area it belongs to, so the work for one screen or flow stays in one folder:

```
src/
  app/        the router: paths.ts (every URL), guards.ts (who may open a route), router.tsx (the route table)
  layouts/    the app shell: LayoutApp (sidebar, header) and LayoutAuth (sign-in screens)
  pages/      PageX.tsx, what a route renders: one per screen
  features/   one folder per product area (a domain, not a page): chat, artifacts (with every viewer), workflows,
              approval-queue, agent-registry, data-management, project-management, auth, admin,
              dashboard, shell (header, sidebar, nav)
  components/ui/<Name>/   shared design-system components, one folder each
  lib/        code with no UI that several features use: api/, highlight/, mime, table/, useTheme
  test/       Vitest setup and the tests that check rules across the app
  dev/        dev-only pages, not in the app build: the viewer playground (see dev/viewer-playground/README.md)
e2e/          Playwright end-to-end tests, by user flow
```

- **A feature folder holds everything for its area:** components, hooks, helpers and tests. Stores go in a `store/` subfolder, as in `features/chat/store/chat.ts`.
- **Every screen has a page and a layout.** `pages/PageX.tsx` owns the logic: data, state, the header (`usePageHeader`), and route params and filters. It has very little markup. `features/<area>/LayoutX.tsx` owns the arrangement: it takes props and renders the feature's pieces, with no data loading or route logic. `PageAgentRegistry` and `LayoutAgentRegistry` are the example.
- **A feature is a domain, not a page.** A piece lives in the feature its data belongs to, even when another page shows it. A screen's layout lives in the feature that owns the screen. When the Jobs Console lands, for example, `features/jobs` would hold the console's layout and also a summary that the Home layout imports from `@/features/jobs`.
- **Other code imports a feature only through its `index.ts`.** Write `import { Chat } from "@/features/chat"`, not `@/features/chat/Chat`. The index names what the feature shares; everything else in the folder is internal to it, so it can change without touching other features. When another feature needs something new, export it from the index. Inside a feature, import its own files directly.
- **Import anything outside your own folder with `@/`**, never `../`, so a file can move without its imports breaking. Use `./` only within the same folder or below it.
- **A shared component gets its own folder** in `components/ui/`, holding the component, its helpers, its tests and an `index.ts` that re-exports it: `components/ui/Button/` has `Button.tsx`, `buttonStyle.ts`, `Button.test.ts`, `Button.dom.test.tsx` and `index.ts`. Import it as `@/components/ui/Button`.
- **Code moves to `lib/` or `components/ui/` once a second feature needs it**, not before.

`npm run lint` enforces the import rules: it fails a deep import into another feature and any `../` import.

## Routes

The app uses [React Router](https://reactrouter.com) 7 in data mode (`createBrowserRouter`), as a client-only single-page app. Every URL is in `src/app/paths.ts`, so links never spell out a path and a prefix such as a workspace can be added in one place.

To add a screen:

1. Add its path to `PATHS` in `src/app/paths.ts`. If it's in the sidebar, also add it to `NAV_PATHS` and `features/shell/nav.tsx`.
2. Add `pages/PageX.tsx` and the layout it renders (see "Every screen has a page and a layout" above).
3. Add a route in `src/app/router.tsx`. Signed-in screens go under the `LayoutApp` route, which already requires sign-in. For extra access rules, give the route a `loader` from `src/app/guards.ts`, as Admin uses `requireAdmin`.

Notes:

- **Loaders gate access.** A guard either returns or throws a `redirect`. Pages load their own data through RTK Query hooks; a loader may *start* a page's query early (see "Server data"), but never waits for it or returns data.
- **Link with `<Link>`, `<NavLink>` or `<Button navTo>`,** not `window.location`, so navigation stays in the app.
- **Params** (`/jobs-console/:jobId`) go in the route's `path`. Pages read them with `useParams()`. Add a helper next to `PATHS` that builds the URL, such as `jobPath(id)`.
- **Unknown URLs** show `PageNotFound` inside the shell, and a route that throws shows `PageError`.
- **Production:** nginx serves `index.html` for any path that isn't a file (`nginx/default.conf.template`), so a reload or deep link reaches the router.


## Server data

Data from the backend goes through [RTK Query](https://redux-toolkit.js.org/rtk-query/overview), which fetches, caches and refetches it. Screens use its hooks and don't call `lib/api/client.ts` themselves. Admin is the first user; other screens move when their real API lands. Chat and its event stream, the signed-in session and the page header keep their own stores.

- **One API, in `src/lib/api/baseApi.ts`.** It uses the same `/api` base and session cookie as `client.ts`. Errors reach screens as `{ status, message }`, where `message` is the backend's `detail`, or a generic message when the body isn't JSON (a proxy's error page). A 401 from any request sends the user to Login and back to the page afterward (wired in `App.tsx`).
- **Endpoints live in their feature.** A feature adds its endpoints with `baseApi.injectEndpoints` in its own file, as `features/admin/adminApi.ts` does, and exports the hooks it generates.
- **The store is in `src/lib/api/store.ts`.** It holds only RTK Query's cache. Tests call `createAppStore()` for a fresh cache each.
- **A session ends in one place, `src/app/endSession.ts`.** Logging out, a lost event stream and a 401 all go through it: it stops chat, forgets the user, goes to Login, and then empties the cache, so the next user in the tab never sees the previous one's data.

To add an endpoint:

1. In the feature's API file, add a `build.query` (to read) or `build.mutation` (to change), with the path and method from the backend router.
2. Give each list a tag (`providesTags`) and have each change invalidate it (`invalidatesTags`), so the list refetches after a create, edit or delete. Add a new tag name to `tagTypes` in `baseApi.ts`.
3. Export the hook (`useListThingsQuery`, `useCreateThingMutation`) and use it in the screen. For a mutation, `await createThing(input).unwrap()` throws on failure, with the error's `message` to show.

In a screen:

```tsx
const list = useListAdminUsersQuery(undefined, { refetchOnMountOrArgChange: LIST_MAX_AGE_SECONDS });
const users = list.data ?? null;   // null until the first load: show the loading state
const [createUser] = useCreateAdminUserMutation();
```

`refetchOnMountOrArgChange` with a number of seconds shows the cached list at once when the user comes back to the screen, and fetches it again only when it's older than that, so a list a loader has just fetched isn't fetched twice. A change refetches its list straight away through its tag, whatever its age.

**Starting a query before the page renders:** a route `loader` can call a feature's helper that dispatches the query's `initiate()` without awaiting it, as the `/admin` route does with `prefetchAdminUsers()`. The page's own hook then picks up the request already in flight.

## Testing

[TESTING.md](../../TESTING.md) says which kind of test a change needs, when it needs none, and how much coverage is enough. This section covers how to write and run the frontend's tests.

```bash
npm test             # run every test once (also: make test; make check runs format-check + lint + typecheck + test)
npm run test:watch   # rerun on save
```

Tests use [Vitest](https://vitest.dev) and sit next to the code they test, in the same folder:

- `*.test.ts` runs in Node, for logic: stores, parsers, formatters. `features/chat/store/chat.test.ts` sits beside `chat.ts`.
- `*.test.tsx` runs in jsdom with [React Testing Library](https://testing-library.com/docs/react-testing-library/intro/), for components. Name it `<Component>.dom.test.tsx`. Find elements by role and accessible name and act through `@testing-library/user-event`. `src/components/ui/FilterChips/FilterChips.dom.test.tsx` is the example.
- A test for a screen as a whole sits beside the screen's main component, such as `features/approval-queue/ApprovalQueue.dom.test.tsx` beside `ApprovalQueue.tsx`.
- A test that checks a rule across the app, rather than one file, goes in `src/test/`.

A test file named any other way never runs, so `src/test/testFiles.test.ts` fails if a file under `src/` imports Vitest or Testing Library without a `.test.ts` or `.test.tsx` name. CI runs every test in `src/` through `npm run test:coverage`, wherever it sits.

### End-to-end tests

```bash
npm run test:e2e      # build the app, serve it on port 5160 and run e2e/ in headless Chromium (also: make test-e2e)
npm run test:e2e:ui   # Playwright's UI mode, to step through a test and watch it run
```

`make test-e2e` and `make test-e2e-full` install the browser the tests need first, so a Playwright update can't leave them without one. The `npm run` commands don't; after a Playwright update, run `make e2e-browsers` once before using them.

Write an end-to-end test only for a flow that crosses the frontend and backend; [TESTING.md](../../TESTING.md#which-test-a-change-needs) says when. End-to-end tests use [Playwright](https://playwright.dev) and live in `e2e/` as `*.spec.ts`, apart from the Vitest suite, so `npm test` stays fast and never runs them. They load the built app in a real browser. Nothing runs behind it, so each test answers the `/api` calls it needs with `page.route`. Find elements by role and accessible name, the same way the component tests do. `e2e/login.spec.ts` is the example. Import `test` and `expect` from `e2e/fixtures.ts`, not from `@playwright/test`: each test then starts as a signed-out visitor with the sign-in calls stubbed, and fails if the app makes an `/api` call that no stub answers.

Use only made-up credentials and data in these tests. CI uploads a failed test's screenshots and trace, including what the page showed and every request and response, and the repo is public, so anyone signed in to GitHub can download them.

Playwright builds and starts the app itself on every run, so the tests always check your current code. If something is already using port 5160, the run fails instead of testing it; stop that server first. When a test fails it keeps a trace and a screenshot in `test-results/`; open a trace with `npx playwright show-trace <path>/trace.zip`. In CI, the `platform: frontend e2e` job uploads them with the HTML report as the `frontend-e2e-report` artifact.

#### Against the full platform

The tests in `e2e/full/` run against the e2e stack: the whole platform, served by nginx, with nothing faked. They check what the faked tests can't: nginx's `/api` proxy, the real backend and its database.

```bash
make up-e2e              # in platform/: start the e2e stack, nginx on http://localhost:8090
npm run test:e2e:full    # in frontend/: run e2e/full/ against it (also: make test-e2e-full)
make down-e2e            # in platform/: stop it and delete its data
```

`make up-e2e` needs no LLM key and nothing for DeepLynx. The backend sends chat turns to a stub agent, `platform/e2e/stub-client-agent`, instead of the client agent: it gives the same answer to every message (its `TEXT_ANSWER`) and never calls an LLM, so `e2e/full/chat.spec.ts` knows the reply in advance. The stub doesn't save chats, so Chat History stays empty in this stack. When a prompt names a mesh, an IFC model, a diagram or JSON, the stub's reply carries that sample from `e2e/samples/` as an artifact, which `e2e/full/viewers.spec.ts` opens in each viewer. The IFC viewer loads web-ifc from unpkg, so that test needs network access. The stack still sets a made-up LLM profile and key and made-up DeepLynx credentials of its own, because the stack won't start without a profile and every agent refuses to start without DeepLynx credentials, and nothing in it calls a model or reaches DeepLynx. Your real `LLM_*`, `EMBEDDING_API_KEY` and `DEEPLYNX_*` values in `platform/.env` don't reach this stack. On a fresh clone it creates `.env` with its secrets and asks only whether to build the SDK image locally. It saves no LLM profile and no DeepLynx answer, so your first `make up` still asks for those.

The e2e stack is its own compose project on its own ports, so it runs beside a dev stack without touching it. Its ports are on `127.0.0.1` only, so other machines can't reach it, because its test admin's password is in the repo. To do the same for your dev stack, set `PUBLISH_ADDR=127.0.0.1` in `platform/.env`. Rebuild it with `make up-e2e` after changing the frontend, since it serves the production build. The first run creates a test admin, `e2e-admin`, which only exists in the e2e stack. Each test starts signed in as it; a test that signs in itself starts from an empty `storageState`, as `e2e/full/sign-in.spec.ts` does (through the form) and `e2e/full/sign-in-api.spec.ts` does (through the API, including a wrong password and a stack that already has its admin).

Import `test` and `expect` from `e2e/full/fixtures.ts`. Nothing is faked there, but a test fails if the page throws or an `/api` call fails or is refused (any status of 400 or more, except the answers the fixture expects). Each run writes to its own folder under `test-results-full/` (set `E2E_RUN_ID` to name it), so two runs at once don't delete each other's files; a failed test keeps its trace in that folder, and `rm -rf test-results-full` clears the old ones. CI's `platform: frontend e2e full` job uploads them as `frontend-e2e-full-report`. That job reports on every pull request but isn't a required check yet.

The platform has no behavior specs yet, so these tests stand in for them. Keep one feature per spec file, say what the feature is in a comment at the top of the file, and give each test a `Behavior:` comment that a reader can follow without the code: who does what, and what they should then see (given, when, then). Say why a test needs the whole stack when a faked test might seem enough. Where a Confluence spec has a requirement ID for the behavior, start the test's name with it, as in `"ROUTE-1: ..."`. `e2e/full/screens.spec.ts` is the example: it opens every main screen from the sidebar and from its own address.
