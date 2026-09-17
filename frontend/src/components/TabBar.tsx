import type { ReactNode } from "react";

export interface TabItem<T extends string = string> {
  id: T;
  label: string;
  icon?: ReactNode;
}

interface Props<T extends string> {
  tabs: TabItem<T>[];
  active: T;
  onChange: (id: T) => void;
  className?: string;
}

/**
 * Segmented pill tab bar. Extracted verbatim from the pattern that used to
 * be the app's primary navigation in ProjectView; kept as a reusable
 * component for section sub-navigation (e.g. inside the Admin page).
 * Not currently mounted at the top level.
 */
export function TabBar<T extends string>({ tabs, active, onChange, className = "" }: Props<T>) {
  return (
    <div className={`inline-flex items-center gap-1 rounded-xl bg-base-200 p-1 ${className}`}>
      {tabs.map((tab) => {
        const isActive = active === tab.id;
        return (
          <button
            key={tab.id}
            onClick={() => onChange(tab.id)}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-all duration-150 cursor-pointer ${
              isActive
                ? "bg-primary text-primary-content shadow-sm"
                : "text-base-content/60 hover:bg-base-300 hover:text-base-content"
            }`}
          >
            {tab.icon}
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
