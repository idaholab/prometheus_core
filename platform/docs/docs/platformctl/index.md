---
title: platformctl
description: Run and diagnose the Prometheus platform from one command
---

# platformctl

`platformctl` is the command that sets up, checks and diagnoses the platform on your laptop. It lives in
`platform/` and needs only Python 3.10 or newer, which it finds for you (a Mac whose `python3` is 3.9 works).

```bash
cd platform
./platformctl --help
```

## The first time

Just run `make up`. It runs `./platformctl config init` first, which creates `.env` from `.env.example`, generates
the secrets, asks which LLM provider you use and for its key, and asks two questions about doing the heavy parts on
this laptop. Press Enter to take the recommended answer. [Setup](setup.md) has the details. When it is done it waits
until the platform answers (`./platformctl status --wait`).

If you answer *yes* to building on this laptop, `make up` saves the answer and stops with "Run the same make command
again", because `make` had already chosen where to get the base image. Run `make up` again.

To prepare `.env` without starting anything, run `./platformctl config init` yourself.

If something does not work, run `./platformctl doctor`. It says what is wrong and how to fix it.
See [Troubleshooting](troubleshooting.md).

## The commands you need today

| Command | What it does |
|---------|--------------|
| `./platformctl doctor` | Diagnose common problems and say how to fix each |
| `./platformctl config init` | Create or complete `.env`; see [Setup](setup.md) |
| `./platformctl config show` | Each setting, its value and where it came from (secrets as `set` or `blank`) |
| `./platformctl config set KEY=value` | Write a setting into `.env` |
| `./platformctl status --wait` | Wait until the platform answers and every agent is registered |
| `./platformctl deeplynx setup` | Start the local DeepLynx and save its key in `.env` |

Starting and stopping the platform is still `make up` and `make down`; every `make` target keeps working, and
[From make](from-make.md) lists the ones that now run `platformctl`. The full option list of any command is
`./platformctl <command> --help`.

## Good to know

- **Nothing you type is echoed if it is a secret.** Secrets are never printed, not even with `--verbose`. A secret is
  read from a hidden prompt or from the environment, never from the command line.
- **`--json`** prints one machine-readable object, for scripts and assistants.
- **`--dry-run`** says what a command would do without doing it.
- Run it as yourself, not with `sudo`.
