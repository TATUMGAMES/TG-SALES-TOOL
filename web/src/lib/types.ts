/** Friendly names for generated API types whose schema names collide. */
import type {
  Tg_sales__api__routers__collaboration__ExportIn,
  Tg_sales__domain__discovery__ContactStatus,
  Tg_sales__domain__enums__ContactStatus,
} from "./api-types";

export type ContactStatus = Tg_sales__domain__enums__ContactStatus;
export type LeadContactStatus = Tg_sales__domain__discovery__ContactStatus;
export type SyncExportIn = Tg_sales__api__routers__collaboration__ExportIn;

export const CONTACT_STATUS_LABELS: Record<ContactStatus, string> = {
  unknown: "Unknown",
  not_contacted: "Not contacted",
  attempted: "Contacted, no reply",
  responded: "Replied",
};

export const ORGANIZATION_TYPE_LABELS: Record<string, string> = {
  unknown: "Unknown",
  studio: "Studio",
  publisher: "Publisher",
  data_buyer: "Data buyer",
  other: "Other",
};

export const LANE_LABELS: Record<string, string> = {
  data_licensing: "Data licensing",
  publisher_partnership: "Publisher partnership",
  mikros_marketing: "MIKROS Marketing",
};
