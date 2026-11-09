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

import { useQueryClient } from "@tanstack/react-query";
import { ImageUp, RotateCcw, Save, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/form";
import { ErrorState, LoadingRows } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { brandImageUrl, type ImageSlot, useBranding } from "@/lib/branding";
import { showError, useAction } from "@/lib/hooks";

const SLOTS: { slot: ImageSlot; title: string; description: string; fallback: string }[] = [
  { slot: "logo", title: "Company logo", description: "Shown in the sidebar and the menu. Square or wide logos work best.", fallback: "/icons/icon.svg" },
  { slot: "compact_logo", title: "Compact logo (optional)", description: "Used where space is tight, such as the phone header. Uses the company logo when not set.", fallback: "/icons/icon.svg" },
  { slot: "favicon", title: "Browser tab icon (optional)", description: "The small icon in the browser tab. Saved as a 64 × 64 image.", fallback: "/icons/icon.svg" },
];

function ImageCard({ slot, title, description, fallback }: (typeof SLOTS)[number]) {
  const client = useQueryClient();
  const branding = useBranding();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const url = brandImageUrl(branding.data, slot);
  const remove = useAction(() => api.delete(`/branding/images/${slot}`), { invalidate: [["branding"], ["logo"]], success: "Image removed" });

  const upload = async (file: File) => {
    setBusy(true);
    try {
      const form = new FormData();
      form.append("image", file);
      await api.put(`/branding/images/${slot}`, form);
      await client.invalidateQueries({ queryKey: ["branding"] });
      await client.invalidateQueries({ queryKey: ["logo"] });
      toast.success("Image saved");
    } catch (error) {
      showError(error);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader title={title} description={description} />
      <div className="flex flex-wrap items-center gap-4 p-5 pt-3">
        <div className="flex size-20 items-center justify-center rounded-lg border bg-muted/40 p-2">
          <img src={url ?? fallback} alt={url ? title : "Default icon"} className="max-h-full max-w-full object-contain" />
        </div>
        <input
          ref={input}
          type="file"
          hidden
          accept="image/png,image/jpeg,image/webp,image/bmp,image/svg+xml,.svg"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void upload(file);
            e.target.value = "";
          }}
        />
        <Button variant="outline" loading={busy} onClick={() => input.current?.click()}><ImageUp /> Choose image…</Button>
        {url ? <Button variant="ghost" onClick={() => remove.mutate()}><Trash2 /> Remove</Button> : null}
      </div>
    </Card>
  );
}

export function BrandingPanel() {
  const branding = useBranding();
  const [name, setName] = useState("");
  const [color, setColor] = useState("");
  const [confirmReset, setConfirmReset] = useState(false);
  useEffect(() => {
    if (branding.data) {
      setName(branding.data.company_name ?? "");
      setColor(branding.data.accent_color ?? "");
    }
  }, [branding.data]);
  const save = useAction(() => api.patch("/branding", { company_name: name || null, accent_color: color || null }), {
    invalidate: [["branding"]],
    success: "Branding saved",
  });
  const reset = useAction(() => api.post("/branding/reset"), { invalidate: [["branding"], ["logo"]], success: "Default branding restored" });

  if (branding.error) return <ErrorState error={branding.error} onRetry={() => branding.refetch()} />;
  if (!branding.data) return <LoadingRows />;

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title="Company"
          description="How this installation shows your company. Changing it does not change the software's license or copyright notices (see About)."
        />
        <div className="grid gap-4 p-5 pt-3 sm:grid-cols-2">
          <Field label="Company name" hint={`Shown under the product name. Leave empty for “${branding.data.default_company_name}”.`}>
            {(p) => <Input {...p} value={name} maxLength={80} onChange={(e) => setName(e.target.value)} placeholder={branding.data.default_company_name} />}
          </Field>
          <Field label="Accent color (optional)" hint="Buttons, links and the selected menu item. Text color is chosen automatically for readability.">
            {(p) => (
              <div className="flex items-center gap-2">
                <input type="color" aria-label="Pick accent color" value={color || "#6f4f8a"} onChange={(e) => setColor(e.target.value)} className="h-9 w-12 cursor-pointer rounded border bg-transparent" />
                <Input {...p} value={color} onChange={(e) => setColor(e.target.value.trim())} placeholder="Default" className="w-32" />
                {color ? <Button variant="ghost" size="sm" onClick={() => setColor("")}>Use default</Button> : null}
              </div>
            )}
          </Field>
        </div>
        <div className="px-5 pb-5">
          <Button loading={save.isPending} onClick={() => save.mutate()}><Save /> Save</Button>
        </div>
      </Card>

      <p className="text-sm text-muted-foreground">{branding.data.requirements}</p>
      {SLOTS.map((slot) => <ImageCard key={slot.slot} {...slot} />)}

      <Card className="space-y-3 p-5 text-sm">
        <p className="font-medium">Where branding is stored</p>
        <p className="text-muted-foreground">
          Images and settings are saved in this installation's data folder (the <code>assets</code> folder next to your database files, or the <code>/data</code> volume with Docker), so they
          survive restarts and updates. Copying files into the project's <code>assets</code> folder does not change the app: upload images here instead.
        </p>
        <Button variant="outline" onClick={() => setConfirmReset(true)}><RotateCcw /> Restore default branding</Button>
      </Card>

      <ConfirmDialog
        open={confirmReset}
        onOpenChange={setConfirmReset}
        title="Restore the default branding?"
        description="The company name and accent color go back to the defaults and the uploaded images are removed. Your CRM records are not affected."
        confirmLabel="Restore defaults"
        danger
        onConfirm={async () => {
          await reset.mutateAsync();
        }}
      />
    </div>
  );
}
