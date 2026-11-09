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
import { Archive, ArchiveRestore, Plus, Save } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardHeader } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, NativeSelect, Textarea } from "@/components/ui/form";
import { ErrorState, LoadingRows } from "@/components/ui/misc";
import { api } from "@/lib/api";
import type { CustomFieldMeta, CustomFieldView } from "@/lib/api-types";
import { useAction } from "@/lib/hooks";

export const CUSTOM_FIELD_QUERIES = [["custom-fields"], ["import-fields"], ["prospect"], ["prospects"]];

export function useCustomFieldMeta() {
  return useQuery({ queryKey: ["custom-field-meta"], queryFn: () => api.get<CustomFieldMeta>("/custom-fields/meta"), staleTime: Infinity });
}

/** Create a custom field; also used from the import wizard ("+ Create custom field"). */
export function CustomFieldDialog({
  open,
  onOpenChange,
  initialLabel = "",
  existing,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialLabel?: string;
  existing?: CustomFieldView | undefined;
  onCreated?: (field: CustomFieldView) => void;
}) {
  const meta = useCustomFieldMeta();
  const [label, setLabel] = useState(initialLabel);
  const [fieldType, setFieldType] = useState("text");
  const [recordType, setRecordType] = useState("prospect");
  const [description, setDescription] = useState("");
  useEffect(() => {
    if (!open) return;
    setLabel(existing?.label ?? initialLabel);
    setFieldType(existing?.field_type ?? "text");
    setRecordType(existing?.record_type ?? "prospect");
    setDescription(existing?.description ?? "");
  }, [open, existing, initialLabel]);
  const save = useAction(
    () =>
      existing
        ? api.put<CustomFieldView>(`/custom-fields/${existing.id}`, { label, description: description || null })
        : api.post<CustomFieldView>("/custom-fields", { label, field_type: fieldType, record_type: recordType, description: description || null }),
    { invalidate: CUSTOM_FIELD_QUERIES, success: existing ? "Custom field saved" : "Custom field created" },
  );
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={existing ? `Edit ${existing.label}` : "Create a custom field"}
      description="For information the standard fields do not cover, such as “Account tier” or “Partnership category”. Custom fields can be filled in on records, imported and exported."
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button
            loading={save.isPending}
            disabled={!label.trim()}
            onClick={() =>
              save.mutate(undefined, {
                onSuccess: (field) => {
                  onCreated?.(field);
                  onOpenChange(false);
                },
              })
            }
          >
            <Save /> {existing ? "Save" : "Create field"}
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Field name" required className="sm:col-span-2">
          {(p) => <Input {...p} autoFocus value={label} maxLength={80} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. Account tier" />}
        </Field>
        <Field label="Type" hint={existing ? "The type cannot change after the field is created." : "Values are checked against the type."}>
          {(p) => (
            <NativeSelect {...p} value={fieldType} disabled={Boolean(existing)} onChange={(e) => setFieldType(e.target.value)}>
              {(meta.data?.field_types ?? []).map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
            </NativeSelect>
          )}
        </Field>
        <Field label="Belongs to">
          {(p) => (
            <NativeSelect {...p} value={recordType} disabled={Boolean(existing)} onChange={(e) => setRecordType(e.target.value)}>
              {(meta.data?.record_types ?? []).map((t) => <option key={t.value} value={t.value}>{t.label}s</option>)}
            </NativeSelect>
          )}
        </Field>
        <Field label="Description" className="sm:col-span-2">
          {(p) => <Textarea {...p} rows={2} maxLength={500} value={description} onChange={(e) => setDescription(e.target.value)} />}
        </Field>
      </div>
    </Dialog>
  );
}

export function CustomFieldsPanel() {
  const fields = useQuery({ queryKey: ["custom-fields", "all"], queryFn: () => api.get<CustomFieldView[]>("/custom-fields", { include_archived: true }) });
  const meta = useCustomFieldMeta();
  const [editing, setEditing] = useState<{ field?: CustomFieldView } | null>(null);
  const archive = useAction((vars: { id: string; archived: boolean }) => api.post(`/custom-fields/${vars.id}/archive`, { archived: vars.archived }), {
    invalidate: CUSTOM_FIELD_QUERIES,
    success: "Saved",
  });
  const typeLabel = (value: string) => meta.data?.field_types.find((t) => t.value === value)?.label ?? value;

  if (fields.error) return <ErrorState error={fields.error} onRetry={() => fields.refetch()} />;
  if (!fields.data) return <LoadingRows />;
  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title="Custom fields"
          description="Extra fields for prospects and contacts. They appear on the record, in the import column choices and in prospect exports. Archived fields are hidden but keep their values."
          actions={<Button onClick={() => setEditing({})}><Plus /> Create custom field</Button>}
        />
        {fields.data.length === 0 ? <p className="p-5 text-sm text-muted-foreground">No custom fields yet.</p> : null}
        <ul className="divide-y">
          {fields.data.map((field) => (
            <li key={field.id} className="flex flex-wrap items-center gap-3 px-5 py-3">
              <div className="min-w-48 flex-1">
                <p className="font-medium">{field.label} {field.archived ? <Badge>Archived</Badge> : null}</p>
                <p className="text-xs text-muted-foreground">
                  {field.record_type === "contact" ? "Contacts" : "Prospects"} · {typeLabel(field.field_type)}
                  {field.description ? ` · ${field.description}` : ""}
                </p>
              </div>
              <Button variant="outline" size="sm" onClick={() => setEditing({ field })}>Edit</Button>
              <Button variant="ghost" size="sm" onClick={() => archive.mutate({ id: field.id, archived: !field.archived })}>
                {field.archived ? <><ArchiveRestore /> Restore</> : <><Archive /> Archive</>}
              </Button>
            </li>
          ))}
        </ul>
      </Card>
      <CustomFieldDialog open={editing !== null} existing={editing?.field} onOpenChange={(open) => !open && setEditing(null)} />
    </div>
  );
}
