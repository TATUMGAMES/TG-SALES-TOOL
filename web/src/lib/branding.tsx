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
import { useEffect } from "react";
import { api, apiUrl } from "./api";
import type { BrandingView } from "./api-types";

/** The product name shown next to the company name; not affected by branding. */
export const PRODUCT_NAME = "TG Sales CRM";

export type ImageSlot = "logo" | "compact_logo" | "favicon";

export function useBranding() {
  return useQuery({ queryKey: ["branding"], queryFn: () => api.get<BrandingView>("/branding"), staleTime: 60_000 });
}

/** URL of an uploaded branding image (with a version so browsers fetch new uploads), or null. */
export function brandImageUrl(branding: BrandingView | undefined, slot: ImageSlot): string | null {
  const image = branding?.images?.[slot];
  return image?.present ? `${apiUrl(`/branding/images/${slot}`)}?v=${image.version ?? ""}` : null;
}

/**
 * Applies the installation's branding to the page: the browser tab icon and
 * title, and the accent color (buttons, links, the selected menu item).
 */
export function useApplyBranding(): void {
  const branding = useBranding().data;
  useEffect(() => {
    if (!branding) return;
    const root = document.documentElement;
    if (branding.accent_color) {
      root.style.setProperty("--primary", branding.accent_color);
      root.style.setProperty("--primary-foreground", branding.accent_text_color ?? "#ffffff");
      root.style.setProperty("--primary-soft", `color-mix(in srgb, ${branding.accent_color} 18%, var(--background))`);
    } else {
      root.style.removeProperty("--primary");
      root.style.removeProperty("--primary-foreground");
      root.style.removeProperty("--primary-soft");
    }
    const favicon = brandImageUrl(branding, "favicon");
    let link = document.querySelector<HTMLLinkElement>("link[rel='icon'][data-branding]");
    if (favicon) {
      if (!link) {
        link = document.createElement("link");
        link.rel = "icon";
        link.dataset.branding = "true";
        document.head.appendChild(link);
      }
      link.type = branding.images.favicon?.media_type ?? "image/png";
      link.href = favicon;
    } else {
      link?.remove();
    }
    document.title = branding.company_name ? `${PRODUCT_NAME} · ${branding.display_name}` : PRODUCT_NAME;
  }, [branding]);
}
