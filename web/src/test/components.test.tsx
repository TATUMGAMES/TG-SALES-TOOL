import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { AppRoutes } from "@/App";
import { ChartCard } from "@/components/ChartCard";
import { ErrorState } from "@/components/ui/misc";
import { ApiError } from "@/lib/api";
import { ProspectForm } from "@/features/prospects/ProspectForm";
import { PipelinePage } from "@/features/pipeline/PipelinePage";
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
      "POST /api/opportunities/o1/move": { ok: true },
    });
    renderWithApp(<PipelinePage />, { route: "/pipeline" });
    expect(await screen.findByText("Pixel Forge")).toBeInTheDocument();
    expect(screen.getByText(/overdue/)).toBeInTheDocument(); // overdue stated in words

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
  });
});
