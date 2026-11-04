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
import App from "./App";
import "./index.css";

const root = ReactDOM.createRoot(document.getElementById("root")!);

// Dev-only review pages, opened with ?harness=<name>. The import() sits behind
// import.meta.env.DEV, so production builds drop it and the page with it.
const harness = import.meta.env.DEV ? new URLSearchParams(window.location.search).get("harness") : null;
if (harness === "builder-states") {
  const { BuilderStatesHarness } = await import("./dev/BuilderStatesHarness");
  root.render(<BuilderStatesHarness />);
} else {
  root.render(<App />);
}
