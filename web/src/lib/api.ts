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

/**
 * API client. Every state-changing request carries the X-TG-Sales header (the
 * server refuses requests without it, which blocks cross-site forgery). Errors
 * come back as { error: { message, action, code } } and are thrown as ApiError,
 * so every screen can show what happened and what to do next.
 */
export class ApiError extends Error {
  readonly action: string;
  readonly code: string;
  readonly status: number;
  readonly problems: string[];

  constructor(message: string, action: string, code: string, status: number, problems: string[] = []) {
    super(message);
    this.action = action;
    this.code = code;
    this.status = status;
    this.problems = problems;
  }
}

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

export type Query = Record<string, string | number | boolean | null | undefined>;

export function withQuery(path: string, query?: Query): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const text = params.toString();
  return text ? `${path}?${text}` : path;
}

export function apiUrl(path: string, query?: Query): string {
  return `${BASE}/api${withQuery(path, query)}`;
}

interface Envelope {
  error?: { message?: string; action?: string; code?: string };
  problems?: string[];
}

async function parse<T>(response: Response): Promise<T> {
  if (response.status === 204) return undefined as T;
  const type = response.headers.get("content-type") ?? "";
  const body: unknown = type.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const envelope = (typeof body === "object" && body !== null ? body : {}) as Envelope;
    throw new ApiError(
      envelope.error?.message ?? "Something went wrong.",
      envelope.error?.action ?? "Try again.",
      envelope.error?.code ?? `http_${response.status}`,
      response.status,
      envelope.problems ?? [],
    );
  }
  return body as T;
}

const OFFLINE = new ApiError(
  "tg_sales is not responding.",
  "Check that the tg_sales window (launch.bat) is still open, then try again.",
  "offline",
  0,
);

async function send<T>(method: string, path: string, body?: unknown, query?: Query): Promise<T> {
  const headers: Record<string, string> = { "X-TG-Sales": "1" };
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  let response: Response;
  try {
    response = await fetch(apiUrl(path, query), { method, headers, body: payload, credentials: "same-origin" });
  } catch {
    throw OFFLINE;
  }
  return parse<T>(response);
}

export const api = {
  get: <T>(path: string, query?: Query) => send<T>("GET", path, undefined, query),
  post: <T>(path: string, body?: unknown) => send<T>("POST", path, body),
  put: <T>(path: string, body?: unknown) => send<T>("PUT", path, body),
  patch: <T>(path: string, body?: unknown) => send<T>("PATCH", path, body),
  delete: <T>(path: string) => send<T>("DELETE", path),
};

const FILENAME = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i;

/** Download a file from the API; the browser saves it (existing files are never replaced). */
export async function download(path: string, body?: unknown, fallbackName = "download"): Promise<void> {
  let response: Response;
  try {
    response = await fetch(apiUrl(path), {
      method: body === undefined ? "GET" : "POST",
      headers: body === undefined ? {} : { "X-TG-Sales": "1", "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw OFFLINE;
  }
  if (!response.ok) await parse(response);
  const blob = await response.blob();
  const match = FILENAME.exec(response.headers.get("content-disposition") ?? "");
  const name = match?.[1] ? decodeURIComponent(match[1]) : fallbackName;
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
