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

import { useQuery } from "@tanstack/react-query";
import {
  Bell,
  BookOpenText,
  FileBarChart2,
  FolderOpen,
  KanbanSquare,
  LayoutDashboard,
  Menu,
  Monitor,
  Moon,
  Plus,
  Search,
  Settings,
  Sparkles,
  Sun,
  Upload,
  Users,
  Wifi,
  WifiOff,
} from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/card";
import { Sheet } from "@/components/ui/dialog";
import { Input } from "@/components/ui/form";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger, Tooltip } from "@/components/ui/misc";
import { api } from "@/lib/api";
import type { Reminder } from "@/lib/api-types";
import { brandImageUrl, PRODUCT_NAME, useApplyBranding, useBranding } from "@/lib/branding";
import { relativeDue } from "@/lib/format";
import { useInfo, useOnline } from "@/lib/hooks";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { useAppDialogs } from "./dialogs";

export const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, mobile: true },
  { to: "/prospects", label: "Prospects", icon: Users, mobile: true },
  { to: "/pipeline", label: "Pipeline", icon: KanbanSquare, mobile: true },
  { to: "/discovery", label: "Discovery", icon: Sparkles, mobile: true },
  { to: "/playbook", label: "Playbook", icon: BookOpenText, mobile: false },
  { to: "/reports", label: "Reports", icon: FileBarChart2, mobile: false },
  { to: "/resources", label: "Resources", icon: FolderOpen, mobile: false },
  { to: "/settings", label: "Settings & Sync", icon: Settings, mobile: true },
] as const;

function Brand() {
  const branding = useBranding().data;
  const logo = brandImageUrl(branding, "logo");
  return (
    <div className="flex items-center gap-2.5">
      <img src={logo ?? "/icons/icon.svg"} alt={logo ? `${branding?.display_name ?? "Company"} logo` : ""} className="size-9 rounded-lg object-contain" />
      <div className="min-w-0 leading-tight">
        <p className="text-sm font-semibold">{PRODUCT_NAME}</p>
        <p className="truncate text-xs text-muted-foreground">{branding?.display_name ?? ""}</p>
      </div>
    </div>
  );
}

function CompactLogo() {
  const branding = useBranding().data;
  const logo = brandImageUrl(branding, "compact_logo") ?? brandImageUrl(branding, "logo");
  return <img src={logo ?? "/icons/icon.svg"} alt={branding?.display_name ?? PRODUCT_NAME} className="size-8 rounded object-contain" />;
}

function NavItems({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav aria-label="Main" className="space-y-1">
      {NAV.map(({ to, label, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          end={to === "/"}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
              isActive
                ? "bg-primary-soft text-foreground shadow-[inset_3px_0_0_var(--brand-purple)]"
                : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )
          }
        >
          <Icon className="size-[18px]" aria-hidden />
          {label}
        </NavLink>
      ))}
    </nav>
  );
}

