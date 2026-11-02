# Fix a problem

Find the cause with the checks of `checks.md`, explain it, and fix it. Invent no other
diagnostics. With an agent, note `<route-key>` (the second command of `registry-details`).

## 1. Get the symptom

1. Match the argument against the "symptom" column of `troubleshooting.md`: the error strings
   first, then the meaning. Several rows match: ask (header `Symptom`, at most 4 rows).
2. No argument or no match: ask (header `Area`): "The stack won't start", "My agent is missing or
   never called", "An error in the chat or the logs", "Files, uploads, plots, or DeepLynx". Then
   ask (header `Symptom`) with the first 4 rows of that group. Free text that matches nothing: run
   the checks of every row of the group.
3. Primer of 2 or 3 lines on the layer, with the slide: the stack (deck 03, slide 3, A5), the
   registry and discovery (deck 03, slide 4; deck 04, A15-A16), the errors (deck 03, A19-A20),
   the files (deck 03, slide 10; deck 04, slides 9-10).

## 2. Run the checks

1. Take the check ids of the row. Add `stack-ps` for the registry, backend, and DeepLynx checks,
   and `agent-running` for the agent checks.
2. Run them in the layer order of `checks.md`, the read-only checks of one layer in one Bash
   call. Note PASS or FAIL and the evidence for each.
3. When a low layer fails and explains the symptom, skip the higher layers until it is fixed.

## 3. State the cause and fix it

1. Say the cause in one or two sentences: the lowest failed check, its evidence, and its source.
2. All checks pass: try the other rows of the group. None fits: say what you checked, and name
   the mentor for the topic (`mentors.md`).
3. Apply the fixes one at a time, by their kind (`SKILL.md`, "Fix kinds").

## 4. Verify and end

1. Run each failed check again. Show a table: check id, PASS or FAIL, evidence.
2. Still failing: go back to step 3 with the next cause. After two rounds with no progress, sum
   up and name the mentor.
3. "Listed, but never called", "Called with the wrong arguments", or "Capability … is currently
   unavailable" with all checks passing: go on with `trace-turn.md`.
4. After a registry fix (agent missing, platform restarted, a platform target ran), ask the check
   question `registry-wipe` once per session, and offer `/how explain registration and discovery`.
5. End with 3 to 5 lines: the symptom, the cause, the fix, the result, and the next step, for
   example "Start a fresh chat conversation and ask: …" (deck 04, slide 18).
