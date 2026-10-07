/**
 * Pure MIME helpers shared by modules that must stay free of React and highlight.js
 * (so `node --test` can load them): `elements.ts`, `highlight/language.ts`, `table/csv.ts`.
 */

/** A MIME type without its parameters (`; charset=...`), trimmed and lowercased. */
export function normalizeMime(mime: string | null | undefined): string {
  return (mime ?? "").split(";", 1)[0].trim().toLowerCase();
}
