/**
 * Placeholder for sidebar destinations that exist in the nav but aren't
 * scoped/built yet (Workflows, Approval Queue, Project Management, Data
 * Management, Jobs Console). Mirrors the old per-tab "coming soon" stubs.
 */
export function ComingSoon({ label }: { label: string }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-2 text-center">
      <p className="m-0 text-lg font-semibold text-base-content">{label}</p>
      <p className="m-0 text-sm text-base-content/50">Coming soon</p>
    </div>
  );
}
