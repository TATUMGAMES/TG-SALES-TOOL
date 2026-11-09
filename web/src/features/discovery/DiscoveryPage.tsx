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

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BadgeCheck, CheckCircle2, ExternalLink, Globe, Link2, Search, Sparkles, X } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge, Card } from "@/components/ui/card";
import { Dialog, Sheet } from "@/components/ui/dialog";
import { Field, Input, NativeSelect, Textarea } from "@/components/ui/form";
import { EmptyState, ErrorState, LoadingRows, PageHeader, Progress, Switch } from "@/components/ui/misc";
import { api } from "@/lib/api";
import type { DiscoveryMeta, DuplicateCandidate, JobRef, LeadStatus, LeadView, RunInfo, Timing } from "@/lib/api-types";
import { formatDate, formatDateTime, humanize } from "@/lib/format";
import { showError, useAction, useOnline } from "@/lib/hooks";
import { useJob } from "@/lib/jobs";
import { cn, plural } from "@/lib/utils";

interface RunOutcome {
  found: number;
  new: number;
  notes: string[];
  error: string | null;
}

interface ContactSearch {
  website: string;
  addresses: { email: string; source_url: string }[];
  checked_urls: string[];
  blocked_by_robots: boolean;
  message: string;
}

const TIMING_LABEL: Record<Timing, string> = { upcoming: "Upcoming", recent: "Recently released", unknown_date: "Date not announced", outside: "Outside the window" };
const TIMING_TONE: Record<Timing, "purple" | "info" | "neutral" | "outline"> = { upcoming: "purple", recent: "info", unknown_date: "neutral", outside: "outline" };
const CRM_LABEL: Record<string, string> = { not_in_crm: "Not in CRM", game_in_crm: "Game already in CRM", studio_in_crm: "Studio already in CRM", possible_match: "Possible match in CRM" };
const CONTACT_LABEL: Record<string, string> = { not_found: "No business contact found", needs_verification: "Needs verification", verified_source: "Verified source" };

