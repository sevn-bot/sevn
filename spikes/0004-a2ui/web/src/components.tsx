import { useContext, useRef, createContext, type Context } from "react";
import { createComponentImplementation } from "@a2ui/react/v0_9";
import { Catalog, CommonSchemas, basicCatalog, type ComponentContext } from "@a2ui/web_core/v0_9";
import { z } from "zod";

export type UiAction = {
  surface_id: string;
  action: string;
  data: Record<string, unknown>;
};

export type SpikeHandlers = {
  onAction: (action: UiAction) => void;
  onSecret: (name: string, value: string) => void;
  onDataModel: (model: unknown) => void;
  readModel: (surfaceId: string) => unknown;
};

const noopHandlers: SpikeHandlers = {
  onAction: () => undefined,
  onSecret: () => undefined,
  onDataModel: () => undefined,
  readModel: () => ({}),
};

export const HandlersContext: Context<SpikeHandlers> = createContext(noopHandlers);

const SecretFieldApi = {
  name: "sevn.SecretField",
  schema: z.object({
    name: z.string(),
    label: z.string(),
    help: z.string(),
    link: z.string(),
  }),
};

const ApprovalCardApi = {
  name: "sevn.ApprovalCard",
  schema: z.object({
    title: z.string(),
  }),
};

const AssistCardApi = {
  name: "sevn.AssistCard",
  schema: z.object({
    prompt: z.string(),
  }),
};

const TableApi = {
  name: "Table",
  schema: z.object({
    rows: CommonSchemas.DynamicValue,
  }),
};

function surfaceIdOf(context: ComponentContext): string {
  return context.dataContext.surface?.id ?? "";
}

const SecretField = createComponentImplementation(SecretFieldApi, ({ props, context }) => {
  const handlers = useContext(HandlersContext);
  const inputRef = useRef<HTMLInputElement>(null);
  const surfaceId = surfaceIdOf(context);
  const save = () => {
    const value = inputRef.current?.value ?? "";
    console.info("«redacted»");
    handlers.onSecret(props.name, value);
    handlers.onDataModel(handlers.readModel(surfaceId));
    handlers.onAction({
      surface_id: surfaceId,
      action: "save",
      data: { secret_submitted: true, name: props.name },
    });
  };
  return (
    <div>
      <label>{props.label}</label>
      <p>{props.help}</p>
      <a href={props.link}>{props.link}</a>
      <input ref={inputRef} type="password" autoComplete="off" />
      <button type="button" onClick={save}>
        Save securely
      </button>
    </div>
  );
});

const ApprovalCard = createComponentImplementation(ApprovalCardApi, ({ props, context }) => {
  const handlers = useContext(HandlersContext);
  const surfaceId = surfaceIdOf(context);
  const emit = (action: string) => {
    handlers.onAction({ surface_id: surfaceId, action, data: {} });
  };
  return (
    <div>
      <p>{props.title}</p>
      <button type="button" onClick={() => emit("approve")}>
        Approve
      </button>
      <button type="button" onClick={() => emit("deny")}>
        Deny
      </button>
    </div>
  );
});

const AssistCard = createComponentImplementation(AssistCardApi, ({ props, context }) => {
  const handlers = useContext(HandlersContext);
  const surfaceId = surfaceIdOf(context);
  return (
    <div>
      <p>{props.prompt}</p>
      <button
        type="button"
        onClick={() =>
          handlers.onAction({
            surface_id: surfaceId,
            action: "Open Computer panel",
            data: {},
          })
        }
      >
        Open Computer panel
      </button>
    </div>
  );
});

function rowCells(row: unknown): unknown[] {
  if (typeof row !== "object" || row === null || Array.isArray(row)) {
    return [];
  }
  return Object.values(row);
}

const Table = createComponentImplementation(TableApi, ({ props }) => {
  const rows = Array.isArray(props.rows) ? props.rows : [];
  return (
    <table>
      <tbody>
        {rows.map((row, index) => (
          <tr key={index}>
            {rowCells(row).map((cell, cellIndex) => (
              <td key={cellIndex}>{typeof cell === "string" ? cell : String(cell)}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
});

export const spikeCatalog = new Catalog(
  basicCatalog.id,
  basicCatalog.protocolVersion,
  [...basicCatalog.components.values(), SecretField, ApprovalCard, AssistCard, Table],
  [...basicCatalog.functions.values()],
  basicCatalog.themeSchema,
);
