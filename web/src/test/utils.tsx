import { QueryClient } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";
import { Providers } from "@/App";

type Handler = (url: URL, init: RequestInit | undefined) => unknown;

/** Replace fetch with a router of fake API responses; returns the recorded calls. */
export function mockApi(routes: Record<string, Handler | unknown>) {
  const calls: { method: string; path: string; body: unknown; headers: Record<string, string> }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const method = init?.method ?? "GET";
      const body = typeof init?.body === "string" ? JSON.parse(init.body) : init?.body;
      calls.push({ method, path: url.pathname, body, headers: (init?.headers as Record<string, string>) ?? {} });
      const key = `${method} ${url.pathname}`;
      const route = key in routes ? routes[key] : routes[url.pathname];
      if (route === undefined) {
        return new Response(JSON.stringify({ error: { message: "Not mocked", action: "", code: "test" } }), {
          status: 404,
          headers: { "content-type": "application/json" },
        });
      }
      const value = typeof route === "function" ? (route as Handler)(url, init) : route;
      if (value instanceof Response) return value;
      return new Response(JSON.stringify(value ?? {}), { status: 200, headers: { "content-type": "application/json" } });
    }),
  );
  return calls;
}

export function renderWithApp(ui: ReactElement, { route = "/" }: { route?: string } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <Providers client={client}>
      <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
    </Providers>,
  );
}

export const INFO = {
  app_name: "TG Sales CRM",
  version: "0.1.0",
  schema_revision: "0001",
  device_id: "01a1-device",
  actor_id: "01a1-actor",
  display_name: "Sam Seller",
  first_run: false,
  desktop_integration: false,
  backups_available: true,
  restore_available: true,
  data_folder: null,
  environment: "test",
};
