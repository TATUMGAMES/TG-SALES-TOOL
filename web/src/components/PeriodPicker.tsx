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
import { Field, Input, NativeSelect } from "@/components/ui/form";
import { api } from "@/lib/api";
import type { PeriodPreset, PeriodView } from "@/lib/api-types";

export interface PeriodValue {
  preset: PeriodPreset;
  start: string;
  end: string;
}

const ORDER: PeriodPreset[] = ["7d", "30d", "1m", "3m", "6m", "12m", "prev_month", "prev_quarter", "prev_year", "custom"];

/** Period presets (with their exact dates) plus a custom range. */
export function PeriodPicker({ value, onChange }: { value: PeriodValue; onChange: (value: PeriodValue) => void; idPrefix?: string }) {
  const periods = useQuery({ queryKey: ["periods"], queryFn: () => api.get<PeriodView[]>("/periods"), staleTime: 60_000 });
  const byPreset = new Map((periods.data ?? []).map((p) => [p.preset, p]));
  const current = byPreset.get(value.preset);
  return (
    <div className="flex flex-wrap items-end gap-2">
      <Field label="Period" className="min-w-48">
        {(p) => (
          <NativeSelect
            {...p}
            value={value.preset}
            onChange={(e) => {
              const preset = e.target.value as PeriodPreset;
              const found = byPreset.get(preset);
              onChange({ preset, start: found?.start ?? value.start, end: found?.end ?? value.end });
            }}
          >
            {ORDER.map((preset) => (
              <option key={preset} value={preset}>
                {preset === "custom" ? "Custom range" : byPreset.get(preset)?.label ?? preset}
              </option>
            ))}
          </NativeSelect>
        )}
      </Field>
      {value.preset === "custom" ? (
        <>
          <Field label="From">{(p) => <Input {...p} type="date" value={value.start} max={value.end || undefined} onChange={(e) => onChange({ ...value, start: e.target.value })} />}</Field>
          <Field label="To">{(p) => <Input {...p} type="date" value={value.end} min={value.start || undefined} onChange={(e) => onChange({ ...value, end: e.target.value })} />}</Field>
        </>
      ) : current ? (
        <p className="pb-2.5 text-xs text-muted-foreground">{current.description}</p>
      ) : null}
    </div>
  );
}
