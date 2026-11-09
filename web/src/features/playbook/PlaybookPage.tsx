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
import { BookOpenText, Check, Copy, CopyPlus, History, Pencil, Plus, ShieldCheck, Star, StarOff } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardHeader } from "@/components/ui/card";
import { ConfirmDialog, Dialog, Sheet } from "@/components/ui/dialog";
import { Field, Input, NativeSelect, Textarea } from "@/components/ui/form";
import { EmptyState, ErrorState, LoadingRows, PageHeader, Switch } from "@/components/ui/misc";
import { api } from "@/lib/api";
import type {
  Channel,
  Created,
  OrganizationDetail,
  Outcome,
  PreviewView,
  SearchResult,
  TemplateDetail,
  TemplateSummary,
} from "@/lib/api-types";
import { formatDateTime } from "@/lib/format";
import { copyText, showError, useAction, useDebounced, usePlaybookMeta } from "@/lib/hooks";
import { cn } from "@/lib/utils";

interface Draft {
  title: string;
  body: string;
  channel: Channel;
  label: string;
  category: string;
  audience: string;
  stage: string;
  notes: string;
  tags: string;
}

const EMPTY: Draft = { title: "", body: "", channel: "email", label: "", category: "", audience: "", stage: "", notes: "", tags: "" };

