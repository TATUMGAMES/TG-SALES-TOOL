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

import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, type Page } from "@playwright/test";

export const ROOT = path.resolve(process.cwd(), "..");
export const FIXTURES = path.join(ROOT, "tests", "fixtures", "imports");
export const PYTHON = path.join(ROOT, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");

export function serverInfo(): { database_url: string; admin_url: string; data_dir: string } {
  return JSON.parse(readFileSync(path.join(ROOT, "web", ".e2e", "e2e-info.json"), "utf8"));
}

/** Finish first-run onboarding if it is showing. */
export async function passOnboarding(page: Page, name = "Sam Seller"): Promise<void> {
  const dialog = page.getByRole("dialog", { name: "Welcome to TG Sales CRM" });
  if (await dialog.isVisible().catch(() => false)) {
    await dialog.getByLabel("Your name").fill(name);
    await dialog.getByRole("button", { name: "Get started" }).click();
    await expect(dialog).toBeHidden();
  }
}

export async function openPage(page: Page, label: string): Promise<void> {
  const mobileMenu = page.getByRole("button", { name: "Open menu" });
  if (await mobileMenu.isVisible()) {
    await mobileMenu.click();
    await page.getByRole("dialog").getByRole("link", { name: label }).click();
  } else {
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: label }).click();
  }
}

export function unique(prefix: string): string {
  return `${prefix} ${Date.now().toString(36)}`;
}