function LeadDetail({ lead, onClose }: { lead: LeadView | null; onClose: () => void }) {
  const client = useQueryClient();
  const [email, setEmail] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [target, setTarget] = useState("");
  const [includeContact, setIncludeContact] = useState(true);
  const duplicates = useQuery({
    queryKey: ["lead-duplicates", lead?.id],
    queryFn: () => api.get<DuplicateCandidate[]>(`/discovery/leads/${lead?.id}/duplicates`),
    enabled: Boolean(lead),
  });
  const finder = useJob<ContactSearch>(() => api.post<JobRef>(`/discovery/leads/${lead?.id}/find-contacts`));
  const refresh = [["leads"]];
  const setContact = useAction(() => api.post(`/discovery/leads/${lead?.id}/contact`, { email, source_url: sourceUrl }), { invalidate: refresh, success: "Contact saved (needs verification)" });
  const verify = useAction(() => api.post(`/discovery/leads/${lead?.id}/verify-contact`), { invalidate: refresh, success: "Marked as verified" });
  const save = useMutation({
    mutationFn: () => api.post<{ id: string }>(`/discovery/leads/${lead?.id}/save`, { existing_organization_id: target || null, include_contact: includeContact }),
    onSuccess: async (result) => {
      await client.invalidateQueries({ queryKey: ["leads"] });
      await client.invalidateQueries({ queryKey: ["prospects"] });
      toast.success("Saved to Prospects", { action: { label: "Open", onClick: () => window.location.assign(`/prospects?id=${result.id}`) } });
      onClose();
    },
    onError: showError,
  });
  const c = lead?.candidate;

  return (
    <Sheet open={lead !== null} onOpenChange={(o) => !o && onClose()} title={c?.title ?? ""} description={c ? `${c.developers.join(", ") || "Developer unknown"}${c.publishers.length ? ` · published by ${c.publishers.join(", ")}` : ""}` : undefined}>
      {lead && c ? (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <Badge tone={TIMING_TONE[lead.timing]}>{TIMING_LABEL[lead.timing]}</Badge>
            <Badge tone="purple">Score {lead.score.total}</Badge>
            <Badge tone={lead.crm_state === "not_in_crm" ? "success" : "warning"}>{CRM_LABEL[lead.crm_state]}</Badge>
            {c.stale || lead.outdated ? <Badge tone="warning">Data may be out of date</Badge> : null}
          </div>
          <Card className="grid gap-2 p-4 text-sm sm:grid-cols-2">
            <p><span className="text-muted-foreground">Release: </span>{c.release_date ? formatDate(c.release_date) : c.release_text || "Not announced"} <span className="text-xs text-muted-foreground">({humanize(c.release_precision)} precision)</span></p>
            <p><span className="text-muted-foreground">Platforms: </span>{c.platforms.join(", ") || "Not listed"}</p>
            <p className="sm:col-span-2"><span className="text-muted-foreground">Genres: </span>{[...c.genres, ...c.categories.slice(0, 4)].join(", ") || "Not listed"}</p>
            <p><span className="text-muted-foreground">Type: </span>{humanize(c.game_type)}{c.parent_title ? ` of ${c.parent_title}` : ""}</p>
            <p><span className="text-muted-foreground">Last checked: </span>{formatDateTime(lead.last_checked)}</p>
            <div className="flex flex-wrap gap-3 sm:col-span-2">
              <a href={c.store_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">Steam page <ExternalLink className="size-3.5" /></a>
              {c.website ? <a href={c.website} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">Studio website <ExternalLink className="size-3.5" /></a> : null}
            </div>
          </Card>

          <section>
            <h3 className="mb-1 text-sm font-semibold">Why this score</h3>
            <ul className="space-y-1 text-sm">
              {lead.score.reasons.map((r, i) => (
                <li key={i} className="flex justify-between gap-2"><span>{r.text}</span><span className={cn("tabular", r.points < 0 ? "text-danger" : "text-success")}>{r.points > 0 ? "+" : ""}{r.points}</span></li>
              ))}
            </ul>
            <p className="mt-1 text-xs text-muted-foreground">Confidence: {lead.score.confidence}. Scores are simple, visible rules, not predictions.</p>
          </section>

          <section className="space-y-2">
            <h3 className="text-sm font-semibold">Business contact</h3>
            <p className="text-sm">
              {lead.contact.email ? <span className="font-medium">{lead.contact.email}</span> : null} <Badge tone={lead.contact.status === "verified_source" ? "success" : lead.contact.status === "needs_verification" ? "warning" : "neutral"}>{CONTACT_LABEL[lead.contact.status]}</Badge>
            </p>
            {lead.contact.source_url ? <p className="text-xs text-muted-foreground">Found at <a className="underline" href={lead.contact.source_url} target="_blank" rel="noopener noreferrer">{lead.contact.source_label || lead.contact.source_url}</a></p> : null}
            <div className="flex flex-wrap gap-2">
              {c.website ? (
                <Button size="sm" variant="outline" loading={finder.running} onClick={() => finder.start().catch(showError)}>
                  <Globe /> Check studio website
                </Button>
              ) : null}
              {lead.contact.email && lead.contact.status !== "verified_source" ? (
                <Button size="sm" variant="outline" onClick={() => verify.mutate()}><BadgeCheck /> Mark contact verified</Button>
              ) : null}
            </div>
            {finder.state.status === "succeeded" ? (
              <Card className="space-y-1 p-3 text-sm">
                {finder.state.result.message ? <p className="text-muted-foreground">{finder.state.result.message}</p> : null}
                {finder.state.result.addresses.map((a) => (
                  <button key={a.email} type="button" className="block text-left text-primary hover:underline" onClick={() => { setEmail(a.email); setSourceUrl(a.source_url); }}>
                    Use {a.email} (from {a.source_url})
                  </button>
                ))}
                {finder.state.result.addresses.length === 0 ? <p>No public business address on the official website.</p> : null}
              </Card>
            ) : null}
            <div className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
              <Input aria-label="Contact email" placeholder="Business email" value={email} onChange={(e) => setEmail(e.target.value)} />
              <Input aria-label="Where you found it" placeholder="Page where it is published" value={sourceUrl} onChange={(e) => setSourceUrl(e.target.value)} />
              <Button size="sm" variant="secondary" disabled={!email || !sourceUrl} onClick={() => setContact.mutate()}>Save contact</Button>
            </div>
            <p className="text-xs text-muted-foreground">Only the store's published contact or the official studio website is used. tg_sales never guesses addresses.</p>
          </section>

          <section className="space-y-2 rounded-xl border p-4">
            <h3 className="text-sm font-semibold">Save to Prospects</h3>
            {(duplicates.data ?? []).length ? (
              <Field label="This studio may already be in your CRM">
                {(p) => (
                  <NativeSelect {...p} value={target} onChange={(e) => setTarget(e.target.value)}>
                    <option value="">Create a new prospect</option>
                    {(duplicates.data ?? []).map((d) => <option key={d.id} value={d.id}>Add to {d.name} ({d.reason})</option>)}
                  </NativeSelect>
                )}
              </Field>
            ) : null}
            <label className="flex items-center gap-2 text-sm"><Switch checked={includeContact} onCheckedChange={setIncludeContact} /> Include the business contact</label>
            <Button loading={save.isPending} onClick={() => save.mutate()} disabled={lead.status === "saved"}>
              <CheckCircle2 /> {lead.status === "saved" ? "Saved to Prospects" : "Save to Prospects"}
            </Button>
            {lead.crm_organization_id ? <Link className="ml-3 text-sm text-primary hover:underline" to={`/prospects?id=${lead.crm_organization_id}`}>Open {lead.crm_organization_name}</Link> : null}
          </section>
          <p className="text-xs text-muted-foreground">Source: <a className="underline" href={c.provenance_url} target="_blank" rel="noopener noreferrer">{c.provenance_url}</a></p>
        </div>
      ) : null}
    </Sheet>
  );
}

export function DiscoveryPage() {
  const online = useOnline();
  const meta = useQuery({ queryKey: ["discovery-meta"], queryFn: () => api.get<DiscoveryMeta>("/discovery/meta") });
  const lastRun = useQuery({ queryKey: ["discovery-last"], queryFn: () => api.get<RunInfo | null>("/discovery/last-run") });
  const [upcoming, setUpcoming] = useState<number | "">("");
  const [recent, setRecent] = useState<number | "">("");
  const [timings, setTimings] = useState<Timing[]>(["upcoming", "recent"]);
  const [status, setStatus] = useState<LeadStatus>("new");
  const [selfPublished, setSelfPublished] = useState(false);
  const [hideInCrm, setHideInCrm] = useState(false);
  const [includeDlc, setIncludeDlc] = useState(false);
  const [minScore, setMinScore] = useState(0);
  const [genre, setGenre] = useState("");
  const [platform, setPlatform] = useState("");
  const [text, setText] = useState("");
  const [open, setOpen] = useState<LeadView | null>(null);
  const [lookupOpen, setLookupOpen] = useState(false);
  const [references, setReferences] = useState("");
  const client = useQueryClient();

  const params = { upcoming_days: upcoming || null, recent_days: recent || null };
  const leads = useQuery({
    queryKey: ["leads", params, timings, status, selfPublished, hideInCrm, includeDlc, minScore, genre, platform],
    queryFn: () =>
      api.post<LeadView[]>("/discovery/leads/search", {
        params,
        filters: { timings, statuses: [status], self_published_only: selfPublished, hide_in_crm: hideInCrm, include_dlc: includeDlc, min_score: minScore, genre: genre || null, platform: platform || null },
      }),
  });
  const runner = useJob<RunOutcome>(() => api.post<JobRef>("/discovery/run", params));
  const lookup = useJob<RunOutcome>(() => api.post<JobRef>("/discovery/lookup", { references: references.split(/[\s,]+/).filter(Boolean) }));
  const dismiss = useAction((id: string) => api.post(`/discovery/leads/${id}/status`, { status: "dismissed" }), { invalidate: [["leads"]] });

  const afterRun = async (outcome: RunOutcome) => {
    await client.invalidateQueries({ queryKey: ["leads"] });
    await client.invalidateQueries({ queryKey: ["discovery-last"] });
    if (outcome.error) toast.error(outcome.error, { description: "Results shown may be from an earlier check." });
    else toast.success(`Found ${plural(outcome.found, "game")} (${outcome.new} new)`);
  };

  const shown = useMemo(() => {
    const q = text.trim().toLowerCase();
    return (leads.data ?? []).filter((l) => !q || l.candidate.title.toLowerCase().includes(q) || l.candidate.developers.join(" ").toLowerCase().includes(q));
  }, [leads.data, text]);
  const progress = runner.state.status === "running" ? runner.state : lookup.state.status === "running" ? lookup.state : null;

  return (
    <div>
      <PageHeader
        title="Game discovery"
        description={meta.data ? `Studios with Steam releases in the next ${meta.data.upcoming_days} days or the last ${meta.data.recent_days} days.` : "Find studios with upcoming and recent Steam releases."}
        actions={
          <>
            <Button variant="outline" onClick={() => setLookupOpen(true)}><Link2 /> Add Steam links</Button>
            <Button disabled={!online} loading={runner.running} onClick={() => runner.start().then(afterRun).catch(showError)}>
              <Search /> Find games
            </Button>
          </>
        }
      />
      {!online ? <p className="mb-4 rounded-lg bg-warning-soft p-3 text-sm text-warning">You are offline. Discovery needs the internet; earlier results stay available below and are marked when they may be out of date.</p> : null}
      {progress ? (
        <Card className="mb-4 flex items-center gap-3 p-4">
          <div className="flex-1"><Progress value={progress.percent} label={progress.message || "Checking Steam…"} /></div>
          <Button variant="outline" size="sm" onClick={() => (runner.running ? runner.cancel() : lookup.cancel())}>Cancel</Button>
        </Card>
      ) : null}

      <Card className="mb-4 grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Upcoming window (days)">{(p) => <Input {...p} type="number" min={1} max={365} placeholder={String(meta.data?.upcoming_days ?? 90)} value={upcoming} onChange={(e) => setUpcoming(e.target.value ? Number(e.target.value) : "")} />}</Field>
        <Field label="Recent window (days)">{(p) => <Input {...p} type="number" min={1} max={730} placeholder={String(meta.data?.recent_days ?? 150)} value={recent} onChange={(e) => setRecent(e.target.value ? Number(e.target.value) : "")} />}</Field>
        <Field label="Show">
          {(p) => (
            <NativeSelect {...p} value={status} onChange={(e) => setStatus(e.target.value as LeadStatus)}>
              <option value="new">To review</option>
              <option value="saved">Saved to Prospects</option>
              <option value="dismissed">Dismissed</option>
            </NativeSelect>
          )}
        </Field>
        <Field label="Minimum score">{(p) => <Input {...p} type="number" value={minScore} onChange={(e) => setMinScore(Number(e.target.value) || 0)} />}</Field>
        <Field label="Genre">{(p) => <Input {...p} value={genre} onChange={(e) => setGenre(e.target.value)} placeholder="e.g. Strategy" />}</Field>
        <Field label="Platform">{(p) => <Input {...p} value={platform} onChange={(e) => setPlatform(e.target.value)} placeholder="Windows, Mac, Linux" />}</Field>
        <Field label="Search results">{(p) => <Input {...p} value={text} onChange={(e) => setText(e.target.value)} placeholder="Game or studio" />}</Field>
        <div className="flex flex-col justify-end gap-2 text-sm">
          <div className="flex flex-wrap gap-2">
            {(["upcoming", "recent", "unknown_date"] as Timing[]).map((t) => (
              <button key={t} type="button" aria-pressed={timings.includes(t)} onClick={() => setTimings(timings.includes(t) ? timings.filter((x) => x !== t) : [...timings, t])}
                className={cn("rounded-full border px-3 py-1 text-xs", timings.includes(t) ? "border-primary bg-primary-soft" : "text-muted-foreground")}>
                {TIMING_LABEL[t]}
              </button>
            ))}
          </div>
        </div>
        <label className="flex items-center gap-2 text-sm"><Switch checked={selfPublished} onCheckedChange={setSelfPublished} /> Self-published only</label>
        <label className="flex items-center gap-2 text-sm"><Switch checked={hideInCrm} onCheckedChange={setHideInCrm} /> Hide studios already in CRM</label>
        <label className="flex items-center gap-2 text-sm"><Switch checked={includeDlc} onCheckedChange={setIncludeDlc} /> Include DLC</label>
      </Card>

      {lastRun.data ? (
        <p className="mb-3 text-xs text-muted-foreground">
          Last check {formatDateTime(lastRun.data.finished_at ?? lastRun.data.started_at)} · {humanize(lastRun.data.status)} · {plural(lastRun.data.found, "game")}
          {lastRun.data.error ? ` · ${lastRun.data.error}` : ""}
        </p>
      ) : null}
      {leads.error ? <ErrorState error={leads.error} onRetry={() => leads.refetch()} /> : null}
      {leads.isLoading ? <LoadingRows rows={6} /> : null}
      {leads.data && shown.length === 0 ? (
        <EmptyState icon={<Sparkles />} title="No games to review" description={lastRun.data ? "Change the filters, or check Steam again." : "Choose “Find games” to check Steam for upcoming and recent releases."} />
      ) : null}

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {shown.map((lead) => (
          <Card key={lead.id} className="flex flex-col p-4">
            <div className="flex items-start justify-between gap-2">
              <button type="button" className="min-w-0 text-left" onClick={() => setOpen(lead)}>
                <p className="truncate font-semibold hover:underline">{lead.candidate.title}</p>
                <p className="truncate text-sm text-muted-foreground">{lead.candidate.developers.join(", ") || "Developer unknown"}</p>
              </button>
              <span className="tabular rounded-lg bg-primary-soft px-2 py-1 text-sm font-semibold" aria-label={`Score ${lead.score.total}`}>{lead.score.total}</span>
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <Badge tone={TIMING_TONE[lead.timing]}>{TIMING_LABEL[lead.timing]}</Badge>
              <Badge tone="outline">{lead.candidate.release_date ? formatDate(lead.candidate.release_date) : lead.candidate.release_text || "Date unknown"}</Badge>
              {lead.crm_state !== "not_in_crm" ? <Badge tone="warning">{CRM_LABEL[lead.crm_state]}</Badge> : null}
              {lead.contact.status !== "not_found" ? <Badge tone={lead.contact.status === "verified_source" ? "success" : "warning"}>{CONTACT_LABEL[lead.contact.status]}</Badge> : null}
              {lead.outdated ? <Badge tone="warning">Out of date</Badge> : null}
            </div>
            <div className="mt-auto flex gap-2 pt-3">
              <Button size="sm" onClick={() => setOpen(lead)}>Review</Button>
              {lead.status === "new" ? <Button size="sm" variant="ghost" onClick={() => dismiss.mutate(lead.id)}><X /> Dismiss</Button> : null}
            </div>
          </Card>
        ))}
      </div>
      {meta.data ? <p className="mt-6 text-xs text-muted-foreground">{meta.data.attribution} Region is not provided by Steam and cannot be filtered.</p> : null}

      <LeadDetail lead={open} onClose={() => setOpen(null)} />
      <Dialog
        open={lookupOpen}
        onOpenChange={setLookupOpen}
        title="Add games by Steam link"
        description="Paste Steam store links or app ids, one per line."
        footer={
          <>
            <Button variant="outline" onClick={() => setLookupOpen(false)}>Cancel</Button>
            <Button disabled={!references.trim() || !online} loading={lookup.running} onClick={() => lookup.start().then((o) => { setLookupOpen(false); setReferences(""); return afterRun(o); }).catch(showError)}>Look up</Button>
          </>
        }
      >
        <Textarea aria-label="Steam links or app ids" rows={6} value={references} onChange={(e) => setReferences(e.target.value)} placeholder={"https://store.steampowered.com/app/413150/\n1145360"} />
      </Dialog>
    </div>
  );
}
