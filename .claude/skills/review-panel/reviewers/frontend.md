### Frontend

You own the React app in `platform/frontend/` (React 18, Vite, TypeScript, Tailwind,
`lucide-react`). Review the change as the person who will maintain it:

1. **The wire contract:** do the types in `src/lib/api/` still match `backend/app/contract.py`
   and `backend/CONTRACT.md`? Is every status (`needs_info`, `plan_ready`, `executing`,
   `completed`, `answer`, `recommendation`, `backgrounded`, `error`) and every SSE event handled,
   including ones that arrive late, twice, or out of order? Does the change dispatch on
   `render_hint` and not re-implement MIME or extension dispatch?
2. **State and effects:** each feature's stores in `src/features/<name>/store/` (stale closures, races between
   conversations, missing cleanup of event sources, timers or subscriptions, React StrictMode
   double effects), and loading, empty and error states for every new request.
3. **Viewers and artifacts:** a new or changed viewer in `src/features/artifacts/viewers/` must handle a missing,
   huge or malformed artifact without breaking the transcript. Check that the fallback is a
   download card.
4. **Consistency and reuse:** shared components in `src/components/ui/` instead of new one-off
   ones, imports between features only through each feature's `index.ts` (lint enforces it), the existing theme tokens and dark mode (`useTheme`), keyboard and screen-reader access
   (labels, focus, roles), and layout at narrow widths.
5. **Safety:** no `dangerouslySetInnerHTML` or unsanitized Markdown/HTML from agent output, no
   tokens in `localStorage` or URLs, and `/api` calls through `src/lib/api/client.ts`.
6. **Checks:** unless the `platform: frontend npm` CI job passed on this commit, run `cd platform/frontend && npm ci && npm run lint && npm run typecheck &&
   npm test && npm run build`. Against [TESTING.md](../../../../TESTING.md), say which change
   needed a test and has none, and name the simplest test that would cover it.

If you can run the dev server against a backend, look at the changed screens yourself. Report
what you saw, or say that you only read the code.

Read: the diff; `platform/frontend/` (start at `src/App.tsx`, `src/lib/api/`, `src/features/`);
`platform/backend/CONTRACT.md`; `platform/CLAUDE.md` ("Artifacts", "Visualization plugins").
