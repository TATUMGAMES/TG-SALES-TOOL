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

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, NativeSelect, Textarea } from "@/components/ui/form";
import type { OpportunityCard, StageInfo } from "@/lib/api-types";
import { usePipelineMeta } from "@/lib/hooks";

/** Won, lost and "not a fit" need a reason (used in reports). */
export function ReasonDialog({
  target,
  onCancel,
  onConfirm,
}: {
  target: { card: Pick<OpportunityCard, "organization_name">; stage: StageInfo } | null;
  onCancel: () => void;
  onConfirm: (code: string, note: string) => Promise<void>;
}) {
  const meta = usePipelineMeta();
  const [code, setCode] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const codes = target ? meta.data?.reason_codes[target.stage.outcome] ?? [] : [];
  useEffect(() => {
    setCode(codes[0]?.value ?? "");
    setNote("");
  }, [target]);

  return (
    <Dialog
      open={target !== null}
      onOpenChange={(o) => !o && onCancel()}
      size="sm"
      title={target ? `Move to ${target.stage.name}` : ""}
      description={target ? `Why is ${target.card.organization_name} ${target.stage.outcome === "won" ? "won" : "closed"}?` : undefined}
      footer={
        <>
          <Button variant="outline" onClick={onCancel}>Cancel</Button>
          <Button
            disabled={!code}
            loading={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await onConfirm(code, note);
              } finally {
                setBusy(false);
              }
            }}
          >
            Move
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <Field label="Reason" required>
          {(p) => (
            <NativeSelect {...p} value={code} onChange={(e) => setCode(e.target.value)}>
              {codes.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
            </NativeSelect>
          )}
        </Field>
        <Field label="Details (optional)">{(p) => <Textarea {...p} rows={3} value={note} onChange={(e) => setNote(e.target.value)} />}</Field>
      </div>
    </Dialog>
  );
}
