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
import { Archive, ArchiveRestore, ArrowDown, ArrowUp, MoveRight, Plus, Save, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardHeader, Dot } from "@/components/ui/card";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { Field, Input, NativeSelect, Textarea } from "@/components/ui/form";
import { ErrorState, LoadingRows, Switch } from "@/components/ui/misc";
import { api } from "@/lib/api";
import type { LaneView } from "@/lib/api-types";
import { useAction } from "@/lib/hooks";
import { DEFAULT_LANE_COLOR } from "@/lib/lanes";
import { plural } from "@/lib/utils";

/** Suggested lane colors (any #rrggbb can be typed). */
const PALETTE = ["#a787bd", "#86c4c2", "#c7d47f", "#f6d271", "#d87b7a", "#8fa8d8"];
const INVALIDATE = [["lanes"], ["pipeline-meta"], ["board"], ["stages"], ["stages-all"], ["dashboard"]];

interface Draft {
  name: string;
  description: string;
  color: string;
  technical_handoff: boolean;
}

const toDraft = (lane?: LaneView): Draft => ({
  name: lane?.name ?? "",
  description: lane?.description ?? "",
  color: lane?.color ?? PALETTE[0]!,
  technical_handoff: lane?.technical_handoff ?? false,
});

function ColorPicker({ value, onChange }: { value: string; onChange: (color: string) => void }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {PALETTE.map((color) => (
        <button
          key={color}
          type="button"
          aria-label={`Color ${color}`}
          aria-pressed={value === color}
          onClick={() => onChange(color)}
          className="size-7 rounded-full border-2 transition-transform aria-pressed:scale-110 aria-pressed:border-foreground"
          style={{ background: color }}
        />
      ))}
      <Input aria-label="Color code" className="w-28" value={value} onChange={(e) => onChange(e.target.value)} placeholder="#rrggbb" />
    </div>
  );
}

function LaneDialog({ lane, open, onOpenChange }: { lane?: LaneView | undefined; open: boolean; onOpenChange: (open: boolean) => void }) {
  const [draft, setDraft] = useState<Draft>(toDraft(lane));
  useEffect(() => {
    if (open) setDraft(toDraft(lane));
  }, [open, lane]);
  const save = useAction(
    () => (lane ? api.put(`/lanes/${lane.key}`, draft) : api.post("/lanes", draft)),
    { invalidate: INVALIDATE, success: lane ? "Lane saved" : "Lane added" },
  );
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={lane ? `Edit ${lane.name}` : "Add a sales lane"}
      description="A lane is a business category of opportunities, such as “Consulting” or “Sponsorships”. Every lane uses the same pipeline stages."
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button loading={save.isPending} disabled={!draft.name.trim()} onClick={() => save.mutate(undefined, { onSuccess: () => onOpenChange(false) })}>
            <Save /> {lane ? "Save" : "Add lane"}
          </Button>
        </>
      }
    >
      <div className="grid gap-3">
        <Field label="Name" required hint={lane ? "Renaming keeps every opportunity and its history." : undefined}>
          {(p) => <Input {...p} autoFocus value={draft.name} maxLength={80} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="e.g. Enterprise Sales" />}
        </Field>
        <Field label="Description">
          {(p) => <Textarea {...p} rows={2} maxLength={500} value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />}
        </Field>
        <Field label="Color" hint="Always shown together with the name.">
          {() => <ColorPicker value={draft.color} onChange={(color) => setDraft({ ...draft, color })} />}
        </Field>
        <label className="flex items-center gap-2 text-sm">
          <Switch checked={draft.technical_handoff} onCheckedChange={(checked) => setDraft({ ...draft, technical_handoff: checked })} />
          Offer technical-review handoffs for this lane's opportunities
        </label>
      </div>
    </Dialog>
  );
}

function MoveDialog({ lane, lanes, onOpenChange }: { lane: LaneView | null; lanes: LaneView[]; onOpenChange: (open: boolean) => void }) {
  const [target, setTarget] = useState("");
  const targets = lanes.filter((l) => l.key !== lane?.key && !l.archived);
  const firstTarget = targets[0]?.key ?? "";
  useEffect(() => setTarget(firstTarget), [lane, firstTarget]);
  const move = useAction(() => api.post<{ opportunities: number; stages: number; backup: string | null }>(`/lanes/${lane?.key}/move`, { target_key: target }), {
    invalidate: INVALIDATE,
    success: (r) => `Moved ${plural(r.opportunities, "opportunity", "opportunities")} and ${plural(r.stages, "stage")}.`,
  });
  return (
    <Dialog
      open={lane !== null}
      onOpenChange={onOpenChange}
      title={`Move records out of ${lane?.name ?? ""}`}
      description="Every opportunity in this lane, and every stage limited to it, moves to the lane you choose. Their history is kept, and each move is recorded on the opportunity's timeline. A backup is made first."
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button loading={move.isPending} disabled={!target} onClick={() => move.mutate(undefined, { onSuccess: () => onOpenChange(false) })}>
            <MoveRight /> Move records
          </Button>
        </>
      }
    >
      <Field label="Move to">
        {(p) => (
          <NativeSelect {...p} value={target} onChange={(e) => setTarget(e.target.value)}>
            {targets.map((l) => <option key={l.key} value={l.key}>{l.name}</option>)}
          </NativeSelect>
        )}
      </Field>
      {lane ? <p className="mt-3 text-sm text-muted-foreground">{plural(lane.opportunity_count, "opportunity", "opportunities")} and {plural(lane.stage_count, "lane-specific stage")} will move.</p> : null}
    </Dialog>
  );
}

