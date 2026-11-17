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

import { useEffect, useId, useRef } from "react";
import { Button } from "@/components/ui/Button";

interface SwitchToRunDialogProps {
  open: boolean;
  /** What would be dropped, e.g. "1 node added, 2 wires changed". */
  changes: string;
  /** Keep editing, Escape or a click on the backdrop: stay changing the template. */
  onCancel: () => void;
  onSaveFirst: () => void;
  onDiscard: () => void;
}

/**
 * The confirm before switching from the template to this run with unsaved
 * structural changes (Figma PPLT-409 D.2d), since a run can only change step
 * settings and would drop them.
 *
 * A native modal <dialog>, as in the admin screens, so the browser traps
 * focus, puts the backdrop over the Builder and closes it on Escape.
 */
export function SwitchToRunDialog({ open, changes, onCancel, onSaveFirst, onDiscard }: SwitchToRunDialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const bodyId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className="modal"
      aria-labelledby={titleId}
      aria-describedby={bodyId}
      // Escape: the browser closes the dialog, so tell the owner
      onCancel={onCancel}
    >
      <div className="modal-box max-w-md border border-base-content/10 bg-base-200">
        <h2 id={titleId} className="m-0 text-base font-semibold">
          Switch to changing this run?
        </h2>
        <p id={bodyId} className="mt-3 mb-0 text-xs leading-relaxed text-base-content/70">
          You have unsaved structural changes to the template ({changes}). A run can only change step settings, so
          these changes would be dropped.
        </p>
        <div className="modal-action mt-5 flex-wrap justify-start gap-2">
          <Button label="Keep editing" size="sm" variant="ghost" onClick={onCancel} />
          <Button label="Save template first" size="sm" onClick={onSaveFirst} />
          <Button label="Discard and switch" size="sm" variant="error" soft onClick={onDiscard} />
        </div>
      </div>
      {/* A click on the backdrop keeps editing, as in the admin dialogs. The
          submit closes the dialog, which fires close, not cancel, so the
          button tells the owner itself. */}
      <form method="dialog" className="modal-backdrop">
        <button onClick={onCancel}>close</button>
      </form>
    </dialog>
  );
}
