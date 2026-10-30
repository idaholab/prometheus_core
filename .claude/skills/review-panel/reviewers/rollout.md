### Rollout and migration

- **This PR:** is it reviewable, and does it contain one logical change? Does it leave `devel`
  working? Can it be reverted on its own? Does it depend on something that isn't merged yet,
  such as docs or slides that use a command from a later PR?
- **People mid-migration:** someone with an existing `.env`, a running stack started by an
  earlier version, a database at an older Alembic revision, an agent scaffolded earlier, an agent
  on an older `prometheus_api` base image, a frontend tab left open across the deploy, or old
  muscle memory. What breaks or confuses them? Does the PR say "what changes for you", and is it
  right?
- **Compatibility:** wire-contract, card, env-var, port, or command changes. Which consumers
  (frontend, client-agent, third-party agents, the hackathon material, the docs) must change at
  the same time, and do they?
- **Timing:** anything participants or other teams rely on right now. Check for events and
  freezes (the hackathon material notes them), and for open PRs that touch the same files
  (`gh pr list --repo idaholab/prometheus_core --state open`, then compare their files with the
  diff).

Read: the diff and the PR description; `git log --oneline -20 <base>`; any plan or
`breaking-changes.md` the change belongs to.
