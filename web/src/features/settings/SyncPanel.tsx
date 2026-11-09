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
import { AlertTriangle, Copy, FileUp, Lock, RefreshCcw, Send } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardHeader } from "@/components/ui/card";
import { Field, Input, NativeSelect } from "@/components/ui/form";
import { ErrorState, Progress, Switch } from "@/components/ui/misc";
import { api, download } from "@/lib/api";
import type { ImportPreview, JobRef, SyncInfo } from "@/lib/api-types";
import { formatDateTime, humanize } from "@/lib/format";
import { copyText, showError } from "@/lib/hooks";
import { useJob } from "@/lib/jobs";
import { plural } from "@/lib/utils";

interface ExportResult {
  file_name: string;
  mode: string;
  records: number;
  events: number;
  encrypted: boolean;
}

const ACTION_LABELS: Record<string, string> = {
  insert: "New",
  update: "Updated",
  skip: "Already up to date",
  converge: "Same on both computers",
  conflict: "Conflicts to review",
  pending: "Waiting for other changes",
  duplicate: "Duplicates (kept yours)",
};

function show(value: unknown): string {
  if (value === null || value === undefined || value === "") return "(empty)";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function SyncPanel() {
  const client = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const info = useQuery({ queryKey: ["sync"], queryFn: () => api.get<SyncInfo>("/sync") });
  const [full, setFull] = useState(false);
  const [encrypt, setEncrypt] = useState(true);
  const [passphrase, setPassphrase] = useState("");
  const [recipientId, setRecipientId] = useState("");
  const [recipientName, setRecipientName] = useState("");
  const [exported, setExported] = useState<ExportResult | null>(null);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importPass, setImportPass] = useState("");
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [previewError, setPreviewError] = useState<unknown>(null);
  const [staging, setStaging] = useState(false);
  const [choices, setChoices] = useState<Record<string, Record<string, "local" | "incoming">>>({});

  const exporter = useJob<ExportResult>(() =>
    api.post<JobRef>("/sync/export", {
      full,
      passphrase: encrypt ? passphrase : null,
      recipient_device_id: recipientId || null,
      recipient_name: recipientName || null,
    }),
  );
  const importer = useJob<{ counts: Record<string, number>; pending_applied: number; pending_remaining: number; backup: string | null }>(() =>
    api.post<JobRef>(`/sync/import/${preview?.token}/apply`, { resolutions: choices }),
  );

  const doExport = async () => {
    try {
      const result = await exporter.start();
      setExported(result);
      await info.refetch();
      await download(`/sync/exports/${encodeURIComponent(result.file_name)}`, undefined, result.file_name);
    } catch (error) {
      showError(error);
    }
  };

  const stage = async () => {
    if (!importFile) return;
    setStaging(true);
    setPreviewError(null);
    try {
      const form = new FormData();
      form.append("package", importFile);
      form.append("passphrase", importPass);
      const result = await api.post<ImportPreview>("/sync/import", form);
      setPreview(result);
      setChoices(Object.fromEntries(result.conflicts.map((c) => [c.key, Object.fromEntries(c.differences.map((d) => [d.field, "local" as const]))])));
    } catch (error) {
      setPreviewError(error);
    } finally {
      setStaging(false);
    }
  };

  const apply = async () => {
    try {
      const result = await importer.start();
      toast.success("Changes imported", {
        description: `${plural(result.counts.insert ?? 0, "new record")}, ${plural(result.counts.update ?? 0, "update")}${result.pending_remaining ? `, ${result.pending_remaining} waiting` : ""}.`,
      });
      setPreview(null);
      setImportFile(null);
      await client.invalidateQueries();
    } catch (error) {
      showError(error);
    }
  };

  const setAll = (value: "local" | "incoming") =>
    preview && setChoices(Object.fromEntries(preview.conflicts.map((c) => [c.key, Object.fromEntries(c.differences.map((d) => [d.field, value]))])));

  const shortPass = encrypt && passphrase.length < 10;

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader title="How collaboration works" description="No server is needed. You and your colleagues exchange change files." />
        <div className="space-y-2 p-5 pt-3 text-sm">
          <p>1. <strong>Export</strong> your changes to a file and send it through a company-approved channel (for example your company email or shared drive).</p>
          <p>2. Your colleague <strong>imports</strong> it. tg_sales shows exactly what will change, asks you to decide when the same record was edited on both computers, and never creates duplicates when a file is imported twice.</p>
          <p className="flex flex-wrap items-center gap-2 text-muted-foreground">
            This computer's sync ID: <code className="rounded bg-muted px-1.5 py-0.5 text-xs">{info.data?.device_id ?? "…"}</code>
            <Button size="sm" variant="ghost" onClick={async () => info.data && (await copyText(info.data.device_id)) && toast.success("Sync ID copied")}><Copy /> Copy</Button>
          </p>
          {info.data?.pending ? <p className="text-warning">{plural(info.data.pending, "received record")} still wait for records from another package.</p> : null}
        </div>
      </Card>

      <div className="grid gap-5 xl:grid-cols-2">
        <Card>
          <CardHeader title="Export changes" description="Creates tg_sales_sync_….zip and downloads it." />
          <div className="space-y-3 p-5 pt-3">
            <Field label="What to include">
              {(p) => (
                <NativeSelect {...p} value={full ? "full" : "delta"} onChange={(e) => setFull(e.target.value === "full")}>
                  <option value="delta">Changes since my last export</option>
                  <option value="full">Everything (for a new colleague)</option>
                </NativeSelect>
              )}
            </Field>
            <label className="flex items-center gap-2 text-sm"><Switch checked={encrypt} onCheckedChange={setEncrypt} /> <Lock className="size-4" /> Encrypt with a passphrase (recommended)</label>
            {encrypt ? (
              <Field label="Passphrase" error={passphrase && shortPass ? "Use at least 10 characters." : undefined} hint="Share it separately (for example by phone), never in the same message as the file.">
                {(p) => <Input {...p} type="password" autoComplete="new-password" value={passphrase} onChange={(e) => setPassphrase(e.target.value)} />}
              </Field>
            ) : (
              <p className="flex gap-2 rounded-lg bg-warning-soft p-2 text-sm text-warning"><AlertTriangle className="size-4 shrink-0" /> Without encryption, anyone who gets the file can read the contact details in it.</p>
            )}
            <details className="text-sm">
              <summary className="cursor-pointer text-muted-foreground">Prepare for a specific colleague (optional)</summary>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                <Input aria-label="Colleague's name" placeholder="Colleague's name" value={recipientName} onChange={(e) => setRecipientName(e.target.value)} />
                <Input aria-label="Colleague's sync ID" placeholder="Their sync ID" value={recipientId} onChange={(e) => setRecipientId(e.target.value)} />
              </div>
            </details>
            {exporter.state.status === "running" ? <Progress value={exporter.state.percent} label={exporter.state.message} /> : null}
            <Button onClick={doExport} loading={exporter.running} disabled={shortPass}><Send /> Export and download</Button>
            {exported ? (
              <p className="text-sm text-success">
                Exported {plural(exported.records, "record")} and {plural(exported.events, "activity", "activities")} to {exported.file_name}{exported.encrypted ? " (encrypted)" : ""}.{" "}
                <button type="button" className="underline" onClick={() => download(`/sync/exports/${encodeURIComponent(exported.file_name)}`, undefined, exported.file_name).catch(showError)}>Download again</button>
              </p>
            ) : null}
          </div>
        </Card>

        <Card>
          <CardHeader title="Import changes" description="Nothing changes until you confirm. A backup is made first." />
          <div className="space-y-3 p-5 pt-3">
            <input ref={input} type="file" accept=".zip,application/zip" hidden onChange={(e) => { setImportFile(e.target.files?.[0] ?? null); setPreview(null); e.target.value = ""; }} />
            <div className="flex flex-wrap items-center gap-2">
              <Button variant="outline" onClick={() => input.current?.click()}><FileUp /> Choose package…</Button>
              <span className="truncate text-sm text-muted-foreground">{importFile?.name ?? "No file selected"}</span>
            </div>
            <Field label="Passphrase (if the package is encrypted)">{(p) => <Input {...p} type="password" autoComplete="off" value={importPass} onChange={(e) => setImportPass(e.target.value)} />}</Field>
            <Button onClick={stage} loading={staging} disabled={!importFile}><RefreshCcw /> Check package</Button>
            {previewError ? <ErrorState error={previewError} /> : null}
          </div>
        </Card>
      </div>

      {preview ? (
        <Card>
          <CardHeader
            title={`Changes from ${preview.source_actor_name}`}
            description={`${preview.file_name} · made ${formatDateTime(preview.created_at)} · ${preview.mode === "full" ? "everything" : "changes only"}${preview.encrypted ? " · encrypted" : ""}`}
          />
          <div className="space-y-4 p-5 pt-3">
            {preview.warnings.map((w) => <p key={w} className="flex gap-2 rounded-lg bg-warning-soft p-2 text-sm text-warning"><AlertTriangle className="size-4 shrink-0" />{w}</p>)}
            <div className="flex flex-wrap gap-2">
              {Object.entries(preview.counts).map(([action, count]) => <Badge key={action} tone={action === "conflict" ? "warning" : action === "insert" ? "success" : "neutral"}>{ACTION_LABELS[action] ?? humanize(action)}: {count}</Badge>)}
            </div>
            {preview.possible_duplicates.length ? (
              <div className="rounded-lg border p-3 text-sm">
                <p className="font-medium">Possible duplicates (not merged automatically)</p>
                <ul className="mt-1 list-disc pl-5 text-muted-foreground">
                  {preview.possible_duplicates.map((d) => <li key={d.incoming_id}>{d.incoming_label} looks like your {d.local_label} ({d.reason})</li>)}
                </ul>
              </div>
            ) : null}
            {preview.conflicts.length ? (
              <div className="space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm font-medium">Edited on both computers: choose which value to keep</p>
                  <div className="flex gap-2">
                    <Button size="sm" variant="outline" onClick={() => setAll("local")}>Keep all mine</Button>
                    <Button size="sm" variant="outline" onClick={() => setAll("incoming")}>Take all theirs</Button>
                  </div>
                </div>
                {preview.conflicts.map((conflict) => (
                  <Card key={conflict.key} className="p-3">
                    <p className="mb-2 text-sm font-medium">{conflict.label}</p>
                    <div className="space-y-2">
                      {conflict.differences.map((d) => (
                        <fieldset key={d.field} className="grid gap-2 rounded-lg bg-muted/40 p-2 text-sm sm:grid-cols-[140px_1fr_1fr]">
                          <legend className="sr-only">{humanize(d.field)}</legend>
                          <span className="font-medium">{humanize(d.field)}</span>
                          {(["local", "incoming"] as const).map((side) => (
                            <label key={side} className="flex cursor-pointer items-start gap-2 rounded-md border bg-card p-2 has-[:checked]:border-primary has-[:checked]:ring-1 has-[:checked]:ring-primary">
                              <input
                                type="radio"
                                name={`${conflict.key}-${d.field}`}
                                checked={choices[conflict.key]?.[d.field] === side}
                                onChange={() => setChoices({ ...choices, [conflict.key]: { ...choices[conflict.key], [d.field]: side } })}
                              />
                              <span><span className="block text-xs text-muted-foreground">{side === "local" ? "Mine" : "Theirs"}</span>{show(side === "local" ? d.local : d.incoming)}</span>
                            </label>
                          ))}
                        </fieldset>
                      ))}
                    </div>
                  </Card>
                ))}
              </div>
            ) : null}
            {importer.state.status === "running" ? <Progress value={importer.state.percent} label={importer.state.message} /> : null}
            <div className="flex flex-wrap gap-2">
              <Button onClick={apply} loading={importer.running}>Import these changes</Button>
              <Button variant="outline" onClick={() => { void api.delete(`/sync/import/${preview.token}`); setPreview(null); }}>Cancel</Button>
            </div>
          </div>
        </Card>
      ) : null}

      <Card>
        <CardHeader title="Sync history" />
        <ul className="divide-y px-5 pb-4">
          {(info.data?.history ?? []).map((entry) => (
            <li key={entry.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-sm">
              <span><Badge tone={entry.kind === "export" ? "purple" : "info"}>{entry.kind === "export" ? "Exported" : "Imported"}</Badge> {entry.file_name}</span>
              <span className="text-xs text-muted-foreground">{formatDateTime(entry.at)}</span>
            </li>
          ))}
          {info.data?.history.length === 0 ? <li className="py-3 text-sm text-muted-foreground">No packages exported or imported yet.</li> : null}
        </ul>
      </Card>
    </div>
  );
}
