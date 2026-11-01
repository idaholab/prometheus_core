# 5: Document the tool for contributors

> **Status: Not started**

Each earlier step already switched the user-facing docs and slides to its
commands. This step covers what's left: the documentation for people who
change platformctl, and a final sweep.

## Work

- **User guide review:** read `platform/docs/docs/platformctl/` start to
  finish as a new user. Trim anything that explains internals, check every
  page is a task with its commands, and check `from-make.md` covers every
  Make target in one line each.
- `ctl/README.md`: how the package is laid out, and how to add an action,
  a check, an adapter, a setting or a target; the help-layout rules
  (`SECTION`, `ORDER`, option groups); output rules (steps, summary,
  `--quiet`); aliases and deprecation; the unit and live tests. Check that
  its "Update the docs too" list matches where the commands are referenced
  now.
- `platform/CLAUDE.md`: a section on platformctl for AI assistants
  (where things live, the "only `runner.py` runs subprocesses" rule, the
  coverage rule, the secrets rule), and how an assistant runs long or
  interactive commands: `up --no-check` in the background, then
  `status --wait --timeout 600 --json`; `--yes`/`--confirm` for
  confirmations; `logs --tail`; never `compose -- config` or `exec ... env`.
- Hackathon `CLAUDE.md` rule 3 and `conventions.md`: add `./platformctl
  compose -- config` and `compose -- exec ... env` to the commands never to
  run, and shorten the secret rules where the tool now enforces them.
- **Python per platform:** `docs/docs/windows-wsl2-setup.md` (clone into the
  WSL home folder, not `/mnt/c`; `core.autocrlf input`; Python 3.10+ per
  distro) and a short Linux Docker Engine section (the `docker` group, the
  containerd image store for the build cache, the Compose plugin version,
  rootless limits with `host-gateway`).
- Root `CONTRIBUTING.md`: the new unit and live test commands.
- **Final sweep:** `git grep -nE 'make (up|up-fg|restart|ng-|down|down-v|logs|ps|check|init-env|generate|clean-generated|regenerate|base-image|build|build-plain|clear-agent-registry|clear-admin-users|clobber|deeplynx-setup)\b'`
  over `platform/`, `hackathon/`, `agent-template/`, `sdk/docs`, the root
  docs and CI. Anything left that means the platform's Makefile switches to
  `./platformctl`. The Makefile, the agent template's own Makefile
  (until step 7), and the one CI job kept on `make` (`platform: up`, step
  3a) are the exceptions. The docs test (every `./platformctl` line parses)
  must pass over everything the sweep touched.

## What changes for you

- Docs only. Roll back: revert the PR.

## Breaking changes

None.

## From the step 1 review

- `ctl/README.md` has a "Reading `--json` output" section (`ok` means doctor ran; read
  `counts.fail` for health). Keep it, and check it matches `design.md` ("Output") and the user
  guide.
- `docs/docs/windows-wsl2-setup.md`: add `./platformctl doctor`, the `bash` or `dos2unix` recovery
  for a CRLF shim, and the Windows-side port caveat from step 3b's section above.

## Review

Before merging, run `/review-panel` on the PR (see `reviews.md`) with these reviewers: user, technical, AI skills.

Ask them to look at:

- **User:** the user guide read start to finish as a new user, each page a task with its commands;
  `from-make.md` covering every Make target in one line.
- **Technical:** whether `ctl/README.md` alone is enough to add an action and a check (try it);
  that it matches the code and the places that name the commands; the final sweep's `git grep`.
- **AI skills:** the `platform/CLAUDE.md` section on running long and interactive commands
  (`up --no-check` in the background, `status --wait --timeout 600 --json`); the commands never to
  run (`compose -- config`, `exec ... env`).

## Done when

- A new contributor can add an action and a check from `ctl/README.md` alone.
- The sweep finds no platform `make` command in the docs or slides.
