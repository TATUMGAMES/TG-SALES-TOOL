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

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, NativeSelect, Textarea } from "@/components/ui/form";
import { ApiError, api } from "@/lib/api";
import type { Created, CustomFieldView, CustomValue, DuplicateCandidate, OrganizationDetail } from "@/lib/api-types";
import { showError } from "@/lib/hooks";
import { CONTACT_STATUS_LABELS, ORGANIZATION_TYPE_LABELS } from "@/lib/types";
import { changedValues, CustomFieldInputs, type CustomDraft, draftFromValues } from "./CustomFieldInputs";

const optional = z.string().trim().max(500).optional();

const schema = z.object({
  name: z.string().trim().min(1, "Enter the studio or company name.").max(200),
  website: optional,
  company_type: z.enum(["unknown", "studio", "publisher", "data_buyer", "other"]),
  location: optional,
  country: optional,
  tags: z.string().max(1000).optional(),
  notes: z.string().max(10_000).optional(),
  reviewed_on: z.string().optional(),
  qualification_source_url: z.string().trim().max(4000).optional(),
  contacts: z
    .array(
      z.object({
        name: optional,
        role_title: optional,
        email: z.union([z.literal(""), z.string().trim().email("Enter a valid email address or leave it empty.")]).optional(),
        status: z.enum(["unknown", "not_contacted", "attempted", "responded"]),
      }),
    )
    .max(20),
});

type Values = z.infer<typeof schema>;

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  existing?: OrganizationDetail | undefined;
  onSaved?: (id: string) => void;
}

const blank: Values = { name: "", website: "", company_type: "unknown", location: "", country: "", tags: "", notes: "", reviewed_on: "", qualification_source_url: "", contacts: [] };

