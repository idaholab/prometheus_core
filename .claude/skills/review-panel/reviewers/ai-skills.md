### AI assistants and skills

AI assistants run this repo's commands and read its guidance files. That includes the hackathon
skills (`hackathon/.claude/skills/`), the `CLAUDE.md` and `AGENTS.md` files, and the skills in
`.claude/skills/`. For what this change touches:

1. **Still true?** Do the skills, the knowledge base (`hackathon/.claude/skills/how/references/`),
   and the `CLAUDE.md` / `AGENTS.md` files still describe the code after this change? Look for
   commands, paths, container or service names, ports, env vars, and file layouts that changed.
   Check the KB "Facts as of" headers and `stale-docs.md`.
2. **`allowed-tools`:** do the patterns in each `SKILL.md` still match the exact commands that
   the skill runs, byte for byte? A mismatch means a permission prompt, which breaks the flow for
   a participant.
3. **Machine-friendly:** can an assistant run every new or changed command without a terminal,
   safely (no prompts without `--yes`, no following logs without a timeout, no pager), and
   parse its output? Is any JSON output stable (fields, errors, exit codes)?
4. **Secrets:** does the change help or hurt the "never show a secret" rules? Look for commands
   that would print a value, and for new files that an assistant might `cat`.
5. **Skill quality:** for a changed `SKILL.md`, does the `description` say when to use it in the
   words a user would type? Are the steps unambiguous, and is each question self-contained? Does
   it still work against an older clone?

Read: the diff; `hackathon/CLAUDE.md`; the `diagnose`, `how` and `create-agent` skills;
`hackathon/.claude/skills/how/references/conventions.md`; `platform/CLAUDE.md`;
`sdk/CLAUDE.md`.
