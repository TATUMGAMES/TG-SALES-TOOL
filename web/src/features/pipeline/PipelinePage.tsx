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

import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  TouchSensor,
  closestCorners,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, GripVertical, KanbanSquare, MoreHorizontal, Plus, Settings2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge, Card, Dot } from "@/components/ui/card";
import { Input } from "@/components/ui/form";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
  EmptyState,
  ErrorState,
  LoadingRows,
  PageHeader,
  Tabs,
  TabsList,
  TabsTrigger,
} from "@/components/ui/misc";
import { api } from "@/lib/api";
import type { Board, OpportunityCard, StageInfo } from "@/lib/api-types";
import { formatDate, relativeDue } from "@/lib/format";
import { showError } from "@/lib/hooks";
import { useLanes } from "@/lib/lanes";
import { cn } from "@/lib/utils";
import { NewOpportunityDialog } from "./NewOpportunityDialog";
import { OpportunitySheet } from "./OpportunitySheet";
import { ReasonDialog } from "./ReasonDialog";
import { StageManager } from "./StageManager";

const OUTCOME_COLOR: Record<string, string> = { won: "var(--brand-green)", lost: "var(--brand-coral)", not_a_fit: "#b4aec0" };

function CardBody({ card, stages, onOpen, onMove, dragHandle }: {
  card: OpportunityCard;
  stages: StageInfo[];
  onOpen: () => void;
  onMove: (stage: StageInfo) => void;
  dragHandle?: React.ReactNode;
}) {
  const due = relativeDue(card.next_action_at);
  const lanes = useLanes();
  const options = stages.filter((s) => s.id !== card.stage_id && (!s.product_lane || s.product_lane === card.product_lane));
  return (
    <Card className="group p-3 transition-shadow hover:shadow-md">
      <div className="flex items-start gap-1.5">
        {dragHandle}
        <button type="button" onClick={onOpen} className="min-w-0 flex-1 text-left">
          <p className="truncate text-sm font-semibold">{card.organization_name}</p>
          <p className="truncate text-xs text-muted-foreground">{card.title ?? lanes.label(card.product_lane)}</p>
        </button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-sm" aria-label={`Move ${card.organization_name}`} className="-mr-1 -mt-1">
              <MoreHorizontal />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent>
            <DropdownMenuLabel>Move to stage</DropdownMenuLabel>
            {options.map((stage) => (
              <DropdownMenuItem key={stage.id} onSelect={() => onMove(stage)}>
                {stage.name}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs">
        <Badge tone="outline" className="gap-1.5">
          <Dot color={lanes.color(card.product_lane)} /> {lanes.label(card.product_lane)}
        </Badge>
        {card.owner_name ? <span className="text-muted-foreground">{card.owner_name}</span> : null}
      </div>
      {!card.closed ? (
        <p className={cn("mt-2 flex items-center gap-1 text-xs", due.overdue ? "font-semibold text-danger" : "text-muted-foreground")}>
          <CalendarClock className="size-3.5" aria-hidden /> {due.text}
          {card.next_action_note ? ` · ${card.next_action_note}` : ""}
        </p>
      ) : null}
      <p className="mt-1 text-[11px] text-muted-foreground">
        {card.last_activity_at ? `Last activity ${formatDate(card.last_activity_at)}` : "No activity yet"}
        {card.release_date ? ` · Release ${formatDate(card.release_date)}` : ""}
      </p>
    </Card>
  );
}

function DraggableCard(props: { card: OpportunityCard; stages: StageInfo[]; onOpen: () => void; onMove: (stage: StageInfo) => void }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: props.card.id, data: props.card });
  return (
    <div ref={setNodeRef} className={cn(isDragging && "opacity-40")}>
      <CardBody
        {...props}
        dragHandle={
          <button
            type="button"
            className="-ml-1 mt-0.5 cursor-grab touch-none rounded p-0.5 text-muted-foreground hover:bg-muted active:cursor-grabbing"
            aria-label={`Drag ${props.card.organization_name}. Press space to pick up, arrow keys to move, space to drop.`}
            {...attributes}
            {...listeners}
          >
            <GripVertical className="size-4" />
          </button>
        }
      />
    </div>
  );
}

function Column({ stage, cards, children, onAdd }: { stage: StageInfo; cards: number; children: React.ReactNode; onAdd: () => void }) {
  const { setNodeRef, isOver } = useDroppable({ id: stage.id, data: stage });
  const lanes = useLanes();
  const color = OUTCOME_COLOR[stage.outcome] ?? (stage.product_lane ? lanes.color(stage.product_lane) : "var(--brand-purple)");
  return (
    <section
      ref={setNodeRef}
      aria-label={`${stage.name}, ${cards} opportunities`}
      className={cn(
        "flex w-[82vw] max-w-[300px] shrink-0 snap-start flex-col rounded-xl border bg-muted/40 sm:w-72",
        isOver && "ring-2 ring-primary",
      )}
    >
      <header className="flex items-center justify-between gap-2 border-b px-3 py-2.5" style={{ boxShadow: `inset 0 3px 0 ${color}` }}>
        <h2 className="truncate text-sm font-semibold">{stage.name}</h2>
        <div className="flex items-center gap-1">
          <Badge>{cards}</Badge>
          {stage.outcome === "open" ? (
            <Button variant="ghost" size="icon-sm" aria-label={`Add opportunity to ${stage.name}`} onClick={onAdd}>
              <Plus />
            </Button>
          ) : null}
        </div>
      </header>
      <div className="flex min-h-24 flex-1 flex-col gap-2 overflow-y-auto p-2" style={{ maxHeight: "calc(100dvh - 17rem)" }}>
        {children}
      </div>
    </section>
  );
}

export function PipelinePage() {
  const client = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [lane, setLane] = useState("all");
  const lanes = useLanes();
  const [filter, setFilter] = useState("");
  const [dragging, setDragging] = useState<OpportunityCard | null>(null);
  const [reason, setReason] = useState<{ card: OpportunityCard; stage: StageInfo } | null>(null);
  const [newIn, setNewIn] = useState<{ stageId?: string } | null>(null);
  const [managing, setManaging] = useState(false);
  const openId = params.get("opportunity");

  const board = useQuery({
    queryKey: ["board", lane],
    queryFn: () => api.get<Board>("/pipeline/board", { lane: lane === "all" ? null : lane }),
  });
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 200, tolerance: 6 } }),
    useSensor(KeyboardSensor),
  );

  const stages = useMemo(
    () => (board.data?.stages ?? []).filter((s) => !s.archived && (lane === "all" || !s.product_lane || s.product_lane === lane)),
    [board.data, lane],
  );
  const cards = useMemo(() => {
    const text = filter.trim().toLowerCase();
    return (board.data?.cards ?? []).filter(
      (c) => !text || c.organization_name.toLowerCase().includes(text) || (c.title ?? "").toLowerCase().includes(text),
    );
  }, [board.data, filter]);

  const open = (id: string | null) => {
    const next = new URLSearchParams(params);
    if (id) next.set("opportunity", id);
    else next.delete("opportunity");
    setParams(next);
  };

  const move = async (card: OpportunityCard, stage: StageInfo, reasonCode?: string, reasonNote?: string) => {
    if (stage.product_lane && stage.product_lane !== card.product_lane) {
      toast.error(`“${stage.name}” is only for ${lanes.label(stage.product_lane)} opportunities.`);
      return;
    }
    if (stage.outcome !== "open" && !reasonCode) {
      setReason({ card, stage });
      return;
    }
    // Optimistic update: the card moves immediately, and moves back if saving fails.
    const key = ["board", lane];
    const previous = client.getQueryData<Board>(key);
    if (previous) {
      client.setQueryData<Board>(key, {
        ...previous,
        cards: previous.cards.map((c) => (c.id === card.id ? { ...c, stage_id: stage.id, closed: stage.outcome !== "open" } : c)),
      });
    }
    try {
      await api.post(`/opportunities/${card.id}/move`, { stage_id: stage.id, reason_code: reasonCode ?? null, reason_note: reasonNote ?? null });
      toast.success(`${card.organization_name} moved to ${stage.name}`);
    } catch (error) {
      if (previous) client.setQueryData(key, previous);
      showError(error);
    } finally {
      await client.invalidateQueries({ queryKey: ["board"] });
      await client.invalidateQueries({ queryKey: ["opportunity", card.id] });
    }
  };

  const onDragEnd = (event: DragEndEvent) => {
    setDragging(null);
    const card = event.active.data.current as OpportunityCard | undefined;
    const stage = event.over?.data.current as StageInfo | undefined;
    if (card && stage && stage.id !== card.stage_id) void move(card, stage);
  };

  return (
    <div>
      <PageHeader
        title="Pipeline"
        description="Drag cards between stages, or use a card's menu to move it. Every move is recorded."
        actions={
          <>
            <Button variant="outline" onClick={() => setManaging(true)}><Settings2 /> Manage stages</Button>
            <Button onClick={() => setNewIn({})}><Plus /> New opportunity</Button>
          </>
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Tabs value={lane} onValueChange={setLane} className="max-w-full overflow-x-auto">
          <TabsList aria-label="Sales lane">
            <TabsTrigger value="all">All lanes</TabsTrigger>
            {lanes.all.filter((l) => !l.archived || l.opportunity_count > 0).map((l) => (
              <TabsTrigger key={l.key} value={l.key}>
                <Dot color={lanes.color(l.key)} className="mr-1.5" />
                {l.name}
                {l.archived ? <span className="ml-1 text-xs opacity-70">(archived)</span> : null}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <Input
          aria-label="Filter cards"
          placeholder="Filter cards by prospect or title…"
          className="max-w-xs"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      </div>

      {board.error ? <ErrorState error={board.error} onRetry={() => board.refetch()} /> : null}
      {board.isLoading ? <LoadingRows rows={5} /> : null}
      {board.data && board.data.cards.length === 0 ? (
        <EmptyState
          icon={<KanbanSquare />}
          title="No opportunities yet"
          description="Create an opportunity for a prospect. A prospect can have one in each sales lane."
          action={<Button onClick={() => setNewIn({})}><Plus /> New opportunity</Button>}
        />
      ) : null}

      {board.data ? (
        <DndContext
          sensors={sensors}
          collisionDetection={closestCorners}
          autoScroll={{ threshold: { x: 0.06, y: 0.1 }, acceleration: 5 }}
          onDragStart={(e) => setDragging((e.active.data.current as OpportunityCard) ?? null)}
          onDragCancel={() => setDragging(null)}
          onDragEnd={onDragEnd}
          accessibility={{
            announcements: {
              onDragStart: ({ active }) => `Picked up ${(active.data.current as OpportunityCard)?.organization_name}.`,
              onDragOver: ({ over }) => (over ? `Over ${(over.data.current as StageInfo)?.name}.` : "Not over a stage."),
              onDragEnd: ({ over }) => (over ? `Dropped in ${(over.data.current as StageInfo)?.name}.` : "Dropped back."),
              onDragCancel: () => "Move cancelled.",
            },
          }}
        >
          <div className="-mx-3 flex snap-x gap-3 overflow-x-auto px-3 pb-4 sm:-mx-5 sm:px-5 lg:mx-0 lg:px-0">
            {stages.map((stage) => {
              const stageCards = cards.filter((c) => c.stage_id === stage.id);
              return (
                <Column key={stage.id} stage={stage} cards={stageCards.length} onAdd={() => setNewIn({ stageId: stage.id })}>
                  {stageCards.map((card) => (
                    <DraggableCard key={card.id} card={card} stages={stages} onOpen={() => open(card.id)} onMove={(s) => void move(card, s)} />
                  ))}
                  {stageCards.length === 0 ? <p className="px-2 py-6 text-center text-xs text-muted-foreground">Drop cards here</p> : null}
                </Column>
              );
            })}
          </div>
          <DragOverlay>
            {dragging ? (
              <div className="w-72 rotate-1 opacity-95">
                <CardBody card={dragging} stages={[]} onOpen={() => undefined} onMove={() => undefined} />
              </div>
            ) : null}
          </DragOverlay>
        </DndContext>
      ) : null}

      <OpportunitySheet id={openId} onClose={() => open(null)} />
      <NewOpportunityDialog
        open={newIn !== null}
        onOpenChange={(o) => !o && setNewIn(null)}
        defaultStageId={newIn?.stageId}
        defaultLane={lane === "all" ? undefined : lane}
        onCreated={(id) => open(id)}
      />
      <ReasonDialog
        target={reason}
        onCancel={() => setReason(null)}
        onConfirm={async (code, note) => {
          if (reason) await move(reason.card, reason.stage, code, note);
          setReason(null);
        }}
      />
      <StageManager open={managing} onOpenChange={setManaging} />
    </div>
  );
}
