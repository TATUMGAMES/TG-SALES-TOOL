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

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, NativeSelect, Textarea } from "@/components/ui/form";
import { api } from "@/lib/api";
import type { ActorInfo, Created, OrgChoice, StageInfo } from "@/lib/api-types";
import { showError, useDebounced, usePipelineMeta } from "@/lib/hooks";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  organization?: { id: string; name: string } | undefined;
  defaultStageId?: string | undefined;
  defaultLane?: string | undefined;
  onCreated?: (id: string) => void;
}

export function NewOpportunityDialog({ open, onOpenChange, organization, defaultStageId, defaultLane, onCreated }: Props) {
  const client = useQueryClient();
  const meta = usePipelineMeta();
  const [orgText, setOrgText] = useState("");
  const [orgId, setOrgId] = useState(organization?.id ?? "");
  const [chosenLane, setLane] = useState(defaultLane ?? "");
  const [stageId, setStageId] = useState(defaultStageId ?? "");
  const [title, setTitle] = useState("");
  const [owner, setOwner] = useState("");
  const [value, setValue] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [nextAt, setNextAt] = useState("");
  const [nextNote, setNextNote] = useState("");
  const [busy, setBusy] = useState(false);
  const search = useDebounced(orgText);

  useEffect(() => {
    if (open) {
      setOrgId(organization?.id ?? "");
      setStageId(defaultStageId ?? "");
      if (defaultLane) setLane(defaultLane);
    }
  }, [open, organization, defaultStageId, defaultLane]);

  const stages = useQuery({ queryKey: ["stages"], queryFn: () => api.get<StageInfo[]>("/pipeline/stages"), enabled: open });
  const actors = useQuery({ queryKey: ["actors"], queryFn: () => api.get<ActorInfo[]>("/pipeline/actors"), enabled: open });
  const orgs = useQuery({
    queryKey: ["org-choices", search],
    queryFn: () => api.get<OrgChoice[]>("/pipeline/organizations", { text: search }),
    enabled: open && !organization,
  });
  const laneChoices = meta.data?.lanes ?? [];
  // The chosen lane, or the first active lane (the configured lanes differ per installation).
  const lane = laneChoices.some((l) => l.value === chosenLane) ? chosenLane : laneChoices[0]?.value ?? "";
  const laneStages = (stages.data ?? []).filter((s) => !s.product_lane || s.product_lane === lane);
  const effectiveStage = stageId && laneStages.some((s) => s.id === stageId) ? stageId : laneStages[0]?.id ?? "";

  const create = async () => {
    setBusy(true);
    try {
      const created = await api.post<Created>("/opportunities", {
        organization_id: orgId,
        product_lane: lane,
        stage_id: effectiveStage,
        title: title || null,
        owner_actor_id: owner || null,
        estimated_value: value ? Number(value) : null,
        currency: value ? currency : null,
        next_action_at: nextAt ? new Date(`${nextAt}T09:00:00`).toISOString() : null,
        next_action_note: nextNote || null,
      });
      await Promise.all([
        client.invalidateQueries({ queryKey: ["board"] }),
        client.invalidateQueries({ queryKey: ["prospect", orgId] }),
        client.invalidateQueries({ queryKey: ["prospects"] }),
      ]);
      toast.success("Opportunity created");
      onOpenChange(false);
      setTitle("");
      onCreated?.(created.id);
    } catch (error) {
      showError(error);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="New opportunity"
      description={organization ? `For ${organization.name}` : "A deal with a prospect in one sales lane."}
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={create} loading={busy} disabled={!orgId || !effectiveStage}>Create opportunity</Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        {!organization ? (
          <Field label="Prospect" required className="sm:col-span-2" hint="Type to search your prospects.">
            {(p) => (
              <div className="space-y-2">
                <Input {...p} placeholder="Type a prospect name" value={orgText} onChange={(e) => setOrgText(e.target.value)} />
                <NativeSelect aria-label="Choose prospect" value={orgId} onChange={(e) => setOrgId(e.target.value)}>
                  <option value="">Choose a prospect…</option>
                  {(orgs.data ?? []).map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
                </NativeSelect>
              </div>
            )}
          </Field>
        ) : null}
        <Field label="Sales lane" required>
          {(p) => (
            <NativeSelect {...p} value={lane} onChange={(e) => setLane(e.target.value)}>
              {laneChoices.map((l) => <option key={l.value} value={l.value}>{l.label}</option>)}
            </NativeSelect>
          )}
        </Field>
        <Field label="Stage" required>
          {(p) => (
            <NativeSelect {...p} value={effectiveStage} onChange={(e) => setStageId(e.target.value)}>
              {laneStages.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </NativeSelect>
          )}
        </Field>
        <Field label="Title" className="sm:col-span-2">{(p) => <Input {...p} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Historical player data, Q3 campaign" />}</Field>
        <Field label="Salesperson">
          {(p) => (
            <NativeSelect {...p} value={owner} onChange={(e) => setOwner(e.target.value)}>
              <option value="">Nobody yet</option>
              {(actors.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </NativeSelect>
          )}
        </Field>
        <div className="grid grid-cols-[1fr_90px] gap-2">
          <Field label="Estimated value">{(p) => <Input {...p} type="number" min={0} inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} placeholder="Optional" />}</Field>
          <Field label="Currency">{(p) => <Input {...p} maxLength={3} value={currency} onChange={(e) => setCurrency(e.target.value.toUpperCase())} />}</Field>
        </div>
        <Field label="Next follow-up">{(p) => <Input {...p} type="date" value={nextAt} onChange={(e) => setNextAt(e.target.value)} />}</Field>
        <Field label="What happens next">{(p) => <Textarea {...p} rows={2} value={nextNote} onChange={(e) => setNextNote(e.target.value)} placeholder="e.g. Send sample data" />}</Field>
      </div>
    </Dialog>
  );
}
