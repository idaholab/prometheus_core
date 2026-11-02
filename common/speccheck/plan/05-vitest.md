# 5: vitest (future)

> **Status: Not started.** Not scheduled. Starts when a frontend spec folder exists or is
> agreed.

## Goal

Let vitest tests claim requirements and prove them, with no change to the checker: a vitest
reporter writes the same `speccheck-results/1` files (`design.md`, "Vitest").

## Work

- **Spike first:** against the vitest version the frontend uses then, confirm (a) a custom
  reporter sees every test case, including skipped and filtered ones, with its state, file and
  line; (b) per-test metadata set inside a test reaches the reporter; (c) what a reporter sees
  for `test.skip`, `test.todo`, `test.fails` and a `.only` run. Write the results into
  `design.md` and choose the claim form.
- **Reporter** in `common/speccheck/vitest/` (TypeScript, no runtime dependencies), mapping
  vitest states onto the outcomes. Validated against the JSON Schema from step 1.
- **Claim helper** `covers("FE-REQ-001-01", "how")` (or the name/tag form if metadata doesn't
  work for skipped tests), with the pytest rules: inside one `it`/`test`, never a `describe`, one
  per case of `test.each`, and a unique explanation.
- **Static check:** `speccheck check` reads a `vitest list --json` run (or the reporter's file from
  a collect-only run), since vitest has no collection hook to fail early.
- **How the frontend gets it:** a local `file:` dependency in `package.json` or a path in the
  vitest config. Decide with the frontend reviewer (lockfile and Docker build impact).
- **First user:** the frontend spec folder, with its config, the `platform-frontend-npm` upload
  and a final job.

## Reviewers

frontend, technical, CI and tests, security. See `reviews.md`.
