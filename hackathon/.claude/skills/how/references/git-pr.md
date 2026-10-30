# Git and pull requests

Facts as of `prometheus_core` `devel` 2026-10-30, after #310 (`prometheus_api` 0.15, no LiteLLM). When the code disagrees with this file, the code is correct.

Code reaches `genesis/hackathon` `main` only through reviewed PRs from your fork (deck 02, slides 2-3). You need
the team `open` (ask a mentor). Use SSH or `gh auth login --hostname github.inl.gov`, and
`export GH_HOST=github.inl.gov`, else `gh` talks to github.com. The platform repositories are read-only.

## Setup once, then every feature

```sh
gh repo fork genesis/hackathon --clone=false
git clone git@github.inl.gov:<you>/hackathon.git && cd hackathon
git remote add upstream git@github.inl.gov:genesis/hackathon.git
git config pull.rebase true; git config rebase.autoStash true; git config rerere.enabled true

git fetch upstream && git switch -c feature/<team>-<what> upstream/main   # upstream/dev for the platform
git commit -m "Imperative subject"
git pull --rebase upstream main && git push -u origin HEAD
gh pr create --repo genesis/hackathon --base main --head <you>:feature/<team>-<what>
```

`origin` is your fork; `upstream` is `genesis`. Never commit to `main` or `dev`. A rebase gives your commits
new SHAs, so push with `--force-with-lease` (never `--force`, never on a shared branch). On a conflict: edit,
`git add`, `git rebase --continue` (or `--abort`). Run `git rebase -i` in your own terminal.

## Commits, PRs, and review

- Subject: imperative, under 72 characters, no period. The body says why. One topic per commit.
- Never commit an `.env`, a key, or a token: check `git status`. Commit `uv.lock` with `pyproject.toml`.
- PR body: `## What`, `## Why`, `## How it was tested`. Use `--draft` while in progress.
- Run `uv run pytest && uv run ruff check .` first: `genesis/hackathon` has no CI.
- Reply to each comment with "Fixed in <sha>", or say why not. A coding agent's reply starts with 🤖. The Day 2
  gate needs one approval from outside your team.
