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

import * as CheckboxPrimitive from "@radix-ui/react-checkbox";
import * as DropdownPrimitive from "@radix-ui/react-dropdown-menu";
import * as ProgressPrimitive from "@radix-ui/react-progress";
import * as SwitchPrimitive from "@radix-ui/react-switch";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { AlertTriangle, Check, Inbox } from "lucide-react";
import { createContext, forwardRef, useContext, useRef, useState, type ComponentProps, type ReactNode } from "react";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "./button";

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("animate-pulse rounded-md bg-muted", className)} />;
}

export function LoadingRows({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-2" role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-12 w-full" />
      ))}
    </div>
  );
}

export function Progress({ value, label }: { value: number; label?: string }) {
  return (
    <div className="space-y-1.5">
      {label ? <p className="text-sm text-muted-foreground">{label}</p> : null}
      <ProgressPrimitive.Root
        value={value}
        className="relative h-2 w-full overflow-hidden rounded-full bg-muted"
        aria-label={label ?? "Progress"}
      >
        <ProgressPrimitive.Indicator
          className="h-full rounded-full bg-[linear-gradient(90deg,var(--brand-purple),var(--brand-teal))] transition-transform"
          style={{ transform: `translateX(-${100 - Math.max(2, Math.min(100, value))}%)` }}
        />
      </ProgressPrimitive.Root>
    </div>
  );
}

export function Switch({ className, ...props }: SwitchPrimitive.SwitchProps) {
  return (
    <SwitchPrimitive.Root
      className={cn(
        "relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent bg-input transition-colors data-[state=checked]:bg-primary focus-visible:outline-2 focus-visible:outline-ring",
        className,
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb className="pointer-events-none block size-5 rounded-full bg-white shadow transition-transform data-[state=checked]:translate-x-5" />
    </SwitchPrimitive.Root>
  );
}

export function Checkbox({ className, ...props }: CheckboxPrimitive.CheckboxProps) {
  return (
    <CheckboxPrimitive.Root
      className={cn(
        "flex size-5 shrink-0 items-center justify-center rounded border border-input bg-card data-[state=checked]:border-primary data-[state=checked]:bg-primary data-[state=checked]:text-primary-foreground focus-visible:outline-2 focus-visible:outline-ring",
        className,
      )}
      {...props}
    >
      <CheckboxPrimitive.Indicator>
        <Check className="size-3.5" strokeWidth={3} />
      </CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  );
}

export const Tabs = TabsPrimitive.Root;

export function TabsList({ className, ...props }: TabsPrimitive.TabsListProps) {
  return (
    <TabsPrimitive.List
      className={cn("inline-flex max-w-full gap-1 overflow-x-auto rounded-lg bg-muted p-1", className)}
      {...props}
    />
  );
}

export function TabsTrigger({ className, ...props }: TabsPrimitive.TabsTriggerProps) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        "whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground transition-colors data-[state=active]:bg-card data-[state=active]:text-foreground data-[state=active]:shadow-sm focus-visible:outline-2 focus-visible:outline-ring",
        className,
      )}
      {...props}
    />
  );
}

export const TabsContent = TabsPrimitive.Content;

