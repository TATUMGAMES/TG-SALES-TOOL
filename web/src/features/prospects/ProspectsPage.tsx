import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Archive, ArchiveRestore, ChevronLeft, ChevronRight, Download, Plus, Search, Tag, Users, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { useAppDialogs } from "@/components/layout/dialogs";
import { Button } from "@/components/ui/button";
import { Badge, Card } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, NativeSelect } from "@/components/ui/form";
import { Checkbox, EmptyState, ErrorState, LoadingRows, PageHeader, Switch } from "@/components/ui/misc";
import { api, download } from "@/lib/api";
import type { SearchResult } from "@/lib/api-types";
import { formatDate, relativeDue } from "@/lib/format";
import { showError, useAction, useDebounced } from "@/lib/hooks";
import { ORGANIZATION_TYPE_LABELS } from "@/lib/types";
import { cn, plural } from "@/lib/utils";
import { ProspectDetail } from "./ProspectDetail";

const PAGE = 50;

export function ProspectsPage() {
  const [params, setParams] = useSearchParams();
  const [text, setText] = useState(params.get("q") ?? "");
  const [tag, setTag] = useState("");
  const [type, setType] = useState("");
  const [archived, setArchived] = useState(false);
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [tagDialog, setTagDialog] = useState<"add_tag" | "remove_tag" | null>(null);
  const [tagText, setTagText] = useState("");
  const dialogs = useAppDialogs();
  const search = useDebounced(text);
  const openId = params.get("id");

  useEffect(() => setText(params.get("q") ?? ""), [params]);
  useEffect(() => setPage(0), [search, tag, type, archived]);

  const filters = { text: search, tag, company_type: type, include_archived: archived, limit: PAGE, offset: page * PAGE };
  const query = useQuery({
    queryKey: ["prospects", filters],
    queryFn: () => api.get<SearchResult>("/prospects", filters),
    placeholderData: keepPreviousData,
  });
  const tags = useQuery({ queryKey: ["prospects", "tags"], queryFn: () => api.get<string[]>("/prospects/tags") });

  const rows = query.data?.rows ?? [];
  const total = query.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE));
  const allSelected = rows.length > 0 && rows.every((r) => selected.has(r.id));
  const ids = useMemo(() => [...selected], [selected]);

  const bulk = useAction(
    (vars: { action: string; tag?: string }) => api.post<{ count: number }>("/prospects/bulk", { ids, ...vars }),
    { invalidate: [["prospects"]], success: (r) => `${plural(r.count, "prospect")} updated` },
  );

  const open = (id: string | null) => {
    const next = new URLSearchParams(params);
    if (id) next.set("id", id);
    else next.delete("id");
    setParams(next, { replace: !id });
  };

  const toggle = (id: string) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  };

  const exportCsv = async () => {
    try {
      await download("/prospects/export", ids.length ? { ids } : { text: search, tag: tag || null, company_type: type || null, include_archived: archived }, "tg_sales_prospects.csv");
    } catch (error) {
      showError(error);
    }
  };

  return (
    <div>
      <PageHeader
        title="Prospects"
        description={query.data ? `${plural(total, "prospect")}${search ? ` matching “${search}”` : ""}` : "Studios, publishers and other companies you sell to."}
        actions={
          <>
            <Button variant="outline" onClick={exportCsv}>
              <Download /> Export CSV
            </Button>
            <Button onClick={dialogs.openNewProspect}>
              <Plus /> New prospect
            </Button>
          </>
        }
      />

      <Card className="mb-4 p-3">
        <div className="grid gap-3 md:grid-cols-[1fr_180px_180px_auto] md:items-center">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <Input
              aria-label="Search prospects"
              placeholder="Names, websites, contacts, games, tags…"
              className="pl-9"
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
          </div>
          <NativeSelect aria-label="Filter by tag" value={tag} onChange={(e) => setTag(e.target.value)}>
            <option value="">All tags</option>
            {(tags.data ?? []).map((t) => <option key={t} value={t}>{t}</option>)}
          </NativeSelect>
          <NativeSelect aria-label="Filter by type" value={type} onChange={(e) => setType(e.target.value)}>
            <option value="">All types</option>
            {Object.entries(ORGANIZATION_TYPE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </NativeSelect>
          <label className="flex items-center gap-2 text-sm">
            <Switch checked={archived} onCheckedChange={setArchived} aria-label="Show archived" /> Show archived
          </label>
        </div>
      </Card>

      {selected.size ? (
        <div className="sticky top-[4.5rem] z-20 mb-3 flex flex-wrap items-center gap-2 rounded-xl border bg-primary-soft p-2 shadow-card">
          <span className="px-2 text-sm font-medium">{plural(selected.size, "selected", "selected")}</span>
          <Button size="sm" variant="outline" onClick={() => setTagDialog("add_tag")}><Tag /> Add tag</Button>
          <Button size="sm" variant="outline" onClick={() => setTagDialog("remove_tag")}><Tag /> Remove tag</Button>
          <Button size="sm" variant="outline" onClick={() => bulk.mutate({ action: "archive" })}><Archive /> Archive</Button>
          <Button size="sm" variant="outline" onClick={() => bulk.mutate({ action: "restore" })}><ArchiveRestore /> Restore</Button>
          <Button size="sm" variant="outline" onClick={exportCsv}><Download /> Export</Button>
          <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}><X /> Clear</Button>
        </div>
      ) : null}

      {query.error ? <ErrorState error={query.error} onRetry={() => query.refetch()} /> : null}
      {query.isLoading ? <LoadingRows rows={8} /> : null}
      {query.data && rows.length === 0 ? (
        <EmptyState
          icon={<Users />}
          title={search || tag || type ? "No prospects match your search or filters" : "No prospects yet"}
          description={search || tag || type ? "Try fewer words or clear the filters." : "Add your first prospect, import a spreadsheet, or discover studios on Steam."}
          action={
            <div className="flex flex-wrap justify-center gap-2">
              <Button onClick={dialogs.openNewProspect}><Plus /> New prospect</Button>
              <Button variant="outline" onClick={dialogs.openImport}>Import a file</Button>
            </div>
          }
        />
      ) : null}

      {rows.length ? (
        <>
          {/* Desktop and tablet: table */}
          <Card className="hidden overflow-hidden md:block">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-muted/60 text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <tr>
                    <th className="w-10 px-3 py-2.5">
                      <Checkbox
                        aria-label="Select all on this page"
                        checked={allSelected}
                        onCheckedChange={(checked) => {
                          const next = new Set(selected);
                          rows.forEach((r) => (checked ? next.add(r.id) : next.delete(r.id)));
                          setSelected(next);
                        }}
                      />
                    </th>
                    <th className="px-3 py-2.5">Name</th>
                    <th className="px-3 py-2.5">Type</th>
                    <th className="px-3 py-2.5">Location</th>
                    <th className="px-3 py-2.5 text-right">Contacts</th>
                    <th className="px-3 py-2.5 text-right">Open deals</th>
                    <th className="px-3 py-2.5">Next follow-up</th>
                    <th className="px-3 py-2.5">Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => {
                    const due = relativeDue(row.next_follow_up);
                    return (
                      <tr
                        key={row.id}
                        className={cn("cursor-pointer border-t transition-colors hover:bg-muted/40", row.archived && "opacity-60")}
                        onClick={() => open(row.id)}
                      >
                        <td className="px-3 py-2.5" onClick={(e) => e.stopPropagation()}>
                          <Checkbox aria-label={`Select ${row.name}`} checked={selected.has(row.id)} onCheckedChange={() => toggle(row.id)} />
                        </td>
                        <td className="px-3 py-2.5">
                          <button type="button" className="text-left font-medium hover:underline" onClick={() => open(row.id)}>
                            {row.name}
                          </button>
                          <div className="mt-0.5 flex flex-wrap gap-1">
                            {row.domain ? <span className="text-xs text-muted-foreground">{row.domain}</span> : null}
                            {row.tags.slice(0, 3).map((t) => <Badge key={t} tone="purple">{t}</Badge>)}
                            {row.archived ? <Badge tone="warning">Archived</Badge> : null}
                          </div>
                        </td>
                        <td className="px-3 py-2.5">{ORGANIZATION_TYPE_LABELS[row.company_type]}</td>
                        <td className="px-3 py-2.5 text-muted-foreground">{[row.location, row.country].filter(Boolean).join(", ") || "—"}</td>
                        <td className="tabular px-3 py-2.5 text-right">{row.contact_count}</td>
                        <td className="tabular px-3 py-2.5 text-right">{row.open_opportunity_count}</td>
                        <td className={cn("px-3 py-2.5", due.overdue && "font-medium text-danger")}>{row.next_follow_up ? due.text : "—"}</td>
                        <td className="px-3 py-2.5 text-muted-foreground">{formatDate(row.updated_at)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>

          {/* Phones: cards */}
          <div className="space-y-2 md:hidden">
            {rows.map((row) => {
              const due = relativeDue(row.next_follow_up);
              return (
                <Card key={row.id} className={cn("flex items-start gap-3 p-3", row.archived && "opacity-60")}>
                  <Checkbox className="mt-1" aria-label={`Select ${row.name}`} checked={selected.has(row.id)} onCheckedChange={() => toggle(row.id)} />
                  <button type="button" className="min-w-0 flex-1 text-left" onClick={() => open(row.id)}>
                    <p className="font-medium">{row.name}</p>
                    <p className="text-xs text-muted-foreground">
                      {ORGANIZATION_TYPE_LABELS[row.company_type]} · {plural(row.contact_count, "contact")} · {plural(row.open_opportunity_count, "open deal")}
                    </p>
                    {row.next_follow_up ? <p className={cn("mt-1 text-xs", due.overdue ? "font-medium text-danger" : "text-muted-foreground")}>{due.text}</p> : null}
                  </button>
                </Card>
              );
            })}
          </div>

          <div className="mt-4 flex items-center justify-between text-sm">
            <span className="text-muted-foreground">
              Page {page + 1} of {pages}
            </span>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" disabled={page === 0} onClick={() => setPage(page - 1)}><ChevronLeft /> Previous</Button>
              <Button variant="outline" size="sm" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>Next <ChevronRight /></Button>
            </div>
          </div>
        </>
      ) : null}

      <ProspectDetail id={openId} onClose={() => open(null)} />

      <Dialog
        open={tagDialog !== null}
        onOpenChange={(o) => !o && setTagDialog(null)}
        title={tagDialog === "add_tag" ? "Add a tag" : "Remove a tag"}
        description={`Applies to ${plural(selected.size, "selected prospect")}.`}
        size="sm"
        footer={
          <>
            <Button variant="outline" onClick={() => setTagDialog(null)}>Cancel</Button>
            <Button
              disabled={!tagText.trim()}
              loading={bulk.isPending}
              onClick={() => tagDialog && bulk.mutate({ action: tagDialog, tag: tagText.trim() }, { onSuccess: () => { setTagDialog(null); setTagText(""); } })}
            >
              {tagDialog === "add_tag" ? "Add tag" : "Remove tag"}
            </Button>
          </>
        }
      >
        <Field label="Tag">{(p) => <Input {...p} list="known-tags" value={tagText} onChange={(e) => setTagText(e.target.value)} autoFocus />}</Field>
        <datalist id="known-tags">{(tags.data ?? []).map((t) => <option key={t} value={t} />)}</datalist>
      </Dialog>
    </div>
  );
}
