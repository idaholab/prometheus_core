# speccheck, for agents

A requirement counts only when a test that claims it ran and passed in CI. Citing an ID in a docstring or comment is not evidence. Details are in [README.md](README.md).

- Claim a requirement with `@pytest.mark.covers("PREFIX-REQ-NNN-XX", "how this test proves it")` on the test function, one mark per ID. On a parametrized test, put it in each `pytest.param(..., marks=...)` instead, never on the function, a class or a module.
- The explanation says what this test does, in your own words: not the requirement's text, not a placeholder, and different from every other claim's.
- Run `pytest --collect-only -q --speccheck-results=.speccheck/collect.jsonl && speccheck check .speccheck/`, chained with `&&` so `check` runs only when pytest exited 0. Fix every problem it prints before you finish.
- If that pytest exits non-zero (4 is a usage error), it wrote no results file. Fix the errors pytest printed first (`speccheck:` ones, or a bad option or `conftest.py`), and run both again. It removes an earlier file only once its session starts, so after a bad option or a `conftest.py` that raises an old file can remain: the `&&` is what keeps `check` from reading it. A `check` that reads no file fails with `no-results` first, then lists every requirement as unclaimed: that is the failed collect, not missing claims.
- Only add `(unimplemented: <reason>)` to a requirement a plan delivers later, never to dodge an unclaimed one: behaviour that exists gets a test. Remove the suffix when you claim it.
- Use `--json` and read `problems[].code`, not the message text. `line: 0` means no line. Exit 0 is fine, 1 is problems, 2 is a usage or config error.
- `lint` needs no CI and no results. `check` needs no CI either, but it needs a collect-only results file to read, or it fails with `no-results`. `verify` and `report` need the results of a real run (`--speccheck-results=FILE`).
