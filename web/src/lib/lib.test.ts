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

import { describe, expect, it } from "vitest";
import { mockApi } from "@/test/utils";
import { ApiError, api, withQuery } from "./api";
import { safeCell, toCsv } from "./csv";
import { formatNumber, relativeDue } from "./format";

describe("api client", () => {
  it("sends the anti-forgery header and JSON", async () => {
    const calls = mockApi({ "POST /api/prospects": { id: "x" } });
    await api.post("/prospects", { organization: { name: "A" } });
    expect(calls[0]?.headers["X-TG-Sales"]).toBe("1");
    expect(calls[0]?.body).toEqual({ organization: { name: "A" } });
  });

  it("turns error envelopes into ApiError with a next action", async () => {
    mockApi({
      "GET /api/prospects/1": new Response(
        JSON.stringify({ error: { message: "That prospect no longer exists.", action: "Refresh the page.", code: "notfound" } }),
        { status: 404, headers: { "content-type": "application/json" } },
      ),
    });
    const error = await api.get("/prospects/1").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).action).toBe("Refresh the page.");
    expect((error as ApiError).status).toBe(404);
  });

  it("drops empty query values", () => {
    expect(withQuery("/x", { a: "1", b: "", c: null, d: undefined, e: false })).toBe("/x?a=1&e=false");
  });
});

describe("csv export", () => {
  it("neutralizes spreadsheet formulas and quotes separators", () => {
    expect(safeCell("=HYPERLINK(1)")).toBe("'=HYPERLINK(1)");
    expect(safeCell("+1")).toBe("'+1");
    expect(safeCell("@cmd")).toBe("'@cmd");
    expect(safeCell('a,"b"')).toBe('"a,""b"""');
    expect(safeCell(null)).toBe("");
    expect(toCsv(["A"], [[1], ["-2"]])).toBe("A\r\n1\r\n'-2\r\n");
  });
});

describe("formatting", () => {
  const now = new Date(2026, 9, 20, 12, 0);
  it("says overdue in words", () => {
    expect(relativeDue(new Date(2026, 9, 18, 9).toISOString(), now)).toEqual({ text: "2 days overdue", overdue: true });
    expect(relativeDue(new Date(2026, 9, 21, 9).toISOString(), now)).toEqual({ text: "In 1 day", overdue: false });
    expect(relativeDue(null, now).text).toBe("No follow-up");
  });
  it("distinguishes zero from not available", () => {
    expect(formatNumber(0)).toBe("0");
    expect(formatNumber(null)).toBe("Not available");
    expect(formatNumber(0.5, "percent")).toBe("50%");
  });
});
