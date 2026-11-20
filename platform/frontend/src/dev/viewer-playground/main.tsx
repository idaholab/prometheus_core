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

import "@fontsource-variable/geist";
import "@fontsource-variable/roboto";
import ReactDOM from "react-dom/client";
import { installSampleFetch } from "./sampleFetch";
import type { ViewerCase } from "./viewerCase";
import { ViewerPlayground } from "./ViewerPlayground";
import "@/index.css";

// One module per cases/*.case.ts, shown in file-name order.
const modules = import.meta.glob<{ default: ViewerCase }>("./cases/*.case.ts", { eager: true });
const cases = Object.keys(modules)
  .sort()
  .map((file) => modules[file].default);

installSampleFetch(Object.assign({}, ...cases.map((c) => c.files)));

ReactDOM.createRoot(document.getElementById("root")!).render(<ViewerPlayground cases={cases} />);
