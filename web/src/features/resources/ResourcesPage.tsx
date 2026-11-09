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
import { ArrowDown, ArrowUp, ExternalLink, FolderOpen, ImageUp, Link2, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardHeader } from "@/components/ui/card";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { Field, Input, NativeSelect, Textarea } from "@/components/ui/form";
import { EmptyState, ErrorState, LoadingRows, PageHeader } from "@/components/ui/misc";
import { api } from "@/lib/api";
import type { ResourceInfo } from "@/lib/api-types";
import { showError, useAction, useInfo } from "@/lib/hooks";

interface Draft {
  title: string;
  kind: "link" | "folder";
  target: string;
  category: string;
  notes: string;
}

function ResourceDialog({ open, onOpenChange, resource }: { open: boolean; onOpenChange: (o: boolean) => void; resource?: ResourceInfo | undefined }) {
  const client = useQueryClient();
  const [draft, setDraft] = useState<Draft>({
    title: resource?.title ?? "",
    kind: (resource?.kind as Draft["kind"]) ?? "link",
    target: resource?.target ?? "",
    category: resource?.category ?? "",
    notes: resource?.notes ?? "",
  });
  const [busy, setBusy] = useState(false);
  const set = (key: keyof Draft) => (e: { target: { value: string } }) => setDraft({ ...draft, [key]: e.target.value });
  const save = async () => {
    setBusy(true);
    try {
      const body = { ...draft, category: draft.category || null, notes: draft.notes || null };
      if (resource) await api.put(`/resources/${resource.id}`, body);
      else await api.post("/resources", body);
      await client.invalidateQueries({ queryKey: ["resources"] });
      onOpenChange(false);
    } catch (error) {
      showError(error);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={resource ? "Edit bookmark" : "Add bookmark"}
      footer={<><Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button><Button onClick={save} loading={busy} disabled={!draft.title.trim() || !draft.target.trim()}>Save</Button></>}>
      <div className="grid gap-3">
        <Field label="Type">
          {(p) => (
            <NativeSelect {...p} value={draft.kind} onChange={set("kind")}>
              <option value="link">Web link (shared with colleagues through sync)</option>
              <option value="folder">Folder on this computer (stays on this computer)</option>
            </NativeSelect>
          )}
        </Field>
        <Field label="Name" required>{(p) => <Input {...p} value={draft.title} onChange={set("title")} placeholder="e.g. Data room" />}</Field>
        <Field label={draft.kind === "link" ? "Web address" : "Folder path"} required hint={draft.kind === "link" ? "Only https/http addresses. Never paste passwords or private share tokens." : "The full path, e.g. C:\\Users\\you\\Documents\\Sales material"}>
          {(p) => <Input {...p} value={draft.target} onChange={set("target")} />}
        </Field>
        <Field label="Category">{(p) => <Input {...p} value={draft.category} onChange={set("category")} placeholder="e.g. Pitch decks" />}</Field>
        <Field label="Notes">{(p) => <Textarea {...p} rows={2} value={draft.notes} onChange={set("notes")} />}</Field>
      </div>
    </Dialog>
  );
}

export function ResourcesPage() {
  const info = useInfo();
  const resources = useQuery({ queryKey: ["resources"], queryFn: () => api.get<ResourceInfo[]>("/resources") });
  const [editing, setEditing] = useState<{ resource?: ResourceInfo } | null>(null);
  const [deleting, setDeleting] = useState<ResourceInfo | null>(null);
  const remove = useAction((id: string) => api.delete(`/resources/${id}`), { invalidate: [["resources"]], success: "Bookmark removed" });
  const reorder = useAction((ids: string[]) => api.put("/resources/order", { ids }), { invalidate: [["resources"]] });
  const openFolder = useAction((id: string) => api.post(`/resources/${id}/open`));

  const items = resources.data ?? [];
  const groups = [...new Set(items.map((r) => r.category ?? "Other"))];
  const move = (index: number, offset: number) => {
    const ids = items.map((r) => r.id);
    const [moved] = ids.splice(index, 1);
    if (moved) ids.splice(index + offset, 0, moved);
    reorder.mutate(ids);
  };

  return (
    <div className="space-y-5">
      <PageHeader title="Resources" description="Bookmarks to internal documents and folders." actions={<Button onClick={() => setEditing({})}><Plus /> Add bookmark</Button>} />
      <Card className="flex flex-wrap items-center justify-between gap-3 p-4 text-sm">
        <p className="text-muted-foreground">The company name, logo, browser icon and accent color are set in Settings › Branding.</p>
        <Button asChild variant="outline" size="sm"><Link to="/settings?tab=branding"><ImageUp /> Open branding settings</Link></Button>
      </Card>

      {resources.error ? <ErrorState error={resources.error} /> : null}
      {resources.isLoading ? <LoadingRows /> : null}
      {items.length === 0 && resources.data ? (
        <EmptyState icon={<Link2 />} title="No bookmarks yet" description="Add links to your data room, pitch decks or shared drives, or folders on this computer." action={<Button onClick={() => setEditing({})}><Plus /> Add bookmark</Button>} />
      ) : null}
      {groups.map((group) => (
        <Card key={group}>
          <CardHeader title={group} />
          <ul className="divide-y px-5 pb-3">
            {items.filter((r) => (r.category ?? "Other") === group).map((r) => {
              const index = items.indexOf(r);
              return (
                <li key={r.id} className="flex flex-wrap items-center gap-2 py-3">
                  {r.kind === "folder" ? <FolderOpen className="size-5 text-brand-teal" aria-hidden /> : <Link2 className="size-5 text-brand-purple" aria-hidden />}
                  <div className="min-w-0 flex-1">
                    <p className="font-medium">{r.title} {r.kind === "folder" ? <Badge tone="outline">This computer only</Badge> : null} {!r.available ? <Badge tone="warning">Folder not found</Badge> : null}</p>
                    <p className="truncate text-xs text-muted-foreground">{r.target}</p>
                    {r.notes ? <p className="text-sm text-muted-foreground">{r.notes}</p> : null}
                  </div>
                  {r.kind === "link" ? (
                    <Button size="sm" asChild><a href={r.target} target="_blank" rel="noopener noreferrer"><ExternalLink /> Open</a></Button>
                  ) : info.data?.desktop_integration ? (
                    <Button size="sm" disabled={!r.available} onClick={() => openFolder.mutate(r.id)}><FolderOpen /> Open folder</Button>
                  ) : null}
                  <Button size="icon-sm" variant="ghost" aria-label={`Move ${r.title} up`} disabled={index === 0} onClick={() => move(index, -1)}><ArrowUp /></Button>
                  <Button size="icon-sm" variant="ghost" aria-label={`Move ${r.title} down`} disabled={index === items.length - 1} onClick={() => move(index, 1)}><ArrowDown /></Button>
                  <Button size="icon-sm" variant="ghost" aria-label={`Edit ${r.title}`} onClick={() => setEditing({ resource: r })}><Pencil /></Button>
                  <Button size="icon-sm" variant="ghost" aria-label={`Remove ${r.title}`} onClick={() => setDeleting(r)}><Trash2 /></Button>
                </li>
              );
            })}
          </ul>
        </Card>
      ))}
      {editing ? <ResourceDialog open onOpenChange={(o) => !o && setEditing(null)} resource={editing.resource} /> : null}
      <ConfirmDialog open={deleting !== null} onOpenChange={(o) => !o && setDeleting(null)} title="Remove this bookmark?" description="Only the bookmark is removed; the document or folder itself is not touched." confirmLabel="Remove" onConfirm={async () => { if (deleting) await remove.mutateAsync(deleting.id); }} />
    </div>
  );
}
