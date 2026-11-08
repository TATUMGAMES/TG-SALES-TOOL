import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, ArchiveRestore, ExternalLink, Gamepad2, KanbanSquare, Mail, MessageSquarePlus, Pencil, UserPlus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { Button } from "@/components/ui/button";
import { Badge, Card, Dot, LANE_COLORS } from "@/components/ui/card";
import { Dialog, Sheet } from "@/components/ui/dialog";
import { Field, Input, NativeSelect, Textarea } from "@/components/ui/form";
import { ErrorState, LoadingRows, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/misc";
import { api } from "@/lib/api";
import type { ContactInfo, OrganizationDetail } from "@/lib/api-types";
import { formatDate, formatDateTime, humanize, relativeDue } from "@/lib/format";
import { showError, useAction } from "@/lib/hooks";
import { CONTACT_STATUS_LABELS, LANE_LABELS, ORGANIZATION_TYPE_LABELS, type ContactStatus } from "@/lib/types";
import { NewOpportunityDialog } from "../pipeline/NewOpportunityDialog";
import { ProspectForm } from "./ProspectForm";

const STATUS_TONE: Record<ContactStatus, "neutral" | "warning" | "success" | "info"> = {
  unknown: "neutral",
  not_contacted: "info",
  attempted: "warning",
  responded: "success",
};

function ContactDialog({
  open,
  onOpenChange,
  organizationId,
  contact,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  organizationId: string;
  contact?: ContactInfo | undefined;
}) {
  const client = useQueryClient();
  const [values, setValues] = useState({
    name: contact?.name ?? "",
    role_title: contact?.role_title ?? "",
    email: contact?.email ?? "",
    linkedin: contact?.social_urls?.linkedin ?? "",
    status: (contact?.status ?? "unknown") as ContactStatus,
    notes: contact?.notes ?? "",
  });
  const [busy, setBusy] = useState(false);
  const [warning, setWarning] = useState<string | null>(null);
  const set = (key: keyof typeof values) => (e: { target: { value: string } }) => setValues({ ...values, [key]: e.target.value });

  const save = async () => {
    setBusy(true);
    try {
      if (values.email) {
        const used = await api.get<string[]>("/contacts/email-in-use", {
          email: values.email,
          exclude_contact_id: contact?.id ?? null,
        });
        if (used.length && !warning) {
          setWarning(`This email is already used for ${used.join(", ")}. Save again to keep it anyway.`);
          setBusy(false);
          return;
        }
      }
      const body = {
        name: values.name || null,
        role_title: values.role_title || null,
        email: values.email || null,
        social_urls: values.linkedin ? { linkedin: values.linkedin } : {},
        status: values.status,
        notes: values.notes || null,
      };
      if (contact) await api.put(`/contacts/${contact.id}`, body);
      else await api.post(`/prospects/${organizationId}/contacts`, body);
      await client.invalidateQueries({ queryKey: ["prospect", organizationId] });
      onOpenChange(false);
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
      title={contact ? "Edit contact" : "Add contact"}
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={save} loading={busy}>Save</Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        {warning ? <p role="alert" className="rounded-lg bg-warning-soft p-2 text-sm text-warning sm:col-span-2">{warning}</p> : null}
        <Field label="Name">{(p) => <Input {...p} value={values.name} onChange={set("name")} autoFocus />}</Field>
        <Field label="Job title">{(p) => <Input {...p} value={values.role_title} onChange={set("role_title")} />}</Field>
        <Field label="Business email">{(p) => <Input {...p} type="email" value={values.email} onChange={set("email")} />}</Field>
        <Field label="LinkedIn profile">{(p) => <Input {...p} value={values.linkedin} onChange={set("linkedin")} placeholder="https://www.linkedin.com/in/…" />}</Field>
        <Field label="Outreach status" hint="Not guessed from the email: set it when you know." className="sm:col-span-2">
          {(p) => (
            <NativeSelect {...p} value={values.status} onChange={set("status")}>
              {Object.entries(CONTACT_STATUS_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </NativeSelect>
          )}
        </Field>
        <Field label="Notes" className="sm:col-span-2">{(p) => <Textarea {...p} value={values.notes} onChange={set("notes")} rows={3} />}</Field>
      </div>
    </Dialog>
  );
}

function GameDialog({ open, onOpenChange, organizationId }: { open: boolean; onOpenChange: (open: boolean) => void; organizationId: string }) {
  const [values, setValues] = useState({ title: "", role: "developer", platform: "", store_url: "", release_date: "" });
  const add = useAction(
    () =>
      api.post(`/prospects/${organizationId}/games`, {
        title: values.title,
        role: values.role,
        platform: values.platform || null,
        store_url: values.store_url || null,
        release_date: values.release_date || null,
        release_precision: values.release_date ? "day" : "unknown",
      }),
    { invalidate: [["prospect", organizationId]], success: "Game added" },
  );
  const set = (key: keyof typeof values) => (e: { target: { value: string } }) => setValues({ ...values, [key]: e.target.value });
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Add game"
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button disabled={!values.title.trim()} loading={add.isPending} onClick={() => add.mutate(undefined, { onSuccess: () => onOpenChange(false) })}>Add game</Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Title" required className="sm:col-span-2">{(p) => <Input {...p} value={values.title} onChange={set("title")} autoFocus />}</Field>
        <Field label="Studio's role">
          {(p) => (
            <NativeSelect {...p} value={values.role} onChange={set("role")}>
              <option value="developer">Developer</option>
              <option value="publisher">Publisher</option>
            </NativeSelect>
          )}
        </Field>
        <Field label="Platform">{(p) => <Input {...p} value={values.platform} onChange={set("platform")} placeholder="PC, Switch…" />}</Field>
        <Field label="Store page">{(p) => <Input {...p} value={values.store_url} onChange={set("store_url")} />}</Field>
        <Field label="Release date">{(p) => <Input {...p} type="date" value={values.release_date} onChange={set("release_date")} />}</Field>
      </div>
    </Dialog>
  );
}

export function ProspectDetail({ id, onClose }: { id: string | null; onClose: () => void }) {
  const query = useQuery({
    queryKey: ["prospect", id],
    queryFn: () => api.get<OrganizationDetail>(`/prospects/${id}`),
    enabled: Boolean(id),
  });
  const [editing, setEditing] = useState(false);
  const [contactDialog, setContactDialog] = useState<{ open: boolean; contact?: ContactInfo }>({ open: false });
  const [gameOpen, setGameOpen] = useState(false);
  const [opportunityOpen, setOpportunityOpen] = useState(false);
  const [note, setNote] = useState("");
  const detail = query.data;

  const archive = useAction(
    (archived: boolean) => api.post("/prospects/bulk", { ids: [id], action: archived ? "archive" : "restore" }),
    { invalidate: [["prospects"], ["prospect", id]], success: "Saved" },
  );
  const addNote = useAction(() => api.post(`/prospects/${id}/notes`, { text: note }), {
    invalidate: [["prospect", id]],
    success: "Note added",
  });
  const archiveContact = useAction(
    (vars: { contactId: string; archived: boolean }) => api.post(`/contacts/${vars.contactId}/archive`, { archived: vars.archived }),
    { invalidate: [["prospect", id]] },
  );

  return (
    <Sheet
      open={Boolean(id)}
      onOpenChange={(open) => !open && onClose()}
      title={detail?.name ?? "Prospect"}
      description={detail ? [ORGANIZATION_TYPE_LABELS[detail.company_type], detail.location, detail.country].filter(Boolean).join(" · ") : undefined}
      actions={
        detail ? (
          <Button variant="ghost" size="icon-sm" aria-label="Edit prospect" onClick={() => setEditing(true)}>
            <Pencil />
          </Button>
        ) : null
      }
    >
      {query.isLoading ? <LoadingRows /> : null}
      {query.error ? <ErrorState error={query.error} onRetry={() => query.refetch()} /> : null}
      {detail ? (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            {detail.archived ? <Badge tone="warning">Archived</Badge> : null}
            {detail.tags.map((tag) => <Badge key={tag} tone="purple">{tag}</Badge>)}
            <Badge tone="outline">Source: {humanize(detail.source)}</Badge>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={() => setOpportunityOpen(true)}><KanbanSquare /> New opportunity</Button>
            <Button size="sm" variant="outline" onClick={() => setContactDialog({ open: true })}><UserPlus /> Add contact</Button>
            <Button size="sm" variant="outline" onClick={() => setGameOpen(true)}><Gamepad2 /> Add game</Button>
            <Button size="sm" variant="ghost" loading={archive.isPending} onClick={() => archive.mutate(!detail.archived)}>
              {detail.archived ? <><ArchiveRestore /> Restore</> : <><Archive /> Archive</>}
            </Button>
          </div>

          {detail.links.length ? (
            <div className="flex flex-wrap gap-2">
              {detail.links.map((link) => (
                <a key={link.url} href={link.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 rounded-full border px-3 py-1 text-xs hover:bg-muted">
                  {link.label} <ExternalLink className="size-3" />
                </a>
              ))}
            </div>
          ) : null}

          <Tabs defaultValue="contacts">
            <TabsList>
              <TabsTrigger value="contacts">Contacts ({detail.contacts.filter((c) => !c.archived).length})</TabsTrigger>
              <TabsTrigger value="opportunities">Opportunities ({detail.opportunities.length})</TabsTrigger>
              <TabsTrigger value="games">Games ({detail.games.length})</TabsTrigger>
              <TabsTrigger value="timeline">Timeline</TabsTrigger>
            </TabsList>

            <TabsContent value="contacts" className="mt-3 space-y-2">
              {detail.contacts.length === 0 ? <p className="text-sm text-muted-foreground">No contacts yet.</p> : null}
              {detail.contacts.map((contact) => (
                <Card key={contact.id} className={contact.archived ? "p-3 opacity-60" : "p-3"}>
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="font-medium">{contact.name ?? "Unnamed contact"} {contact.archived ? <Badge>Archived</Badge> : null}</p>
                      <p className="text-sm text-muted-foreground">{contact.role_title ?? "—"}</p>
                      {contact.email ? (
                        <a href={`mailto:${contact.email}`} className="mt-1 inline-flex items-center gap-1 text-sm text-primary underline-offset-2 hover:underline">
                          <Mail className="size-3.5" /> {contact.email}
                        </a>
                      ) : null}
                      {contact.provenance ? <p className="mt-1 text-xs text-muted-foreground">Source: {contact.provenance}</p> : null}
                    </div>
                    <div className="flex items-center gap-1">
                      <Badge tone={STATUS_TONE[contact.status]}>{CONTACT_STATUS_LABELS[contact.status]}</Badge>
                      <Button variant="ghost" size="icon-sm" aria-label={`Edit ${contact.name ?? "contact"}`} onClick={() => setContactDialog({ open: true, contact })}>
                        <Pencil />
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => archiveContact.mutate({ contactId: contact.id, archived: !contact.archived })}>
                        {contact.archived ? "Restore" : "Archive"}
                      </Button>
                    </div>
                  </div>
                </Card>
              ))}
            </TabsContent>

            <TabsContent value="opportunities" className="mt-3 space-y-2">
              {detail.opportunities.length === 0 ? (
                <p className="text-sm text-muted-foreground">No opportunities. A prospect can have several, one per product lane.</p>
              ) : null}
              {detail.opportunities.map((opp) => {
                const due = relativeDue(opp.next_action_at);
                return (
                  <Link key={opp.id} to={`/pipeline?opportunity=${opp.id}`} className="block">
                    <Card className="p-3 transition-colors hover:bg-muted/50">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="flex items-center gap-2 font-medium">
                          <Dot color={LANE_COLORS[opp.product_lane] ?? "var(--brand-purple)"} />
                          {opp.title ?? LANE_LABELS[opp.product_lane]}
                        </p>
                        <Badge tone={opp.closed ? "neutral" : "purple"}>{opp.stage_name}</Badge>
                      </div>
                      <p className={due.overdue ? "mt-1 text-sm font-medium text-danger" : "mt-1 text-sm text-muted-foreground"}>
                        {LANE_LABELS[opp.product_lane]} · {due.text}
                        {opp.next_action_note ? ` · ${opp.next_action_note}` : ""}
                      </p>
                    </Card>
                  </Link>
                );
              })}
            </TabsContent>

            <TabsContent value="games" className="mt-3 space-y-2">
              {detail.games.length === 0 ? <p className="text-sm text-muted-foreground">No games yet.</p> : null}
              {detail.games.map((game) => (
                <Card key={game.id} className="flex flex-wrap items-center justify-between gap-2 p-3">
                  <div>
                    <p className="font-medium">{game.title}</p>
                    <p className="text-sm text-muted-foreground">
                      {humanize(game.role)} · {game.platform ?? "Platform unknown"} · Release {game.release_date ? formatDate(game.release_date) : "date unknown"}
                    </p>
                  </div>
                  {game.store_url ? (
                    <a href={game.store_url} target="_blank" rel="noopener noreferrer" className="text-sm text-primary hover:underline">
                      Store page
                    </a>
                  ) : null}
                </Card>
              ))}
            </TabsContent>

            <TabsContent value="timeline" className="mt-3 space-y-3">
              <div className="flex gap-2">
                <Input aria-label="New note" placeholder="Add a note…" value={note} onChange={(e) => setNote(e.target.value)} />
                <Button disabled={!note.trim()} loading={addNote.isPending} onClick={() => addNote.mutate(undefined, { onSuccess: () => setNote("") })}>
                  <MessageSquarePlus /> Add
                </Button>
              </div>
              <ol className="relative space-y-3 border-l pl-4">
                {detail.timeline.map((entry) => (
                  <li key={entry.id} className={entry.voided ? "opacity-60" : undefined}>
                    <span className="absolute -left-[5px] mt-1.5 size-2.5 rounded-full bg-brand-purple" aria-hidden />
                    <p className={entry.voided ? "text-sm line-through" : "text-sm"}>{entry.summary}</p>
                    <p className="text-xs text-muted-foreground">
                      {formatDateTime(entry.occurred_at)} {entry.voided ? "· marked as a mistake" : ""}
                    </p>
                  </li>
                ))}
              </ol>
            </TabsContent>
          </Tabs>

          {detail.notes ? (
            <Card className="p-3">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Notes</p>
              <p className="mt-1 whitespace-pre-wrap text-sm">{detail.notes}</p>
            </Card>
          ) : null}
          <p className="text-xs text-muted-foreground">
            Added {formatDateTime(detail.created_at)} · Updated {formatDateTime(detail.updated_at)}
          </p>

          <ProspectForm open={editing} onOpenChange={setEditing} existing={detail} />
          {contactDialog.open ? (
            <ContactDialog
              open
              onOpenChange={(open) => setContactDialog({ open })}
              organizationId={detail.id}
              contact={contactDialog.contact}
            />
          ) : null}
          {gameOpen ? <GameDialog open onOpenChange={setGameOpen} organizationId={detail.id} /> : null}
          <NewOpportunityDialog open={opportunityOpen} onOpenChange={setOpportunityOpen} organization={{ id: detail.id, name: detail.name }} />
        </div>
      ) : null}
    </Sheet>
  );
}

