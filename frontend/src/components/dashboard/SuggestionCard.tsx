import type { ReactNode } from "react";

interface Props {
  icon: ReactNode;
  title: string;
  description: string;
  onClick?: () => void;
}

/**
 * A single action suggestion on the dashboard-home welcome panel:
 * an icon pill, a title, and a one-line description. DaisyUI `card`
 * rendered as a button so the whole card is the click target.
 */
export function SuggestionCard({ icon, title, description, onClick }: Props) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="card w-full bg-base-200 border border-base-300 text-left transition-colors hover:border-primary/40 hover:bg-base-300 cursor-pointer"
    >
      <div className="card-body gap-2.5 p-4">
        <div className="flex items-center gap-2.5">
          <span className="flex items-center justify-center rounded-md bg-primary/10 p-1.5 text-primary">
            {icon}
          </span>
          <span className="font-semibold text-base-content">{title}</span>
        </div>
        <p className="m-0 text-xs leading-snug text-base-content/60">{description}</p>
      </div>
    </button>
  );
}
