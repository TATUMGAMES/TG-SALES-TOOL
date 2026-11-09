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

import path from "node:path";
import { test } from "@playwright/test";
import { ROOT, passOnboarding } from "./helpers";

// Documentation screenshots (synthetic data from the workflow tests). Run with SCREENSHOTS=1.
test.skip(!process.env.SCREENSHOTS, "set SCREENSHOTS=1 to refresh docs/screenshots");

const PAGES = ["/", "/prospects", "/pipeline", "/discovery", "/playbook", "/reports", "/settings?tab=sync"];

test("capture pages", async ({ page }, info) => {
  const dark = info.project.name === "mobile";
  await page.emulateMedia({ colorScheme: dark ? "dark" : "light" });
  await page.goto("/");
  await passOnboarding(page);
  if (info.project.name === "desktop") await page.request.post("/api/playbook/examples", { headers: { "X-TG-Sales": "1" } });
  for (const url of PAGES) {
    await page.goto(url);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(700);
    const name = url === "/" ? "dashboard" : url.slice(1).split("?")[0];
    await page.screenshot({ path: path.join(ROOT, "docs", "screenshots", `web_${name}_${info.project.name}_${dark ? "dark" : "light"}.png`) });
  }
});
