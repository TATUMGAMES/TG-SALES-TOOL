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

import { execFileSync, spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { FIXTURES, PYTHON, ROOT, passOnboarding, serverInfo, unique } from "./helpers";

// The complete sales workflow, through the real UI against the real API and PostgreSQL.
test.describe.configure({ mode: "serial" });
test.beforeEach(({}, info) => {
  test.skip(info.project.name !== "desktop", "the full workflow runs on desktop; other sizes are covered by responsive.spec");
});

const studio = unique("Aurora Pixel Works");

test("1. launch and onboarding", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("dialog", { name: "Welcome to TG Sales CRM" })).toBeVisible();
  await passOnboarding(page, "Sam Seller");
  await expect(page.getByText("Signed in on this computer as Sam Seller")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
});

test("2. create a prospect with a contact", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "New prospect" }).click();
  const dialog = page.getByRole("dialog", { name: "New prospect" });
  await dialog.getByLabel("Name").fill(studio);
  await dialog.getByLabel("Website").fill("aurora-pixel.example");
  await dialog.getByRole("button", { name: "Add contact" }).click();
  await dialog.getByLabel("Contact name").fill("Ana Example");
  await dialog.getByLabel("Email").fill("ana@aurora-pixel.example");
  await dialog.getByRole("button", { name: "Create prospect" }).click();
  await expect(page.getByText("Prospect created", { exact: true })).toBeVisible();
  const sheet = page.getByRole("dialog", { name: studio });
  await expect(sheet.getByText("ana@aurora-pixel.example")).toBeVisible();
  await expect(sheet.getByRole("tabpanel").getByText("Unknown", { exact: true })).toBeVisible(); // outreach status is not guessed
});

test("3. import prospects from a file", async ({ page }) => {
  await page.goto("/prospects");
  await page.getByRole("button", { name: "Import" }).first().click();
  const wizard = page.getByRole("dialog", { name: "Import prospects" });
  await wizard.locator('input[type="file"]').setInputFiles(path.join(FIXTURES, "messy_prospects.csv"));
  await expect(wizard.getByText("messy_prospects.csv")).toBeVisible();
  await wizard.getByRole("button", { name: "Continue" }).click();
  await expect(wizard.getByText("Column in your file")).toBeVisible();
  await wizard.getByRole("button", { name: "Check rows" }).click();
  await expect(wizard.getByText(/prospects? found/)).toBeVisible();
  const createAll = wizard.getByRole("button", { name: "Create new for all undecided" });
  if (await createAll.isVisible()) await createAll.click();
  await wizard.getByRole("button", { name: "Preview result" }).click();
  await expect(wizard.getByText("This is exactly what will happen:")).toBeVisible();
  await wizard.getByRole("button", { name: "Import now" }).click();
  await expect(wizard.getByText("Import saved.")).toBeVisible();
  await wizard.getByRole("button", { name: "Done" }).click();
  await expect(page.getByRole("button", { name: "Pixel Forge Studios" })).toBeVisible();
});

test("4. pipeline: create, drag and move an opportunity; record outreach", async ({ page }) => {
  await page.goto("/pipeline");
  await page.getByRole("button", { name: "New opportunity" }).first().click();
  const dialog = page.getByRole("dialog", { name: "New opportunity" });
  await dialog.getByPlaceholder("Type a prospect name").fill("Aurora");
  await dialog.getByLabel("Choose prospect").selectOption({ label: studio });
  await dialog.getByLabel("Title").fill("Player analytics data");
  await dialog.getByRole("button", { name: "Create opportunity" }).click();
  await expect(page.getByText("Opportunity created", { exact: true })).toBeVisible();
  await page.keyboard.press("Escape");

  // Keyboard/menu alternative to dragging.
  const card = page.getByRole("region", { name: /^Discovered, / }).getByText(studio);
  await expect(card).toBeVisible();
  await page.getByRole("button", { name: `Move ${studio}` }).click();
  await page.getByRole("menuitem", { name: "Contacted" }).click();
  await expect(page.getByRole("region", { name: /^Contacted, / }).getByText(studio)).toBeVisible();

  // Drag and drop to the next stage.
  const handle = page.getByRole("button", { name: new RegExp(`^Drag ${studio}`) });
  const target = page.getByRole("region", { name: /^Follow-Up, / });
  await target.scrollIntoViewIfNeeded();
  const from = await handle.boundingBox();
  if (!from) throw new Error("board not laid out");
  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
  await page.mouse.down();
  await page.mouse.move(from.x + from.width / 2 + 12, from.y + 12, { steps: 4 });
  const to = await target.boundingBox();
  if (!to) throw new Error("target column not laid out");
  await page.mouse.move(to.x + to.width / 2, to.y + 90, { steps: 12 });
  await page.waitForTimeout(150);
  await page.mouse.up();
  await expect(page.getByText(`${studio} moved to Follow-Up`)).toBeVisible();

  // Record outreach in the opportunity panel.
  await page.getByRole("region", { name: /^Follow-Up, / }).getByRole("button", { name: `${studio} Player analytics data` }).click();
  const sheet = page.getByRole("dialog", { name: studio });
  await sheet.getByLabel("What happened").selectOption({ label: "Email" });
  await sheet.getByLabel("Notes").first().fill("Sent the introduction");
  await sheet.getByRole("button", { name: "Log activity" }).click();
  await expect(page.getByText("Activity logged", { exact: true })).toBeVisible();
  await expect(sheet.getByText(/Sent the introduction/)).toBeVisible();

  // Won requires a reason.
  await sheet.getByLabel("Stage").selectOption({ label: "Won" });
  const reason = page.getByRole("dialog", { name: "Move to Won" });
  await reason.getByRole("button", { name: "Move" }).click();
  await expect(page.getByText("Stage changed", { exact: true })).toBeVisible();
});

