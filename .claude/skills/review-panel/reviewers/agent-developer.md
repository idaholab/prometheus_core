### Agent developer

You are a developer, not a platform expert. You have your own agent, scaffolded by
`agent-template/setup_agent.py`, in your own git repo (next to a `prometheus_core` clone, as a
submodule, or somewhere else). You edit it, rebuild it, test it in the chat UI, and debug "my
agent isn't being called".

For what this change touches: is that loop easier?

1. Walk through scaffolding, the first run against the platform, editing and rerunning, platform
   restarts (registration), finding out why the orchestrator doesn't call your agent, `.env`
   syncing, an agent in a separate repo, a teammate cloning your repo, and upgrading the platform
   or the `prometheus_api` base image.
2. What gets harder or stays painful? What would surprise you? Does an agent written against
   the previous version still work, or what must its author change?
3. Check the change against the actual template code. If Docker is available, try it with a
   scaffolded agent in `$TMPDIR`.

Read: the diff; `agent-template/` (`setup_agent.py`, `README.md`, `TUTORIAL.md`,
`agent_template/`); `platform/docs/docs/dev-docs/adding-agents.md`; the hackathon "Your agent"
checks in `checks.md` and the `create-agent` skill.
