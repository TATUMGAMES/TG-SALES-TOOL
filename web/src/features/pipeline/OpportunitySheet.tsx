import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Circle, ExternalLink, FileText, ListPlus, MessageSquarePlus, Save, Undo2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { Button } from "@/components/ui/button";
import { Badge, Card, Dot, LANE_COLORS } from "@/components/ui/card";
import { ConfirmDialog, Sheet } from "@/components/ui/dialog";
import { Field, Input, NativeSelect } from "@/components/ui/form";
import { ErrorState, LoadingRows, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/misc";
import { api } from "@/lib/api";
import type { ActivityType, ActorInfo, OpportunityDetail, StageInfo } from "@/lib/api-types";
import { formatDateTime, formatMoney, isoDate, relativeDue } from "@/lib/format";
import { useAction, usePipelineMeta } from "@/lib/hooks";
import { LANE_LABELS } from "@/lib/types";
import { cn } from "@/lib/utils";
import { HandoffDialog } from "./HandoffDialog";
import { ReasonDialog } from "./ReasonDialog";

function toLocalInput(value: string | null): string {
  return value ? isoDate(new Date(value)) : "";
}

export function OpportunitySheet({ id, onClose }: { id: string | null; onClose: () => void }) {
  const client = useQueryClient();
  const meta = usePipelineMeta();
  const query = useQuery({
    queryKey: ["opportunity", id],
    queryFn: () => api.get<OpportunityDetail>(`/opportunities/${id}`),
    enabled: Boolean(id),
  });
  const stages = useQuery({ queryKey: ["stages"], queryFn: () => api.get<StageInfo[]>("/pipeline/stages"), enabled: Boolean(id) });
  const actors = useQuery({ queryKey: ["actors"], queryFn: () => api.get<ActorInfo[]>("/pipeline/actors"), enabled: Boolean(id) });
  const detail = query.data;
  const invalidate = [["opportunity", id], ["board"], ["reminders"], ["dashboard"]];

  const [edit, setEdit] = useState({ title: "", owner: "", value: "", currency: "", probability: "", nextAt: "", nextNote: "" });
  const [activity, setActivity] = useState({ type: "email" as ActivityType, contact: "", note: "", when: "" });
  const [note, setNote] = useState("");
  const [task, setTask] = useState({ title: "", due: "" });
  const [reasonStage, setReasonStage] = useState<StageInfo | null>(null);
  const [voiding, setVoiding] = useState<string | null>(null);
  const [voidReason, setVoidReason] = useState("");
  const [handoff, setHandoff] = useState(false);

  useEffect(() => {
    if (!detail) return;
    setEdit({
      title: detail.card.title ?? "",
      owner: detail.owner_actor_id ?? "",
      value: detail.estimated_value?.toString() ?? "",
      currency: detail.currency ?? "USD",
      probability: detail.probability !== null ? String(Math.round(detail.probability * 100)) : "",
      nextAt: toLocalInput(detail.card.next_action_at),
      nextNote: detail.card.next_action_note ?? "",
    });
  }, [detail]);

  const save = useAction(
    () =>
      api.put(`/opportunities/${id}`, {
        title: edit.title || null,
        owner_actor_id: edit.owner || null,
        estimated_value: edit.value ? Number(edit.value) : null,
        currency: edit.value ? edit.currency || "USD" : null,
        probability: edit.probability ? Number(edit.probability) / 100 : null,
        next_action_at: edit.nextAt ? new Date(`${edit.nextAt}T09:00:00`).toISOString() : null,
        next_action_note: edit.nextNote || null,
      }),
    { invalidate, success: "Saved" },
  );
  const move = useAction(
    (vars: { stageId: string; code?: string; note?: string }) =>
      api.post(`/opportunities/${id}/move`, { stage_id: vars.stageId, reason_code: vars.code ?? null, reason_note: vars.note ?? null }),
    { invalidate, success: "Stage changed" },
  );
  const log = useAction(
    () =>
      api.post(`/opportunities/${id}/activities`, {
        type: activity.type,
        contact_id: activity.contact || null,
        note: activity.note || null,
        occurred_at: activity.when ? new Date(activity.when).toISOString() : null,
      }),
    { invalidate, success: "Activity logged" },
  );
  const addNote = useAction(() => api.post(`/opportunities/${id}/notes`, { text: note }), { invalidate, success: "Note added" });
  const addTask = useAction(
    () => api.post(`/opportunities/${id}/tasks`, { title: task.title, due_at: task.due ? new Date(`${task.due}T09:00:00`).toISOString() : null }),
    { invalidate, success: "Task added" },
  );
  const toggleTask = useAction((vars: { taskId: string; done: boolean }) => api.post(`/tasks/${vars.taskId}/done`, { done: vars.done }), { invalidate });
  const voidActivity = useAction((vars: { activityId: string; reason: string }) => api.post(`/activities/${vars.activityId}/void`, { reason: vars.reason }), {
    invalidate,
    success: "Marked as a mistake (kept in history)",
  });

  const laneStages = (stages.data ?? []).filter((s) => detail && (!s.product_lane || s.product_lane === detail.card.product_lane));
  const due = relativeDue(detail?.card.next_action_at);

  return (
    <Sheet
      open={Boolean(id)}
      onOpenChange={(o) => !o && onClose()}
      title={detail ? detail.card.organization_name : "Opportunity"}
      description={detail ? detail.card.title ?? LANE_LABELS[detail.card.product_lane] : undefined}
    >
      {query.isLoading ? <LoadingRows /> : null}
      {query.error ? <ErrorState error={query.error} onRetry={() => query.refetch()} /> : null}
      {detail ? (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="outline" className="gap-1.5"><Dot color={LANE_COLORS[detail.card.product_lane] ?? ""} />{LANE_LABELS[detail.card.product_lane]}</Badge>
            <Badge tone={detail.stage.outcome === "won" ? "success" : detail.stage.outcome === "open" ? "purple" : "neutral"}>{detail.stage.name}</Badge>
            {detail.outcome_reason ? <Badge tone="outline">Reason: {detail.outcome_reason}</Badge> : null}
            {!detail.card.closed ? <span className={cn("text-sm", due.overdue ? "font-semibold text-danger" : "text-muted-foreground")}>{due.text}</span> : null}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button asChild size="sm" variant="outline">
              <Link to={`/prospects?id=${detail.card.organization_id}`}><ExternalLink /> Open prospect</Link>
            </Button>
            {detail.card.product_lane === "data_licensing" ? (
              <Button size="sm" variant="outline" onClick={() => setHandoff(true)}><FileText /> Prepare technical handoff</Button>
            ) : null}
          </div>

          <Field label="Stage">
            {(p) => (
              <NativeSelect
                {...p}
                value={detail.stage.id}
                onChange={(e) => {
                  const stage = laneStages.find((s) => s.id === e.target.value);
                  if (!stage) return;
                  if (stage.outcome !== "open") setReasonStage(stage);
                  else move.mutate({ stageId: stage.id });
                }}
              >
                {laneStages.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </NativeSelect>
            )}
          </Field>

          <Tabs defaultValue="log">
            <TabsList>
              <TabsTrigger value="log">Log activity</TabsTrigger>
              <TabsTrigger value="details">Details</TabsTrigger>
              <TabsTrigger value="tasks">Tasks ({detail.tasks.filter((t) => !t.completed_at).length})</TabsTrigger>
            </TabsList>
            <TabsContent value="log" className="mt-3 space-y-3">
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="What happened">
                  {(p) => (
                    <NativeSelect {...p} value={activity.type} onChange={(e) => setActivity({ ...activity, type: e.target.value as ActivityType })}>
                      {(meta.data?.loggable_activities ?? []).map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
                    </NativeSelect>
                  )}
                </Field>
                <Field label="With">
                  {(p) => (
                    <NativeSelect {...p} value={activity.contact} onChange={(e) => setActivity({ ...activity, contact: e.target.value })}>
                      <option value="">No specific contact</option>
                      {detail.contacts.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
                    </NativeSelect>
                  )}
                </Field>
                <Field label="When" hint="Leave empty for now. Earlier dates are fine.">
                  {(p) => <Input {...p} type="datetime-local" value={activity.when} onChange={(e) => setActivity({ ...activity, when: e.target.value })} />}
                </Field>
                <Field label="Notes">{(p) => <Input {...p} value={activity.note} onChange={(e) => setActivity({ ...activity, note: e.target.value })} placeholder="What was discussed or agreed" />}</Field>
              </div>
              <p className="text-xs text-muted-foreground">tg_sales only records what you did. It never sends emails or messages.</p>
              <Button loading={log.isPending} onClick={() => log.mutate(undefined, { onSuccess: () => setActivity({ ...activity, note: "", when: "" }) })}>
                <ListPlus /> Log activity
              </Button>
              <div className="flex gap-2 pt-2">
                <Input aria-label="Add a note" placeholder="Add a note…" value={note} onChange={(e) => setNote(e.target.value)} />
                <Button variant="outline" disabled={!note.trim()} loading={addNote.isPending} onClick={() => addNote.mutate(undefined, { onSuccess: () => setNote("") })}>
                  <MessageSquarePlus /> Note
                </Button>
              </div>
            </TabsContent>

            <TabsContent value="details" className="mt-3">
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Title" className="sm:col-span-2">{(p) => <Input {...p} value={edit.title} onChange={(e) => setEdit({ ...edit, title: e.target.value })} />}</Field>
                <Field label="Salesperson">
                  {(p) => (
                    <NativeSelect {...p} value={edit.owner} onChange={(e) => setEdit({ ...edit, owner: e.target.value })}>
                      <option value="">Nobody</option>
                      {(actors.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                    </NativeSelect>
                  )}
                </Field>
                <Field label="Probability (%)">{(p) => <Input {...p} type="number" min={0} max={100} value={edit.probability} onChange={(e) => setEdit({ ...edit, probability: e.target.value })} />}</Field>
                <Field label="Estimated value" hint={detail.estimated_value !== null ? formatMoney(detail.estimated_value, detail.currency) : undefined}>
                  {(p) => <Input {...p} type="number" min={0} value={edit.value} onChange={(e) => setEdit({ ...edit, value: e.target.value })} />}
                </Field>
                <Field label="Currency">{(p) => <Input {...p} maxLength={3} value={edit.currency} onChange={(e) => setEdit({ ...edit, currency: e.target.value.toUpperCase() })} />}</Field>
                <Field label="Next follow-up">{(p) => <Input {...p} type="date" value={edit.nextAt} onChange={(e) => setEdit({ ...edit, nextAt: e.target.value })} />}</Field>
                <Field label="What happens next">{(p) => <Input {...p} value={edit.nextNote} onChange={(e) => setEdit({ ...edit, nextNote: e.target.value })} />}</Field>
              </div>
              <Button className="mt-3" loading={save.isPending} onClick={() => save.mutate()}><Save /> Save details</Button>
            </TabsContent>

            <TabsContent value="tasks" className="mt-3 space-y-3">
              <div className="grid gap-2 sm:grid-cols-[1fr_160px_auto]">
                <Input aria-label="New task" placeholder="New task, e.g. Send sample data" value={task.title} onChange={(e) => setTask({ ...task, title: e.target.value })} />
                <Input aria-label="Due date" type="date" value={task.due} onChange={(e) => setTask({ ...task, due: e.target.value })} />
                <Button disabled={!task.title.trim()} loading={addTask.isPending} onClick={() => addTask.mutate(undefined, { onSuccess: () => setTask({ title: "", due: "" }) })}>Add task</Button>
              </div>
              {detail.tasks.map((t) => {
                const taskDue = relativeDue(t.due_at);
                return (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => toggleTask.mutate({ taskId: t.id, done: !t.completed_at })}
                    className="flex w-full items-center gap-3 rounded-lg border bg-card p-3 text-left hover:bg-muted/50"
                    aria-pressed={Boolean(t.completed_at)}
                  >
                    {t.completed_at ? <CheckCircle2 className="size-5 text-success" /> : <Circle className="size-5 text-muted-foreground" />}
                    <span className={cn("flex-1 text-sm", t.completed_at && "text-muted-foreground line-through")}>{t.title}</span>
                    {t.due_at && !t.completed_at ? <span className={cn("text-xs", taskDue.overdue ? "font-semibold text-danger" : "text-muted-foreground")}>{taskDue.text}</span> : null}
                  </button>
                );
              })}
            </TabsContent>
          </Tabs>

          <section>
            <h3 className="mb-2 text-sm font-semibold">History</h3>
            <ol className="space-y-2">
              {detail.activities.map((a) => (
                <li key={a.id}>
                  <Card className={cn("flex items-start justify-between gap-2 p-3", a.voided && "opacity-60")}>
                    <div className="min-w-0">
                      <p className={cn("text-sm", a.voided && "line-through")}>{a.summary}</p>
                      <p className="text-xs text-muted-foreground">
                        {formatDateTime(a.occurred_at)}{a.actor_name ? ` · ${a.actor_name}` : ""}{a.contact_name ? ` · with ${a.contact_name}` : ""}{a.voided ? " · marked as a mistake" : ""}
                      </p>
                    </div>
                    {!a.voided && (meta.data?.loggable_activities.some((x) => x.value === a.type) || a.type === "note") ? (
                      <Button variant="ghost" size="sm" onClick={() => setVoiding(a.id)}><Undo2 /> Mistake</Button>
                    ) : null}
                  </Card>
                </li>
              ))}
            </ol>
          </section>

          <ReasonDialog
            target={reasonStage ? { card: detail.card, stage: reasonStage } : null}
            onCancel={() => setReasonStage(null)}
            onConfirm={async (code, reasonNote) => {
              if (reasonStage) await move.mutateAsync({ stageId: reasonStage.id, code, note: reasonNote });
              setReasonStage(null);
            }}
          />
          <ConfirmDialog
            open={voiding !== null}
            onOpenChange={(o) => {
              if (!o) {
                setVoiding(null);
                setVoidReason("");
              }
            }}
            title="Mark as a mistake?"
            description={
              <div className="space-y-2">
                <p>The entry stays in the history, crossed out, and stops counting in reports.</p>
                <Input aria-label="Reason" placeholder="Why, e.g. logged twice" value={voidReason} onChange={(e) => setVoidReason(e.target.value)} />
              </div>
            }
            confirmLabel="Mark as mistake"
            onConfirm={async () => {
              if (voiding) await voidActivity.mutateAsync({ activityId: voiding, reason: voidReason || "Recorded by mistake" });
              setVoidReason("");
            }}
          />
          <HandoffDialog open={handoff} onOpenChange={setHandoff} opportunity={detail} onRecorded={() => client.invalidateQueries({ queryKey: ["opportunity", id] })} />
        </div>
      ) : null}
    </Sheet>
  );
}
