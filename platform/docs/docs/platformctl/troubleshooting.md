---
title: Troubleshooting
description: Find out what is wrong with a setup and how to fix it
---

# Troubleshooting

```bash
./platformctl doctor
```

`doctor` checks the common causes of a platform that does not start, one line each:

```
PASS  docker                 Docker Desktop 29.9.2, Compose 5.6.1, context desktop-linux
FAIL  platform-env           .env does not exist
      fix: Run `./platformctl config init`: it creates .env, fills blank secrets and asks for the LLM profile and key.
PASS  ports-free             3 ports are free

1 problem: run the fixes above, then ./platformctl doctor again
```

- **FAIL** means something is broken; `doctor` exits 1. **WARN** is worth fixing but does not stop the platform
  (exit 0). **SKIP** means the check did not apply, and says why.
- It only reports. It never changes anything.
- `./platformctl doctor --list` shows every check. Name one or more to run only those:
  `./platformctl doctor ports-free`.
- `./platformctl doctor --tag preflight` runs only the checks that must pass before a start.
- `--json` prints the result as one object, for scripts and assistants.

## Common problems

| You see | Run |
|---------|-----|
| `.env does not exist`, or `not set: ...` | `./platformctl config init` |
| A port is held by another process | Free it, or choose another with `./platformctl config set BACKEND_PORT=<free port>` |
| `status --wait` times out | `./platformctl doctor`, then look at the check it names |
| An agent is not registered | `make logs SERVICE=<agent>` and check the agent's `agent_card.json` name |
| `.env` is readable by others | `chmod 600 .env` |
