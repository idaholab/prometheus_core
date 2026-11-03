---
title: Set up
description: Create .env, choose an LLM provider, and decide what runs on your laptop
---

# Set up

```bash
./platformctl config init
```

Run it as often as you like: it never changes a value that is already set.

## What it does

1. **Creates `.env`** from `.env.example` (readable by you only, mode 0600), if there is none.
2. **Generates the secrets** that are blank (`AGENT_SECRET`, the database passwords and so on).
3. **Gets the LLM provider and key.** If `LLM_CONFIG_PROFILE` or its key is blank, you choose from a menu (arrow keys,
   Enter) and type the key. The key is not shown as you type. In CI, set `LLM_CONFIG_PROFILE` and `LLM_API_KEY` in the
   environment and they are saved without a prompt.
4. **Asks two questions**, when `.env` does not already decide them. Enter takes the recommended answer:
    - *Build everything on this laptop (no INL login needed)?* Sets `LOCAL_SDK`. The recommended answer comes from a
      quick check of whether your machine can reach the INL registry: if it can, it is *no*.
    - *Run DeepLynx (file storage) on this laptop?* Sets `LOCAL_DEEPLYNX`.
5. **Lists keys that `.env.example` has and your `.env` lacks.** A key added after you made your `.env` never
   reaches it by itself; this tells you. It lists them and does not add them: copy the lines you want.

### If you already have a `.env`

Nothing in it is changed or overwritten. The two questions in step 4 are asked once, on the first run after you
update, because an older `.env` does not say what you want (`LOCAL_SDK` and `LOCAL_DEEPLYNX` are commented out in
`.env.example`). Your answer is saved, so you are not asked again. To skip the questions, give the flags
(`--local-sdk` / `--no-local-sdk`, `--local-deeplynx` / `--no-local-deeplynx`), use `--yes`, or run without a
terminal. A `.env` that other users can read is made owner-only (0600), and `config init` says so.

It ends with what to do next, for example `Next: make up`.

Use the flags to answer without being asked: `--local-sdk` / `--no-local-sdk` and `--local-deeplynx` /
`--no-local-deeplynx`. `--yes` takes the recommended answers.

### Without a terminal

Scripts, CI and assistants have no terminal, so nothing is asked. `config init` then fails (exit 1) only when the LLM
profile or key is missing, as before. An unanswered local question keeps its default (off), with a one-line note
naming the flag that turns it on.

## Local DeepLynx

With `LOCAL_DEEPLYNX=true`, run:

```bash
./platformctl deeplynx setup
```

It starts the DeepLynx containers, waits for the server, finds the project `Prometheus` (or creates it), makes an API
key and saves the `DEEPLYNX_*` settings in `.env`. It ends with the address of the DeepLynx web interface. Run again
at any time: if `.env` already holds a key the server accepts, nothing changes. After `make down-v` the DeepLynx
database is gone, and the next run creates a new project and key.

## Look at, and change, settings

```bash
./platformctl config show                 # every setting, its value and where it came from
./platformctl config set BACKEND_PORT=9000 PROFILE=prod
```

`config show` prints a secret as `set` or `blank`, never its value. `config set` writes into `.env` in place and keeps
the rest of the file. It refuses a secret on the command line, because it would end up in your shell history. To
set a secret, put the value in the environment and name the key:

```bash
read -rs LLM_API_KEY && export LLM_API_KEY    # type the key; it is not shown
./platformctl config set --from-env LLM_API_KEY
```

(`--set KEY=VALUE` before or after any command is different: it overrides a setting for that one run and writes
nothing.)
