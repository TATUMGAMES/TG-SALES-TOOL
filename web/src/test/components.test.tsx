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

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { AppRoutes } from "@/App";
import { ChartCard } from "@/components/ChartCard";
import { ErrorState } from "@/components/ui/misc";
import { ApiError } from "@/lib/api";
import { ProspectForm } from "@/features/prospects/ProspectForm";
import { PipelinePage } from "@/features/pipeline/PipelinePage";
import { LanesPanel } from "@/features/settings/LanesPanel";
import { labelForKey } from "@/lib/lanes";
import { INFO, mockApi, renderWithApp } from "./utils";

const STAGES = [
  { id: "s1", name: "Discovered", sort_order: 10, product_lane: null, outcome: "open", archived: false, opportunity_count: 1 },
  { id: "s2", name: "Contacted", sort_order: 20, product_lane: null, outcome: "open", archived: false, opportunity_count: 0 },
  { id: "s3", name: "Won", sort_order: 30, product_lane: null, outcome: "won", archived: false, opportunity_count: 0 },
];
const CARD = {
  id: "o1",
  organization_id: "org1",
  organization_name: "Pixel Forge",
  title: "Player data",
  product_lane: "data_licensing",
  stage_id: "s1",
  owner_name: null,
  last_activity_at: null,
  next_action_at: "2020-01-01T09:00:00Z",
  next_action_note: "Send sample",
  release_date: null,
  closed: false,
};
const LANE = (key: string, name: string, extra: object = {}) => ({
  id: `id-${key}`,
  key,
  name,
  description: null,
  color: "#86c4c2",
  sort_order: 10,
  technical_handoff: false,
  archived: false,
  opportunity_count: 0,
  stage_count: 0,
  in_use: false,
  ...extra,
});
const LANES = [LANE("data_licensing", "Data licensing", { opportunity_count: 1, in_use: true, technical_handoff: true })];
const BRANDING = {
  company_name: "Acme Consulting",
  display_name: "Acme Consulting",
  default_company_name: "Tatum Games",
  accent_color: null,
  accent_text_color: null,
  images: { logo: { present: false, media_type: null, version: null } },
  requirements: "",
  max_bytes: 5242880,
};
const META = {
  lanes: [{ value: "data_licensing", label: "Data licensing" }],
  outcomes: ["open", "won", "lost", "not_a_fit"],
  loggable_activities: [{ value: "email", label: "Email" }],
  activity_labels: {},
  reason_codes: { won: [{ value: "signed", label: "Contract signed" }] },
  review_notice: "Share only with authorized reviewers.",
};

describe("error state", () => {
  it("shows the message and the next action", async () => {
    const retried: string[] = [];
    renderWithApp(<ErrorState error={new ApiError("tg_sales is not responding.", "Check that launch.bat is open.", "offline", 0)} onRetry={() => retried.push("x")} />);
    expect(screen.getByRole("alert")).toHaveTextContent("tg_sales is not responding.");
    expect(screen.getByRole("alert")).toHaveTextContent("Check that launch.bat is open.");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retried).toHaveLength(1);
  });
});

describe("chart card", () => {
  it("offers the same numbers as an accessible table", async () => {
    renderWithApp(
      <ChartCard title="Funnel" headers={["Step", "Count"]} rows={[["Created", 4], ["Won", null]]} csvName="f">
        <div>chart</div>
      </ChartCard>,
    );
    expect(screen.getByRole("img", { name: /Funnel chart/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show data table" }));
    const table = screen.getByRole("table");
    expect(within(table).getByText("Created")).toBeInTheDocument();
    expect(within(table).getByText("Not available")).toBeInTheDocument();
  });
});

describe("prospect form", () => {
  it("validates input and warns about duplicates before creating", async () => {
    const calls = mockApi({
      "POST /api/prospects/duplicates": [{ id: "d1", name: "Pixel Forge Studios", domain: "pixelforge.example", strength: "strong", reason: "same website domain", archived: false }],
      "POST /api/prospects": { id: "new1" },
    });
    renderWithApp(<ProspectForm open onOpenChange={() => undefined} />);
    await userEvent.click(screen.getByRole("button", { name: "Create prospect" }));
    expect(await screen.findByText("Enter the studio or company name.")).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText(/^Name/), "Pixel Forge");
    await userEvent.click(screen.getByRole("button", { name: "Add contact" }));
    await userEvent.type(screen.getByLabelText("Email"), "not-an-email");
    await userEvent.click(screen.getByRole("button", { name: "Create prospect" }));
    expect(await screen.findByText(/valid email address/)).toBeInTheDocument();

    await userEvent.clear(screen.getByLabelText("Email"));
    await userEvent.type(screen.getByLabelText("Email"), "ana@pixelforge.example");
    await userEvent.click(screen.getByRole("button", { name: "Create prospect" }));
    expect(await screen.findByText("This looks like a prospect you already have")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST" && c.path === "/api/prospects")).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: "Create anyway" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/api/prospects")).toBe(true));
    const created = calls.find((c) => c.path === "/api/prospects")!;
    expect(created.body).toMatchObject({ allow_duplicate: true, contacts: [{ email: "ana@pixelforge.example", status: "unknown" }] });
  });
});

