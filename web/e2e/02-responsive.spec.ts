import { expect, test } from "@playwright/test";
import { openPage, passOnboarding, unique } from "./helpers";

const PAGES: [string, string][] = [
  ["Dashboard", "/"],
  ["Prospects", "/prospects"],
  ["Pipeline", "/pipeline"],
  ["Discovery", "/discovery"],
  ["Playbook", "/playbook"],
  ["Reports", "/reports"],
  ["Resources", "/resources"],
  ["Settings & Sync", "/settings"],
];

test("every page is reachable and fits the screen", async ({ page }, info) => {
  await page.goto("/");
  await passOnboarding(page);
  for (const [label, url] of PAGES) {
    await openPage(page, label);
    await expect(page).toHaveURL(new RegExp(`${url === "/" ? "/$" : url}`));
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    // No page-level horizontal scrolling (the pipeline board scrolls inside its own area).
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, `${label} overflows horizontally on ${info.project.name}`).toBeLessThanOrEqual(1);
  }
});

test("mobile navigation and touch-friendly controls", async ({ page }, info) => {
  test.skip(info.project.name === "desktop", "phones and tablets only");
  await page.goto("/");
  await passOnboarding(page);
  const bottom = page.getByRole("navigation", { name: "Quick navigation" });
  await expect(bottom).toBeVisible();
  await bottom.getByRole("link", { name: "Pipeline" }).click();
  await expect(page.getByRole("heading", { name: "Pipeline" })).toBeVisible();
  const buttons = await page.getByRole("button").evaluateAll((elements) =>
    elements
      .filter((e) => (e as HTMLElement).offsetParent !== null)
      .map((e) => e.getBoundingClientRect())
      .filter((r) => r.width > 0 && r.height > 0 && (r.height < 30 || r.width < 30)).length,
  );
  expect(buttons).toBeLessThanOrEqual(6);
});

test("create a prospect and switch themes on this screen size", async ({ page }, info) => {
  await page.goto("/");
  await passOnboarding(page);
  const name = unique(`Responsive ${info.project.name}`);
  await page.getByRole("button", { name: "New prospect" }).click();
  await page.getByRole("dialog", { name: "New prospect" }).getByLabel("Name").fill(name);
  await page.getByRole("button", { name: "Create prospect" }).click();
  await expect(page.getByRole("dialog", { name })).toBeVisible();
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Change theme" }).click();
  await page.getByRole("menuitemradio", { name: /Dark/ }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.reload();
  await expect(page.locator("html")).toHaveClass(/dark/);
});

test("pipeline cards can be moved on touch screens", async ({ page }, info) => {
  test.skip(info.project.name === "desktop", "phones and tablets only");
  const headers = { "X-TG-Sales": "1" };
  const name = unique(`Touch ${info.project.name}`);
  const org = await (await page.request.post("/api/prospects", { headers, data: { organization: { name } } })).json();
  const stages = await (await page.request.get("/api/pipeline/stages")).json();
  const discovered = stages.find((s: { name: string }) => s.name === "Discovered");
  await page.request.post("/api/opportunities", { headers, data: { organization_id: org.id, product_lane: "publisher_partnership", stage_id: discovered.id } });
  await page.goto("/pipeline");
  await passOnboarding(page);
  await page.getByRole("button", { name: `Move ${name}` }).tap();
  await page.getByRole("menuitem", { name: "Researching" }).tap();
  await expect(page.getByText(`${name} moved to Researching`, { exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: /^Researching, / }).getByRole("button", { name: new RegExp(`^${name}`) })).toBeAttached();
});
