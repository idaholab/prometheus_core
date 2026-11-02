# speccheck, for agents

A requirement counts only when a test that claims it ran and passed in CI. Citing an ID in a docstring or comment is not evidence. Details are in [README.md](README.md).

- Claim a requirement with `@pytest.mark.covers("PREFIX-REQ-NNN-XX", "how this test proves it")` on the test function, one mark per ID. On a parametrized test, put it in each `pytest.param(..., marks=...)` instead, never on the function, a class or a module.
- The explanation says what this test does, in your own words: not the requirement's text, not a placeholder, and different from every other claim's.
- Run `pytest --collect-only -q --speccheck-results=.speccheck/collect.jsonl`, then `speccheck check .speccheck/`. Fix every problem it prints before you finish.
- If that pytest exits non-zero (4 is a usage error), it wrote no results file, so `check` would only say `results-missing` and call every requirement unclaimed. Fix the `speccheck:` errors pytest printed first, and run both again.
- Don't add `⚠ untested` or `(planned: ...)` to dodge an unclaimed requirement. Remove the marker when you claim it.
- Use `--json` and read `problems[].code`, not the message text. `line: 0` means no line. Exit 0 is fine, 1 is problems, 2 is a usage or config error.
- `check` and `lint` need no CI. `verify` and `report` need the results of a real run (`--speccheck-results=FILE`).
