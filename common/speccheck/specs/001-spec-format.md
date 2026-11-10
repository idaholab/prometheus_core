# 001 - Spec format

## Purpose

A spec folder is plain markdown that people review. `lint` makes sure every requirement in it can
be found, has one ID, and says whether it is implemented yet.

## Requirements

- SPC-REQ-001-01: A spec file MUST be named `NNN-short-name.md`, and its first line MUST be its
  title, `# NNN - Name`. Any other `.md` file in the folder is a problem.
- SPC-REQ-001-02: When the config requires an index, `000-index.md` MUST exist and MUST link every
  spec as a markdown link. Mentioning a spec's number or name in prose is not enough.
- SPC-REQ-001-03: A spec MUST have at least one requirement. A spec with none MUST be a problem
  that says to delete it and list its number in the index's `removed:` line (SPC-REQ-001-11).
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
- SPC-REQ-001-09: Two texts MUST count as the same text when they are equal after removing the
  unimplemented suffix (SPC-REQ-001-07), collapsing each run of whitespace to one space, trimming
  the ends, ignoring case, and dropping one trailing full stop and any whitespace before it. Two
  requirements in the folder MUST NOT have the same text. Each requirement whose text an earlier
  one in the folder (in spec and line order) already has MUST be a problem at its own line that
  names its ID and the first one's ID and line.
- SPC-REQ-001-10: A spec MAY have one `removed:` line above its first `##` section, listing the
  IDs removed from it, separated by commas (an empty item is ignored), and it MAY wrap as a bullet
  does (SPC-REQ-001-06). A second `removed:` line MUST be a problem. Each listed ID MUST be well
  formed with the spec's own number, MUST be listed once, and MUST NOT be a requirement in any
  spec of the folder.
- SPC-REQ-001-11: `000-index.md` MAY have one `removed:` line above its first `##` section,
  listing the numbers of the specs removed from the folder, written and checked as SPC-REQ-001-10
  says. Each number MUST be three digits other than `000` and listed once. A spec file with a
  listed number MUST be a problem, and MUST NOT be read.
