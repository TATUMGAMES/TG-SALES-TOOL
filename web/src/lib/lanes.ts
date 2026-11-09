/*
 * Copyright 2013-present Tatum Games, LLC.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy
 * of the License at: https://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
 * WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 */

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { api } from "./api";
import type { LaneView } from "./api-types";

/** Fallback color when a lane has none; colors are always shown next to the lane name. */
export const DEFAULT_LANE_COLOR = "var(--brand-purple)";

/** Readable name for a lane key that has no lane (e.g. a colleague's lane not synced yet). */
export function labelForKey(key: string): string {
  const text = key.replace(/_/g, " ").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : "Unknown lane";
}

export interface Lanes {
  /** Every lane, including archived ones, in display order. */
  all: LaneView[];
  /** Lanes that can be chosen for new opportunities and stages. */
  active: LaneView[];
  label: (key: string | null | undefined) => string;
  color: (key: string | null | undefined) => string;
  get: (key: string | null | undefined) => LaneView | undefined;
  loading: boolean;
}

/** The configured sales lanes (Settings > Sales lanes), shared by every page. */
export function useLanes(): Lanes {
  const query = useQuery({ queryKey: ["lanes"], queryFn: () => api.get<LaneView[]>("/lanes", { include_archived: true }), staleTime: 60_000 });
  return useMemo(() => {
    const all = query.data ?? [];
    const byKey = new Map(all.map((lane) => [lane.key, lane]));
    return {
      all,
      active: all.filter((lane) => !lane.archived),
      label: (key) => (key ? byKey.get(key)?.name ?? labelForKey(key) : "All lanes"),
      color: (key) => (key ? byKey.get(key)?.color ?? DEFAULT_LANE_COLOR : DEFAULT_LANE_COLOR),
      get: (key) => (key ? byKey.get(key) : undefined),
      loading: query.isLoading,
    };
  }, [query.data, query.isLoading]);
}