test("5. reports and dashboard snapshots", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: /^Won: 1\./ })).toBeVisible();
  await page.getByRole("button", { name: "Snapshot" }).click();
  await page.getByRole("menuitem", { name: "Whole dashboard" }).click();
  await expect(page.getByText("Snapshot saved", { exact: true })).toBeVisible();

  await page.goto("/reports");
  await page.getByLabel("Period").selectOption({ label: "Last 3 months" });
  await page.getByRole("button", { name: "Create report" }).click();
  await expect(page.getByText(/Report created \(\d+ pages\)/)).toBeVisible({ timeout: 60_000 });
  const pdf = page.getByRole("link", { name: "Open PDF" }).first();
  const href = await pdf.getAttribute("href");
  const response = await page.request.get(href ?? "");
  expect(response.headers()["content-type"]).toContain("application/pdf");
  expect((await response.body()).subarray(0, 4).toString()).toBe("%PDF");
  await expect(page.getByText(/dashboard_snapshot_\d{4}-\d{2}-\d{2}_\d+\.png/)).toBeVisible();
});

test("6. discover games and save a studio", async ({ page }) => {
  await page.goto("/discovery");
  await page.getByRole("button", { name: "Find games" }).click();
  await expect(page.getByText(/Found \d+ games?/)).toBeVisible({ timeout: 60_000 });
  await page.getByRole("button", { name: "Review" }).first().click();
  const sheet = page.getByRole("dialog").last();
  await sheet.getByRole("button", { name: "Save to Prospects" }).click();
  await expect(page.getByRole("region", { name: /Notifications/ }).getByText("Saved to Prospects")).toBeVisible();
});

test("7. export and import synchronization packages", async ({ page }) => {
  await page.goto("/settings?tab=sync");
  await page.getByLabel(/Encrypt with a passphrase/).click();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export and download" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/^tg_sales_sync_sam-seller_\d{8}T\d{6}Z_[0-9a-f]{8}\.zip$/);

  const out = mkdtempSync(path.join(os.tmpdir(), "tg-colleague-"));
  const packagePath = execFileSync(PYTHON, [path.join(ROOT, "tests", "e2e_make_package.py"), "--admin-url", serverInfo().admin_url, "--out", out], { encoding: "utf8" }).trim();
  await page.locator('input[type="file"][accept*="zip"]').setInputFiles(packagePath);
  await page.getByRole("button", { name: "Check package" }).click();
  await expect(page.getByText("Changes from Colleague")).toBeVisible();
  await expect(page.getByText(/New: \d+/)).toBeVisible();
  await page.getByRole("button", { name: "Import these changes" }).click();
  await expect(page.getByText("Changes imported", { exact: true })).toBeVisible();
  await page.goto("/prospects?q=Colleague");
  await expect(page.getByRole("button", { name: "Colleague Games" })).toBeVisible();

  // Importing the same package again changes nothing.
  await page.goto("/settings?tab=sync");
  await page.locator('input[type="file"][accept*="zip"]').setInputFiles(packagePath);
  await page.getByRole("button", { name: "Check package" }).click();
  await expect(page.getByText("This package was imported before; importing it again changes nothing.")).toBeVisible();
});

test("8. restart: data persists in PostgreSQL", async ({ page }) => {
  const info = serverInfo();
  const second = spawn(PYTHON, [path.join(ROOT, "tests", "e2e_server.py"), "--port", "8798", "--database-url", info.database_url, "--admin-url", info.admin_url, "--data-dir", info.data_dir], { stdio: "ignore" });
  try {
    await expect
      .poll(async () => (await page.request.get("http://127.0.0.1:8798/api/health").catch(() => null))?.status() ?? 0, { timeout: 60_000 })
      .toBe(200);
    await page.goto(`http://127.0.0.1:8798/prospects?q=${encodeURIComponent(studio)}`);
    await expect(page.getByRole("button", { name: studio })).toBeVisible();
    await page.goto("http://127.0.0.1:8798/reports");
    await expect(page.getByRole("link", { name: "Open PDF" }).first()).toBeVisible();
  } finally {
    second.kill();
  }
});
