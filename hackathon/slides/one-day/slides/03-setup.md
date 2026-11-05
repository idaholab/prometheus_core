---
title: Setting up
footer: One day · Setting up · https://idaholab.github.io/prometheus_core/hackathon/one-day
accent: gh
index:
  time: '11:00'
  heading: Setting up
  color: var(--green)
  blurb: 'Start the platform and local DeepLynx, log in and check health, try the debug agents, then scaffold your own agent and see it appear under /agents. Plus a catch-up slide.'
---

# Setting up {.title kicker="Agent developer hackathon · One day · 11:00 am" pills="Hands-on | about 2 hours | lunch at noon while images build"}
By the end of this block the platform runs on your laptop, you have talked to the debug agents, and your own agent is registered and visible in the chat.
Note: Lunch is at noon. The first make up builds images, which is idle time; people eat while it runs. The checkpoints start at 1:00.

---

## Start the platform {eyebrow="Step 1 of 5"}

:::: cols 1.1fr 1fr gap=28px
```bash {.sm}
cd prometheus_core/platform
make up
```

```text {.xs}
Build the SDK base image locally (LOCAL_SDK)? [Y/n] (Enter = yes):
Run DeepLynx locally (LOCAL_DEEPLYNX)? [Y/n] (Enter = yes):
Choose an LLM profile (LLM_CONFIG_PROFILE; up/down, Enter):
<KEY> for <profile> (input hidden):
```

::: callout info
**Repo updated?** Run `git pull` in `prometheus_core`, then `make up` again in `platform/` and in your agent folder. Your `.env` files are not touched.
:::
|||
- Answer **yes** to both questions (press Enter). The first builds the SDK image from your clone; the second starts DeepLynx next to the platform, creates its project and API key, and writes them into `.env`.
- Pick the **LLM profile** you were given a key for, and paste the key. It is hidden as you type and stays in `.env`, which is never committed.
- The first run builds images and can take a while. Keep going; it prints when everything is up.

::: callout warn
`make up` only asks in a terminal, and only for what `.env` is missing. If it stops with `[ERROR] … is empty in .env`, run `make init-env` and answer again.
:::
::::

---

## Log in and check health {eyebrow="Step 2 of 5"}

:::: cols 1fr 1fr gap=28px
::: steps
#### Open the chat

{.small}
`http://localhost:5150`. The first time, a wizard asks for a username and password. Any local values work; the first user is the admin.

#### Say hello

{.small}
Type "hello". A reply means the orchestrator, your LLM profile and the chat all work.

#### See the stored artifact

{.small}
DeepLynx is at `http://localhost:3000`. The files the agents produce are stored there.
:::
|||
```bash {.sm}
make ps       # all "Up" / "(healthy)"
make check    # every agent registered?
make logs SERVICE=client-agent
```

::: callout warn
Every chat turn fails with "No 'userToken' found…"? The backend could not create its signing key. Look at `make logs SERVICE=backend`.
:::
::::

---

## Try the debug agents {eyebrow="Step 3 of 5"}

:::: cols 1.1fr 1fr gap=28px
```bash {.sm}
make down
echo "DEBUG_AGENTS=true" >> .env
make up
```

```text {.sm}
/agents
Create an image of the word 'INL'
  with white background and blue text.
Convert that to a PNG.
```
|||
- The debug agents are small agents that exist to be tried: they make images, return JSON, and show code samples.
- `/agents` lists what is registered. The artifact debug agent should be there.
- Ask for the image, then for the PNG, and watch the chat pick a skill each time. Look at the artifacts in DeepLynx.

::: callout info
This is the same loop your own agent will go through: the orchestrator reads a card, picks a skill, and the result comes back as an artifact.
:::
::::

---

## Scaffold your agent {eyebrow="Step 4 of 5"}

:::: cols 1.1fr 1fr gap=28px
```bash {.sm}
cd prometheus_core/agent-template
python setup_agent.py
#  name, description, slug,
#  class name, first skill id
#  output folder: ../../<your-agent>
#  copy secrets from the platform .env? yes

cd ../../<your-agent>
uv sync
```
|||
- Answer **yes** to copying the secrets. Your agent's `.env` then has the keys it needs and `LOCAL_SDK`, so it builds from the same SDK image as the platform.
- Open the folder in your editor. `agent.py` is the class, `agent_card.json` is what the orchestrator reads.
- Choose skill ids that do not clash with the built-in agents. `/agents` shows what is taken.

::: callout warn
Put the folder **beside** the clone, not inside it. Commit nothing yet: `.env` holds your keys.
:::
::::

---

## Start it and find it {eyebrow="Step 5 of 5"}

::: cols 1.1fr 1fr gap=28px
```bash {.sm}
cd <your-agent>
make up        # build and start
make logs      # "Registered '<name>' ..."
```

```text {.sm}
/agents
```
|||
- The agent registers itself with the platform on startup. Give the orchestrator about a minute to notice, then type `/agents` in a **fresh chat**.
- Ask the chat something your skill's description fits and watch it route.

| If this happens | Look at |
|---|---|
| Not under `/agents` | `make logs`; restart the agent |
| Missing right after a platform `make up` | restart your agent: the registry was emptied |
| Build fails on `uv.lock` | run `uv sync` and rebuild |
| Skill never called | the card's `description` |
:::

---

# Bonus: catch up {.section .bonus num="+"}
Not finished with the homework? These slides get you to the same place.

---

## No clone, tools, or key yet? {eyebrow="Bonus · Catch up"}

```bash {.sm}
git clone https://github.com/idaholab/prometheus_core.git
cd prometheus_core/platform
make up        # answer the prompts as on step 1
```

:::: cols 1fr 1fr gap=28px
::: card acc tag="Needed"
### Installed

{.small}
Git, Docker (running), `uv` and an editor such as VS Code.
:::
|||
::: card acc tag="Needed"
### An LLM key

{.small}
For the profile you pick at the menu. Ask a mentor if you do not have one yet.
:::
::::
