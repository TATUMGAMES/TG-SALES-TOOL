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

import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router";
import { ImportWizard } from "@/features/imports/ImportWizard";
import { ProspectForm } from "@/features/prospects/ProspectForm";

interface AppDialogs {
  openImport: () => void;
  openNewProspect: () => void;
}

const DialogsContext = createContext<AppDialogs | null>(null);

/** Dialogs reachable from everywhere (header buttons, empty states). */
export function AppDialogsProvider({ children }: { children: ReactNode }) {
  const [importOpen, setImportOpen] = useState(false);
  const [prospectOpen, setProspectOpen] = useState(false);
  const navigate = useNavigate();
  const value = useMemo(
    () => ({ openImport: () => setImportOpen(true), openNewProspect: () => setProspectOpen(true) }),
    [],
  );
  return (
    <DialogsContext.Provider value={value}>
      {children}
      <ImportWizard open={importOpen} onOpenChange={setImportOpen} />
      <ProspectForm open={prospectOpen} onOpenChange={setProspectOpen} onSaved={(id) => navigate(`/prospects?id=${id}`)} />
    </DialogsContext.Provider>
  );
}

export function useAppDialogs(): AppDialogs {
  const value = useContext(DialogsContext);
  if (!value) throw new Error("useAppDialogs must be used inside AppDialogsProvider");
  return value;
}
