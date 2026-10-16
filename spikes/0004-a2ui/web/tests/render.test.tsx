// @vitest-environment jsdom

import { createElement, type ComponentType } from "react";
import { cleanup, render, type RenderResult } from "@testing-library/react";
import { expect, vi } from "vitest";
import {
  applyData,
  changedLeaves,
  firstChoiceValue,
  grownListPaths,
  leaves,
  messagesOf,
  readPayload,
  secretField,
  surfaceId,
  type JsonObject,
} from "./support/payload.ts";
import { red } from "./support/red.ts";
import {
  buttonNamed,
  chooseChoice,
  dateInputs,
  flush,
  hrefs,
  passwordInputs,
  queryAllByRole,
  rowCount,
  tableElement,
  textControls,
  textOf,
  typeInto,
} from "./support/roles.ts";

const BASIC_CATALOG = "https://a2ui.org/specification/v0_9/catalogs/basic/catalog.json";
const FORM_TEXT = "ada@example.com";
const FORM_DATE = "2026-10-17";

type UiAction = {
  surface_id: string;
  action: string;
  data: Record<string, unknown>;
};

type SpikeProps = {
  messages: readonly JsonObject[];
  onAction?: (action: UiAction) => void;
  onSecret?: (name: string, value: string) => void;
  onDataModel?: (model: unknown) => void;
};

async function loadApp(): Promise<ComponentType<SpikeProps>> {
  const mod = await import("../src/App.tsx");
  return mod.App as ComponentType<SpikeProps>;
}

async function mount(
  App: ComponentType<SpikeProps>,
  props: SpikeProps,
): Promise<RenderResult> {
  const view = render(createElement(App, props));
  await flush(view.container);
  return view;
}

function assertAction(action: UiAction, expectedSurface: string): void {
  expect(Object.keys(action).sort()).toEqual(["action", "data", "surface_id"]);
  expect(action.surface_id).toBe(expectedSurface);
  expect(typeof action.action).toBe("string");
  expect(action.action.length).toBeGreaterThan(0);
  expect(typeof action.data).toBe("object");
  expect(action.data).not.toBeNull();
  expect(Array.isArray(action.data)).toBe(false);
}

function flat(args: unknown[]): string {
  return args
    .map((arg) => (typeof arg === "string" ? arg : JSON.stringify(arg)))
    .join(" ");
}

red("W2")("renders p1 form fields by role", async () => {
  const payload = readPayload("p1-form");
  const messages = messagesOf(payload, false);
  const App = await loadApp();
  const view = await mount(App, { messages });
  try {
    expect(textControls(view.container).length).toBeGreaterThan(0);
    expect(
      queryAllByRole(view.container, "radio").length +
        queryAllByRole(view.container, "combobox").length,
    ).toBeGreaterThan(0);
    expect(dateInputs(view.container).length).toBeGreaterThan(0);
    expect(buttonNamed(view.container, /^submit$/i)).toBeTruthy();
  } finally {
    view.unmount();
    cleanup();
  }
});

red("W2")("submit emits ui.action with the form data", async () => {
  const payload = readPayload("p1-form");
  const messages = messagesOf(payload, false);
  const choice = firstChoiceValue(messages);
  const onAction = vi.fn<(action: UiAction) => void>();
  const App = await loadApp();
  const view = await mount(App, { messages, onAction });
  try {
    for (const control of textControls(view.container)) {
      typeInto(control, FORM_TEXT);
    }
    for (const control of dateInputs(view.container)) {
      typeInto(control, FORM_DATE);
    }
    chooseChoice(view.container, choice);
    buttonNamed(view.container, /^submit$/i)?.click();
    await flush(view.container);
    expect(onAction).toHaveBeenCalledTimes(1);
    const action = onAction.mock.calls[0]?.[0];
    if (!action) {
      throw new Error("missing action");
    }
    assertAction(action, surfaceId(messages));
    const encoded = JSON.stringify(action.data);
    expect(encoded).toContain(FORM_TEXT);
    expect(encoded).toContain(FORM_DATE);
    expect(encoded).toContain(choice);
  } finally {
    view.unmount();
    cleanup();
  }
});

red("W2")("p2 incremental update adds a row without remounting the table", async () => {
  const payload = readPayload("p2-table-update");
  expect(payload.update && payload.update.length > 0).toBe(true);
  const initial = messagesOf(payload, false);
  const full = messagesOf(payload, true);
  const beforeModel = applyData(initial);
  const afterModel = applyData(full);
  expect(grownListPaths(beforeModel, afterModel).length).toBeGreaterThan(0);
  const changes = changedLeaves(beforeModel, afterModel);
  expect(changes.length).toBeGreaterThan(0);
  const remaining = new Set(leaves(afterModel).values());
  const App = await loadApp();
  const view = await mount(App, { messages: initial });
  try {
    const table = tableElement(view.container);
    expect(table).toBeTruthy();
    if (!table) {
      return;
    }
    const rowsBefore = rowCount(table);
    expect(rowsBefore).toBeGreaterThan(0);
    view.rerender(createElement(App, { messages: full }));
    await flush(view.container);
    const again = tableElement(view.container);
    expect(again).toBe(table);
    expect(table.isConnected).toBe(true);
    expect(rowCount(table)).toBeGreaterThan(rowsBefore);
    const shown = textOf(table);
    for (const change of changes) {
      expect(shown).toContain(change.next);
      if (!remaining.has(change.previous)) {
        expect(shown).not.toContain(change.previous);
      }
    }
  } finally {
    view.unmount();
    cleanup();
  }
});

