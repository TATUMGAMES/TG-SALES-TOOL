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
import { AlertTriangle, CheckCircle2, FileSpreadsheet, History, Undo2, Upload } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge, Card } from "@/components/ui/card";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { Field, NativeSelect } from "@/components/ui/form";
import { ErrorState, Progress, Switch, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/misc";
import { ApiError, api, download } from "@/lib/api";
import type { DateOrder, FieldView, ImportHistoryEntry, JobRef, UploadResult } from "@/lib/api-types";

interface TableView {
  headers: string[];
  sample: string[][];
  row_count: number;
  description: string;
  notes: string[];
  reliable: boolean;
  problem: string | null;
  sheet: string | null;
  suggestions: { column: number; header: string; field: string | null; confidence: number; note: string }[];
}
import { formatBytes, formatDateTime } from "@/lib/format";
import { useJob } from "@/lib/jobs";
import { showError, useAction } from "@/lib/hooks";
import { cn, plural } from "@/lib/utils";
import { CustomFieldDialog } from "../settings/CustomFieldsPanel";

type Step = "file" | "mapping" | "review" | "preview" | "done";

const CREATE_FIELD = "__create_custom_field__";
const TYPE_NAMES: Record<string, string> = { date: "a date", url: "a web address", number: "a number", boolean: "yes or no" };

/** A quick check of example values so obviously wrong choices stand out before importing. */
function looksLike(type: string, value: string): boolean {
  const text = value.trim();
  if (!text) return true;
  switch (type) {
    case "date":
      return /^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}$/.test(text) || /^\d{1,2}[-/.]\d{1,2}[-/.]\d{4}$/.test(text) || (/\d{4}/.test(text) && !Number.isNaN(Date.parse(text)));
    case "url":
      return /^(https?:\/\/)?[^\s/:]+\.[^\s/:]{2,}(:\d+)?([/?#]\S*)?$/i.test(text);
    case "number":
      return !Number.isNaN(Number(text.replace(/[\s,$€£¥]/g, "")));
    case "boolean":
      return /^(y|yes|n|no|true|false|1|0|x|✓|✔|✗|☑|☐)$/i.test(text);
    default:
      return true;
  }
}

interface Group {
  key: string;
  name: string;
  rows: number[];
  action: string;
  effective_action: string;
  effective_target_id: string | null;
  reason: string;
  target_name: string | null;
  needs_decision: boolean;
  decision: string | null;
  candidates: { id: string; name: string; reason: string; strength: string }[];
  contacts: number;
  games: number;
}

interface IssueView {
  row: number;
  severity: string;
  column: string;
  message: string;
}

interface PlanView {
  groups: Group[];
  unresolved: number;
  error_rows: number;
  blank_rows: number;
  issues: IssueView[];
  issue_count: number;
  previous_imports: { at: string; file_name: string }[];
}

interface Outcome {
  committed: boolean;
  counts: Record<string, number>;
  issues: IssueView[];
  issue_count: number;
  backup?: string | null;
}

const ACTION_LABEL: Record<string, string> = { create: "New prospect", update: "Add to existing", skip: "Skip", review: "Needs a decision" };
const ACTION_TONE: Record<string, "success" | "info" | "neutral" | "warning"> = { create: "success", update: "info", skip: "neutral", review: "warning" };

function IssueList({ issues, total }: { issues: IssueView[]; total: number }) {
  if (!issues.length) return null;
  return (
    <div className="max-h-48 overflow-y-auto rounded-lg border">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-muted text-left">
          <tr><th className="px-2 py-1">Row</th><th className="px-2 py-1">Column</th><th className="px-2 py-1">Problem</th></tr>
        </thead>
        <tbody>
          {issues.map((issue, index) => (
            <tr key={index} className="border-t">
              <td className="px-2 py-1 tabular">{issue.row}</td>
              <td className="px-2 py-1">{issue.column}</td>
              <td className={cn("px-2 py-1", issue.severity === "error" && "text-danger")}>
                {issue.severity === "error" ? "Error: " : "Warning: "}{issue.message}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {total > issues.length ? <p className="p-2 text-xs text-muted-foreground">… and {total - issues.length} more. Export the problems as CSV to see all.</p> : null}
    </div>
  );
}

export function ImportWizard({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const client = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const [step, setStep] = useState<Step>("file");
  const [upload, setUpload] = useState<UploadResult | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<unknown>(null);
  const [sheet, setSheet] = useState<string>("");
  const [table, setTable] = useState<TableView | null>(null);
  const [mapping, setMapping] = useState<Record<number, string>>({});
  const [dateOrder, setDateOrder] = useState<DateOrder>("auto");
  const [plan, setPlan] = useState<PlanView | null>(null);
  const [onlyUndecided, setOnlyUndecided] = useState(true);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [tab, setTab] = useState("import");
  const [undoId, setUndoId] = useState<string | null>(null);
  const [overwrite, setOverwrite] = useState(false);
  const [creating, setCreating] = useState<{ column: number; header: string } | null>(null);

  const fields = useQuery({ queryKey: ["import-fields"], queryFn: () => api.get<FieldView[]>("/imports/fields"), enabled: open });
  const history = useQuery({ queryKey: ["import-history"], queryFn: () => api.get<ImportHistoryEntry[]>("/imports/history"), enabled: open && tab === "history" });

  const sid = upload?.session_id ?? "";
  const reader = useJob<TableView>(() => api.post<JobRef>(`/imports/${sid}/read`, { sheet: sheet || null }));
  const planner = useJob<PlanView>(() =>
    api.post<JobRef>(`/imports/${sid}/plan`, {
      mappings: Object.entries(mapping).map(([column, field]) => ({ column: Number(column), field: field || null })),
      date_order: dateOrder,
      overwrite,
    }),
  );
  const previewer = useJob<Outcome>(() => api.post<JobRef>(`/imports/${sid}/preview`));
  const committer = useJob<Outcome>(() => api.post<JobRef>(`/imports/${sid}/commit`));
  const undo = useAction((jobId: string) => api.post<{ reverted: number; kept: number }>(`/imports/history/${jobId}/undo`), {
    invalidate: [["import-history"], ["prospects"]],
    success: (r) => `Import undone: ${plural(r.reverted, "change")} reverted${r.kept ? `, ${r.kept} kept because they were edited since` : ""}.`,
  });

  const reset = () => {
    if (sid && step !== "done") void api.delete(`/imports/${sid}`).catch(() => undefined);
    setStep("file");
    setUpload(null);
    setTable(null);
    setPlan(null);
    setOutcome(null);
    setMapping({});
    setSheet("");
    setOverwrite(false);
    setUploadError(null);
    reader.reset();
    planner.reset();
    previewer.reset();
    committer.reset();
  };

  const close = (next: boolean) => {
    if (!next) {
      if (reader.running || planner.running || previewer.running || committer.running) return;
      reset();
    }
    onOpenChange(next);
  };

  const chooseFile = async (file: File) => {
    setUploading(true);
    setUploadError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const result = await api.post<UploadResult>("/imports/upload", form);
      setUpload(result);
      setSheet(result.sheets[0] ?? "");
    } catch (error) {
      setUploadError(error);
    } finally {
      setUploading(false);
    }
  };

  const read = async () => {
    try {
      const result = await reader.start();
      setTable(result);
      setMapping(Object.fromEntries(result.suggestions.map((s) => [s.column, s.field ?? ""])));
      setStep("mapping");
    } catch (error) {
      showError(error);
    }
  };

  const runPlan = async () => {
    try {
      const result = await planner.start();
      setPlan(result);
      setOnlyUndecided(result.unresolved > 0);
      setStep("review");
    } catch (error) {
      showError(error);
    }
  };

  const decide = async (body: object) => {
    try {
      setPlan(await api.post<PlanView>(`/imports/${sid}/decisions`, body));
    } catch (error) {
      showError(error);
    }
  };

  const runPreview = async () => {
    try {
      setOutcome(await previewer.start());
      setStep("preview");
    } catch (error) {
      showError(error);
    }
  };

  const commit = async () => {
    try {
      const result = await committer.start();
      setOutcome(result);
      setStep("done");
      await client.invalidateQueries({ queryKey: ["prospects"] });
      await client.invalidateQueries({ queryKey: ["import-history"] });
      toast.success("Import saved");
    } catch (error) {
      showError(error);
    }
  };

  const groups = useMemo(() => (plan?.groups ?? []).filter((g) => !onlyUndecided || g.action === "review"), [plan, onlyUndecided]);
  const job = [reader, planner, previewer, committer].find((j) => j.running);
  const progress = job?.state.status === "running" ? job.state : null;
  const mappedFields = new Set(Object.values(mapping).filter(Boolean));
  const fieldInfo = new Map((fields.data ?? []).map((f) => [f.field, f]));
  const usedTwice = Object.values(mapping).filter((f, i, all) => f && all.indexOf(f) !== i && !fieldInfo.get(f)?.multiple);
  const fieldGroups = [...new Set((fields.data ?? []).map((f) => f.group ?? "Standard fields"))].map(
    (group) => [group, (fields.data ?? []).filter((f) => (f.group ?? "Standard fields") === group)] as const,
  );
  const columnNote = (column: number): { text: string; tone: "danger" | "warning" } | null => {
    const target = mapping[column];
    if (!target || !table) return null;
    const info = fieldInfo.get(target);
    if (!info) return null;
    const others = Object.entries(mapping).filter(([c, f]) => f === target && Number(c) !== column);
    if (others.length && !info.multiple) {
      const names = others.map(([c]) => table.headers[Number(c)] || `column ${Number(c) + 1}`).join(", ");
      return { text: `Also chosen for ${names}. Each field can be used by one column.`, tone: "danger" };
    }
    const type = info.value_type ?? "text";
    const examples = table.sample.map((row) => row[column] ?? "").filter((v) => v.trim()).slice(0, 10);
    const bad = examples.filter((v) => !looksLike(type, v));
    if (bad.length && TYPE_NAMES[type]) {
      return { text: `${plural(bad.length, "example")} ${bad.length === 1 ? "does" : "do"} not look like ${TYPE_NAMES[type]} (e.g. “${bad[0]}”). Those values will be reported and left empty.`, tone: "warning" };
    }
    return null;
  };

  const footer = (() => {
    if (tab === "history") return <Button variant="outline" onClick={() => close(false)}>Close</Button>;
    if (progress) return <Button variant="outline" onClick={() => job?.cancel()}>Cancel</Button>;
    switch (step) {
      case "file":
        return <Button onClick={read} disabled={!upload}>Continue</Button>;
      case "mapping":
        return (
          <>
            <Button variant="outline" onClick={() => setStep("file")}>Back</Button>
            <Button onClick={runPlan} disabled={!mappedFields.has("organization_name") || usedTwice.length > 0}>Check rows</Button>
          </>
        );
      case "review":
        return (
          <>
            <Button variant="outline" onClick={() => setStep("mapping")}>Back</Button>
            <Button onClick={runPreview} disabled={(plan?.unresolved ?? 0) > 0}>Preview result</Button>
          </>
        );
      case "preview":
        return (
          <>
            <Button variant="outline" onClick={() => setStep("review")}>Back</Button>
            <Button onClick={commit}>Import now</Button>
          </>
        );
      default:
        return (
          <>
            <Button variant="outline" onClick={reset}>Import another file</Button>
            <Button onClick={() => close(false)}>Done</Button>
          </>
        );
    }
  })();

  const stepNames: [Step, string][] = [["file", "File"], ["mapping", "Columns"], ["review", "Matches"], ["preview", "Preview"], ["done", "Result"]];
  const stepIndex = stepNames.findIndex(([s]) => s === step);

  return (
    <Dialog open={open} onOpenChange={close} size="xl" title="Import prospects" description="CSV, Excel (.xlsx) or text files. Nothing is saved until you choose “Import now”." footer={footer}>
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="mb-4">
          <TabsTrigger value="import"><Upload className="mr-1 inline size-4" /> Import a file</TabsTrigger>
          <TabsTrigger value="history"><History className="mr-1 inline size-4" /> Import history</TabsTrigger>
        </TabsList>

        <TabsContent value="import" className="space-y-4">
          <ol className="flex flex-wrap gap-2 text-xs" aria-label="Steps">
            {stepNames.map(([s, label], index) => (
              <li key={s} aria-current={s === step ? "step" : undefined} className={cn("rounded-full px-3 py-1", index === stepIndex ? "bg-primary text-primary-foreground" : index < stepIndex ? "bg-success-soft text-success" : "bg-muted text-muted-foreground")}>
                {index + 1}. {label}
              </li>
            ))}
          </ol>

          {progress ? <Progress value={progress.percent} label={progress.message || "Working…"} /> : null}

          {step === "file" ? (
            <div className="space-y-4">
              <input
                ref={fileInput}
                type="file"
                accept=".csv,.xlsx,.txt,text/csv,text/plain"
                hidden
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void chooseFile(file);
                  e.target.value = "";
                }}
              />
              <button
                type="button"
                onClick={() => fileInput.current?.click()}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  const file = e.dataTransfer.files?.[0];
                  if (file) void chooseFile(file);
                }}
                className="flex w-full flex-col items-center gap-2 rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors hover:border-primary hover:bg-primary-soft/40"
              >
                <FileSpreadsheet className="size-8 text-primary" />
                <span className="font-medium">{uploading ? "Checking the file…" : "Choose a file or drop it here"}</span>
                <span className="text-sm text-muted-foreground">CSV, XLSX or TXT, up to 50 MB. Macro-enabled and old .xls files are refused for safety.</span>
              </button>
              {uploadError ? <ErrorState error={uploadError} /> : null}
              {upload ? (
                <Card className="space-y-3 p-4">
                  <p className="flex items-center gap-2 font-medium"><CheckCircle2 className="size-4 text-success" /> {upload.file_name} <Badge>{upload.kind.toUpperCase()}</Badge> <span className="text-sm text-muted-foreground">{formatBytes(upload.size_bytes)}</span></p>
                  {upload.warnings.map((w) => <p key={w} className="flex gap-2 text-sm text-warning"><AlertTriangle className="size-4 shrink-0" />{w}</p>)}
                  {upload.sheets.length > 1 ? (
                    <Field label="Sheet">
                      {(p) => (
                        <NativeSelect {...p} value={sheet} onChange={(e) => setSheet(e.target.value)}>
                          {upload.sheets.map((s) => <option key={s} value={s}>{s}</option>)}
                        </NativeSelect>
                      )}
                    </Field>
                  ) : null}
                </Card>
              ) : null}
            </div>
          ) : null}

          {step === "mapping" && table ? (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">{table.description} · {plural(table.row_count, "row")}</p>
              {table.notes.map((n) => <p key={n} className="text-sm text-warning">{n}</p>)}
              {!table.reliable ? <ErrorState error={new ApiError(table.problem ?? "This file could not be read reliably.", "Save it as CSV or XLSX with one row per contact, then try again.", "unreliable", 400)} /> : null}
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Dates like 03/04/2027 mean" hint="Ambiguous dates are saved as unknown unless you choose.">
                  {(p) => (
                    <NativeSelect {...p} value={dateOrder} onChange={(e) => setDateOrder(e.target.value as DateOrder)}>
                      <option value="auto">Ask me (keep ambiguous dates unknown)</option>
                      <option value="month_first">Month first (US: 03/04 = March 4)</option>
                      <option value="day_first">Day first (03/04 = 3 April)</option>
                    </NativeSelect>
                  )}
                </Field>
              </div>
              <label className="flex items-start gap-2 rounded-lg border p-3 text-sm">
                <Switch checked={overwrite} onCheckedChange={setOverwrite} aria-label="Replace existing values" />
                <span>
                  <span className="font-medium">Replace existing values with the file's values</span>
                  <span className="block text-xs text-muted-foreground">
                    Off (recommended): for prospects you already have, the import only fills empty fields and reports different values. On: different values of the website, type, location,
                    country, review date, qualification source URL, contact job titles, game details and custom fields are replaced. Names, notes, tags and outreach status are never replaced.
                    Undo restores replaced values.
                  </span>
                </span>
              </label>
              <p className="text-xs text-muted-foreground">Suggestions are only a starting point: check every column. Columns set to “Don't import” are left out; nothing else is dropped without a warning.</p>
              {!mappedFields.has("organization_name") ? <p className="text-sm font-medium text-danger">Choose which column holds the studio or company name.</p> : null}
              {usedTwice.length ? <p className="text-sm font-medium text-danger">Each field can be used by one column only.</p> : null}
              <div className="overflow-x-auto rounded-lg border">
                <table className="w-full text-sm">
                  <thead className="bg-muted text-left text-xs uppercase text-muted-foreground">
                    <tr><th className="px-3 py-2">Column in your file</th><th className="px-3 py-2">Examples</th><th className="px-3 py-2">Save as</th><th className="px-3 py-2">Match</th></tr>
                  </thead>
                  <tbody>
                    {table.suggestions.map((s) => (
                      <tr key={s.column} className="border-t align-top">
                        <td className="px-3 py-2 font-medium">{s.header || `Column ${s.column + 1}`}</td>
                        <td className="max-w-56 px-3 py-2 text-xs text-muted-foreground">
                          {table.sample.slice(0, 3).map((row) => row[s.column]).filter(Boolean).join(" · ") || "—"}
                        </td>
                        <td className="px-3 py-2">
                          <NativeSelect
                            aria-label={`Field for ${s.header}`}
                            value={mapping[s.column] ?? ""}
                            onChange={(e) => {
                              if (e.target.value === CREATE_FIELD) setCreating({ column: s.column, header: s.header });
                              else setMapping({ ...mapping, [s.column]: e.target.value });
                            }}
                          >
                            <option value="">Don't import</option>
                            {fieldGroups.map(([group, items]) => (
                              <optgroup key={group} label={group}>
                                {items.map((f) => <option key={f.field} value={f.field}>{f.label}</option>)}
                              </optgroup>
                            ))}
                            <option value={CREATE_FIELD}>+ Create custom field…</option>
                          </NativeSelect>
                          {(() => {
                            const note = columnNote(s.column);
                            return note ? <p className={cn("mt-1 text-xs", note.tone === "danger" ? "font-medium text-danger" : "text-warning")}>{note.text}</p> : null;
                          })()}
                        </td>
                        <td className="px-3 py-2 text-xs">
                          {mapping[s.column] && mapping[s.column] !== (s.field ?? "") ? (
                            <Badge tone="info">Your choice</Badge>
                          ) : s.field ? (
                            <Badge tone={s.confidence >= 0.9 ? "success" : "warning"}>Suggested · {Math.round(s.confidence * 100)}% sure</Badge>
                          ) : (
                            <span className="text-muted-foreground">{s.note || "Not recognized"}</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}

          {step === "review" && plan ? (
            <div className="space-y-3">
              <div className="flex flex-wrap gap-2 text-sm">
                <Badge tone="info">{plural(plan.groups.length, "prospect")} found</Badge>
                {plan.unresolved ? <Badge tone="warning">{plan.unresolved} need a decision</Badge> : <Badge tone="success">All decided</Badge>}
                {plan.error_rows ? <Badge tone="danger">{plural(plan.error_rows, "row")} with errors (skipped)</Badge> : null}
                {plan.blank_rows ? <Badge>{plural(plan.blank_rows, "blank row")}</Badge> : null}
              </div>
              {plan.previous_imports.length ? (
                <p className="rounded-lg bg-info-soft p-2 text-sm text-info">
                  Some of these rows were imported before ({plan.previous_imports.map((p) => p.file_name).join(", ")}). Unchanged rows are skipped automatically.
                </p>
              ) : null}
              <div className="flex flex-wrap items-center gap-2">
                <label className="flex items-center gap-2 text-sm"><Switch checked={onlyUndecided} onCheckedChange={setOnlyUndecided} /> Only show prospects that need a decision</label>
                {plan.unresolved ? (
                  <>
                    <Button size="sm" variant="outline" onClick={() => decide({ all_unresolved: "create" })}>Create new for all undecided</Button>
                    <Button size="sm" variant="outline" onClick={() => decide({ all_unresolved: "skip" })}>Skip all undecided</Button>
                  </>
                ) : null}
              </div>
              <div className="max-h-[40vh] space-y-2 overflow-y-auto">
                {groups.map((group) => (
                  <Card key={group.key} className={cn("p-3", group.needs_decision && "border-warning")}>
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <p className="font-medium">{group.name}</p>
                        <p className="text-xs text-muted-foreground">
                          Rows {group.rows.slice(0, 6).join(", ")}{group.rows.length > 6 ? "…" : ""} · {plural(group.contacts, "contact")} · {plural(group.games, "game")}
                        </p>
                        <p className="mt-1 text-sm">{group.reason}</p>
                      </div>
                      <Badge tone={ACTION_TONE[group.effective_action] ?? "neutral"}>
                        {group.needs_decision ? "Needs a decision" : ACTION_LABEL[group.effective_action]}
                        {group.effective_action === "update" && group.target_name ? `: ${group.target_name}` : ""}
                      </Badge>
                    </div>
                    {group.action === "review" ? (
                      <div className="mt-2 flex flex-wrap gap-2">
                        <Button size="sm" variant={group.decision === "create" ? "default" : "outline"} onClick={() => decide({ decisions: [{ group_key: group.key, decision: "create" }] })}>Create new</Button>
                        {group.candidates.map((c) => (
                          <Button
                            key={c.id}
                            size="sm"
                            variant={group.decision === "merge" && group.effective_target_id === c.id ? "default" : "outline"}
                            onClick={() => decide({ decisions: [{ group_key: group.key, decision: "merge", target_id: c.id }] })}
                          >
                            Add to {c.name} <span className="text-xs opacity-80">({c.reason})</span>
                          </Button>
                        ))}
                        <Button size="sm" variant={group.decision === "skip" ? "default" : "outline"} onClick={() => decide({ decisions: [{ group_key: group.key, decision: "skip" }] })}>Skip</Button>
                      </div>
                    ) : null}
                  </Card>
                ))}
                {groups.length === 0 ? <p className="text-sm text-muted-foreground">Nothing needs a decision.</p> : null}
              </div>
              <IssueList issues={plan.issues} total={plan.issue_count} />
              {plan.issue_count ? (
                <Button size="sm" variant="outline" onClick={() => download(`/imports/${sid}/problems.csv`, undefined, "import_problems.csv").catch(showError)}>
                  Export problems as CSV
                </Button>
              ) : null}
            </div>
          ) : null}

          {(step === "preview" || step === "done") && outcome ? (
            <div className="space-y-3">
              <p className="font-medium">{step === "done" ? "Import saved." : "This is exactly what will happen:"}</p>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {[
                  ["Rows imported", outcome.counts.rows_imported],
                  ["Rows skipped", outcome.counts.rows_skipped],
                  ["Rows failed", outcome.counts.rows_failed ?? outcome.counts.error_rows],
                  ["Warnings", outcome.counts.warnings],
                  ["New prospects", outcome.counts.organizations_created],
                  ["Updated prospects", outcome.counts.organizations_updated],
                  ["New contacts", outcome.counts.contacts_created],
                  ["New games", outcome.counts.games_created],
                  ...(overwrite ? [["Values replaced", outcome.counts.values_replaced]] : []),
                ].map(([label, value]) => (
                  <Card key={String(label)} className="p-3">
                    <p className="text-xs text-muted-foreground">{label}</p>
                    <p className="tabular text-xl font-semibold">{Number(value ?? 0).toLocaleString()}</p>
                  </Card>
                ))}
              </div>
              <p className="text-sm text-muted-foreground">
                {overwrite
                  ? "Different existing values are replaced with the file's values (never names, notes, tags or outreach status)."
                  : "Existing values are not overwritten; the import only adds missing information."}{" "}
                Skipped rows changed nothing (already present or chosen to skip); failed rows are listed below with the reason. You can undo an import from Import history.
              </p>
              {outcome.backup ? <p className="text-xs text-muted-foreground">A backup was saved first ({outcome.backup}).</p> : null}
              <IssueList issues={outcome.issues} total={outcome.issue_count} />
            </div>
          ) : null}
        </TabsContent>

        <TabsContent value="history">
          {history.error ? <ErrorState error={history.error} /> : null}
          <div className="space-y-2">
            {(history.data ?? []).map((entry) => (
              <Card key={entry.id} className="flex flex-wrap items-center justify-between gap-2 p-3">
                <div>
                  <p className="font-medium">{entry.file_name}{entry.sheet_name ? ` › ${entry.sheet_name}` : ""}</p>
                  <p className="text-xs text-muted-foreground">
                    {formatDateTime(entry.started_at)} · {entry.created} new · {entry.updated} updated · {entry.skipped} skipped · {entry.errors} errors
                  </p>
                </div>
                {entry.undone_at ? (
                  <Badge>Undone {formatDateTime(entry.undone_at)}</Badge>
                ) : entry.status === "committed" ? (
                  <Button size="sm" variant="outline" onClick={() => setUndoId(entry.id)}><Undo2 /> Undo import</Button>
                ) : (
                  <Badge>{entry.status}</Badge>
                )}
              </Card>
            ))}
            {history.data?.length === 0 ? <p className="text-sm text-muted-foreground">No imports yet.</p> : null}
          </div>
        </TabsContent>
      </Tabs>
      <CustomFieldDialog
        open={creating !== null}
        initialLabel={creating?.header ?? ""}
        onOpenChange={(o) => !o && setCreating(null)}
        onCreated={(field) => {
          if (creating) setMapping((current) => ({ ...current, [creating.column]: field.target }));
          void fields.refetch();
        }}
      />
      <ConfirmDialog
        open={undoId !== null}
        onOpenChange={(o) => !o && setUndoId(null)}
        title="Undo this import?"
        description="Records the import created or changed are reverted. Anything edited since the import is kept."
        confirmLabel="Undo import"
        danger
        onConfirm={async () => {
          if (undoId) await undo.mutateAsync(undoId);
        }}
      />
    </Dialog>
  );
}