describe("pipeline", () => {
  it("moves a card with the accessible menu and asks for a reason when won", async () => {
    const calls = mockApi({
      "/api/pipeline/board": { stages: STAGES, cards: [CARD] },
      "/api/pipeline/meta": META,
      "/api/pipeline/stages": STAGES,
      "/api/lanes": [LANE("data_licensing", "Licensing deals", { opportunity_count: 1, in_use: true })],
      "POST /api/opportunities/o1/move": { ok: true },
    });
    renderWithApp(<PipelinePage />, { route: "/pipeline" });
    expect(await screen.findByText("Pixel Forge")).toBeInTheDocument();
    expect(screen.getByText(/overdue/)).toBeInTheDocument(); // overdue stated in words
    // Lane names come from the configured lanes (renamed here), never a built-in list.
    expect((await screen.findAllByText("Licensing deals")).length).toBeGreaterThan(0);

    await userEvent.click(screen.getByRole("button", { name: "Move Pixel Forge" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Contacted" }));
    await waitFor(() => expect(calls.find((c) => c.path === "/api/opportunities/o1/move")?.body).toMatchObject({ stage_id: "s2" }));

    await userEvent.click(screen.getByRole("button", { name: "Move Pixel Forge" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Won" }));
    const dialog = await screen.findByRole("dialog", { name: "Move to Won" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Move" }));
    await waitFor(() =>
      expect(calls.filter((c) => c.path === "/api/opportunities/o1/move").at(-1)?.body).toMatchObject({ stage_id: "s3", reason_code: "signed" }),
    );
  });
});

describe("navigation", () => {
  it("shows every section in the sidebar and the empty dashboard guidance", async () => {
    mockApi({
      "/api/system/info": INFO,
      "/api/reminders": [],
      "/api/periods": [],
      "/api/dashboard/salespeople": [],
      "/api/branding/logo": new Response(null, { status: 204 }),
      "/api/branding": BRANDING,
      "/api/lanes": LANES,
      "/api/dashboard": {
        period: { preset: "30d", label: "Last 30 days", start: "2026-09-21", end: "2026-10-20", description: "2026-09-21 to 2026-10-20" },
        previous: { preset: "custom", label: "Previous period", start: "2026-08-22", end: "2026-09-20", description: "" },
        data: {
          report: { period: { dates: { start: "", end: "" }, p0: "", p1: "" }, filters: {}, metrics: {}, stages: [], sources: [], trend: { size: "day", labels: [], series: {} }, funnel: [], funnel_cohort: 0 },
          recent: [],
          releases: { labels: [], counts: [], rows: [] },
          computed_at: "2026-10-20T12:00:00Z",
          has_data: false,
        },
      },
    });
    renderWithApp(<AppRoutes />);
    const nav = screen.getByRole("navigation", { name: "Main" });
    for (const label of ["Dashboard", "Prospects", "Pipeline", "Discovery", "Playbook", "Reports", "Resources", "Settings & Sync"]) {
      expect(within(nav).getByRole("link", { name: label })).toBeInTheDocument();
    }
    expect(await screen.findByText("Your dashboard fills up as you work")).toBeInTheDocument();
    expect(await screen.findByText(/Signed in on this computer as Sam Seller/)).toBeInTheDocument();
    // The company name comes from Settings > Branding.
    expect(await screen.findByText("Acme Consulting")).toBeInTheDocument();
  });
});

describe("sales lanes", () => {
  it("lists lanes, protects lanes in use and archives on request", async () => {
    const calls = mockApi({
      "/api/lanes": [...LANES, LANE("sponsorships", "Sponsorships")],
      "/api/lanes/presets": [{ key: "generic", label: "General" }],
      "POST /api/lanes/data_licensing/archive": LANES[0],
    });
    renderWithApp(<LanesPanel />);
    expect(await screen.findByText("Sponsorships")).toBeInTheDocument();
    const rows = screen.getAllByRole("listitem");
    const licensing = rows.find((row) => within(row).queryByText("Data licensing"))!;
    const sponsorships = rows.find((row) => within(row).queryByText("Sponsorships"))!;
    // A lane with records offers "Move records" instead of "Delete".
    expect(within(licensing).queryByRole("button", { name: /Delete/ })).toBeNull();
    expect(within(licensing).getByRole("button", { name: /Move records/ })).toBeInTheDocument();
    expect(within(sponsorships).getByRole("button", { name: /Delete/ })).toBeInTheDocument();
    await userEvent.click(within(licensing).getByRole("button", { name: /Archive/ }));
    await waitFor(() => expect(calls.find((c) => c.path === "/api/lanes/data_licensing/archive")?.body).toEqual({ archived: true }));
  });

  it("shows a readable name for a lane key without a lane", () => {
    expect(labelForKey("colleague_lane")).toBe("Colleague lane");
    expect(labelForKey("")).toBe("Unknown lane");
  });
});
