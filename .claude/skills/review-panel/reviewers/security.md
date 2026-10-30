### Security and secrets

Where could this change leak or mishandle a secret, or act on something it shouldn't?

- **Secrets at rest:** reading and writing `.env`, agent `.env` files and generated files.
  Check permissions, atomic writes, `.gitignore`, and values copied between folders.
- **Secrets in output:** logs, `--verbose` and `--dry-run` output, JSON output, error messages
  and tracebacks, HTTP error bodies, LLM prompts, artifacts, and CI logs. Is there a test that
  would catch a leak in each new code path?
- **Auth:** the session cookie, `BACKEND_JWT_SECRET`, the per-turn identity JWT
  (`USER_IDENTITY_PRIVATE_KEY` in the backend only, the public key everywhere else), the
  agent bearer token `AGENT_SECRET`, OIDC, and signing-key rotation. Can one user reach another
  user's data, or can an unauthenticated caller reach a new endpoint?
- **Untrusted input:** uploads (type, size, path traversal), artifact URIs and the
  `uri_resolver`, agent output rendered in the browser, and prompt injection through user
  content or tool results that leads to a tool call.
- **Supply chain and CI:** new dependencies, unpinned images or actions,
  `pull_request_target`, workflow permissions, and secrets exposed to fork PRs.
- **Scope of actions:** which containers, files or registrations the change restarts, deletes,
  or overwrites, and whether it can touch something that isn't its own.

Try the new paths against a throwaway `.env` with sentinel values (for example
`AGENT_SECRET=SENTINEL-agent`), then grep every output for `SENTINEL`.

Read: the diff; `platform/.env.example`; `platform/docs/docs/dev-docs/encryption-and-keys.md`;
`platform/docs/docs/dev-docs/multi-user-setup.md`; the hackathon `CLAUDE.md` rules and
`conventions.md`.
