import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, DatabaseBackup, Download, FileUp, FolderOpen, HardDriveDownload, RotateCcw, ShieldCheck, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardHeader } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Field, Input, NativeSelect } from "@/components/ui/form";
import { ErrorState, LoadingRows, PageHeader, Progress, Switch, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/misc";
import { api, download } from "@/lib/api";
import type { AppSettings, BackupInfo, BackupsView, IntegrityView, JobRef } from "@/lib/api-types";
import { formatBytes, formatDateTime, humanize } from "@/lib/format";
import { showError, useAction, useInfo } from "@/lib/hooks";
import { useJob } from "@/lib/jobs";
import { useTheme, type ThemeChoice } from "@/lib/theme";
import { SyncPanel } from "./SyncPanel";

function GeneralPanel() {
  const client = useQueryClient();
  const info = useInfo();
  const { theme, setTheme } = useTheme();
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api.get<AppSettings>("/settings") });
  const [name, setName] = useState("");
  const [draft, setDraft] = useState<AppSettings>({});
  useEffect(() => setName(info.data?.display_name ?? ""), [info.data]);
  useEffect(() => settings.data && setDraft(settings.data), [settings.data]);
  const saveName = useAction(() => api.put("/me", { display_name: name }), { invalidate: [["info"]], success: "Name saved" });
  const save = useAction(() => api.patch<AppSettings>("/settings", draft), { invalidate: [["settings"], ["discovery-meta"]], success: "Settings saved" });
  const zones = typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : [];
  const num = (key: keyof AppSettings) => (e: { target: { value: string } }) => setDraft({ ...draft, [key]: Number(e.target.value) });

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader title="You" description="Shown on the records you create, including in sync packages." />
        <div className="flex flex-wrap items-end gap-2 p-5 pt-3">
          <Field label="Your name" className="min-w-64 flex-1">{(p) => <Input {...p} value={name} onChange={(e) => setName(e.target.value)} />}</Field>
          <Button onClick={() => saveName.mutate()} loading={saveName.isPending} disabled={!name.trim()}>Save name</Button>
        </div>
      </Card>
      <Card>
        <CardHeader title="Appearance" />
        <div className="grid gap-3 p-5 pt-3 sm:grid-cols-3">
          <Field label="Theme">
            {(p) => (
              <NativeSelect {...p} value={theme} onChange={(e) => { setTheme(e.target.value as ThemeChoice); setDraft({ ...draft, theme: e.target.value as ThemeChoice }); }}>
                <option value="system">Same as Windows</option>
                <option value="light">Light</option>
                <option value="dark">Dark</option>
              </NativeSelect>
            )}
          </Field>
          <Field label="Time zone" hint="Used for periods and reports.">
            {(p) => (
              <NativeSelect {...p} value={draft.time_zone ?? ""} onChange={(e) => setDraft({ ...draft, time_zone: e.target.value || null })}>
                <option value="">This computer's time zone</option>
                {zones.map((z) => <option key={z} value={z}>{z}</option>)}
              </NativeSelect>
            )}
          </Field>
          <Field label="Number and date format">
            {(p) => (
              <NativeSelect {...p} value={draft.locale ?? "en-US"} onChange={(e) => setDraft({ ...draft, locale: e.target.value })}>
                <option value="en-US">English (United States)</option>
                <option value="en-GB">English (United Kingdom)</option>
                <option value="fr-FR">Français</option>
                <option value="de-DE">Deutsch</option>
                <option value="es-ES">Español</option>
              </NativeSelect>
            )}
          </Field>
        </div>
      </Card>
      <Card>
        <CardHeader title="Imports and discovery" />
        <div className="grid gap-3 p-5 pt-3 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Ambiguous dates in imports">
            {(p) => (
              <NativeSelect {...p} value={draft.import_date_order ?? "auto"} onChange={(e) => setDraft({ ...draft, import_date_order: e.target.value as AppSettings["import_date_order"] })}>
                <option value="auto">Ask each time</option>
                <option value="month_first">Month first</option>
                <option value="day_first">Day first</option>
              </NativeSelect>
            )}
          </Field>
          <Field label="Upcoming window (days)">{(p) => <Input {...p} type="number" min={1} max={365} value={draft.discovery_upcoming_days ?? 90} onChange={num("discovery_upcoming_days")} />}</Field>
          <Field label="Recent window (days)">{(p) => <Input {...p} type="number" min={1} max={730} value={draft.discovery_recent_days ?? 150} onChange={num("discovery_recent_days")} />}</Field>
          <Field label="Keep Steam data for (hours)">{(p) => <Input {...p} type="number" min={1} max={336} value={draft.discovery_cache_hours ?? 24} onChange={num("discovery_cache_hours")} />}</Field>
        </div>
      </Card>
      <Card>
        <CardHeader title="Automatic backups" />
        <div className="grid gap-3 p-5 pt-3 sm:grid-cols-3">
          <Field label="Back up every (hours, 0 = off)">{(p) => <Input {...p} type="number" min={0} max={720} value={draft.backup_interval_hours ?? 24} onChange={num("backup_interval_hours")} />}</Field>
          <Field label="Keep the latest">{(p) => <Input {...p} type="number" min={1} max={100} value={draft.backup_keep_latest ?? 10} onChange={num("backup_keep_latest")} />}</Field>
          <Field label="Plus one per month for (months)">{(p) => <Input {...p} type="number" min={0} max={36} value={draft.backup_keep_monthly ?? 6} onChange={num("backup_keep_monthly")} />}</Field>
        </div>
      </Card>
      <Button onClick={() => save.mutate(undefined, { onSuccess: () => client.invalidateQueries({ queryKey: ["periods"] }) })} loading={save.isPending}>Save settings</Button>
      {settings.error ? <ErrorState error={settings.error} /> : null}
    </div>
  );
}

