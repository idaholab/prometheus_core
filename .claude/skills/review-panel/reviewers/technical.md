### Technical

Review the design and the tests across the whole change:

1. **Design and extensibility:** does the change fit the existing structure, or does it add a
   second way to do something that already has one? Did it leak an abstraction, such as logic
   copied from `sdk/prometheus_api` into a consumer, a second place that decides images or
   config, or a setting outside the config it belongs to? Is anything over-engineered or
   speculative? Could it be smaller?
2. **Correctness:** find the edge cases and failure paths the change gets wrong: config
   precedence, concurrency, retries, timeouts, error handling, cleanup. Check your claims with
   small experiments in `$TMPDIR` instead of trusting the comments or the PR text.
3. **Tests:** run the tests of the touched components. Is the coverage meaningful, or does it
   restate the implementation? What's untested?
4. **Consistency:** look for contradictions between the code, its docs (`CLAUDE.md`, `AGENTS.md`,
   READMEs, `CONTRACT.md`) and the PR description, and for anything the PR promises that isn't
   there.

Read: the diff; `platform/CLAUDE.md`; the code the change replaces or calls; the
docs it touches.

You may use ~900 words. After "Not covered", add a `Contradictions:` line listing each one
as file:section vs file:section, or "none".
