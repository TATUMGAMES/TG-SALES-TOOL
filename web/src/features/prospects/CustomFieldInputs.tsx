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

import { ExternalLink } from "lucide-react";
import { Field, Input, NativeSelect } from "@/components/ui/form";
import type { CustomValue } from "@/lib/api-types";
import { formatDate } from "@/lib/format";

/** Form values of custom fields as text, by key ("" = empty). */
export type CustomDraft = Record<string, string>;

export function draftFromValues(fields: CustomValue[], values: Record<string, unknown> = {}): CustomDraft {
  return Object.fromEntries(
    fields.map((f) => {
      const value = f.key in values ? values[f.key] : f.value;
      return [f.key, value === null || value === undefined ? "" : typeof value === "boolean" ? (value ? "yes" : "no") : String(value)];
    }),
  );
}

/** The changes to send: only fields whose text differs from the original (empty clears). */
export function changedValues(original: CustomDraft, draft: CustomDraft): Record<string, string | null> {
  return Object.fromEntries(
    Object.entries(draft)
      .filter(([key, value]) => (original[key] ?? "") !== value)
      .map(([key, value]) => [key, value.trim() === "" ? null : value]),
  );
}

export function CustomFieldInputs({ fields, draft, onChange }: { fields: CustomValue[]; draft: CustomDraft; onChange: (draft: CustomDraft) => void }) {
  if (!fields.length) return null;
  const set = (key: string, value: string) => onChange({ ...draft, [key]: value });
  return (
    <>
      {fields.map((f) => (
        <Field key={f.key} label={f.label}>
          {(p) =>
            f.field_type === "boolean" ? (
              <NativeSelect {...p} value={draft[f.key] ?? ""} onChange={(e) => set(f.key, e.target.value)}>
                <option value="">—</option>
                <option value="yes">Yes</option>
                <option value="no">No</option>
              </NativeSelect>
            ) : (
              <Input
                {...p}
                value={draft[f.key] ?? ""}
                onChange={(e) => set(f.key, e.target.value)}
                type={f.field_type === "date" ? "date" : f.field_type === "number" ? "number" : "text"}
                inputMode={f.field_type === "url" ? "url" : f.field_type === "number" ? "decimal" : undefined}
                placeholder={f.field_type === "url" ? "https://…" : undefined}
                step={f.field_type === "number" ? "any" : undefined}
              />
            )
          }
        </Field>
      ))}
    </>
  );
}

/** Read-only display of a custom value; URLs open safely in a new tab. */
export function CustomValueText({ field }: { field: CustomValue }) {
  const value = field.value;
  if (value === null || value === undefined || value === "") return <span className="text-muted-foreground">—</span>;
  if (field.field_type === "boolean") return <>{value ? "Yes" : "No"}</>;
  if (field.field_type === "date") return <>{formatDate(String(value))}</>;
  if (field.field_type === "url" && /^https?:\/\//i.test(String(value))) {
    return (
      <a href={String(value)} target="_blank" rel="noopener noreferrer nofollow" className="inline-flex max-w-full items-center gap-1 break-all text-primary hover:underline">
        {String(value)} <ExternalLink className="size-3 shrink-0" />
      </a>
    );
  }
  return <span className="whitespace-pre-wrap break-words">{String(value)}</span>;
}
