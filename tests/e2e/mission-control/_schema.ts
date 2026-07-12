// Mission Control dashboard schema loader (MC W2 — schema-driven E2E).

import fs from "node:fs";
import path from "node:path";

export type McSchemaView = {
  id: string;
  label: string;
  selector: string;
};

export type McSchemaTab = {
  group: string;
  title: string;
  kind: string;
  views: McSchemaView[];
  read_endpoints?: string[];
  actions?: unknown[];
  key_selectors?: Record<string, string>;
};

export type McSchemaNavTab = {
  group: string;
  name: string;
  path: string;
  slug: string;
  kind?: string;
};

export type McSchemaNavGroup = {
  name: string;
  tabs: Array<{ slug: string; name: string; path: string; kind?: string }>;
};

export type MissionControlSchema = {
  schema_version: number;
  tab_count: number;
  nav: {
    groups: McSchemaNavGroup[];
    tab_count: number;
    tabs: McSchemaNavTab[];
    post_v1_placeholder_slugs?: string[];
  };
  shell: {
    key_selectors: Record<string, string>;
  };
  tabs: Record<string, McSchemaTab>;
};

const schemaPath = path.resolve(__dirname, "../../../infra/mission-control.schema.json");

/** Parsed golden dashboard contract (`infra/mission-control.schema.json`). */
export const mcSchema: MissionControlSchema = JSON.parse(
  fs.readFileSync(schemaPath, "utf8"),
) as MissionControlSchema;
