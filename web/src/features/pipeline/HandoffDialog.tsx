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

import { useMutation } from "@tanstack/react-query";
import { Check, Copy, ShieldAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, NativeSelect, Textarea } from "@/components/ui/form";
import { api } from "@/lib/api";
import type { HandoffView, OpportunityDetail } from "@/lib/api-types";
import { copyText, showError, usePipelineMeta } from "@/lib/hooks";

const SECTIONS = [
  ["proposed_dataset", "Proposed dataset"],
  ["use_case", "Intended use case"],
  ["fields_and_format", "Fields and format"],
  ["refresh_cadence", "Refresh cadence"],
  ["privacy_security", "Privacy and security requirements"],
  ["delivery_expectations", "Delivery expectations"],
  ["open_questions", "Unresolved questions"],
] as const;

type Sections = Record<(typeof SECTIONS)[number][0], string>;

/** A copyable handoff email for the technical lead. tg_sales never sends it. */
export function HandoffDialog({
  open,
  onOpenChange,
  opportunity,
  onRecorded,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  opportunity: OpportunityDetail;
  onRecorded: () => void;
}) {
  const meta = usePipelineMeta();
  const [recipient, setRecipient] = useState("");
  const [contactId, setContactId] = useState("");
  const [sections, setSections] = useState<Sections>(() => Object.fromEntries(SECTIONS.map(([k]) => [k, ""])) as Sections);
  const [view, setView] = useState<HandoffView | null>(null);
  const [copied, setCopied] = useState(false);

  const render = useMutation({
    mutationFn: () => api.post<HandoffView>(`/opportunities/${opportunity.card.id}/handoff/render`, { recipient, contact_id: contactId || null, ...sections }),
    onSuccess: setView,
    onError: showError,
  });
  useEffect(() => {
    if (!open) return;
    const timer = setTimeout(() => render.mutate(), 250);
    return () => clearTimeout(timer);
  }, [open, recipient, contactId, sections]);

  const emailInvalid = recipient.trim() !== "" && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(recipient.trim());

  const copyAndRecord = async () => {
    if (!view) return;
    if (await copyText(view.body)) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
      try {
        await api.post(`/opportunities/${opportunity.card.id}/handoff`, { recipient, contact_id: contactId || null });
        toast.success("Draft copied and handoff recorded. Send it from your email program.");
        onRecorded();
      } catch (error) {
        showError(error);
      }
    } else {
      toast.error("Copying failed. Select the text and copy it manually.");
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      size="xl"
      title="Prepare technical handoff"
      description={`${opportunity.card.organization_name} · data licensing`}
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Close</Button>
          <Button onClick={copyAndRecord} disabled={!view || emailInvalid}>
            {copied ? <Check /> : <Copy />} {copied ? "Copied" : "Copy draft and record handoff"}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-3">
          <p className="flex gap-2 rounded-lg bg-warning-soft p-3 text-sm text-warning">
            <ShieldAlert className="size-4 shrink-0" /> {meta.data?.review_notice ?? "Share only with authorized reviewers."}
          </p>
          <Field label="Technical lead's email address (optional)" error={emailInvalid ? "Enter a valid recipient email address, or leave it empty." : undefined}>
            {(p) => <Input {...p} type="email" value={recipient} onChange={(e) => setRecipient(e.target.value)} />}
          </Field>
          <Field label="Contact at the studio">
            {(p) => (
              <NativeSelect {...p} value={contactId} onChange={(e) => setContactId(e.target.value)}>
                <option value="">None</option>
                {opportunity.contacts.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
              </NativeSelect>
            )}
          </Field>
          {SECTIONS.map(([key, label]) => (
            <Field key={key} label={label}>
              {(p) => <Textarea {...p} rows={2} value={sections[key]} onChange={(e) => setSections({ ...sections, [key]: e.target.value })} />}
            </Field>
          ))}
        </div>
        <div className="space-y-2">
          <p className="text-sm font-medium">Preview</p>
          {view?.missing.length ? <p className="text-xs text-muted-foreground">Still empty: {view.missing.join(", ")}</p> : null}
          <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap rounded-lg border bg-muted/50 p-3 font-sans text-sm">{view?.body ?? "…"}</pre>
        </div>
      </div>
    </Dialog>
  );
}