red("W2")(
  "p3 secret input is type=password and the value is passed only to onSecret",
  async () => {
    const payload = readPayload("p3-secret");
    const messages = messagesOf(payload, true);
    const field = secretField(messages);
    const canary = `canary-${crypto.randomUUID()}`;
    const onAction = vi.fn<(action: UiAction) => void>();
    const onSecret = vi.fn<(name: string, value: string) => void>();
    const models: unknown[] = [];
    const lines: string[] = [];
    const spies = (["log", "info", "debug", "warn", "error"] as const).map((method) =>
      vi.spyOn(console, method).mockImplementation((...args: unknown[]) => {
        lines.push(flat(args));
      }),
    );
    const App = await loadApp();
    const view = await mount(App, {
      messages,
      onAction,
      onSecret,
      onDataModel: (model: unknown) => {
        models.push(model);
      },
    });
    try {
      const shown = textOf(view.container);
      expect(shown).toContain(field.label);
      expect(shown).toContain(field.help);
      expect(hrefs(view.container)).toContain(field.link);
      const input = passwordInputs(view.container)[0];
      expect(input).toBeTruthy();
      if (!input) {
        return;
      }
      expect(input.getAttribute("type")).toBe("password");
      expect(input.getAttribute("autocomplete")).toBe("off");
      const modelsBefore = models.length;
      typeInto(input, canary);
      buttonNamed(view.container, /^save securely$/i)?.click();
      await flush(view.container);
      expect(input.value).toBe(canary);
      expect(onSecret).toHaveBeenCalledTimes(1);
      expect(onSecret).toHaveBeenCalledWith(field.name, canary);
      expect(onAction).toHaveBeenCalledTimes(1);
      const action = onAction.mock.calls[0]?.[0];
      if (!action) {
        throw new Error("missing action");
      }
      assertAction(action, surfaceId(messages));
      expect(action.data).toEqual({ secret_submitted: true, name: field.name });
      expect(JSON.stringify(action)).not.toContain(canary);
      expect(models.length).toBeGreaterThan(modelsBefore);
      expect(JSON.stringify(models)).not.toContain(canary);
      const logged = `${lines.join("\n")}\n${textOf(view.container)}`;
      expect(logged).toContain("«redacted»");
      expect(logged).not.toContain(canary);
    } finally {
      for (const spy of spies) {
        spy.mockRestore();
      }
      view.unmount();
      cleanup();
    }
  },
);

red("W2")("p4 approve and deny emit distinct actions", async () => {
  const payload = readPayload("p4-approval");
  const messages = messagesOf(payload, true);
  const onAction = vi.fn<(action: UiAction) => void>();
  const App = await loadApp();
  const view = await mount(App, { messages, onAction });
  try {
    const expectedSurface = surfaceId(messages);
    buttonNamed(view.container, /^approve$/i)?.click();
    buttonNamed(view.container, /^deny$/i)?.click();
    await flush(view.container);
    expect(onAction).toHaveBeenCalledTimes(2);
    const approve = onAction.mock.calls[0]?.[0];
    const deny = onAction.mock.calls[1]?.[0];
    if (!approve || !deny) {
      throw new Error("missing approval actions");
    }
    assertAction(approve, expectedSurface);
    assertAction(deny, expectedSurface);
    expect(approve.action).toBe("approve");
    expect(deny.action).toBe("deny");
  } finally {
    view.unmount();
    cleanup();
  }
});

red("W2")("p5 assist emits the Open Computer panel action", async () => {
  const payload = readPayload("p5-assist");
  const messages = messagesOf(payload, true);
  const onAction = vi.fn<(action: UiAction) => void>();
  const App = await loadApp();
  const view = await mount(App, { messages, onAction });
  try {
    const button = buttonNamed(view.container, /^Open Computer panel$/);
    expect(button).toBeTruthy();
    button?.click();
    await flush(view.container);
    expect(onAction).toHaveBeenCalledTimes(1);
    const action = onAction.mock.calls[0]?.[0];
    if (!action) {
      throw new Error("missing assist action");
    }
    assertAction(action, surfaceId(messages));
    expect(action.action).toBe("Open Computer panel");
  } finally {
    view.unmount();
    cleanup();
  }
});

red("W2")("unknown component shows fallback text", async () => {
  const messages: JsonObject[] = [
    {
      version: "v0.9",
      createSurface: { surfaceId: "unknown-surface", catalogId: BASIC_CATALOG },
    },
    {
      version: "v0.9",
      updateComponents: {
        surfaceId: "unknown-surface",
        components: [
          { id: "root", component: "Column", children: ["ok", "bad"] },
          { id: "ok", component: "Text", text: "Still here" },
          { id: "bad", component: "sevn.NotRegistered", text: "nope" },
        ],
      },
    },
  ];
  const App = await loadApp();
  const view = await mount(App, { messages });
  try {
    const shown = textOf(view.container).replace(/\s+/g, " ");
    expect(shown).toContain("Unsupported: sevn.NotRegistered");
    expect(shown).toContain("Still here");
  } finally {
    view.unmount();
    cleanup();
  }
});
