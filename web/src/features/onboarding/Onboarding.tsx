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
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, NativeSelect } from "@/components/ui/form";
import { api } from "@/lib/api";
import { showError, useInfo } from "@/lib/hooks";
import { useTheme, type ThemeChoice } from "@/lib/theme";

/** First run: the salesperson's name (shown on their records) and the theme. */
export function Onboarding() {
  const info = useInfo();
  const client = useQueryClient();
  const { theme, setTheme } = useTheme();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const open = Boolean(info.data?.first_run) && !dismissed;

  const finish = async () => {
    setBusy(true);
    try {
      await api.put("/me", { display_name: name });
      await api.patch("/settings", { theme, show_onboarding: false });
      await client.invalidateQueries({ queryKey: ["info"] });
      toast.success(`Welcome, ${name.trim()}!`);
      setDismissed(true);
    } catch (error) {
      showError(error);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => !next && setDismissed(true)}
      title="Welcome to TG Sales CRM"
      description="Two quick choices and you are ready. You can change them later in Settings."
      footer={
        <>
          <Button variant="ghost" onClick={() => setDismissed(true)}>Later</Button>
          <Button onClick={finish} loading={busy} disabled={!name.trim()}>Get started</Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="Your name" hint="Colleagues see it on the prospects, deals and notes you add.">
          {(p) => <Input {...p} autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Sam Seller" />}
        </Field>
        <Field label="Theme">
          {(p) => (
            <NativeSelect {...p} value={theme} onChange={(e) => setTheme(e.target.value as ThemeChoice)}>
              <option value="system">Same as Windows</option>
              <option value="light">Light</option>
              <option value="dark">Dark</option>
            </NativeSelect>
          )}
        </Field>
        <p className="text-sm text-muted-foreground">Set your company name, logo, sales lanes and custom fields any time in Settings.</p>
      </div>
    </Dialog>
  );
}
