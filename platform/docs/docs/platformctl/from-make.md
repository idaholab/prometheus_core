---
title: From make
description: The old make targets and the platformctl commands they now run
---

# From make

Every `make` target keeps working. These now run `platformctl`, and print the command they run:

| make | platformctl | What it now does for you |
|------|-------------|--------------------------|
| `make init-env` | `./platformctl config init` | Asks whether to build on this laptop and run DeepLynx here, and lists keys `.env.example` has that your `.env` lacks |
| `make check` | `./platformctl status --wait` | Says what it is waiting for, and which `doctor` check explains a timeout |
| `make deeplynx-setup` | `./platformctl deeplynx setup` | Prints the steps and the DeepLynx web address |
| `make doctor` (new) | `./platformctl doctor` | Diagnoses common problems and says how to fix them |

The scripts these replace, `scripts/init_env.py`, `scripts/check_platform.py` and `scripts/deeplynx_setup.py`, are
now short stubs: they print `moved: run ./platformctl ...` and run the new command. They are removed in a later
step.

## Variables given to make

`make BACKEND_PORT=9000 up` still beats a value in `.env`, as before; so does every other setting you give on the
make command line. A variable set in your shell (`BACKEND_PORT=9000 make up`) still loses to `.env`.
A variable that is not a setting is ignored with a one-line warning naming it.
