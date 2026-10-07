/**
 * Delimited-text (CSV / TSV) parsing and sorting for the table viewer
 * (`viewers/TableElement.tsx`). Pure functions with no imports, so they are unit-tested
 * directly with `node --test`.
 *
 * Parsing follows RFC 4180: fields may be quoted, `""` inside a quoted field is a literal
 * quote, and quoted fields may contain delimiters and line breaks. It is also lenient the
 * way real-world files need: CRLF / LF / CR line endings, a leading BOM, a missing
 * trailing newline, blank lines, and ragged rows.
 */

export interface ParsedTable {
  header: string[];
  rows: string[][];
  /** The delimiter that was used (given or detected). */
  delimiter: string;
}

const CANDIDATE_DELIMITERS = [",", "\t", ";"] as const;

/**
 * Delimiter for a file name / MIME type when it is unambiguous (TSV), else `undefined`
 * so the caller falls back to detection from the content.
 */
export function delimiterFor(
  name: string | null | undefined,
  mimeType: string | null | undefined,
): string | undefined {
  const mime = (mimeType ?? "").split(";", 1)[0].trim().toLowerCase();
  if (mime === "text/tab-separated-values") return "\t";
  if (name && name.toLowerCase().endsWith(".tsv")) return "\t";
  return undefined;
}

function stripBom(text: string): string {
  return text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
}

/**
 * Pick the delimiter from the first record: whichever of `,` / tab / `;` occurs most
 * outside quotes. Ties go to the earlier candidate; no candidate at all gives `,`.
 */
export function detectDelimiter(text: string): string {
  const counts = new Map<string, number>(CANDIDATE_DELIMITERS.map((d) => [d, 0]));
  let inQuotes = false;
  for (const ch of stripBom(text)) {
    if (ch === '"') {
      inQuotes = !inQuotes;
    } else if (!inQuotes) {
      if (ch === "\n" || ch === "\r") break;
      if (counts.has(ch)) counts.set(ch, (counts.get(ch) ?? 0) + 1);
    }
  }
  let best: string = ",";
  let bestCount = 0;
  for (const d of CANDIDATE_DELIMITERS) {
    const count = counts.get(d) ?? 0;
    if (count > bestCount) {
      best = d;
      bestCount = count;
    }
  }
  return best;
}

/** Split `text` into records of raw fields. Blank lines are dropped. */
function splitRecords(text: string, delimiter: string): string[][] {
  const records: string[][] = [];
  let record: string[] = [];
  let field = "";
  let inQuotes = false;
  // True once the current record has any content (a field, a delimiter or a quote), so a
  // blank line can be told apart from a record whose only field is empty-but-quoted.
  let started = false;

  const endField = () => {
    record.push(field);
    field = "";
  };
  const endRecord = () => {
    if (started) {
      endField();
      records.push(record);
    }
    record = [];
    started = false;
  };

  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        field += ch;
      }
      continue;
    }
    if (ch === '"' && field === "") {
      inQuotes = true;
      started = true;
    } else if (ch === delimiter) {
      endField();
      started = true;
    } else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      endRecord();
    } else {
      field += ch;
      started = true;
    }
  }
  endRecord();
  return records;
}

/**
 * Parse delimited text. The first record is the header; every other record is padded or
 * truncated to the header's width. Empty input gives an empty header and no rows.
 */
export function parseDelimited(text: string, delimiter?: string): ParsedTable {
  const body = stripBom(text);
  const used = delimiter ?? detectDelimiter(body);
  const records = splitRecords(body, used);
  if (records.length === 0) return { header: [], rows: [], delimiter: used };
  const [header, ...rest] = records;
  const width = header.length;
  const rows = rest.map((row) => {
    if (row.length === width) return row;
    if (row.length > width) return row.slice(0, width);
    return [...row, ...new Array<string>(width - row.length).fill("")];
  });
  return { header, rows, delimiter: used };
}

const NUMBER_PATTERN = /^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/;

/** Whether a cell is a plain decimal number (including `1.5e-3`); not hex or `Infinity`. */
export function isNumeric(cell: string): boolean {
  return NUMBER_PATTERN.test(cell.trim());
}

/**
 * Ascending order for two non-empty cells: numbers by value, and before any text; text
 * with `localeCompare` in numeric mode (so `item2` < `item10`).
 */
export function compareCells(a: string, b: string): number {
  const aNum = isNumeric(a);
  const bNum = isNumeric(b);
  if (aNum && bNum) return Number(a) - Number(b);
  if (aNum) return -1;
  if (bNum) return 1;
  return a.localeCompare(b, undefined, { numeric: true });
}

/**
 * Rows sorted by one column (a stable sort that returns a new array). Empty cells stay
 * last in both directions.
 */
export function sortRows(rows: string[][], column: number, direction: "asc" | "desc"): string[][] {
  const sign = direction === "asc" ? 1 : -1;
  return rows
    .map((row, index) => ({ row, index }))
    .sort((x, y) => {
      const a = x.row[column] ?? "";
      const b = y.row[column] ?? "";
      if (a === "" || b === "") {
        if (a === b) return x.index - y.index;
        return a === "" ? 1 : -1;
      }
      return sign * compareCells(a, b) || x.index - y.index;
    })
    .map(({ row }) => row);
}

/** Per column: true when it has at least one value and every non-empty cell is numeric. */
export function numericColumns(header: string[], rows: string[][]): boolean[] {
  return header.map((_, column) => {
    let seen = false;
    for (const row of rows) {
      const cell = row[column] ?? "";
      if (cell === "") continue;
      if (!isNumeric(cell)) return false;
      seen = true;
    }
    return seen;
  });
}
