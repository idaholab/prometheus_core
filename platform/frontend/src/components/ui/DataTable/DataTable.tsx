// This file is part of Prometheus
// https://inl.gov/super-intelligence/prometheus/
//
// Copyright 2026 Battelle Energy Alliance, LLC
// All rights reserved, see NOTICE.txt for full restrictions
// https://github.com/idaholab/prometheus_core/blob/main/NOTICE.txt
//
// Licensed under the MIT License, please see LICENSE for details
// https://github.com/idaholab/prometheus_core/blob/main/LICENSE
//
// SPDX-License-Identifier: MIT

import { useMemo, useState, type ReactNode } from "react";
import {
  columnFilteringFeature,
  createFilteredRowModel,
  createSortedRowModel,
  filterFn_includesString,
  flexRender,
  globalFilteringFeature,
  rowSortingFeature,
  sortFn_alphanumeric,
  sortFn_datetime,
  sortFn_text,
  tableFeatures,
  useTable,
  type ColumnDef,
  type ColumnFiltersState,
  type RowData,
  type SortingState,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";

/* Figma F.1. The header is sticky and opaque so rows scroll under it when
 * `maxHeight` is set. Cells don't wrap: a table too wide for its container
 * scrolls sideways inside the card instead of squashing its columns. */
const TH_CLASSES =
  "sticky top-0 z-[1] h-10 whitespace-nowrap border-b border-base-content/10 bg-base-100 px-5 text-[10px] font-medium uppercase tracking-[0.06em] text-base-content/60";
const TR_CLASSES = "border-b border-base-content/10 last:border-b-0 hover:bg-base-content/[0.03]";
const TD_CLASSES = "h-12 whitespace-nowrap px-5 text-[13px] text-base-content/70";

export type CellValue = string | number | null | undefined;

/* TanStack Table 9 only bundles the features a table registers. Sorting picks
 * a sort function from the column's values, as v8 did by default, so the ones
 * it can pick are registered here. */
const features = tableFeatures({
  columnFilteringFeature,
  globalFilteringFeature,
  rowSortingFeature,
  filteredRowModel: createFilteredRowModel(),
  sortedRowModel: createSortedRowModel(),
  filterFns: { includesString: filterFn_includesString },
  sortFns: { alphanumeric: sortFn_alphanumeric, text: sortFn_text, datetime: sortFn_datetime },
});

export interface DataTableColumn<T> {
  /** Unique per table; also the key for `columnFilters` and `defaultSort`. */
  id: string;
  /** Header text. Omit for an unlabelled column such as row actions. */
  header?: string;
  /**
   * The cell's plain value, used for sorting, search and `columnFilters`, and
   * drawn as text when there is no `cell`. Columns without one can't be sorted,
   * searched or filtered.
   */
  value?: (row: T) => CellValue;
  /** Custom cell content (badges, links, buttons). */
  cell?: (row: T) => ReactNode;
  sortable?: boolean;
  align?: "left" | "right";
  /** Classes for this column's cells, e.g. `font-semibold text-base-content` for F.1's name column. */
  className?: string;
}

interface DataTableProps<T> {
  data: T[];
  columns: DataTableColumn<T>[];
  /** Stable row key; defaults to the row index. */
  rowId?: (row: T) => string;
  /** Case-insensitive search across every column with a `value`, e.g. from a SearchInput. */
  search?: string;
  /**
   * Exact-match filters by column id, e.g. from a role dropdown or FilterChips.
   * An undefined or empty value means no filter on that column ("All").
   */
  columnFilters?: Record<string, string | undefined>;
  defaultSort?: { id: string; desc?: boolean };
  /** Shown when `data` is empty. */
  empty?: ReactNode;
  /** Shown when rows exist but search or filters hide them all. */
  noMatches?: ReactNode;
  /** Caps the height (any CSS length); the body scrolls under a sticky header. */
  maxHeight?: string;
  /** Accessible name for the table. */
  label?: string;
}

/**
 * App-wide data table styled after Figma F.1, with sorting and filtering from
 * TanStack Table (headless, so the markup and look are ours). Search and filter
 * controls live outside the table; pass their values in as `search` and
 * `columnFilters`.
 */
export function DataTable<T extends RowData>({
  data,
  columns,
  rowId,
  search = "",
  columnFilters,
  defaultSort,
  empty = "No rows yet.",
  noMatches = "No matching rows.",
  maxHeight,
  label,
}: DataTableProps<T>) {
  const [sorting, setSorting] = useState<SortingState>(defaultSort ? [{ id: defaultSort.id, desc: !!defaultSort.desc }] : []);

  const columnDefs = useMemo<ColumnDef<typeof features, T>[]>(
    () =>
      columns.map((col) => ({
        id: col.id,
        header: col.header ?? "",
        // TanStack only puts undefined last when sorting, so null becomes undefined.
        accessorFn: col.value ? (row: T) => col.value!(row) ?? undefined : undefined,
        cell: ({ row }) => (col.cell ? col.cell(row.original) : (col.value?.(row.original) ?? "")),
        enableSorting: !!col.sortable && !!col.value,
        enableGlobalFilter: !!col.value,
        enableColumnFilter: !!col.value,
        filterFn: (row, columnId, wanted: string) => String(row.getValue(columnId) ?? "") === wanted,
        sortUndefined: "last",
        meta: col,
      })),
    [columns],
  );

  const filters = useMemo<ColumnFiltersState>(
    () =>
      Object.entries(columnFilters ?? {})
        .filter(([, value]) => value)
        .map(([id, value]) => ({ id, value })),
    [columnFilters],
  );

  const table = useTable({
    features,
    data,
    columns: columnDefs,
    state: { sorting, globalFilter: search.trim(), columnFilters: filters },
    onSortingChange: setSorting,
    getRowId: rowId ? (row) => rowId(row) : undefined,
    globalFilterFn: "includesString",
  });

  const rows = table.getRowModel().rows;
  const columnOf = (meta: unknown) => meta as DataTableColumn<T>;

  return (
    // min-w-0 lets the card shrink inside a flex or grid parent, so a wide table
    // scrolls here rather than widening the page.
    <div className="w-full min-w-0 overflow-hidden rounded-lg border border-base-content/10 bg-base-100">
      <div className="overflow-auto" style={maxHeight ? { maxHeight } : undefined}>
        <table className="w-full border-collapse text-left" aria-label={label}>
          <thead>
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id}>
                {group.headers.map((header) => {
                  const col = columnOf(header.column.columnDef.meta);
                  const sorted = header.column.getIsSorted();
                  const right = col.align === "right";
                  return (
                    <th
                      key={header.id}
                      className={`${TH_CLASSES}${right ? " text-right" : ""}`}
                      aria-sort={sorted ? (sorted === "asc" ? "ascending" : "descending") : undefined}
                    >
                      {header.column.getCanSort() ? (
                        <button
                          type="button"
                          className={`inline-flex items-center gap-1 uppercase hover:text-base-content${right ? " flex-row-reverse" : ""}`}
                          onClick={header.column.getToggleSortingHandler()}
                        >
                          {col.header}
                          {sorted === "asc" ? (
                            <ArrowUp size={10} aria-hidden />
                          ) : sorted === "desc" ? (
                            <ArrowDown size={10} aria-hidden />
                          ) : (
                            <ArrowUpDown size={10} className="opacity-40" aria-hidden />
                          )}
                        </button>
                      ) : (
                        col.header
                      )}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} className={TR_CLASSES}>
                {row.getAllCells().map((cell) => {
                  const col = columnOf(cell.column.columnDef.meta);
                  const classes = [TD_CLASSES, col.align === "right" && "text-right", col.className]
                    .filter(Boolean)
                    .join(" ");
                  return (
                    <td key={cell.id} className={classes}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {/* Outside the scroller, so it centres in the card rather than across a
          table that may be wider than the screen. */}
      {rows.length === 0 && (
        <p className="m-0 px-5 py-8 text-center text-xs text-base-content/50">{data.length === 0 ? empty : noMatches}</p>
      )}
    </div>
  );
}
