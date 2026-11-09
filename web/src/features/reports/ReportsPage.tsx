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
import { Camera, Download, ExternalLink, FileBarChart2, FileText, FolderOpen, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { PeriodPicker, type PeriodValue } from "@/components/PeriodPicker";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardHeader } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Field, NativeSelect } from "@/components/ui/form";
import { EmptyState, ErrorState, LoadingRows, PageHeader, Progress, Switch } from "@/components/ui/misc";
import { api, apiUrl, download } from "@/lib/api";
import type { ActorChoice, JobRef, ReportInfo, SnapshotView } from "@/lib/api-types";
import { formatDate, formatDateTime } from "@/lib/format";
import { showError, useAction, useInfo } from "@/lib/hooks";
import { useJob } from "@/lib/jobs";
import { useLanes } from "@/lib/lanes";

export function ReportsPage() {
  const client = useQueryClient();
  const info = useInfo();
  const [period, setPeriod] = useState<PeriodValue>({ preset: "1m", start: "", end: "" });
  const [actor, setActor] = useState("");
  const [lane, setLane] = useState("");
  const lanes = useLanes();
  const [html, setHtml] = useState(true);
  const [deleting, setDeleting] = useState<ReportInfo | null>(null);
  const [deletingSnapshot, setDeletingSnapshot] = useState<SnapshotView | null>(null);
  const [selectedSnapshot, setSelectedSnapshot] = useState<string | null>(null);

  const people = useQuery({ queryKey: ["salespeople"], queryFn: () => api.get<ActorChoice[]>("/dashboard/salespeople") });
  const reports = useQuery({ queryKey: ["reports"], queryFn: () => api.get<ReportInfo[]>("/reports") });
  const snapshots = useQuery({ queryKey: ["snapshots"], queryFn: () => api.get<SnapshotView[]>("/snapshots") });
  const creator = useJob<{ report_id: string; pages: number }>(() =>
    api.post<JobRef>("/reports", {
      preset: period.preset,
      start: period.preset === "custom" ? period.start : null,
      end: period.preset === "custom" ? period.end : null,
      actor_id: actor || null,
      lane: lane || null,
      include_html: html,
    }),
  );
  const removeReport = useAction((id: string) => api.delete(`/reports/${id}`), { invalidate: [["reports"]], success: "Report deleted" });
  const removeSnapshot = useAction((id: string) => api.delete(`/snapshots/${id}`), { invalidate: [["snapshots"]], success: "Snapshot deleted" });
  const openFolder = useAction((id: string) => api.post(`/reports/${id}/open-folder`));

  const create = async () => {
    try {
      const result = await creator.start();
      await client.invalidateQueries({ queryKey: ["reports"] });
      toast.success(`Report created (${result.pages} pages)`, {
        action: { label: "Open PDF", onClick: () => window.open(apiUrl(`/reports/${result.report_id}/pdf`), "_blank", "noopener") },
      });
    } catch (error) {
      showError(error);
    }
  };

  const selected = snapshots.data?.find((s) => s.id === selectedSnapshot) ?? snapshots.data?.[0];

  return (
    <div className="space-y-5">
      <PageHeader title="Reports" description="PDF reports with CSV data for any period, and saved dashboard snapshots." />

      <Card>
        <CardHeader title="Create a report" description="Uses exactly the same numbers as the dashboard for the same period and filters." />
        <div className="flex flex-wrap items-end gap-3 p-5 pt-3">
          <PeriodPicker value={period} onChange={setPeriod} idPrefix="report" />
          <Field label="Salesperson" className="min-w-44">
            {(p) => (
              <NativeSelect {...p} value={actor} onChange={(e) => setActor(e.target.value)}>
                <option value="">Everyone</option>
                {(people.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </NativeSelect>
            )}
          </Field>
          <Field label="Sales lane" className="min-w-48">
            {(p) => (
              <NativeSelect {...p} value={lane} onChange={(e) => setLane(e.target.value)}>
                <option value="">All lanes</option>
                {lanes.all.map((l) => <option key={l.key} value={l.key}>{l.name}{l.archived ? " (archived)" : ""}</option>)}
              </NativeSelect>
            )}
          </Field>
          <label className="flex items-center gap-2 pb-2.5 text-sm"><Switch checked={html} onCheckedChange={setHtml} /> Also save an HTML preview</label>
          {creator.running ? (
            <Button variant="outline" onClick={() => creator.cancel()}>Cancel</Button>
          ) : (
            <Button onClick={create} disabled={period.preset === "custom" && !(period.start && period.end)}><FileBarChart2 /> Create report</Button>
          )}
        </div>
        {creator.state.status === "running" ? <div className="px-5 pb-5"><Progress value={creator.state.percent} label={creator.state.message || "Creating the report…"} /></div> : null}
        {creator.state.status === "cancelled" ? <p className="px-5 pb-5 text-sm text-muted-foreground">Report cancelled. Nothing was saved.</p> : null}
      </Card>

      <Card>
        <CardHeader title="Saved reports" description="Newest first. Downloads never replace files you already have." />
        <div className="p-5 pt-3">
          {reports.error ? <ErrorState error={reports.error} onRetry={() => reports.refetch()} /> : null}
          {reports.isLoading ? <LoadingRows rows={3} /> : null}
          {reports.data?.length === 0 ? <EmptyState icon={<FileText />} title="No reports yet" description="Create your first report above." /> : null}
          <div className="space-y-2">
            {(reports.data ?? []).map((r) => (
              <Card key={r.id} className="flex flex-wrap items-center justify-between gap-3 p-3">
                <div className="min-w-0">
                  <p className="font-medium">{r.title}</p>
                  <p className="text-xs text-muted-foreground">
                    {formatDate(r.period_start)} – {formatDate(r.period_end)} · {r.filter_text || "All salespeople, all lanes"} · created {formatDateTime(r.generated_at)}
                    {r.page_count ? ` · ${r.page_count} pages` : ""}
                  </p>
                  {!r.exists ? <Badge tone="warning" className="mt-1">Files missing from the reports folder</Badge> : null}
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {r.has_pdf ? <Button size="sm" asChild><a href={apiUrl(`/reports/${r.id}/pdf`)} target="_blank" rel="noopener noreferrer"><ExternalLink /> Open PDF</a></Button> : null}
                  {r.has_html ? <Button size="sm" variant="outline" asChild><a href={apiUrl(`/reports/${r.id}/html`)} target="_blank" rel="noopener noreferrer">Open HTML preview</a></Button> : null}
                  {r.exists ? <Button size="sm" variant="outline" onClick={() => download(`/reports/${r.id}/download`).catch(showError)}><Download /> Download all</Button> : null}
                  {r.exists && info.data?.desktop_integration ? <Button size="sm" variant="ghost" onClick={() => openFolder.mutate(r.id)}><FolderOpen /> Show files</Button> : null}
                  <Button size="sm" variant="ghost" aria-label={`Delete report ${r.title}`} onClick={() => setDeleting(r)}><Trash2 /></Button>
                </div>
                {r.csv_files.length ? (
                  <details className="w-full text-xs">
                    <summary className="cursor-pointer text-muted-foreground">CSV data files ({r.csv_files.length})</summary>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {r.csv_files.map((name) => (
                        <a key={name} href={apiUrl(`/reports/${r.id}/csv/${encodeURIComponent(name)}`)} className="rounded border px-2 py-1 hover:bg-muted">{name}</a>
                      ))}
                    </div>
                  </details>
                ) : null}
              </Card>
            ))}
          </div>
        </div>
      </Card>

      <Card>
        <CardHeader title="Dashboard snapshots" description="Taken with the Snapshot button on the Dashboard." />
        <div className="grid gap-4 p-5 pt-3 lg:grid-cols-[1fr_1.2fr]">
          <div className="space-y-2">
            {snapshots.data?.length === 0 ? <EmptyState icon={<Camera />} title="No snapshots yet" description="Open the Dashboard and choose Snapshot." /> : null}
            {(snapshots.data ?? []).map((s) => (
              <button key={s.id} type="button" onClick={() => setSelectedSnapshot(s.id)} className="block w-full text-left">
                <Card className={`p-3 ${selected?.id === s.id ? "ring-2 ring-primary" : ""}`}>
                  <p className="truncate text-sm font-medium">{s.file_name}</p>
                  <p className="text-xs text-muted-foreground">
                    {formatDateTime(s.generated_at)} · {String(s.filters.period ?? "")} · {s.filters.area === "whole" ? "Whole dashboard" : "Visible area"}
                    {s.width ? ` · ${s.width}×${s.height}` : ""}
                  </p>
                </Card>
              </button>
            ))}
          </div>
          {selected ? (
            <div className="space-y-2">
              {selected.exists ? (
                <img src={apiUrl(`/snapshots/${selected.id}/image`)} alt={`Dashboard snapshot ${selected.file_name}`} className="max-h-[60vh] w-full rounded-lg border object-contain" />
              ) : (
                <p className="text-sm text-warning">The image file is missing from the snapshots folder.</p>
              )}
              <div className="flex flex-wrap gap-2">
                <Button size="sm" asChild><a href={apiUrl(`/snapshots/${selected.id}/image`)} target="_blank" rel="noopener noreferrer"><ExternalLink /> Open</a></Button>
                <Button size="sm" variant="outline" onClick={() => download(`/snapshots/${selected.id}/image?download=true`, undefined, selected.file_name).catch(showError)}><Download /> Download</Button>
                <Button size="sm" variant="ghost" onClick={() => setDeletingSnapshot(selected)}><Trash2 /> Delete</Button>
              </div>
            </div>
          ) : null}
        </div>
      </Card>

      <ConfirmDialog open={deleting !== null} onOpenChange={(o) => !o && setDeleting(null)} title="Delete this report?" description="The PDF, HTML preview and CSV files are removed from the reports folder." confirmLabel="Delete" danger onConfirm={async () => { if (deleting) await removeReport.mutateAsync(deleting.id); }} />
      <ConfirmDialog open={deletingSnapshot !== null} onOpenChange={(o) => !o && setDeletingSnapshot(null)} title="Delete this snapshot?" description="The image is removed from the snapshots folder." confirmLabel="Delete" danger onConfirm={async () => { if (deletingSnapshot) await removeSnapshot.mutateAsync(deletingSnapshot.id); setSelectedSnapshot(null); }} />
    </div>
  );
}
