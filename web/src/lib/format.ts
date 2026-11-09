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

/** Display formatting. Timestamps arrive in UTC and are shown in local time. */
const locale = (): string => (typeof navigator !== "undefined" ? navigator.language : "en-US");

export function formatDate(value: string | null | undefined, options?: Intl.DateTimeFormatOptions): string {
  if (!value) return "—";
  const date = value.length === 10 ? new Date(`${value}T00:00:00`) : new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(locale(), options ?? { year: "numeric", month: "short", day: "numeric" });
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(locale(), {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** "In 3 days", "2 days overdue", "Due today" — overdue is always said in words, never only color. */
export function relativeDue(value: string | null | undefined, now = new Date()): { text: string; overdue: boolean } {
  if (!value) return { text: "No follow-up", overdue: false };
  const due = new Date(value);
  const startOf = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((startOf(due) - startOf(now)) / 86_400_000);
  if (days === 0) return { text: due < now ? "Due today (overdue)" : "Due today", overdue: due < now };
  if (days < 0) return { text: `${-days} day${days === -1 ? "" : "s"} overdue`, overdue: true };
  return { text: `In ${days} day${days === 1 ? "" : "s"}`, overdue: false };
}

export function formatNumber(value: number | null | undefined, unit?: string): string {
  if (value === null || value === undefined) return "Not available";
  if (unit === "percent") return `${Math.round(value * 100)}%`;
  if (unit === "days") return `${value.toLocaleString(locale(), { maximumFractionDigits: 1 })} days`;
  return value.toLocaleString(locale(), { maximumFractionDigits: 2 });
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatMoney(value: number | null | undefined, currency: string | null | undefined): string {
  if (value === null || value === undefined) return "—";
  try {
    return value.toLocaleString(locale(), {
      style: "currency",
      currency: currency || "USD",
      maximumFractionDigits: 0,
    });
  } catch {
    return `${value.toLocaleString()} ${currency ?? ""}`.trim();
  }
}

export function humanize(value: string): string {
  const text = value.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** A local date as YYYY-MM-DD (for date inputs). */
export function isoDate(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}