function TemplateEditor({ open, onOpenChange, template, onSaved }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  template?: TemplateDetail | undefined;
  onSaved: (id: string) => void;
}) {
  const meta = usePlaybookMeta();
  const client = useQueryClient();
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!open) return;
    const s = template?.summary;
    setDraft(s ? { title: s.title, body: s.body, channel: s.channel, label: s.label ?? "", category: s.category ?? "", audience: s.audience ?? "", stage: s.stage ?? "", notes: template?.notes ?? "", tags: s.tags.join(", ") } : EMPTY);
  }, [open, template]);
  const set = (key: keyof Draft) => (e: { target: { value: string } }) => setDraft({ ...draft, [key]: e.target.value });
  const limit = draft.channel === "linkedin_connect" ? meta.data?.linkedin_note_limit ?? 300 : null;
  const vocab = meta.data?.vocabulary;

  const save = async () => {
    setBusy(true);
    const body = {
      title: draft.title,
      body: draft.body,
      channel: draft.channel,
      label: draft.label || null,
      category: draft.category || null,
      audience: draft.audience || null,
      stage: draft.stage || null,
      notes: draft.notes || null,
      tags: draft.tags.split(",").map((t) => t.trim()).filter(Boolean),
      expected_revision: template?.summary.revision ?? null,
    };
    try {
      let id = template?.summary.id;
      if (id) await api.put(`/playbook/templates/${id}`, body);
      else id = (await api.post<Created>("/playbook/templates", body)).id;
      await client.invalidateQueries({ queryKey: ["templates"] });
      await client.invalidateQueries({ queryKey: ["template", id] });
      await client.invalidateQueries({ queryKey: ["playbook-meta"] });
      toast.success(template?.summary.is_approved && draft.body !== template.summary.body ? "Saved. The text changed, so approval was removed." : "Template saved");
      onOpenChange(false);
      onSaved(id);
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
      size="lg"
      title={template ? "Edit template" : "New template"}
      description="Placeholders like {studio_name} are filled in from a prospect when you copy."
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={save} loading={busy} disabled={!draft.title.trim() || !draft.body.trim()}>Save</Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Title" required className="sm:col-span-2">{(p) => <Input {...p} value={draft.title} onChange={set("title")} autoFocus />}</Field>
        <Field label="Channel">
          {(p) => (
            <NativeSelect {...p} value={draft.channel} onChange={set("channel")}>
              {(meta.data?.channels ?? []).map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
            </NativeSelect>
          )}
        </Field>
        <Field label="Audience">{(p) => <Input {...p} list="audiences" value={draft.audience} onChange={set("audience")} />}</Field>
        <Field label="Category">{(p) => <Input {...p} list="categories" value={draft.category} onChange={set("category")} />}</Field>
        <Field label="Label">{(p) => <Input {...p} list="labels" value={draft.label} onChange={set("label")} placeholder="e.g. Launch support introduction" />}</Field>
        <Field label="Pipeline stage">{(p) => <Input {...p} list="stages-vocab" value={draft.stage} onChange={set("stage")} />}</Field>
        <Field label="Tags" hint="Separate tags with commas.">{(p) => <Input {...p} value={draft.tags} onChange={set("tags")} />}</Field>
        <Field
          label="Message"
          required
          className="sm:col-span-2"
          hint={
            <span className={cn(limit && draft.body.length > limit && "font-medium text-danger")}>
              {draft.body.length.toLocaleString()} characters{limit ? ` · LinkedIn connection notes allow ${limit}` : ""}
            </span>
          }
        >
          {(p) => <Textarea {...p} rows={9} value={draft.body} onChange={set("body")} />}
        </Field>
        <div className="flex flex-wrap gap-1.5 sm:col-span-2">
          {(meta.data?.placeholders ?? []).map((ph) => (
            <button key={ph.value} type="button" className="rounded-full border px-2.5 py-1 text-xs hover:bg-muted" onClick={() => setDraft({ ...draft, body: `${draft.body}{${ph.value}}` })}>
              {`{${ph.value}}`} <span className="text-muted-foreground">{ph.label}</span>
            </button>
          ))}
        </div>
        <Field label="Internal notes" className="sm:col-span-2">{(p) => <Textarea {...p} rows={2} value={draft.notes} onChange={set("notes")} />}</Field>
      </div>
      <datalist id="audiences">{[...(vocab?.audiences ?? []), ...(meta.data?.suggested_audiences ?? [])].map((a) => <option key={a} value={a} />)}</datalist>
      <datalist id="categories">{(vocab?.categories ?? []).map((a) => <option key={a} value={a} />)}</datalist>
      <datalist id="labels">{(vocab?.labels ?? []).map((a) => <option key={a} value={a} />)}</datalist>
      <datalist id="stages-vocab">{(vocab?.stages ?? []).map((a) => <option key={a} value={a} />)}</datalist>
    </Dialog>
  );
}

function TemplateView({ id, onClose, onEdit }: { id: string; onClose: () => void; onEdit: (t: TemplateDetail) => void }) {
  const meta = usePlaybookMeta();
  const detail = useQuery({ queryKey: ["template", id], queryFn: () => api.get<TemplateDetail>(`/playbook/templates/${id}`) });
  const [orgText, setOrgText] = useState("");
  const [orgId, setOrgId] = useState("");
  const [contactId, setContactId] = useState("");
  const [gameId, setGameId] = useState("");
  const [copied, setCopied] = useState(false);
  const [confirmCopy, setConfirmCopy] = useState(false);
  const [history, setHistory] = useState(false);
  const [outcome, setOutcome] = useState<Outcome>("reply");
  const [outcomeNote, setOutcomeNote] = useState("");
  const search = useDebounced(orgText);
  const orgs = useQuery({ queryKey: ["prospects", "picker", search], queryFn: () => api.get<SearchResult>("/prospects", { text: search, limit: 20 }) });
  const org = useQuery({ queryKey: ["prospect", orgId], queryFn: () => api.get<OrganizationDetail>(`/prospects/${orgId}`), enabled: Boolean(orgId) });
  const preview = useQuery({
    queryKey: ["template-preview", id, detail.data?.summary.revision, orgId, contactId, gameId],
    queryFn: () => api.post<PreviewView>(`/playbook/templates/${id}/preview`, { organization_id: orgId || null, contact_id: contactId || null, game_id: gameId || null }),
    enabled: Boolean(detail.data),
  });
  const refresh = [["template", id], ["templates"]];
  const flag = useAction((vars: { what: "favorite" | "approved" | "archived"; value: boolean }) => api.post(`/playbook/templates/${id}/${vars.what}`, { value: vars.value }), { invalidate: refresh });
  const duplicate = useAction(() => api.post<Created>(`/playbook/templates/${id}/duplicate`), { invalidate: [["templates"]], success: "Copy created" });
  const restore = useAction((revision: number) => api.post(`/playbook/templates/${id}/restore`, { revision, expected_revision: detail.data?.summary.revision }), { invalidate: refresh, success: "Revision restored" });
  const addOutcome = useAction(() => api.post(`/playbook/templates/${id}/outcomes`, { outcome, note: outcomeNote || null }), { invalidate: refresh, success: "Outcome recorded" });

  const doCopy = async () => {
    if (!preview.data) return;
    if (await copyText(preview.data.text)) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
      toast.success("Copied. Paste it into your email or LinkedIn.");
    } else toast.error("Copying failed. Select the text and copy it manually.");
  };

  const t = detail.data;
  const counts = useMemo(() => {
    const result: Record<string, number> = {};
    for (const o of t?.outcomes ?? []) result[o.outcome] = (result[o.outcome] ?? 0) + 1;
    return result;
  }, [t]);

  return (
    <Sheet open onOpenChange={(o) => !o && onClose()} title={t?.summary.title ?? "Template"} description={t ? meta.data?.channels.find((c) => c.value === t.summary.channel)?.label : undefined}
      actions={t ? <Button variant="ghost" size="icon-sm" aria-label="Edit template" onClick={() => onEdit(t)}><Pencil /></Button> : null}>
      {detail.error ? <ErrorState error={detail.error} /> : null}
      {detail.isLoading ? <LoadingRows /> : null}
      {t ? (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-2">
            {t.summary.is_approved ? <Badge tone="success"><ShieldCheck className="size-3.5" /> Approved for external use</Badge> : <Badge tone="warning">Not approved yet</Badge>}
            {t.summary.audience ? <Badge tone="outline">{t.summary.audience}</Badge> : null}
            {t.summary.category ? <Badge tone="outline">{t.summary.category}</Badge> : null}
            {t.summary.tags.map((tag) => <Badge key={tag} tone="purple">{tag}</Badge>)}
            {t.summary.archived ? <Badge>Archived</Badge> : null}
            {t.example_key ? <Badge tone="info">Example: check facts before use</Badge> : null}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={() => flag.mutate({ what: "favorite", value: !t.summary.is_favorite })}>{t.summary.is_favorite ? <><StarOff /> Remove favorite</> : <><Star /> Add to favorites</>}</Button>
            <Button size="sm" variant="outline" onClick={() => flag.mutate({ what: "approved", value: !t.summary.is_approved })}>{t.summary.is_approved ? "Remove approval" : "Mark approved"}</Button>
            <Button size="sm" variant="outline" onClick={() => duplicate.mutate()}><CopyPlus /> Duplicate</Button>
            <Button size="sm" variant="outline" onClick={() => setHistory(true)}><History /> History</Button>
            <Button size="sm" variant="ghost" onClick={() => flag.mutate({ what: "archived", value: !t.summary.archived })}>{t.summary.archived ? "Restore" : "Archive"}</Button>
          </div>

          <Card className="space-y-3 p-4">
            <p className="text-sm font-semibold">Personalize for a prospect</p>
            <div className="grid gap-2 sm:grid-cols-2">
              <Input aria-label="Search prospects" placeholder="Type a prospect name (optional)" value={orgText} onChange={(e) => setOrgText(e.target.value)} />
              <NativeSelect aria-label="Prospect" value={orgId} onChange={(e) => { setOrgId(e.target.value); setContactId(""); setGameId(""); }}>
                <option value="">No prospect</option>
                {(orgs.data?.rows ?? []).map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
              </NativeSelect>
              {org.data ? (
                <>
                  <NativeSelect aria-label="Contact" value={contactId} onChange={(e) => setContactId(e.target.value)}>
                    <option value="">Default contact</option>
                    {org.data.contacts.filter((c) => !c.archived).map((c) => <option key={c.id} value={c.id}>{c.name ?? c.email}</option>)}
                  </NativeSelect>
                  <NativeSelect aria-label="Game" value={gameId} onChange={(e) => setGameId(e.target.value)}>
                    <option value="">Default game</option>
                    {org.data.games.map((g) => <option key={g.id} value={g.id}>{g.title}</option>)}
                  </NativeSelect>
                </>
              ) : null}
            </div>
            {preview.data?.warning ? <p role="status" className="rounded-lg bg-warning-soft p-2 text-sm text-warning">{preview.data.warning}</p> : null}
            {preview.data?.length_warning ? <p className="rounded-lg bg-danger-soft p-2 text-sm text-danger">{preview.data.length_warning}</p> : null}
            <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-lg border bg-muted/40 p-3 font-sans text-sm">{preview.data?.text ?? t.summary.body}</pre>
            <Button onClick={() => (preview.data && !preview.data.complete ? setConfirmCopy(true) : void doCopy())}>
              {copied ? <Check /> : <Copy />} {copied ? "Copied ✓" : "Copy message"}
            </Button>
            <p className="text-xs text-muted-foreground">tg_sales never sends messages and never connects to LinkedIn.</p>
          </Card>

          <Card>
            <CardHeader title="Outcomes" description="Record what happened when you used this template." />
            <div className="space-y-3 p-5 pt-3">
              <div className="flex flex-wrap gap-2 text-sm">
                {(meta.data?.outcomes ?? []).map((o) => <Badge key={o.value} tone="outline">{o.label}: {counts[o.value] ?? 0}</Badge>)}
              </div>
              <div className="grid gap-2 sm:grid-cols-[180px_1fr_auto]">
                <NativeSelect aria-label="Outcome" value={outcome} onChange={(e) => setOutcome(e.target.value as Outcome)}>
                  {(meta.data?.outcomes ?? []).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </NativeSelect>
                <Input aria-label="Note" placeholder="Optional note" value={outcomeNote} onChange={(e) => setOutcomeNote(e.target.value)} />
                <Button variant="outline" loading={addOutcome.isPending} onClick={() => addOutcome.mutate(undefined, { onSuccess: () => setOutcomeNote("") })}>Record</Button>
              </div>
              <ul className="space-y-1 text-sm">
                {(t.outcomes ?? []).slice(0, 10).map((o) => (
                  <li key={o.id} className="text-muted-foreground">{formatDateTime(o.recorded_at)} · {meta.data?.outcomes.find((x) => x.value === o.outcome)?.label}{o.note ? ` · ${o.note}` : ""}</li>
                ))}
              </ul>
            </div>
          </Card>
          {t.notes ? <Card className="p-4 text-sm"><p className="mb-1 text-xs font-medium uppercase text-muted-foreground">Notes</p><p className="whitespace-pre-wrap">{t.notes}</p></Card> : null}

          <ConfirmDialog
            open={confirmCopy}
            onOpenChange={setConfirmCopy}
            title="Copy with unfilled placeholders?"
            description={<p>{preview.data?.warning}</p>}
            confirmLabel="Copy anyway"
            onConfirm={doCopy}
          />
          <Dialog open={history} onOpenChange={setHistory} size="lg" title="Revision history" description="Every saved edit is kept. Restoring creates a new revision.">
            <ol className="space-y-2">
              {t.revisions.map((r) => (
                <li key={r.revision}>
                  <Card className="space-y-2 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="text-sm font-medium">Revision {r.revision} · {r.summary}</p>
                      {r.revision !== t.summary.revision ? (
                        <Button size="sm" variant="outline" onClick={() => restore.mutate(r.revision, { onSuccess: () => setHistory(false) })}>Restore this revision</Button>
                      ) : <Badge tone="success">Current</Badge>}
                    </div>
                    <p className="text-xs text-muted-foreground">{formatDateTime(r.created_at)}{r.author ? ` · ${r.author}` : ""}</p>
                    <pre className="max-h-32 overflow-auto whitespace-pre-wrap rounded bg-muted/50 p-2 font-sans text-xs">{r.content.body}</pre>
                  </Card>
                </li>
              ))}
            </ol>
          </Dialog>
        </div>
      ) : null}
    </Sheet>
  );
}

export function PlaybookPage() {
  const meta = usePlaybookMeta();
  const [text, setText] = useState("");
  const [channel, setChannel] = useState("");
  const [audience, setAudience] = useState("");
  const [category, setCategory] = useState("");
  const [favorites, setFavorites] = useState(false);
  const [approved, setApproved] = useState(false);
  const [archived, setArchived] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [editor, setEditor] = useState<{ template?: TemplateDetail } | null>(null);
  const search = useDebounced(text);
  const filters = { text: search, channel: channel || null, audience: audience || null, category: category || null, favorites_only: favorites, approved_only: approved, archived };
  const list = useQuery({ queryKey: ["templates", filters], queryFn: () => api.get<TemplateSummary[]>("/playbook/templates", filters) });
  const examples = useAction(() => api.post<{ count: number }>("/playbook/examples"), {
    invalidate: [["templates"], ["playbook-meta"]],
    success: (r) => (r.count ? `${r.count} example templates added (unapproved: check their facts first)` : "The examples are already in your library"),
  });
  const channels = meta.data?.channels ?? [];

  return (
    <div>
      <PageHeader
        title="Playbook"
        description="Approved outreach language for email, LinkedIn and calls. Copy, personalize, send yourself."
        actions={
          <>
            <Button variant="outline" onClick={() => examples.mutate()} loading={examples.isPending}><BookOpenText /> Add example templates</Button>
            <Button onClick={() => setEditor({})}><Plus /> New template</Button>
          </>
        }
      />
      <Card className="mb-4 grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4">
        <Input aria-label="Search templates" placeholder="Search templates" value={text} onChange={(e) => setText(e.target.value)} className="lg:col-span-2" />
        <NativeSelect aria-label="Channel" value={channel} onChange={(e) => setChannel(e.target.value)}>
          <option value="">All channels</option>
          {channels.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
        </NativeSelect>
        <NativeSelect aria-label="Audience" value={audience} onChange={(e) => setAudience(e.target.value)}>
          <option value="">All audiences</option>
          {(meta.data?.vocabulary.audiences ?? []).map((a) => <option key={a} value={a}>{a}</option>)}
        </NativeSelect>
        <NativeSelect aria-label="Category" value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">All categories</option>
          {(meta.data?.vocabulary.categories ?? []).map((a) => <option key={a} value={a}>{a}</option>)}
        </NativeSelect>
        <label className="flex items-center gap-2 text-sm"><Switch checked={favorites} onCheckedChange={setFavorites} /> Favorites</label>
        <label className="flex items-center gap-2 text-sm"><Switch checked={approved} onCheckedChange={setApproved} /> Approved only</label>
        <label className="flex items-center gap-2 text-sm"><Switch checked={archived} onCheckedChange={setArchived} /> Show archived</label>
      </Card>
      {list.error ? <ErrorState error={list.error} onRetry={() => list.refetch()} /> : null}
      {list.isLoading ? <LoadingRows /> : null}
      {list.data?.length === 0 ? (
        <EmptyState icon={<BookOpenText />} title="No templates found" description="Create a template, or add the example templates to get started."
          action={<Button onClick={() => setEditor({})}><Plus /> New template</Button>} />
      ) : null}
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {(list.data ?? []).map((t) => (
          <button key={t.id} type="button" onClick={() => setOpen(t.id)} className="text-left">
            <Card className={cn("h-full p-4 transition-shadow hover:shadow-md", t.archived && "opacity-60")}>
              <div className="flex items-start justify-between gap-2">
                <p className="font-semibold">{t.title}</p>
                {t.is_favorite ? <Star className="size-4 shrink-0 fill-brand-yellow text-brand-yellow" aria-label="Favorite" /> : null}
              </div>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                <Badge tone="info">{channels.find((c) => c.value === t.channel)?.label ?? t.channel}</Badge>
                {t.is_approved ? <Badge tone="success">Approved</Badge> : <Badge tone="warning">Not approved</Badge>}
                {t.audience ? <Badge tone="outline">{t.audience}</Badge> : null}
              </div>
              <p className="mt-2 line-clamp-3 text-sm text-muted-foreground">{t.body}</p>
            </Card>
          </button>
        ))}
      </div>
      {open ? <TemplateView id={open} onClose={() => setOpen(null)} onEdit={(template) => setEditor({ template })} /> : null}
      <TemplateEditor open={editor !== null} onOpenChange={(o) => !o && setEditor(null)} template={editor?.template} onSaved={(id) => setOpen(id)} />
    </div>
  );
}