export function ProspectForm({ open, onOpenChange, existing, onSaved }: Props) {
  const client = useQueryClient();
  const [duplicates, setDuplicates] = useState<DuplicateCandidate[]>([]);
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: blank });
  const contacts = useFieldArray({ control: form.control, name: "contacts" });
  const definitions = useQuery({
    queryKey: ["custom-fields", "prospect"],
    queryFn: () => api.get<CustomFieldView[]>("/custom-fields", { record_type: "prospect" }),
    enabled: open && !existing,
  });
  const customFields: CustomValue[] = existing
    ? existing.custom_fields ?? []
    : (definitions.data ?? []).map((f) => ({ key: f.key, label: f.label, field_type: f.field_type, value: null }));
  const [customOriginal, setCustomOriginal] = useState<CustomDraft>({});
  const [custom, setCustom] = useState<CustomDraft>({});
  const customKey = customFields.map((f) => `${f.key}:${String(f.value)}`).join("|");

  useEffect(() => {
    if (!open) return;
    const initial = draftFromValues(customFields);
    setCustomOriginal(initial);
    setCustom(initial);
  }, [open, customKey]); // customFields is rebuilt each render; customKey tracks its content

  useEffect(() => {
    if (!open) return;
    setDuplicates([]);
    form.reset(
      existing
        ? {
            name: existing.name,
            website: existing.website ?? "",
            company_type: existing.company_type,
            location: existing.location ?? "",
            country: existing.country ?? "",
            tags: existing.tags.join(", "),
            notes: existing.notes ?? "",
            reviewed_on: existing.reviewed_on ?? "",
            qualification_source_url: existing.qualification_source_url ?? "",
            contacts: [],
          }
        : blank,
    );
  }, [open, existing, form]);

  const toBody = (values: Values) => ({
    name: values.name,
    website: values.website || null,
    company_type: values.company_type,
    location: values.location || null,
    country: values.country || null,
    tags: (values.tags ?? "").split(",").map((t) => t.trim()).filter(Boolean),
    notes: values.notes || null,
    reviewed_on: values.reviewed_on || null,
    qualification_source_url: values.qualification_source_url || null,
    custom_fields: changedValues(customOriginal, custom),
  });

  const save = async (values: Values, allowDuplicate = false) => {
    try {
      let id: string;
      if (existing) {
        await api.put(`/prospects/${existing.id}`, toBody(values));
        id = existing.id;
      } else {
        const contactBodies = values.contacts
          .filter((c) => c.name || c.email)
          .map((c) => ({ name: c.name || null, role_title: c.role_title || null, email: c.email || null, status: c.status }));
        if (!allowDuplicate) {
          const found = await api.post<DuplicateCandidate[]>("/prospects/duplicates", {
            organization: toBody(values),
            emails: contactBodies.map((c) => c.email).filter(Boolean),
          });
          if (found.length) {
            setDuplicates(found);
            return;
          }
        }
        id = (
          await api.post<Created>("/prospects", {
            organization: toBody(values),
            contacts: contactBodies,
            allow_duplicate: true,
          })
        ).id;
      }
      await client.invalidateQueries({ queryKey: ["prospects"] });
      await client.invalidateQueries({ queryKey: ["prospect", id] });
      toast.success(existing ? "Prospect saved" : "Prospect created");
      onOpenChange(false);
      onSaved?.(id);
    } catch (error) {
      if (error instanceof ApiError && error.code === "validation") form.setError("name", { message: error.problems[0] ?? error.message });
      showError(error);
    }
  };

  const errors = form.formState.errors;
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title={existing ? `Edit ${existing.name}` : "New prospect"}
      description="A studio, publisher or other company you may sell to."
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          {duplicates.length ? (
            <Button variant="secondary" onClick={form.handleSubmit((v) => save(v, true))} loading={form.formState.isSubmitting}>
              Create anyway
            </Button>
          ) : null}
          <Button onClick={form.handleSubmit((v) => save(v))} loading={form.formState.isSubmitting}>
            {existing ? "Save" : "Create prospect"}
          </Button>
        </>
      }
    >
      <form className="grid gap-4 sm:grid-cols-2" onSubmit={form.handleSubmit((v) => save(v))} noValidate>
        {duplicates.length ? (
          <div role="alert" className="rounded-lg border border-warning/40 bg-warning-soft p-3 text-sm sm:col-span-2">
            <p className="flex items-center gap-2 font-medium text-warning">
              <AlertTriangle className="size-4" /> This looks like a prospect you already have
            </p>
            <ul className="mt-2 space-y-1">
              {duplicates.map((d) => (
                <li key={d.id} className="flex flex-wrap items-center gap-2">
                  <a className="font-medium underline" href={`/prospects?id=${d.id}`}>
                    {d.name}
                  </a>
                  <Badge tone="warning">{d.reason}</Badge>
                  {d.archived ? <Badge>Archived</Badge> : null}
                </li>
              ))}
            </ul>
            <p className="mt-2 text-foreground/80">Open the existing prospect, or choose “Create anyway” if this really is a different company.</p>
          </div>
        ) : null}
        <Field label="Name" required error={errors.name?.message} className="sm:col-span-2">
          {(p) => <Input {...p} {...form.register("name")} autoFocus placeholder="e.g. Pixel Forge Studios" />}
        </Field>
        <Field label="Website" error={errors.website?.message} hint="Only http(s) addresses are saved.">
          {(p) => <Input {...p} {...form.register("website")} placeholder="pixelforge.example" inputMode="url" />}
        </Field>
        <Field label="Type">
          {(p) => (
            <NativeSelect {...p} {...form.register("company_type")}>
              {Object.entries(ORGANIZATION_TYPE_LABELS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </NativeSelect>
          )}
        </Field>
        <Field label="City or region">{(p) => <Input {...p} {...form.register("location")} />}</Field>
        <Field label="Country">{(p) => <Input {...p} {...form.register("country")} />}</Field>
        <Field label="Tags" hint="Separate tags with commas." className="sm:col-span-2">
          {(p) => <Input {...p} {...form.register("tags")} placeholder="indie, vr" />}
        </Field>
        <Field label="Notes" className="sm:col-span-2">
          {(p) => <Textarea {...p} {...form.register("notes")} rows={3} />}
        </Field>
        <Field label="Review date" hint="When this prospect was last reviewed or qualified.">
          {(p) => <Input {...p} type="date" {...form.register("reviewed_on")} />}
        </Field>
        <Field label="Qualification source URL" error={errors.qualification_source_url?.message} hint="The page where you found or qualified this prospect. Saved exactly as entered.">
          {(p) => <Input {...p} {...form.register("qualification_source_url")} inputMode="url" placeholder="https://…" />}
        </Field>
        <CustomFieldInputs fields={customFields} draft={custom} onChange={setCustom} />

        {!existing ? (
          <div className="space-y-3 sm:col-span-2">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium">Contacts</p>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => contacts.append({ name: "", role_title: "", email: "", status: "unknown" })}
              >
                <Plus /> Add contact
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              Outreach status is never guessed from an email address. Set it only if you know.
            </p>
            {contacts.fields.map((item, index) => (
              <div key={item.id} className="grid gap-2 rounded-lg border p-3 sm:grid-cols-[1fr_1fr_1fr_auto]">
                <Input aria-label="Contact name" placeholder="Name" {...form.register(`contacts.${index}.name`)} />
                <Input aria-label="Job title" placeholder="Job title" {...form.register(`contacts.${index}.role_title`)} />
                <div>
                  <Input
                    aria-label="Email"
                    placeholder="Email"
                    type="email"
                    aria-invalid={Boolean(errors.contacts?.[index]?.email)}
                    {...form.register(`contacts.${index}.email`)}
                  />
                  {errors.contacts?.[index]?.email ? (
                    <p className="mt-1 text-xs text-danger">{errors.contacts[index]?.email?.message}</p>
                  ) : null}
                </div>
                <div className="flex gap-2">
                  <NativeSelect aria-label="Outreach status" {...form.register(`contacts.${index}.status`)}>
                    {Object.entries(CONTACT_STATUS_LABELS).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </NativeSelect>
                  <Button type="button" variant="ghost" size="icon" aria-label="Remove contact" onClick={() => contacts.remove(index)}>
                    <Trash2 />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        ) : null}
        <button type="submit" hidden />
      </form>
    </Dialog>
  );
}