export function LanesPanel() {
  const lanes = useQuery({ queryKey: ["lanes"], queryFn: () => api.get<LaneView[]>("/lanes", { include_archived: true }) });
  const presets = useQuery({ queryKey: ["lane-presets"], queryFn: () => api.get<{ key: string; label: string }[]>("/lanes/presets") });
  const [editing, setEditing] = useState<{ lane?: LaneView } | null>(null);
  const [moving, setMoving] = useState<LaneView | null>(null);
  const [deleting, setDeleting] = useState<LaneView | null>(null);
  const [preset, setPreset] = useState("");

  const all = lanes.data ?? [];
  const active = all.filter((l) => !l.archived);
  const reorder = useAction((keys: string[]) => api.put("/lanes/order", { keys }), { invalidate: INVALIDATE });
  const archive = useAction((vars: { key: string; archived: boolean }) => api.post(`/lanes/${vars.key}/archive`, { archived: vars.archived }), {
    invalidate: INVALIDATE,
    success: "Saved",
  });
  const remove = useAction((key: string) => api.delete(`/lanes/${key}`), { invalidate: INVALIDATE, success: "Lane deleted" });
  const applyPreset = useAction((key: string) => api.post(`/lanes/presets/${key}`), { invalidate: INVALIDATE, success: "Preset lanes added" });

  const move = (index: number, offset: number) => {
    const keys = active.map((l) => l.key);
    const target = index + offset;
    if (target < 0 || target >= keys.length) return;
    [keys[index], keys[target]] = [keys[target]!, keys[index]!];
    reorder.mutate(keys);
  };

  if (lanes.error) return <ErrorState error={lanes.error} onRetry={() => lanes.refetch()} />;
  if (!lanes.data) return <LoadingRows />;

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title="Sales lanes"
          description="Lanes group opportunities by what you sell. They appear in the pipeline, dashboard and report filters, and in new opportunities. Stages (Contacted, Negotiation, Won…) are managed on the Pipeline page."
          actions={<Button onClick={() => setEditing({})}><Plus /> Add lane</Button>}
        />
        <ul className="divide-y">
          {all.map((lane) => {
            const index = active.findIndex((l) => l.key === lane.key);
            return (
              <li key={lane.key} className="flex flex-wrap items-center gap-3 px-5 py-3">
                <Dot color={lane.color ?? DEFAULT_LANE_COLOR} />
                <div className="min-w-48 flex-1">
                  <p className="font-medium">
                    {lane.name} {lane.archived ? <Badge>Archived</Badge> : null} {lane.technical_handoff ? <Badge tone="info">Technical handoffs</Badge> : null}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {lane.description ? `${lane.description} · ` : ""}
                    {plural(lane.opportunity_count, "opportunity", "opportunities")}
                    {lane.stage_count ? ` · ${plural(lane.stage_count, "lane-specific stage")}` : ""}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-1">
                  {!lane.archived ? (
                    <>
                      <Button variant="ghost" size="icon-sm" aria-label={`Move ${lane.name} up`} disabled={index <= 0} onClick={() => move(index, -1)}><ArrowUp /></Button>
                      <Button variant="ghost" size="icon-sm" aria-label={`Move ${lane.name} down`} disabled={index >= active.length - 1} onClick={() => move(index, 1)}><ArrowDown /></Button>
                    </>
                  ) : null}
                  <Button variant="outline" size="sm" onClick={() => setEditing({ lane })}>Edit</Button>
                  {lane.in_use ? <Button variant="outline" size="sm" onClick={() => setMoving(lane)}><MoveRight /> Move records</Button> : null}
                  <Button variant="ghost" size="sm" onClick={() => archive.mutate({ key: lane.key, archived: !lane.archived })}>
                    {lane.archived ? <><ArchiveRestore /> Restore</> : <><Archive /> Archive</>}
                  </Button>
                  {!lane.in_use ? (
                    <Button variant="ghost" size="sm" className="text-danger" onClick={() => setDeleting(lane)}><Trash2 /> Delete</Button>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      </Card>

      <Card className="space-y-2 p-5 text-sm">
        <p className="font-medium">Keeping your records safe</p>
        <p className="text-muted-foreground">
          Archiving hides a lane from new opportunities but keeps its opportunities, stages and history exactly as they are. A lane can be deleted only when nothing uses it:
          move its records to another lane first, or archive it instead.
        </p>
      </Card>

      <Card>
        <CardHeader title="Add a set of lanes" description="Adds the preset's lanes that you do not have yet. Existing lanes are not changed." />
        <div className="flex flex-wrap items-end gap-2 p-5 pt-3">
          <Field label="Preset" className="min-w-72 flex-1">
            {(p) => (
              <NativeSelect {...p} value={preset} onChange={(e) => setPreset(e.target.value)}>
                <option value="">Choose a preset…</option>
                {(presets.data ?? []).map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}
              </NativeSelect>
            )}
          </Field>
          <Button variant="outline" disabled={!preset} loading={applyPreset.isPending} onClick={() => applyPreset.mutate(preset)}>Add preset lanes</Button>
        </div>
      </Card>

      <LaneDialog open={editing !== null} lane={editing?.lane} onOpenChange={(open) => !open && setEditing(null)} />
      <MoveDialog lane={moving} lanes={all} onOpenChange={(open) => !open && setMoving(null)} />
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={`Delete the lane “${deleting?.name ?? ""}”?`}
        description="No opportunity or stage uses this lane, so nothing else is affected. You can create a lane with the same name again later."
        confirmLabel="Delete lane"
        danger
        onConfirm={async () => {
          if (deleting) await remove.mutateAsync(deleting.key);
        }}
      />
    </div>
  );
}
