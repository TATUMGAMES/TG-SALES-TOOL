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
