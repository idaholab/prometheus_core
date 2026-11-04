# 001 - Spec format

status: implemented

## Purpose

A spec folder is plain markdown that people review. `lint` makes sure every requirement in it can
be found, has one ID, and says whether it is implemented yet.

## Requirements

- SPC-REQ-001-01: A spec file MUST be named `NNN-short-name.md`, and its first line MUST be its
  title, `# NNN - Name`. Any other `.md` file in the folder is a problem.
- SPC-REQ-001-02: When the config requires an index, `000-index.md` MUST exist and MUST link every
  spec as a markdown link. Mentioning a spec's number or name in prose is not enough.
- SPC-REQ-001-03: A spec MUST have one `status:` line above its first `##` section, with the
  value `draft` or `implemented`. An `implemented` spec MUST have at least one
  requirement. A `draft` spec's requirements MUST be checked like an `implemented` spec's.
- SPC-REQ-001-04: A requirement MUST be a bullet `- <prefix>-REQ-NNN-XX: text` or
  `- <prefix>-BEH-NNN-XX: text`, where NNN is the spec's own number. A bullet that starts like an
  ID in any other form (`*`, bold, nested, without the prefix) is a problem, so it can't go unseen.
- SPC-REQ-001-05: An ID MUST be unique across the folder.
- SPC-REQ-001-06: A bullet's text MAY continue on the lines straight after it that start with two
  or more spaces. A blank line, or a line starting with less than two spaces or with a tab, ends
  it. The bullet MUST be read as one text, its lines trimmed and joined with one space.
- SPC-REQ-001-07: A requirement whose text ends with `(unimplemented: <reason>)`, with or without a
  full stop before or after it, MUST be unimplemented, and its reason is the text after the colon,
  trimmed. Its text without the suffix MUST be what comes before the suffix, trimmed.
  `(unimplemented)` or an empty reason MUST be a problem that says a reason is required. The
  suffix anywhere other than the end of the text MUST NOT count.
- SPC-REQ-001-08: Lines inside fenced code blocks MUST NOT be read as requirements or headers.
- SPC-REQ-001-09: A spec's `tests:` line and an index's `id-prefix:` line from the old checker MUST
  be reported, saying where the setting lives now.
- SPC-REQ-001-10: Two texts MUST count as the same text when they are equal after removing the
  unimplemented suffix (SPC-REQ-001-07), collapsing each run of whitespace to one space, trimming
  the ends, ignoring case, and dropping one trailing full stop and any whitespace before it. Two
  requirements in the folder MUST NOT have the same text. Each requirement whose text an earlier
  one in the folder (in spec and line order) already has MUST be a problem at its own line that
  names its ID and the first one's ID and line.
