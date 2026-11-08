import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Archive, ArchiveRestore, Plus } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge, Card } from "@/components/ui/card";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { Field, Input, NativeSelect } from "@/components/ui/form";
import { ErrorState, LoadingRows } from "@/components/ui/misc";
import { api } from "@/lib/api";
import type { ProductLane, StageInfo, StageOutcome } from "@/lib/api-types";
import { useAction } from "@/lib/hooks";
import { LANE_LABELS } from "@/lib/types";

const OUTCOMES: Record<StageOutcome, string> = { open: "Open", won: "Won", lost: "Lost", not_a_fit: "Not a fit" };

function StageRow({ stage, stages, index, onMove }: { stage: StageInfo; stages: StageInfo[]; index: number; onMove: (offset: number) => void }) {
  const [name, setName] = useState(stage.name);
  const [archiving, setArchiving] = useState(false);
  const [target, setTarget] = useState("");
  const invalidate = [["stages-all"], ["stages"], ["board"]];
  const rename = useAction(() => api.patch(`/pipeline/stages/${stage.id}`, { name }), { invalidate, success: "Stage renamed" });
  const outcome = useAction((value: StageOutcome) => api.patch(`/pipeline/stages/${stage.id}`, { outcome: value }), { invalidate, success: "Saved" });
  const archive = useAction(() => api.post<{ count: number }>(`/pipeline/stages/${stage.id}/archive`, { move_to_stage_id: target || null }), {
    invalidate,
    success: (r) => `Stage archived${r.count ? `; ${r.count} opportunities moved` : ""}`,
  });
  const restore = useAction(() => api.post(`/pipeline/stages/${stage.id}/restore`), { invalidate, success: "Stage restored" });
  const destinations = stages.filter((s) => s.id !== stage.id && !s.archived && (!s.product_lane || !stage.product_lane || s.product_lane === stage.product_lane));

  return (
    <Card className="flex flex-wrap items-center gap-2 p-3">
      <div className="flex flex-col">
        <Button variant="ghost" size="icon-sm" aria-label={`Move ${stage.name} up`} disabled={index === 0 || stage.archived} onClick={() => onMove(-1)}><ArrowUp /></Button>
        <Button variant="ghost" size="icon-sm" aria-label={`Move ${stage.name} down`} disabled={index === stages.length - 1 || stage.archived} onClick={() => onMove(1)}><ArrowDown /></Button>
      </div>
      <Input aria-label="Stage name" className="min-w-40 flex-1" value={name} onChange={(e) => setName(e.target.value)} onBlur={() => name.trim() && name !== stage.name && rename.mutate()} disabled={stage.archived} />
      <NativeSelect aria-label={`Outcome of ${stage.name}`} className="w-36" value={stage.outcome} onChange={(e) => outcome.mutate(e.target.value as StageOutcome)} disabled={stage.archived}>
        {Object.entries(OUTCOMES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </NativeSelect>
      {stage.product_lane ? <Badge tone="info">{LANE_LABELS[stage.product_lane]} only</Badge> : null}
      <Badge>{stage.opportunity_count ?? 0} open</Badge>
      {stage.archived ? (
        <Button variant="outline" size="sm" onClick={() => restore.mutate()}><ArchiveRestore /> Restore</Button>
      ) : (
        <Button variant="ghost" size="sm" onClick={() => setArchiving(true)}><Archive /> Archive</Button>
      )}
      <ConfirmDialog
        open={archiving}
        onOpenChange={setArchiving}
        title={`Archive “${stage.name}”?`}
        description={
          <div className="space-y-2">
            <p>History and reports keep the stage. Choose where its current opportunities should go.</p>
            <NativeSelect aria-label="Move opportunities to" value={target} onChange={(e) => setTarget(e.target.value)}>
              <option value="">Choose a stage…</option>
              {destinations.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </NativeSelect>
          </div>
        }
        confirmLabel="Archive stage"
        onConfirm={async () => {
          await archive.mutateAsync();
        }}
      />
    </Card>
  );
}

export function StageManager({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const query = useQuery({
    queryKey: ["stages-all"],
    queryFn: () => api.get<StageInfo[]>("/pipeline/stages", { include_archived: true }),
    enabled: open,
  });
  const [name, setName] = useState("");
  const [lane, setLane] = useState<"" | ProductLane>("");
  const [outcome, setOutcome] = useState<StageOutcome>("open");
  const invalidate = [["stages-all"], ["stages"], ["board"]];
  const create = useAction(() => api.post("/pipeline/stages", { name, lane: lane || null, outcome }), { invalidate, success: "Stage added" });
  const reorder = useAction((ids: string[]) => api.put("/pipeline/stages/order", { stage_ids: ids }), { invalidate });
  const stages = query.data ?? [];
  const active = stages.filter((s) => !s.archived);

  return (
    <Dialog open={open} onOpenChange={onOpenChange} size="lg" title="Manage stages" description="Rename, reorder, add or archive stages. History and reports stay correct.">
      {query.error ? <ErrorState error={query.error} /> : null}
      {query.isLoading ? <LoadingRows /> : null}
      <div className="space-y-2">
        {active.map((stage, index) => (
          <StageRow
            key={stage.id}
            stage={stage}
            stages={active}
            index={index}
            onMove={(offset) => {
              const ids = active.map((s) => s.id);
              const [moved] = ids.splice(index, 1);
              if (moved) ids.splice(index + offset, 0, moved);
              reorder.mutate(ids);
            }}
          />
        ))}
      </div>
      {stages.some((s) => s.archived) ? (
        <div className="mt-4 space-y-2">
          <p className="text-sm font-medium text-muted-foreground">Archived stages</p>
          {stages.filter((s) => s.archived).map((stage, index) => (
            <StageRow key={stage.id} stage={stage} stages={stages} index={index} onMove={() => undefined} />
          ))}
        </div>
      ) : null}
      <Card className="mt-4 grid gap-3 p-3 sm:grid-cols-[1fr_160px_170px_auto] sm:items-end">
        <Field label="New stage">{(p) => <Input {...p} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Paid pilot" />}</Field>
        <Field label="Outcome">
          {(p) => (
            <NativeSelect {...p} value={outcome} onChange={(e) => setOutcome(e.target.value as StageOutcome)}>
              {Object.entries(OUTCOMES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </NativeSelect>
          )}
        </Field>
        <Field label="Product lane">
          {(p) => (
            <NativeSelect {...p} value={lane} onChange={(e) => setLane(e.target.value as "" | ProductLane)}>
              <option value="">All lanes</option>
              {Object.entries(LANE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </NativeSelect>
          )}
        </Field>
        <Button disabled={!name.trim()} loading={create.isPending} onClick={() => create.mutate(undefined, { onSuccess: () => setName("") })}>
          <Plus /> Add
        </Button>
      </Card>
    </Dialog>
  );
}
