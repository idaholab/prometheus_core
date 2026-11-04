# speccheck specs

What speccheck promises to the people and agents who write specs and tests. Each requirement here
is proven by one of speccheck's own test runs, or by a CI job of `speccheck.yml`. `speccheck.toml`
next to this folder says which. IDs carry the `SPC` prefix.

| Spec | Covers |
|---|---|
| [001](001-spec-format.md) | Spec files, the index, headers, bullets, the unimplemented suffix, what `lint` rejects |
| [002](002-config.md) | Finding and validating the config |
| [003](003-claims.md) | The `covers` marker, its explanations, and the collection check |
| [004](004-results-files.md) | The results file: format, outcomes, writing it, xdist |
| [005](005-evidence-and-verify.md) | A requirement's status, `check` and `verify` |
| [006](006-report.md) | The markdown report: its layout, job names, links and escaping |
| [007](007-ci-jobs.md) | `record`, and the composite actions |
| [008](008-command-line.md) | Commands, global options, exit codes, `--json`, the step summary |
