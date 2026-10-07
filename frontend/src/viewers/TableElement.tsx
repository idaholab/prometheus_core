/**
 * src/viewers/TableElement.tsx
 *
 * Renders a `table` artifact (render_hint === "table") — CSV / TSV — as a sortable table
 * with a toggle to the raw text. Like `CodeElement`, the body comes from the inline
 * `source` prop or is fetched from the content proxy (see `useArtifactText`), and the
 * card header (name, copy, download) matches it.
 *
 * Only the first MAX_TABLE_ROWS rows are drawn (the footer says so, and Download gives the
 * whole file); sorting still considers every row. Files over MAX_PARSE_CHARS are not
 * parsed at all and open as raw text, so a huge file can't freeze the page.
 */

import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, Table as TableIcon } from "lucide-react";
import type { ViewerProps } from "@/lib/elements/elements";
import { numericColumns, parseDelimited, sortRows } from "@/lib/table/csv";
import { ArtifactTextCard } from "./ArtifactTextCard";
import { useArtifactText } from "./useArtifactText";

interface TableProps {
  source?: string;
  title?: string;
  url?: string;
  /** Set for TSV; otherwise detected from the content. */
  delimiter?: string;
}

type Mode = "table" | "raw";
type SortState = { column: number; direction: "asc" | "desc" } | null;

export const MAX_TABLE_ROWS = 1000;
const MAX_PARSE_CHARS = 5_000_000;

const fmt = new Intl.NumberFormat("en-US");

export function TableElement({ element }: ViewerProps) {
  const { source = "", title, url = "", delimiter } = (element.props ?? {}) as TableProps;
  const name = title || element.name || "Table";

  const { text, loadState } = useArtifactText(source, url);
  const tooLarge = text.length > MAX_PARSE_CHARS;

  const [chosenMode, setMode] = useState<Mode>("table");
  const mode: Mode = tooLarge ? "raw" : chosenMode;
  const [sort, setSort] = useState<SortState>(null);

  const parsed = useMemo(
    () => (tooLarge || !text ? null : parseDelimited(text, delimiter)),
    [text, delimiter, tooLarge],
  );
  const numeric = useMemo(() => (parsed ? numericColumns(parsed.header, parsed.rows) : []), [parsed]);
  const sorted = useMemo(
    () => (parsed && sort ? sortRows(parsed.rows, sort.column, sort.direction) : parsed?.rows ?? []),
    [parsed, sort],
  );

  // none -> ascending -> descending -> none
  const cycleSort = (column: number) =>
    setSort((current) => {
      if (!current || current.column !== column) return { column, direction: "asc" };
      return current.direction === "asc" ? { column, direction: "desc" } : null;
    });

  const toggle = !tooLarge && (
    <div className="join" role="group" aria-label="View mode">
      {(["table", "raw"] as const).map((m) => (
        <button
          key={m}
          onClick={() => setMode(m)}
          className={`btn btn-xs join-item ${mode === m ? "btn-active" : ""}`}
          aria-pressed={mode === m}
        >
          {m === "table" ? "Table" : "Raw"}
        </button>
      ))}
    </div>
  );

  return (
    <ArtifactTextCard
      name={name}
      icon={TableIcon}
      url={url}
      text={text}
      loadState={loadState}
      badge={
        parsed && (
          <span className="badge badge-ghost badge-sm font-normal shrink-0">
            {fmt.format(parsed.rows.length)} rows × {parsed.header.length} cols
          </span>
        )
      }
      actions={toggle}
    >
      {tooLarge && (
        <div className="bg-base-100 px-4 py-2 text-xs text-base-content/60 border-b border-base-300">
          Too large to show as a table — showing the raw text. Download the file to open it elsewhere.
        </div>
      )}

      {mode === "raw" && (
        <pre className="m-0 overflow-auto max-h-96">
          <code className="block bg-base-100 px-4 py-3 whitespace-pre text-sm leading-5">{text}</code>
        </pre>
      )}

      {mode === "table" && parsed && (
        <>
          <div className="overflow-auto max-h-96 bg-base-100">
            <table className="table table-xs table-zebra table-pin-rows">
              <thead>
                <tr>
                  {parsed.header.map((label, column) => {
                    const active = sort?.column === column ? sort : null;
                    return (
                      <th
                        key={column}
                        aria-sort={
                          active ? (active.direction === "asc" ? "ascending" : "descending") : "none"
                        }
                        className={numeric[column] ? "text-right" : ""}
                      >
                        <button
                          onClick={() => cycleSort(column)}
                          className="inline-flex items-center gap-1 font-semibold whitespace-nowrap hover:text-primary"
                          title="Sort by this column"
                        >
                          {label || <span className="text-base-content/40">(blank)</span>}
                          {active && (active.direction === "asc" ? <ArrowUp size={11} /> : <ArrowDown size={11} />)}
                        </button>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {sorted.slice(0, MAX_TABLE_ROWS).map((row, r) => (
                  <tr key={r}>
                    {row.map((cell, c) => (
                      <td key={c} className={`whitespace-nowrap ${numeric[c] ? "text-right tabular-nums" : ""}`}>
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {parsed.rows.length === 0 && (
            <div className="bg-base-100 px-4 py-2 text-xs text-base-content/50 border-t border-base-300">
              No rows
            </div>
          )}
          {parsed.rows.length > MAX_TABLE_ROWS && (
            <div className="bg-base-100 px-4 py-2 text-xs text-base-content/60 border-t border-base-300">
              Showing {fmt.format(MAX_TABLE_ROWS)} of {fmt.format(parsed.rows.length)} rows — download for the full
              file.
            </div>
          )}
        </>
      )}
    </ArtifactTextCard>
  );
}

export default TableElement;
