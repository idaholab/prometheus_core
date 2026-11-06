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

import assert from "node:assert/strict";
import { test } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ArtifactLinks } from "./ArtifactLinks.tsx";

const html = (links: { label: string; url: string }[] | undefined) =>
  renderToStaticMarkup(createElement(ArtifactLinks, { links }));

test("each link is a new-tab button with no opener", () => {
  const out = html([{ label: "Open interactive dashboard", url: "https://agent.example/console/7" }]);
  assert.match(out, /href="https:\/\/agent\.example\/console\/7"/);
  assert.match(out, /target="_blank"/);
  assert.match(out, /rel="noopener noreferrer"/);
  assert.match(out, />Open interactive dashboard</);
});

test("non-web URLs and empty labels are not rendered", () => {
  const out = html([
    { label: "bad", url: "javascript:alert(1)" },
    { label: "relative", url: "/console/7" },
    { label: "", url: "https://agent.example/x" },
  ]);
  assert.equal(out, "");
  assert.equal(html(undefined), "");
});