function BackupsPanel() {
  const client = useQueryClient();
  const backups = useQuery({ queryKey: ["backups"], queryFn: () => api.get<BackupsView>("/backups") });
  const creator = useJob<BackupInfo>(() => api.post<JobRef>("/backups"));
  const [restoring, setRestoring] = useState<BackupInfo | null>(null);
  const [deleting, setDeleting] = useState<BackupInfo | null>(null);
  const restorer = useJob<{ restored: string; safety_backup: string }, [string]>((name) => api.post<JobRef>(`/backups/${name}/restore`, { confirm: "RESTORE" }));
  const verify = useAction((name: string) => api.post<BackupInfo>(`/backups/${name}/verify`), { success: "Backup verified: it is complete and readable" });
  const remove = useAction((name: string) => api.delete(`/backups/${name}`), { invalidate: [["backups"]], success: "Backup deleted" });

  if (backups.error) return <ErrorState error={backups.error} />;
  if (!backups.data) return <LoadingRows />;
  if (!backups.data.available) {
    return <ErrorState error={{ message: "Backups are not available.", action: "Run setup.bat again to install the database backup programs." }} />;
  }
  return (
    <div className="space-y-4">
      <Card className="flex flex-wrap items-center justify-between gap-3 p-4">
        <p className="text-sm text-muted-foreground">
          Backups are verified after writing. tg_sales keeps the latest {backups.data.keep_latest} plus one per month for {backups.data.keep_monthly} months, and backs up automatically before upgrades, imports and sync.
        </p>
        <Button
          loading={creator.running}
          onClick={() => creator.start().then(() => { toast.success("Backup created"); return client.invalidateQueries({ queryKey: ["backups"] }); }).catch(showError)}
        >
          <DatabaseBackup /> Back up now
        </Button>
      </Card>
      {restorer.state.status === "running" ? <Progress value={restorer.state.percent} label={restorer.state.message} /> : null}
      <div className="space-y-2">
        {backups.data.backups.map((b) => (
          <Card key={b.name} className="flex flex-wrap items-center justify-between gap-2 p-3">
            <div className="min-w-0">
              <p className="text-sm font-medium">{formatDateTime(b.created_at)} <Badge tone={b.reason === "manual" ? "purple" : "neutral"}>{humanize(b.reason)}</Badge></p>
              <p className="truncate text-xs text-muted-foreground">{b.name} · {formatBytes(b.size_bytes)} · {b.table_counts.organizations ?? 0} prospects · version {b.app_version}</p>
            </div>
            <div className="flex flex-wrap gap-1.5">
              <Button size="sm" variant="outline" onClick={() => verify.mutate(b.name)}><ShieldCheck /> Verify</Button>
              <Button size="sm" variant="outline" onClick={() => download(`/backups/${b.name}/download`, undefined, b.name).catch(showError)}><Download /> Download</Button>
              {backups.data?.restore_available ? <Button size="sm" variant="outline" onClick={() => setRestoring(b)}><RotateCcw /> Restore</Button> : null}
              <Button size="sm" variant="ghost" aria-label="Delete backup" onClick={() => setDeleting(b)}><Trash2 /></Button>
            </div>
          </Card>
        ))}
        {backups.data.backups.length === 0 ? <p className="text-sm text-muted-foreground">No backups yet.</p> : null}
      </div>
      <p className="text-xs text-muted-foreground">Downloaded backups contain all your CRM data. Store them somewhere only you and your company can access.</p>
      <ConfirmDialog
        open={restoring !== null}
        onOpenChange={(o) => !o && setRestoring(null)}
        title="Restore this backup?"
        description={
          <>
            <p>All current data is replaced by the backup from {restoring ? formatDateTime(restoring.created_at) : ""}.</p>
            <p>A safety backup of your current data is made first, and the current database is kept until the next restore, so this can be undone.</p>
          </>
        }
        typeToConfirm="RESTORE"
        confirmLabel="Restore"
        danger
        onConfirm={async () => {
          if (!restoring) return;
          try {
            await restorer.start(restoring.name);
            toast.success("Backup restored");
            await client.invalidateQueries();
          } catch (error) {
            showError(error);
          }
        }}
      />
      <ConfirmDialog open={deleting !== null} onOpenChange={(o) => !o && setDeleting(null)} title="Delete this backup?" description="The backup file is removed from the backups folder." confirmLabel="Delete" danger onConfirm={async () => { if (deleting) await remove.mutateAsync(deleting.name); }} />
    </div>
  );
}

