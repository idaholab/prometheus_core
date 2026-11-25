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

/**
 * The Redux store. It holds only RTK Query's cache for now: chat, the session
 * and the page header keep their own stores.
 * `createAppStore` makes a fresh store, so each test gets its own cache.
 */
import { configureStore } from "@reduxjs/toolkit";
import { baseApi } from "./baseApi";

export function createAppStore() {
  return configureStore({
    reducer: { [baseApi.reducerPath]: baseApi.reducer },
    middleware: (getDefault) => getDefault().concat(baseApi.middleware),
  });
}

export type AppStore = ReturnType<typeof createAppStore>;

/** The app's store. Route loaders reach it here to start a query before a page renders. */
export const appStore = createAppStore();
