# Make an explainer page

Make one HTML page that explains one concept at the level of the slides, fact-checked before
the user sees it. Write only `<root>/.explainers/<slug>.html` (gitignored). No secret anywhere.

| topic | KB files | body class | bank id | next pages |
|---|---|---|---|---|
| One chat turn | `platform.md`, `card.md`, `run-and-register.md` | (none) | `chat-turn` | The agent card; Registration and discovery |
| The agent card | `card.md` | `t-agent` | `card-interface` | One chat turn; Files and artifacts |
| Files and artifacts | `artifacts.md` | `t-agent` | `artifacts` | Input-required; One chat turn |
| Input-required | `asking-the-user.md` | `t-agent` | `input-required` | Long-running work; Files and artifacts |
| Registration and discovery | `run-and-register.md` | (none) | `registry-wipe` | One chat turn; The agent card |

Other topics: the KB files of `index.md`; secrets use `secrets`; git uses `git-pr.md` and `t-git`.

## Steps

1. **Topic.** Use the request. With none, ask (header `Topic`): "One chat turn" (recommended),
   "The agent card", "Files and artifacts", "Input-required". The slug is the topic in lowercase,
   each run outside `a-z0-9` changed to `-`, at most 60 characters.
2. **One round.** Ask in one call: `You know` ("Saw the slides", "New to it", "Built with it");
   `Confusing` (2 to 4 likely confusions of the topic); `Depth` ("Overview" recommended, 3-5
   panels; "Details", 6-8 panels with code); and, when the page exists, `Old page` ("Replace
   it", "Keep both" with `<slug>-2`, "Open the old one", which skips to step 7).
3. **Facts.** Read the topic's KB files. List `F1. <fact> (source: <deck label or path:line>)`.
   Give most room to the confusion. When the KB is silent, read the code with read-only Bash
   (`prometheus_api` in `<agent>/.venv/lib/python3*/site-packages/` or `docker compose -p <project> exec -T <service>`).
   Leave out what nothing settles, and name the mentor (`mentors.md`).
4. **Draft.** Copy `explain-template.html` in this folder, and obey the rules in its top comment.
   Pitch the text at the `You know` answer. One panel answers the confusion. The last panel holds
   2 or 3 check questions, not the bank question of step 8. Fill the footer with `date +%F` and
   the "facts as of" line of a KB file. Write the draft; do not open it yet.
5. **Claims and fact-check.** List each factual statement as `C1. <claim> (source: ...)`: box and
   arrow labels, table cells, code, and each check answer. Spawn one `general-purpose` subagent
   ("Fact-check explainer page") with this prompt, filled in, and wait for it:

   ```text
   Fact-check one explainer page for Prometheus hackathon participants. Read only; change no
   file and no state. Never show a secret: no cat on .env, env, printenv, docker inspect,
   docker compose config, curl -v. Paths: root <root>; KB <root>/.claude/skills/how/references/;
   platform <platform>; template <template>; agent <agent or none>; prometheus_api <path, "in
   the container of <project>", or none>; draft <root>/.explainers/<slug>.html. Read files
   outside root with Bash (sed -n, grep -n). You have no slides: a deck claim is supported when
   a KB file states it. When the code disagrees with the KB, the code is correct.
   Claims: <C1 ...>
   For each claim, open its source and the code it names. Verdict: CONFIRMED, WRONG,
   UNSUPPORTED, or STALE (the KB says it, the code differs). Then read the draft once and report
   wrong unlisted statements as UNLISTED, and any key value as SECRET (without the value).
   Return: "Summary: <n> checked: <a> confirmed, ...". Then per non-confirmed finding, at most
   5 lines: id, verdict, claim, evidence (path:line + 2-line quote), fix (text + source, or
   "remove"). Then "Confirmed: C1, C2, ...".
   ```

6. **Fix.** Apply each fix, or remove the statement. For STALE, tell the user which KB file is
   out of date. When fixes change more than 3 claims or a diagram, check those once more; after
   two rounds, remove what still fails. Check that every tag closes. Then run these checks:

   ```sh
   grep -nE '<script|<link|@import|src="https?:|url\(https?:|\son[a-z]+=' "<page>" || echo "no external references"
   python3 -c 'import re,sys,pathlib as P
   page=P.Path(sys.argv[1]).read_text(); hits=set()
   for e in map(P.Path,sys.argv[2:]):
    for k,v in re.findall(r"(?m)^\s*([A-Z0-9_]*(?:KEY|SECRET|PASSWORD|TOKEN)[A-Z0-9_]*)\s*=\s*[\x27\"]?([^\x27\"\n]{8,})",e.read_text() if e.is_file() else ""):
     v in page and hits.add(k)
   print("secret values on the page:",sorted(hits) or "none")' "<page>" "<platform>/.env" "<agent>/.env"
   ```

7. **Open.** Open the page with "Open a file in the browser" of `conventions.md`, or give the
   path. When `git -C <root> check-ignore -q .explainers/<slug>.html` fails, say not to commit it.
8. **Check and next.** Unless "skip the quiz", ask the topic's bank question of `teaching.md`
   (header `Check`), or one question from a confirmed claim; give 2 lines of feedback with the
   source and the panel. Then ask (header `Next page`): the two next pages, "Deeper version"
   after an overview, "No, thanks".