interface TransferResult {
  ok: boolean;
  dry_run: boolean;
  tables: Record<string, { source: number; inserted: number; already_present: number; conflicts: number; invalid: number }>;
  issues: { table: string; record_id: string | null; kind: string; column: string | null; message: string }[];
  issue_count: number;
  verification: Record<string, unknown>;
  report_file: string;
}

function DesktopPanel() {
  const client = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [dryRun, setDryRun] = useState(true);
  const transfer = useJob<TransferResult>(() => {
    const form = new FormData();
    if (file) form.append("database", file);
    form.append("dry_run", String(dryRun));
    return api.post<JobRef>("/legacy/transfer", form);
  });
  const result = transfer.state.status === "succeeded" ? transfer.state.result : null;
  return (
    <div className="space-y-4">
      <Card className="space-y-3 p-4 text-sm">
        <p>Bring in the data from the earlier Windows desktop version of tg_sales (the file <code>tg_sales.db</code> in <code>%LOCALAPPDATA%\TatumGames\tg_sales\data</code>).</p>
        <p className="text-muted-foreground">The original file is never changed. Records keep their ids and history; running it again adds nothing twice. Every transferred record is checked afterwards and a report is saved.</p>
        <input ref={input} type="file" accept=".db,.sqlite,.sqlite3" hidden onChange={(e) => { setFile(e.target.files?.[0] ?? null); e.target.value = ""; transfer.reset(); }} />
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" onClick={() => input.current?.click()}><FileUp /> Choose tg_sales.db…</Button>
          <span className="text-muted-foreground">{file?.name ?? "No file selected"}</span>
        </div>
        <label className="flex items-center gap-2"><Switch checked={dryRun} onCheckedChange={setDryRun} /> Trial run first (shows what would happen, saves nothing)</label>
        <Button disabled={!file} loading={transfer.running} onClick={() => transfer.start().then(() => client.invalidateQueries()).catch(showError)}><HardDriveDownload /> {dryRun ? "Run trial" : "Transfer now"}</Button>
        {transfer.state.status === "running" ? <Progress value={transfer.state.percent} label={transfer.state.message} /> : null}
      </Card>
      {result ? (
        <Card className="space-y-3 p-4 text-sm">
          <p className="flex items-center gap-2 font-medium">
            {result.ok ? <CheckCircle2 className="size-4 text-success" /> : null}
            {result.dry_run ? "Trial run: nothing was saved." : result.ok ? "Transfer complete and verified." : "Transfer finished with items to review."}
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-left text-muted-foreground"><tr><th className="py-1">Table</th><th className="text-right">In file</th><th className="text-right">Added</th><th className="text-right">Already here</th><th className="text-right">Conflicts</th><th className="text-right">Unreadable</th></tr></thead>
              <tbody>
                {Object.entries(result.tables).filter(([, t]) => t.source > 0).map(([name, t]) => (
                  <tr key={name} className="border-t"><td className="py-1">{humanize(name)}</td><td className="text-right">{t.source}</td><td className="text-right">{t.inserted}</td><td className="text-right">{t.already_present}</td><td className="text-right">{t.conflicts}</td><td className="text-right">{t.invalid}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          {result.issues.length ? (
            <ul className="max-h-48 list-disc overflow-y-auto pl-5 text-xs">
              {result.issues.map((i, n) => <li key={n}>{humanize(i.table)} {i.column ? `(${i.column})` : ""}: {i.message}</li>)}
            </ul>
          ) : null}
          {!result.dry_run ? <p className="text-xs text-muted-foreground">The full report was saved as {result.report_file} in the migration_reports folder of your data folder.</p> : null}
        </Card>
      ) : null}
    </div>
  );
}

function AboutPanel() {
  const info = useInfo();
  const [integrity, setIntegrity] = useState<IntegrityView | null>(null);
  const check = useAction(() => api.post<IntegrityView>("/system/integrity"), {});
  const openFolder = useAction((folder: string) => api.post("/system/open-folder", { folder }));
  return (
    <div className="space-y-4">
      <Card className="grid gap-2 p-4 text-sm sm:grid-cols-2">
        <p><span className="text-muted-foreground">Version: </span>{info.data?.version}</p>
        <p><span className="text-muted-foreground">Database schema: </span>{info.data?.schema_revision}</p>
        <p className="sm:col-span-2"><span className="text-muted-foreground">Sync ID: </span><code className="text-xs">{info.data?.device_id}</code></p>
        {info.data?.data_folder ? <p className="sm:col-span-2"><span className="text-muted-foreground">Data folder: </span>{info.data.data_folder}</p> : null}
      </Card>
      {info.data?.desktop_integration ? (
        <Card className="flex flex-wrap gap-2 p-4">
          {["data", "backups", "reports", "snapshots", "logs"].map((folder) => (
            <Button key={folder} size="sm" variant="outline" onClick={() => openFolder.mutate(folder)}><FolderOpen /> Open {folder} folder</Button>
          ))}
        </Card>
      ) : null}
      <Card className="space-y-2 p-4">
        <Button variant="outline" loading={check.isPending} onClick={() => check.mutate(undefined, { onSuccess: setIntegrity })}><ShieldCheck /> Check database health</Button>
        {integrity ? (
          integrity.ok ? <p className="text-sm text-success">Everything looks healthy ({formatDateTime(integrity.checked_at)}).</p> : <ErrorState error={{ message: integrity.problems.join("; "), action: "Restore a recent backup, or send the log file to your support contact." }} />
        ) : null}
      </Card>
      <Card className="space-y-2 p-4 text-sm">
        <p className="font-medium">Privacy</p>
        <p className="text-muted-foreground">Your CRM data stays on this computer, in a private PostgreSQL database that only accepts connections from this computer. Anyone who can sign in to your Windows account can read it; use BitLocker or your company's disk encryption to protect a lost laptop.</p>
        <p className="text-muted-foreground">Only two things leave this computer: Game discovery requests public store pages from Steam and official studio websites, and sync packages you export yourself. There is no telemetry.</p>
      </Card>
    </div>
  );
}

export function SettingsPage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "general";
  return (
    <div>
      <PageHeader title="Settings & Sync" description="Your preferences, collaboration with colleagues, backups and more." />
      <Tabs value={tab} onValueChange={(value) => setParams({ tab: value })}>
        <TabsList className="mb-5">
          <TabsTrigger value="general">General</TabsTrigger>
          <TabsTrigger value="sync">Sync</TabsTrigger>
          <TabsTrigger value="backups">Backups</TabsTrigger>
          <TabsTrigger value="desktop">Desktop data</TabsTrigger>
          <TabsTrigger value="about">About</TabsTrigger>
        </TabsList>
        <TabsContent value="general"><GeneralPanel /></TabsContent>
        <TabsContent value="sync"><SyncPanel /></TabsContent>
        <TabsContent value="backups"><BackupsPanel /></TabsContent>
        <TabsContent value="desktop"><DesktopPanel /></TabsContent>
        <TabsContent value="about"><AboutPanel /></TabsContent>
      </Tabs>
    </div>
  );
}