export function Tooltip({ content, children }: { content: ReactNode; children: ReactNode }) {
  return (
    <TooltipPrimitive.Root delayDuration={300}>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          sideOffset={6}
          className="z-50 max-w-xs rounded-md bg-foreground px-2.5 py-1.5 text-xs text-background shadow animate-fade-in"
        >
          {content}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}

export const TooltipProvider = TooltipPrimitive.Provider;

const MenuToggle = createContext<((update: (open: boolean) => boolean) => void) | null>(null);

/**
 * Dropdown menu that is safe on touch screens: Radix opens menus on pointer-down,
 * so on a phone the same tap can land on (and select) a menu item. Touch and pen
 * input open the menu on a completed tap instead; mouse and keyboard are unchanged.
 */
export function DropdownMenu({ children, ...props }: DropdownPrimitive.DropdownMenuProps) {
  const [open, setOpen] = useState(false);
  return (
    <MenuToggle.Provider value={setOpen}>
      <DropdownPrimitive.Root open={open} onOpenChange={setOpen} {...props}>
        {children}
      </DropdownPrimitive.Root>
    </MenuToggle.Provider>
  );
}

export const DropdownMenuTrigger = forwardRef<HTMLButtonElement, DropdownPrimitive.DropdownMenuTriggerProps>(
  ({ onPointerDown, onClick, ...props }, ref) => {
    const toggle = useContext(MenuToggle);
    const pointer = useRef<string>("mouse");
    return (
      <DropdownPrimitive.Trigger
        ref={ref}
        {...props}
        onPointerDown={(event) => {
          pointer.current = event.pointerType;
          if (event.pointerType !== "mouse") event.preventDefault();
          onPointerDown?.(event);
        }}
        onClick={(event) => {
          if (pointer.current !== "mouse" && event.detail > 0) toggle?.((open) => !open);
          pointer.current = "mouse";
          onClick?.(event);
        }}
      />
    );
  },
);
DropdownMenuTrigger.displayName = "DropdownMenuTrigger";

export function DropdownMenuContent({ className, ...props }: DropdownPrimitive.DropdownMenuContentProps) {
  return (
    <DropdownPrimitive.Portal>
      <DropdownPrimitive.Content
        sideOffset={6}
        align="end"
        className={cn("z-50 min-w-48 rounded-lg border bg-card p-1 shadow-lg animate-fade-in", className)}
        {...props}
      />
    </DropdownPrimitive.Portal>
  );
}

export function DropdownMenuItem({ className, danger, ...props }: DropdownPrimitive.DropdownMenuItemProps & { danger?: boolean }) {
  return (
    <DropdownPrimitive.Item
      className={cn(
        "flex cursor-pointer select-none items-center gap-2 rounded-md px-2.5 py-2 text-sm outline-none data-[highlighted]:bg-muted data-[disabled]:pointer-events-none data-[disabled]:opacity-50 [&_svg]:size-4",
        danger && "text-danger",
        className,
      )}
      {...props}
    />
  );
}

export function DropdownMenuLabel(props: ComponentProps<typeof DropdownPrimitive.Label>) {
  return <DropdownPrimitive.Label className="px-2.5 py-1.5 text-xs font-medium text-muted-foreground" {...props} />;
}

export function DropdownMenuSeparator() {
  return <DropdownPrimitive.Separator className="my-1 h-px bg-border" />;
}

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: ReactNode;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed px-6 py-12 text-center">
      <div className="flex size-12 items-center justify-center rounded-full bg-primary-soft text-primary [&_svg]:size-6">
        {icon ?? <Inbox />}
      </div>
      <div className="space-y-1">
        <p className="font-semibold">{title}</p>
        {description ? <p className="mx-auto max-w-md text-sm text-muted-foreground">{description}</p> : null}
      </div>
      {action}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const plain = typeof error === "object" && error !== null ? (error as { message?: unknown; action?: unknown }) : {};
  const message =
    error instanceof ApiError ? error.message : typeof plain.message === "string" ? plain.message : "Something went wrong.";
  const action = error instanceof ApiError ? error.action : typeof plain.action === "string" ? plain.action : "Try again.";
  return (
    <div role="alert" className="flex flex-col items-start gap-2 rounded-xl border border-danger/30 bg-danger-soft p-4 sm:flex-row sm:items-center">
      <AlertTriangle className="size-5 shrink-0 text-danger" aria-hidden />
      <div className="flex-1 text-sm">
        <p className="font-medium text-danger">{message}</p>
        <p className="text-foreground/80">{action}</p>
      </div>
      {onRetry ? (
        <Button variant="outline" size="sm" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description ? <p className="mt-1 text-sm text-muted-foreground">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function Separator({ className }: { className?: string }) {
  return <hr className={cn("border-border", className)} />;
}
