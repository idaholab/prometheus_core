---
title: Everyday use
description: Check that the running platform is ready
---

# Everyday use

Starting, stopping and restarting the platform is still done with `make` (`make up`, `make restart`, `make down`);
see [From make](from-make.md).

## Is it ready?

```bash
./platformctl status --wait
```

It checks what a container health check cannot see from inside: that the backend (and the frontend and its `/api`
proxy, when one is started) answer on their ports on your laptop, and that every agent has registered. With `--wait`
it repeats the check until everything passes, up to `CHECK_TIMEOUT` seconds (300 by default; `--timeout N` changes it).

```
Waiting up to 300s for the platform:
  backend
  frontend
  frontend /api proxy
  3 agent(s) registered
  [OK] backend
  [OK] frontend
  [OK] frontend /api proxy
  [OK] 3 agent(s) registered
The platform is up.
```

If it times out, it says what never passed and which `doctor` check explains it:

```
[ERROR] Not ready after 300s:
  3 agent(s) registered: not registered: synthesis-agent
Run: ./platformctl doctor platform-env
```

Without `--wait` it checks once and exits: 0 when everything is ready, 1 when it is not. `--json` prints the same
facts as one object.

`make up` runs this at the end, so it returns only when the platform is ready. `CHECK=false make up` skips it.
