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
import { toCanvas } from "html-to-image";
import { Camera, Info, LayoutDashboard, Plus, RefreshCw, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { Link } from "react-router";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from "recharts";
import { toast } from "sonner";
import { ChartCard } from "@/components/ChartCard";
import { PeriodPicker, type PeriodValue } from "@/components/PeriodPicker";
import { useAppDialogs } from "@/components/layout/dialogs";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardHeader, SERIES_COLORS } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, NativeSelect } from "@/components/ui/form";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  EmptyState,
  ErrorState,
  PageHeader,
  Skeleton,
  Tooltip,
} from "@/components/ui/misc";
import { api } from "@/lib/api";
import type { ActorChoice, DashboardView, Metric, Reminder, SnapshotView } from "@/lib/api-types";
import { formatDate, formatDateTime, formatNumber, humanize, relativeDue } from "@/lib/format";
import { showError } from "@/lib/hooks";
import { useTheme } from "@/lib/theme";
import { useLanes } from "@/lib/lanes";
import { cn } from "@/lib/utils";

const PRIMARY_METRICS = ["leads_added", "contacts_attempted", "replies", "active_opportunities", "won", "lost", "win_rate", "follow_ups_overdue"];
const SECONDARY_METRICS = ["contacts_added", "technical_handoffs", "proposals", "follow_ups_due"];
// Accent colors follow meaning (won green, lost coral, overdue yellow); the label always says it too.
const ACCENT: Record<string, string> = {
  leads_added: "var(--brand-purple)",
  contacts_added: "var(--brand-purple)",
  contacts_attempted: "var(--brand-teal)",
  replies: "var(--brand-teal)",
  active_opportunities: "var(--brand-purple)",
  technical_handoffs: "var(--brand-teal)",
  proposals: "var(--brand-purple)",
  won: "var(--brand-green)",
  lost: "var(--brand-coral)",
  win_rate: "var(--brand-green)",
  follow_ups_due: "var(--brand-yellow)",
  follow_ups_overdue: "var(--brand-coral)",
};

function MetricCard({ metric, accent, onOpen }: { metric: Metric; accent: string; onOpen: () => void }) {
  const unavailable = metric.value === null;
  return (
    <button
      type="button"
      onClick={onOpen}
      className="group relative overflow-hidden rounded-xl border bg-card p-4 text-left shadow-card transition-shadow hover:shadow-md focus-visible:outline-2 focus-visible:outline-ring"
      aria-label={`${metric.label}: ${formatNumber(metric.value, metric.unit)}. Show the records behind this number.`}
    >
      <span aria-hidden className="absolute inset-x-0 top-0 h-1" style={{ background: accent }} />
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium text-muted-foreground">{metric.label}</p>
        {metric.current_state ? <Badge tone="info">Now</Badge> : null}
      </div>
      <p className={cn("tabular mt-2 text-3xl font-semibold tracking-tight", unavailable && "text-lg font-medium text-muted-foreground")}>
        {formatNumber(metric.value, metric.unit)}
      </p>
      <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{metric.caption}</p>
    </button>
  );
}

function DrillDown({ metric, onClose }: { metric: Metric | null; onClose: () => void }) {
  return (
    <Dialog open={metric !== null} onOpenChange={(o) => !o && onClose()} size="lg" title={metric?.label ?? ""} description={metric?.caption}>
      {metric && (metric.rows ?? []).length === 0 ? <p className="text-sm text-muted-foreground">No records behind this number.</p> : null}
      <ul className="divide-y">
        {(metric?.rows ?? []).map((row, i) => (
          <li key={i} className="flex flex-wrap items-baseline justify-between gap-2 py-2 text-sm">
            <div className="min-w-0">
              {row.organization_id ? (
                <Link className="font-medium hover:underline" to={`/prospects?id=${row.organization_id}`} onClick={onClose}>{row.organization}</Link>
              ) : (
                <span className="font-medium">{row.organization}</span>
              )}
              <p className="text-muted-foreground">{row.detail}</p>
            </div>
            <span className="text-xs text-muted-foreground">{row.when ? formatDateTime(row.when) : ""}</span>
          </li>
        ))}
      </ul>
    </Dialog>
  );
}

