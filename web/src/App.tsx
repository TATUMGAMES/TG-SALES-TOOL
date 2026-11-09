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

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense, useState, type ReactNode } from "react";
import { BrowserRouter, Link, Route, Routes } from "react-router";
import { Toaster } from "sonner";
import { AppShell } from "@/components/layout/AppShell";
import { AppDialogsProvider } from "@/components/layout/dialogs";
import { Button } from "@/components/ui/button";
import { EmptyState, LoadingRows, TooltipProvider } from "@/components/ui/misc";
import { ApiError } from "@/lib/api";
import { ThemeProvider, useTheme } from "@/lib/theme";
import { Onboarding } from "@/features/onboarding/Onboarding";

const DashboardPage = lazy(() => import("@/features/dashboard/DashboardPage").then((m) => ({ default: m.DashboardPage })));
const ProspectsPage = lazy(() => import("@/features/prospects/ProspectsPage").then((m) => ({ default: m.ProspectsPage })));
const PipelinePage = lazy(() => import("@/features/pipeline/PipelinePage").then((m) => ({ default: m.PipelinePage })));
const DiscoveryPage = lazy(() => import("@/features/discovery/DiscoveryPage").then((m) => ({ default: m.DiscoveryPage })));
const PlaybookPage = lazy(() => import("@/features/playbook/PlaybookPage").then((m) => ({ default: m.PlaybookPage })));
const ReportsPage = lazy(() => import("@/features/reports/ReportsPage").then((m) => ({ default: m.ReportsPage })));
const ResourcesPage = lazy(() => import("@/features/resources/ResourcesPage").then((m) => ({ default: m.ResourcesPage })));
const SettingsPage = lazy(() => import("@/features/settings/SettingsPage").then((m) => ({ default: m.SettingsPage })));

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 10_000,
        refetchOnWindowFocus: true,
        retry: (count, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2,
      },
    },
  });
}

function ThemedToaster() {
  const { resolved } = useTheme();
  return <Toaster theme={resolved} position="top-right" richColors closeButton toastOptions={{ duration: 5000 }} />;
}

export function Providers({ children, client }: { children: ReactNode; client?: QueryClient }) {
  const [queryClient] = useState(() => client ?? makeQueryClient());
  return (
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          {children}
          <ThemedToaster />
        </TooltipProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}

function NotFound() {
  return <EmptyState title="Page not found" description="This page does not exist." action={<Button asChild><Link to="/">Go to the dashboard</Link></Button>} />;
}

export function AppRoutes() {
  return (
    <AppDialogsProvider>
      <AppShell>
        <Suspense fallback={<LoadingRows rows={6} />}>
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/prospects" element={<ProspectsPage />} />
            <Route path="/pipeline" element={<PipelinePage />} />
            <Route path="/discovery" element={<DiscoveryPage />} />
            <Route path="/playbook" element={<PlaybookPage />} />
            <Route path="/reports" element={<ReportsPage />} />
            <Route path="/resources" element={<ResourcesPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </Suspense>
      </AppShell>
      <Onboarding />
    </AppDialogsProvider>
  );
}

export default function App() {
  return (
    <Providers>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </Providers>
  );
}