function ThemeMenu() {
  const { theme, setTheme, resolved } = useTheme();
  const options = [
    { value: "light", label: "Light", icon: Sun },
    { value: "dark", label: "Dark", icon: Moon },
    { value: "system", label: "Same as Windows", icon: Monitor },
  ] as const;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Change theme">
          {resolved === "dark" ? <Moon /> : <Sun />}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        <DropdownMenuLabel>Theme</DropdownMenuLabel>
        {options.map(({ value, label, icon: Icon }) => (
          <DropdownMenuItem key={value} onSelect={() => setTheme(value)} aria-checked={theme === value} role="menuitemradio">
            <Icon /> {label} {theme === value ? <span className="ml-auto text-xs text-muted-foreground">Selected</span> : null}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function RemindersMenu() {
  const navigate = useNavigate();
  const reminders = useQuery({
    queryKey: ["reminders"],
    queryFn: () => api.get<Reminder[]>("/reminders"),
    refetchInterval: 120_000,
  });
  const items = reminders.data ?? [];
  const overdue = items.filter((r) => r.overdue).length;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={`Follow-ups: ${items.length} due, ${overdue} overdue`} className="relative">
          <Bell />
          {items.length ? (
            <span
              className={cn(
                "absolute right-1 top-1 flex min-w-4 items-center justify-center rounded-full px-1 text-[10px] font-bold",
                overdue ? "bg-brand-coral text-[#3a1010]" : "bg-brand-yellow text-[#3a2c00]",
              )}
            >
              {items.length}
            </span>
          ) : null}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-80 max-w-[90vw]">
        <DropdownMenuLabel>Follow-ups due today and overdue</DropdownMenuLabel>
        {items.length === 0 ? <p className="px-2.5 py-3 text-sm text-muted-foreground">Nothing due. Nice work.</p> : null}
        {items.slice(0, 8).map((reminder, index) => (
          <DropdownMenuItem
            key={`${reminder.opportunity_id ?? reminder.task_id}-${index}`}
            onSelect={() => reminder.opportunity_id && navigate(`/pipeline?opportunity=${reminder.opportunity_id}`)}
          >
            <div className="min-w-0">
              <p className="truncate font-medium">{reminder.title}</p>
              <p className="truncate text-xs text-muted-foreground">
                {reminder.organization_name} · {relativeDue(reminder.due_at).text}
              </p>
            </div>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function GlobalSearch({ className }: { className?: string }) {
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const submit = (event: FormEvent) => {
    event.preventDefault();
    navigate(`/prospects?q=${encodeURIComponent(text.trim())}`);
  };
  return (
    <form role="search" onSubmit={submit} className={cn("relative", className)}>
      <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
      <Input
        aria-label="Search prospects, contacts, games and tags"
        placeholder="Search names, websites, contacts, games, tags…"
        className="pl-9"
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
    </form>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const online = useOnline();
  const info = useInfo();
  const location = useLocation();
  const dialogs = useAppDialogs();
  const branding = useBranding().data;
  useApplyBranding();

  return (
    <div className="min-h-dvh lg:pl-64">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-card focus:px-3 focus:py-2">
        Skip to content
      </a>
      <aside className="fixed inset-y-0 left-0 hidden w-64 flex-col border-r bg-sidebar px-4 py-5 lg:flex">
        <Brand />
        <div className="mt-8 flex-1 overflow-y-auto">
          <NavItems />
        </div>
        <div className="space-y-1 text-xs text-muted-foreground">
          <p className="truncate">Signed in on this computer as {info.data?.display_name ?? "…"}</p>
          <p>Version {info.data?.version ?? ""}</p>
        </div>
      </aside>

      <header className="sticky top-0 z-30 border-b bg-background/90 backdrop-blur pt-[env(safe-area-inset-top)]">
        <div className="flex h-16 items-center gap-2 px-3 sm:px-5">
          <Button variant="ghost" size="icon" className="lg:hidden" aria-label="Open menu" onClick={() => setMenuOpen(true)}>
            <Menu />
          </Button>
          <div className="lg:hidden">
            <CompactLogo />
          </div>
          <GlobalSearch className="hidden flex-1 sm:block sm:max-w-md" />
          <div className="ml-auto flex items-center gap-1">
            <Tooltip content={online ? "Online. Game discovery can reach Steam." : "Offline. Everything except game discovery still works."}>
              <span>
                <Badge tone={online ? "success" : "warning"} className="hidden md:inline-flex">
                  {online ? <Wifi className="size-3.5" /> : <WifiOff className="size-3.5" />}
                  {online ? "Online" : "Offline"}
                </Badge>
              </span>
            </Tooltip>
            <Button variant="outline" size="sm" className="hidden sm:inline-flex" onClick={dialogs.openImport}>
              <Upload /> Import
            </Button>
            <Button size="sm" onClick={dialogs.openNewProspect} aria-label="New prospect">
              <Plus /> <span className="hidden sm:inline">New prospect</span>
            </Button>
            <RemindersMenu />
            <ThemeMenu />
          </div>
        </div>
        {location.pathname === "/prospects" ? null : (
          <div className="px-3 pb-3 sm:hidden">
            <GlobalSearch />
          </div>
        )}
      </header>

      <Sheet open={menuOpen} onOpenChange={setMenuOpen} title={PRODUCT_NAME} description={branding?.display_name ?? ""}>
        <NavItems onNavigate={() => setMenuOpen(false)} />
        <div className="mt-6 grid gap-2">
          <Button variant="outline" onClick={() => { setMenuOpen(false); dialogs.openImport(); }}>
            <Upload /> Import a file
          </Button>
        </div>
      </Sheet>

      <main id="main" className="mx-auto w-full max-w-[1500px] px-3 py-5 pb-24 sm:px-5 lg:px-8 lg:pb-10">
        {children}
      </main>

      <nav
        aria-label="Quick navigation"
        className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t bg-card/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden"
      >
        {NAV.filter((item) => item.mobile).map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              cn(
                "flex flex-col items-center gap-0.5 py-2 text-[11px] font-medium",
                isActive ? "text-primary" : "text-muted-foreground",
              )
            }
          >
            <Icon className="size-5" aria-hidden />
            <span className="truncate">{label.split(" ")[0]}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
