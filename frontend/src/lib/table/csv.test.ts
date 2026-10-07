import assert from "node:assert/strict";
import test from "node:test";

import {
  compareCells,
  delimiterFor,
  detectDelimiter,
  isNumeric,
  numericColumns,
  parseDelimited,
  sortRows,
} from "./csv.ts";

test("parses a simple file", () => {
  const t = parseDelimited("a,b,c\n1,2,3\n4,5,6\n");
  assert.deepEqual(t.header, ["a", "b", "c"]);
  assert.deepEqual(t.rows, [
    ["1", "2", "3"],
    ["4", "5", "6"],
  ]);
  assert.equal(t.delimiter, ",");
});

test("quoted fields keep delimiters, line breaks and escaped quotes", () => {
  const t = parseDelimited('name,note\n"Smith, J","said ""hi""\nthen left"\n');
  assert.deepEqual(t.rows, [["Smith, J", 'said "hi"\nthen left']]);
});

test("handles CRLF, CR, a BOM and a missing trailing newline", () => {
  assert.deepEqual(parseDelimited("a,b\r\n1,2\r\n3,4").rows, [
    ["1", "2"],
    ["3", "4"],
  ]);
  assert.deepEqual(parseDelimited("a,b\r1,2\r3,4\r").rows.length, 2);
  const t = parseDelimited("﻿a,b\n1,2\n");
  assert.deepEqual(t.header, ["a", "b"]);
});

test("blank lines are dropped but empty fields are kept", () => {
  const t = parseDelimited("a,b,c\n\n1,,3\n\n,,\n");
  assert.deepEqual(t.rows, [
    ["1", "", "3"],
    ["", "", ""],
  ]);
});

test("a quoted empty field is a record, not a blank line", () => {
  assert.deepEqual(parseDelimited('a\n""\n').rows, [[""]]);
});

test("ragged rows are padded or truncated to the header width", () => {
  const t = parseDelimited("a,b,c\n1\n1,2,3,4,5\n");
  assert.deepEqual(t.rows, [
    ["1", "", ""],
    ["1", "2", "3"],
  ]);
});

test("empty and header-only input", () => {
  assert.deepEqual(parseDelimited(""), { header: [], rows: [], delimiter: "," });
  assert.deepEqual(parseDelimited("\n\n").rows, []);
  const t = parseDelimited("a,b\n");
  assert.deepEqual(t.header, ["a", "b"]);
  assert.deepEqual(t.rows, []);
});

test("detects tab and semicolon delimiters, ignoring quoted ones", () => {
  assert.equal(detectDelimiter("a\tb\tc\n1\t2\t3"), "\t");
  assert.equal(detectDelimiter("a;b;c\n1;2;3"), ";");
  assert.equal(detectDelimiter('"a,b,c";d\n1;2'), ";");
  assert.equal(detectDelimiter("single\nvalue"), ",");
  assert.equal(parseDelimited("a;b\n1;2").delimiter, ";");
  assert.deepEqual(parseDelimited("a\tb\n1\t2").rows, [["1", "2"]]);
});

test("an explicit delimiter overrides detection", () => {
  assert.deepEqual(parseDelimited("a,b\tc\n1,2\t3", "\t").header, ["a,b", "c"]);
});

test("delimiterFor knows TSV by name or MIME only", () => {
  assert.equal(delimiterFor("data.tsv", null), "\t");
  assert.equal(delimiterFor("DATA.TSV", undefined), "\t");
  assert.equal(delimiterFor("sample", "text/tab-separated-values; charset=utf-8"), "\t");
  assert.equal(delimiterFor("data.csv", "text/csv"), undefined);
  assert.equal(delimiterFor(null, null), undefined);
});

test("isNumeric accepts plain decimals and scientific notation only", () => {
  for (const ok of ["0", "-1", "+2.5", ".5", "5.", "1.2e-3", "1E6", " 42 "]) {
    assert.equal(isNumeric(ok), true, ok);
  }
  for (const bad of ["", "abc", "0x1F", "Infinity", "NaN", "1,000", "1e", "--1"]) {
    assert.equal(isNumeric(bad), false, bad);
  }
});

test("compareCells orders numbers by value, before text, and text naturally", () => {
  assert.ok(compareCells("2", "10") < 0);
  assert.ok(compareCells("1.2e-3", "0.01") < 0);
  assert.ok(compareCells("5", "abc") < 0);
  assert.ok(compareCells("abc", "5") > 0);
  assert.ok(compareCells("item2", "item10") < 0);
  assert.equal(compareCells("7", "7.0"), 0);
});

test("sortRows sorts both ways, keeps empties last and is stable", () => {
  const rows = [
    ["b", "10"],
    ["a", ""],
    ["c", "2"],
    ["d", "10"],
  ];
  assert.deepEqual(
    sortRows(rows, 1, "asc").map((r) => r[0]),
    ["c", "b", "d", "a"],
  );
  assert.deepEqual(
    sortRows(rows, 1, "desc").map((r) => r[0]),
    ["b", "d", "c", "a"],
  );
  assert.deepEqual(
    sortRows(rows, 0, "desc").map((r) => r[0]),
    ["d", "c", "b", "a"],
  );
  // The input is not mutated.
  assert.deepEqual(rows[0], ["b", "10"]);
});

test("numericColumns needs at least one value and no text", () => {
  const header = ["id", "label", "empty", "mixed"];
  const rows = [
    ["1", "x", "", "1"],
    ["2.5", "y", "", "oops"],
    ["", "", "", "3"],
  ];
  assert.deepEqual(numericColumns(header, rows), [true, false, false, false]);
});
