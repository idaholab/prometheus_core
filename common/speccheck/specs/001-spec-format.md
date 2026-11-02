# 001 - Spec format

status: implemented

## Purpose

A spec folder is plain markdown that people review. `lint` makes sure every requirement in it can
be found, has one ID, and says whether it is tested, planned or retired.

## Requirements

- SPC-REQ-001-01: A spec file MUST be named `NNN-short-name.md`, and its first line MUST be its
  title, `# NNN - Name`. Any other `.md` file in the folder is a problem.
- SPC-REQ-001-02: When the config requires an index, `000-index.md` MUST exist and MUST link every
  spec as a markdown link. Mentioning a spec's number or name in prose is not enough.
- SPC-REQ-001-03: A spec MUST have one `status:` line above its first `##` section, with the
  value `draft`, `implemented` or `retired`. An `implemented` spec MUST have at least one
  requirement. A `draft` spec's requirements MUST be checked like an `implemented` spec's.
- SPC-REQ-001-04: A requirement MUST be a bullet `- <prefix>-REQ-NNN-XX: text` or
  `- <prefix>-BEH-NNN-XX: text`, where NNN is the spec's own number. A bullet that starts like an
  ID in any other form (`*`, bold, nested, without the prefix) is a problem, so it can't go unseen.
- SPC-REQ-001-05: An ID MUST be unique across the folder.
- SPC-REQ-001-06: A bullet's text MAY continue on lines indented two spaces, and the untested and
  planned markers (see the README) count wherever they are in it. A bullet MUST NOT carry both.
- SPC-REQ-001-07: A requirement whose text starts with `Retired.` or `Retired:`, or that is in a
  `retired` spec, MUST be treated as retired.
- SPC-REQ-001-08: Lines inside fenced code blocks MUST NOT be read as requirements or headers.
- SPC-REQ-001-09: A spec's `tests:` line and an index's `id-prefix:` line from the old checker MUST
  be reported, saying where the setting lives now.
- SPC-REQ-001-10: Two requirements in the folder that aren't retired MUST NOT have the same text,
  compared after collapsing whitespace, ignoring case and dropping a trailing full stop. The
  problem MUST name both IDs.
