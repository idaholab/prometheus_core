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

import { AdminOidcProviders } from "./AdminOidcProviders";
import { AdminSigningKeys } from "./AdminSigningKeys";
import { AdminUsers } from "./AdminUsers";

export type AdminSubTab = "users" | "signing-keys" | "identity-providers";

const SUB_TABS: { id: AdminSubTab; label: string }[] = [
  { id: "users", label: "Users" },
  { id: "signing-keys", label: "Signing Keys" },
  { id: "identity-providers", label: "Identity Providers" },
];

interface LayoutAdminProps {
  subTab: AdminSubTab;
  onSubTabChange: (subTab: AdminSubTab) => void;
}

/**
 * Admin layout: the sub-tab row, then the selected sub-tab's panel. PageAdmin
 * owns which sub-tab is showing.
 */
export function LayoutAdmin({ subTab, onSubTabChange }: LayoutAdminProps) {
  return (
    <div className="flex flex-col flex-1 overflow-hidden">
      <div className="px-4 pt-1">
        <div className="inline-flex items-center gap-1 border-b border-base-300">
          {SUB_TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => onSubTabChange(tab.id)}
              className={`px-3 py-2 text-sm font-medium border-b-2 transition-colors cursor-pointer ${
                subTab === tab.id
                  ? "border-primary text-base-content"
                  : "border-transparent text-base-content/50 hover:text-base-content"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>
      <div className="flex flex-1 overflow-hidden">
        {subTab === "users" && <AdminUsers />}
        {subTab === "signing-keys" && <AdminSigningKeys />}
        {subTab === "identity-providers" && <AdminOidcProviders />}
      </div>
    </div>
  );
}