export function DashboardPage() {
  const client = useQueryClient();
  const dialogs = useAppDialogs();
  const { resolved } = useTheme();
  const area = useRef<HTMLDivElement>(null);
  const [period, setPeriod] = useState<PeriodValue>({ preset: "30d", start: "", end: "" });
  const [actor, setActor] = useState("");
  const [lane, setLane] = useState("");
  const lanes = useLanes();
  const [drill, setDrill] = useState<Metric | null>(null);
  const [snapping, setSnapping] = useState(false);

  const query = useQuery({
    queryKey: ["dashboard", period, actor, lane],
    queryFn: () =>
      api.get<DashboardView>("/dashboard", {
        preset: period.preset,
        start: period.preset === "custom" ? period.start : null,
        end: period.preset === "custom" ? period.end : null,
        actor_id: actor || null,
        lane: lane || null,
      }),
    enabled: period.preset !== "custom" || Boolean(period.start && period.end),
  });
  const people = useQuery({ queryKey: ["salespeople"], queryFn: () => api.get<ActorChoice[]>("/dashboard/salespeople") });
  const reminders = useQuery({ queryKey: ["reminders"], queryFn: () => api.get<Reminder[]>("/reminders") });

  const data = query.data?.data;
  const report = data?.report;
  const grid = resolved === "dark" ? "#3a3343" : "#e6e1ec";
  const axis = resolved === "dark" ? "#b2a9bd" : "#5d5568";

  const snapshot = async (whole: boolean) => {
    const node = area.current;
    if (!node || !query.data) return;
    setSnapping(true);
    try {
      const pixelRatio = Math.min(3, Math.max(2, window.devicePixelRatio || 1));
      const background = getComputedStyle(document.body).backgroundColor;
      // Rendered from the page's own content, never a screen capture: nothing else can appear in it.
      let canvas = await toCanvas(node, {
        pixelRatio,
        backgroundColor: background,
        filter: (el) => !(el instanceof HTMLElement && el.dataset.snapshotExclude !== undefined),
      });
      if (!whole) {
        const rect = node.getBoundingClientRect();
        const top = Math.max(0, -rect.top);
        const height = Math.min(rect.height - top, window.innerHeight - Math.max(0, rect.top));
        const crop = document.createElement("canvas");
        crop.width = canvas.width;
        crop.height = Math.max(1, Math.round(height * pixelRatio));
        crop.getContext("2d")?.drawImage(canvas, 0, Math.round(top * pixelRatio), canvas.width, crop.height, 0, 0, crop.width, crop.height);
        canvas = crop;
      }
      const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
      if (!blob) throw new Error("The snapshot could not be created.");
      const form = new FormData();
      form.append("image", blob, "dashboard.png");
      form.append(
        "filters",
        JSON.stringify({
          period: query.data.period.label,
          period_start: query.data.period.start,
          period_end: query.data.period.end,
          salesperson: people.data?.find((p) => p.id === actor)?.name ?? null,
          lane: lane ? lanes.label(lane) : null,
          area: whole ? "whole" : "visible",
        }),
      );
      const saved = await api.post<SnapshotView>("/snapshots", form);
      await client.invalidateQueries({ queryKey: ["snapshots"] });
      toast.success("Snapshot saved", {
        description: saved.file_name,
        action: { label: "Open", onClick: () => window.open(`/api/snapshots/${saved.id}/image`, "_blank", "noopener") },
      });
    } catch (error) {
      showError(error);
    } finally {
      setSnapping(false);
    }
  };

  const trendRows = report ? report.trend.labels.map((label, i) => [label, ...Object.values(report.trend.series).map((s) => s[i] ?? 0)]) : [];
  const trendSeries = report ? Object.keys(report.trend.series) : [];
  const chartData = report ? report.trend.labels.map((label, i) => ({ label, ...Object.fromEntries(trendSeries.map((s) => [s, report.trend.series[s]?.[i] ?? 0])) })) : [];
  const stageData = report ? report.stages.filter((s) => s.at_period_end > 0 || s.outcome === "open").map((s) => ({ name: s.name, count: s.at_period_end, outcome: s.outcome })) : [];
  const releaseData = data ? data.releases.labels.map((label, i) => ({ label, count: data.releases.counts[i] ?? 0 })) : [];

  return (
    <div>
      <PageHeader
        title="Dashboard"
        description="Your sales activity at a glance. Choose any card to see the records behind it."
        actions={
          <>
            <Button variant="ghost" size="icon" aria-label="Refresh" onClick={() => query.refetch()} disabled={query.isFetching}>
              <RefreshCw className={query.isFetching ? "animate-spin" : undefined} />
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" loading={snapping} disabled={!query.data}>
                  <Camera /> Snapshot
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent>
                <DropdownMenuItem onSelect={() => void snapshot(false)}>Visible area</DropdownMenuItem>
                <DropdownMenuItem onSelect={() => void snapshot(true)}>Whole dashboard</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </>
        }
      />

      <Card className="mb-5 flex flex-wrap items-end gap-3 p-4">
        <PeriodPicker value={period} onChange={setPeriod} idPrefix="dash" />
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
      </Card>

      {query.error ? <ErrorState error={query.error} onRetry={() => query.refetch()} /> : null}

      <div ref={area} className="space-y-5 bg-background">
        {query.data ? (
          <div className="hidden text-sm text-muted-foreground print:block">{query.data.period.label} · {query.data.period.description}</div>
        ) : null}

        {query.isLoading ? (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="h-32" />)}</div>
        ) : null}

        {data && !data.has_data ? (
          <EmptyState
            icon={<LayoutDashboard />}
            title="Your dashboard fills up as you work"
            description="Add or import prospects, create opportunities in the pipeline and log your outreach. Numbers appear here automatically."
            action={
              <div className="flex flex-wrap justify-center gap-2" data-snapshot-exclude>
                <Button onClick={dialogs.openNewProspect}><Plus /> New prospect</Button>
                <Button variant="outline" onClick={dialogs.openImport}><Upload /> Import a file</Button>
              </div>
            }
          />
        ) : null}

        {report ? (
          <>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              {PRIMARY_METRICS.map((key) => {
                const metric = report.metrics[key];
                return metric ? <MetricCard key={key} metric={metric} accent={ACCENT[key] ?? "var(--brand-purple)"} onOpen={() => setDrill(metric)} /> : null;
              })}
            </div>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              {SECONDARY_METRICS.map((key) => {
                const metric = report.metrics[key];
                return metric ? <MetricCard key={key} metric={metric} accent={ACCENT[key] ?? "var(--brand-purple)"} onOpen={() => setDrill(metric)} /> : null;
              })}
            </div>

            <div className="grid gap-5 xl:grid-cols-2">
              <ChartCard
                title="Activity over time"
                description={`By ${report.trend.size}; each line adds up to its card.`}
                headers={["Period", ...trendSeries]}
                rows={trendRows}
                csvName="dashboard_trend"
              >
                <ResponsiveContainer width="100%" height={260}>
                  <LineChart data={chartData} margin={{ left: -16, right: 8, top: 8 }}>
                    <CartesianGrid stroke={grid} vertical={false} />
                    <XAxis dataKey="label" stroke={axis} fontSize={11} tickLine={false} minTickGap={16} />
                    <YAxis stroke={axis} fontSize={11} allowDecimals={false} tickLine={false} />
                    <ChartTooltip contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 8 }} />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    {trendSeries.map((series, i) => (
                      <Line key={series} type="monotone" dataKey={series} stroke={SERIES_COLORS[i % SERIES_COLORS.length]} strokeWidth={2.5} dot={false} />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </ChartCard>

              <ChartCard
                title="Pipeline by stage"
                description="Opportunities in each stage at the end of the period."
                headers={["Stage", "Opportunities", "Moved on", "Moved forward", "Median days in stage"]}
                rows={report.stages.map((s) => [s.name, s.at_period_end, s.exits, s.forward_exits, s.median_days])}
                csvName="dashboard_stages"
              >
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart data={stageData} margin={{ left: -16, right: 8, top: 8 }}>
                    <CartesianGrid stroke={grid} vertical={false} />
                    <XAxis dataKey="name" stroke={axis} fontSize={11} tickLine={false} interval={0} angle={-25} textAnchor="end" height={60} />
                    <YAxis stroke={axis} fontSize={11} allowDecimals={false} tickLine={false} />
                    <ChartTooltip cursor={{ fill: "var(--muted)" }} contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 8 }} />
                    <Bar dataKey="count" name="Opportunities" radius={[6, 6, 0, 0]}>
                      {stageData.map((s) => (
                        <Cell key={s.name} fill={s.outcome === "won" ? "#c7d47f" : s.outcome === "lost" ? "#d87b7a" : s.outcome === "not_a_fit" ? "#b4aec0" : "#a787bd"} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </ChartCard>

              <ChartCard
                title="Funnel"
                description={`Of the ${report.funnel_cohort} opportunities created in this period, how far they got.`}
                headers={["Step", "Opportunities"]}
                rows={report.funnel.map((f) => [f.label, f.count])}
                csvName="dashboard_funnel"
              >
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={report.funnel} layout="vertical" margin={{ left: 24, right: 16 }}>
                    <CartesianGrid stroke={grid} horizontal={false} />
                    <XAxis type="number" stroke={axis} fontSize={11} allowDecimals={false} />
                    <YAxis type="category" dataKey="label" stroke={axis} fontSize={11} width={110} />
                    <ChartTooltip cursor={{ fill: "var(--muted)" }} contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 8 }} />
                    <Bar dataKey="count" name="Opportunities" fill="#86c4c2" radius={[0, 6, 6, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </ChartCard>

              <ChartCard
                title="Release windows"
                description="Games of your prospects releasing around now (recorded release dates only)."
                headers={["Month", "Games"]}
                rows={releaseData.map((r) => [r.label, r.count])}
                csvName="dashboard_releases"
              >
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={releaseData} margin={{ left: -16, right: 8, top: 8 }}>
                    <CartesianGrid stroke={grid} vertical={false} />
                    <XAxis dataKey="label" stroke={axis} fontSize={11} tickLine={false} />
                    <YAxis stroke={axis} fontSize={11} allowDecimals={false} tickLine={false} />
                    <ChartTooltip cursor={{ fill: "var(--muted)" }} contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 8 }} />
                    <Bar dataKey="count" name="Games" fill="#f6d271" radius={[6, 6, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </ChartCard>
            </div>

            <div className="grid gap-5 xl:grid-cols-3">
              <Card>
                <CardHeader title="Follow-ups" description="Overdue and due today." actions={<Link to="/pipeline" className="text-sm text-primary hover:underline">Open pipeline</Link>} />
                <ul className="divide-y px-5 pb-4">
                  {(reminders.data ?? []).slice(0, 8).map((r, i) => {
                    const due = relativeDue(r.due_at);
                    return (
                      <li key={i} className="py-2.5">
                        <Link to={r.opportunity_id ? `/pipeline?opportunity=${r.opportunity_id}` : "/pipeline"} className="block hover:underline">
                          <p className="text-sm font-medium">{r.title}</p>
                          <p className={cn("text-xs", due.overdue ? "font-semibold text-danger" : "text-muted-foreground")}>{r.organization_name} · {due.text}</p>
                        </Link>
                      </li>
                    );
                  })}
                  {reminders.data?.length === 0 ? <li className="py-3 text-sm text-muted-foreground">Nothing due.</li> : null}
                </ul>
              </Card>
              <Card>
                <CardHeader title="Recent activity" />
                <ul className="divide-y px-5 pb-4">
                  {data!.recent.slice(0, 8).map((a, i) => (
                    <li key={i} className={cn("py-2.5", a.voided && "opacity-60")}>
                      <p className={cn("text-sm", a.voided && "line-through")}><span className="font-medium">{a.organization}</span> · {a.summary}</p>
                      <p className="text-xs text-muted-foreground">{formatDateTime(a.occurred_at)} · {humanize(a.kind)}</p>
                    </li>
                  ))}
                  {data!.recent.length === 0 ? <li className="py-3 text-sm text-muted-foreground">No activity in this period.</li> : null}
                </ul>
              </Card>
              <Card>
                <CardHeader title="Where leads come from" description="Leads added in the period and how many progressed." />
                <div className="px-5 pb-4">
                  <table className="w-full text-sm">
                    <thead className="text-left text-xs text-muted-foreground">
                      <tr><th className="py-1.5">Source</th><th className="py-1.5 text-right">Leads</th><th className="py-1.5 text-right">Progressed</th></tr>
                    </thead>
                    <tbody>
                      {report.sources.map((s) => (
                        <tr key={s.source} className="border-t">
                          <td className="py-1.5">{humanize(s.source)}</td>
                          <td className="tabular py-1.5 text-right">{s.leads}</td>
                          <td className="tabular py-1.5 text-right">{s.progressed}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {report.sources.length === 0 ? <p className="py-2 text-sm text-muted-foreground">No leads added in this period.</p> : null}
                </div>
              </Card>
            </div>
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Info className="size-3.5" />
              Numbers come from recorded events (history is never rebuilt from today's state). Calculated {formatDateTime(data!.computed_at)}.
              <Tooltip content="“Not available” means the number cannot be calculated (for example a win rate with nothing won or lost). 0 means nothing happened.">
                <button type="button" className="underline">What does “Not available” mean?</button>
              </Tooltip>
            </p>
          </>
        ) : null}
      </div>
      <DrillDown metric={drill} onClose={() => setDrill(null)} />
      {query.data ? <span className="sr-only">Period from {formatDate(query.data.period.start)} to {formatDate(query.data.period.end)}</span> : null}
    </div>
  );
}
