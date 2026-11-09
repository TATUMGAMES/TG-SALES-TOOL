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

import { deflateSync } from "node:zlib";
import { expect, test } from "@playwright/test";
import { passOnboarding, unique } from "./helpers";

// Customizing an installation through the real UI: branding, sales lanes, custom
// fields, and importing review dates and qualification source URLs.
test.describe.configure({ mode: "serial" });
test.beforeEach(({}, info) => {
  test.skip(info.project.name !== "desktop", "customization flows run on desktop");
});

/** A tiny solid-color PNG, built in memory (no binary fixture needed). */
function png(width = 32, height = 32): Buffer {
  const crcTable = Array.from({ length: 256 }, (_, n) => {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    return c >>> 0;
  });
  const crc = (buf: Buffer) => {
    let c = 0xffffffff;
    for (const byte of buf) c = crcTable[(c ^ byte) & 0xff]! ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  };
  const chunk = (type: string, data: Buffer) => {
    const length = Buffer.alloc(4);
    length.writeUInt32BE(data.length);
    const body = Buffer.concat([Buffer.from(type, "ascii"), data]);
    const sum = Buffer.alloc(4);
    sum.writeUInt32BE(crc(body));
    return Buffer.concat([length, body, sum]);
  };
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header.set([8, 2, 0, 0, 0], 8); // 8-bit RGB
  const row = Buffer.concat([Buffer.from([0]), Buffer.alloc(width * 3, 0x55)]);
  const pixels = deflateSync(Buffer.concat(Array.from({ length: height }, () => row)));
  return Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), chunk("IHDR", header), chunk("IDAT", pixels), chunk("IEND", Buffer.alloc(0))]);
}

test("branding: company name and logo persist after a reload, and can be reset", async ({ page }) => {
  await page.goto("/settings?tab=branding");
  await passOnboarding(page);
  await page.getByLabel("Company name").fill("Northwind Traders");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  const sidebar = page.locator("aside");
  await expect(sidebar.getByText("Northwind Traders")).toBeVisible();

  await page.locator('input[type="file"]').first().setInputFiles({ name: "logo.png", mimeType: "image/png", buffer: png() });
  await expect(page.getByText("Image saved")).toBeVisible();
  await expect(sidebar.getByRole("img", { name: "Northwind Traders logo" })).toBeVisible();

  await page.reload();
  await expect(sidebar.getByText("Northwind Traders")).toBeVisible();
  await expect(sidebar.getByRole("img", { name: "Northwind Traders logo" })).toBeVisible();

  await page.getByRole("button", { name: "Restore default branding" }).click();
  await page.getByRole("alertdialog", { name: "Restore the default branding?" }).getByRole("button", { name: "Restore defaults" }).click();
  await expect(sidebar.getByText("Tatum Games")).toBeVisible();
});

test("sales lanes: a new lane appears in the pipeline, and renaming keeps it", async ({ page }) => {
  const lane = unique("Consulting");
  await page.goto("/settings?tab=lanes");
  await passOnboarding(page);
  await expect(page.getByRole("listitem").filter({ hasText: "General Sales" })).toBeVisible(); // a new installation's defaults
  await page.getByRole("button", { name: "Add lane" }).click();
  const dialog = page.getByRole("dialog", { name: "Add a sales lane" });
  await dialog.getByLabel("Name").fill(lane);
  await dialog.getByRole("button", { name: "Add lane" }).click();
  await expect(page.getByText("Lane added")).toBeVisible();

  await page.goto("/pipeline");
  await expect(page.getByRole("tab", { name: lane })).toBeVisible();

  await page.goto("/settings?tab=lanes");
  await page.getByRole("listitem").filter({ hasText: lane }).getByRole("button", { name: "Edit" }).click();
  const edit = page.getByRole("dialog", { name: `Edit ${lane}` });
  await edit.getByLabel("Name").fill(`${lane} Services`);
  await edit.getByRole("button", { name: "Save" }).click();
  await page.goto("/pipeline");
  await expect(page.getByRole("tab", { name: `${lane} Services` })).toBeVisible();
});

test("import: review date, qualification source URL and a new custom field", async ({ page }) => {
  const company = unique("Quill Research Studio");
  const url = "https://research.example/search?q=indie+studios&page=2#row-7";
  const csv = `Company,Reviewed On,Qualification Source URL,Partnership Category\n${company},2026-03-14,"${url}",Co-marketing\n`;
  await page.goto("/prospects");
  await passOnboarding(page);
  await page.getByRole("button", { name: "Import" }).first().click();
  const wizard = page.getByRole("dialog", { name: "Import prospects" });
  await wizard.locator('input[type="file"]').setInputFiles({ name: "research.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
  await wizard.getByRole("button", { name: "Continue" }).click();
  await expect(wizard.getByText("Column in your file")).toBeVisible();
  await expect(wizard.getByLabel("Field for Reviewed On")).toHaveValue("review_date");
  await expect(wizard.getByLabel("Field for Qualification Source URL")).toHaveValue("qualification_source_url");

  await wizard.getByLabel("Field for Partnership Category").selectOption({ label: "+ Create custom field…" });
  const create = page.getByRole("dialog", { name: "Create a custom field" });
  await expect(create.getByLabel("Field name")).toHaveValue("Partnership Category");
  await create.getByRole("button", { name: "Create field" }).click();
  await expect(wizard.getByLabel("Field for Partnership Category")).toHaveValue("custom:prospect:partnership_category");

  await wizard.getByRole("button", { name: "Check rows" }).click();
  await wizard.getByRole("button", { name: "Preview result" }).click();
  await expect(wizard.getByText("This is exactly what will happen:")).toBeVisible();
  await wizard.getByRole("button", { name: "Import now" }).click();
  await expect(wizard.getByText("Import saved.")).toBeVisible();
  await wizard.getByRole("button", { name: "Done" }).click();

  await page.getByRole("button", { name: company }).click();
  const sheet = page.getByRole("dialog", { name: company });
  await expect(sheet.getByText("Partnership Category")).toBeVisible();
  await expect(sheet.getByText("Co-marketing")).toBeVisible();
  const link = sheet.locator(`a[href="${url}"]`).first();
  await expect(link).toBeVisible(); // the complete URL, query and fragment included
  await expect(link).toHaveAttribute("rel", /noopener/);
});
