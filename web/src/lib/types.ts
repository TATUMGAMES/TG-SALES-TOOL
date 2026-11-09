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
