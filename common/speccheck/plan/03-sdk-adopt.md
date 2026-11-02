# 3: The sdk on speccheck

> **Status: Not started**

## Goal

Check `sdk/specs/` with speccheck from real test runs: move its IDs to the `SDK-` prefix, turn its
existing citations into markers, and add the final job for the sdk. Requirements nobody cites yet
are marked so this step can pass, and step 4 works through them.

## Work

- **Config** in `sdk/pyproject.toml` (`[tool.speccheck]`): `specs = "specs"`, `id-prefix = "SDK"`,
  producers `sdk-python`, `sdk-docker`, `sdk-install`, and any `test.yml` job whose tests
  claim sdk requirements (`agent-template`, `platform-agent` use the sdk, but should only claim
  their own specs; decide here).
- **Prefix:** rename every `REQ-NNN-XX`/`BEH-NNN-XX` to `SDK-REQ-...`/`SDK-BEH-...`, in
  `sdk/specs/`, in the tests, and in every doc that names one (`grep` across the repository,
  including `agent-template/` and `platform/`). One mechanical commit, separate from the rest, so
  it is easy to review.
- **Markers:** turn the existing citations (docstrings such as `"""Covers REQ-002-14."""` and
  comments such as `# REQ-005-14, BEH-005-05: ...`, about 43 IDs) into `covers(ID, how)` marks,
  each saying how that test proves the requirement. A parametrized test claims per
  `pytest.param(..., marks=...)`, never on the function, and class or module marks move down to
  each test.
- **The rest:** run `check` and mark each requirement no test claims `⚠ untested`, with a line
  under the spec's Open questions. That is about 200. This is honest about the current state, and
  step 4 removes the markers.
- **CI** in `test.yml`: producer variables and `speccheck-upload` in `sdk-python` (each leg) and
  `sdk-docker` (results path in the mounted checkout, CI variables passed with `-e`); `record`
  for spec 013's packaging requirements in `sdk-install` and `sdk-docker`; and a final
  `speccheck-sdk` job.
- **Docker:** the sdk's dev group now includes a path dependency outside `sdk/`. Check that
  `sdk-docker`'s `uv export --only-dev` still installs (the checkout is mounted at `/src`, so
  `../common/speccheck` is not there). Likely fix: mount the repository root and work in
  `/src/sdk`.
- **Docs:** `sdk/docs/SDD_SPEC_AUTHORING.md` and `SDD_TESTING_STANDARD.md` say how to claim a
  requirement (the marker) and point to speccheck's README for the checked rules, instead of the
  docstring form. `sdk/specs/000-index.md`'s "How Agents Use These Specs" says the same.
- **Agent skills and instructions** that tell an agent how to cite IDs (`sdk/AGENTS.md`,
  `CLAUDE.md` files, hackathon skills) are updated in the same PR.

## Done when

- `speccheck-sdk` passes in `test.yml` on a PR and with `--complete` on `devel`.
- No source file in the repository still cites a bare `REQ-NNN-XX` from `sdk/specs`.
- Breaking or skipping a test that claims an `SDK-` requirement fails the final job.

## Reviewers

technical, CI and tests, agent developer, AI skills, rollout. See `reviews.md`.
