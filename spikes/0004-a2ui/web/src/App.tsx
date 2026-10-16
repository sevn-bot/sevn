import { useEffect, useMemo, useRef, useState, type ComponentProps } from "react";
import { A2uiSurface } from "@a2ui/react/v0_9";
import { MessageProcessor, type ProcessableMessage } from "@a2ui/web_core/v0_9";
import { HandlersContext, spikeCatalog, type SpikeHandlers, type UiAction } from "./components.tsx";
import { demoMessages } from "./demo.ts";

export type SpikeProps = {
  messages?: readonly Record<string, unknown>[];
  onAction?: (action: UiAction) => void;
  onSecret?: (name: string, value: string) => void;
  onDataModel?: (model: unknown) => void;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function cloneModel(value: unknown): unknown {
  return structuredClone(value);
}

function unknownNames(messages: readonly Record<string, unknown>[]): string[] {
  const known = new Set(spikeCatalog.components.keys());
  const found: string[] = [];
  for (const message of messages) {
    const update = message.updateComponents;
    if (!isRecord(update) || !Array.isArray(update.components)) {
      continue;
    }
    for (const component of update.components) {
      if (!isRecord(component) || typeof component.component !== "string") {
        continue;
      }
      if (!known.has(component.component) && !found.includes(component.component)) {
        found.push(component.component);
      }
    }
  }
  return found;
}

type SpikeSurface = ComponentProps<typeof A2uiSurface>["surface"];

function samePrefix(
  previous: readonly Record<string, unknown>[],
  next: readonly Record<string, unknown>[],
): boolean {
  return (
    previous.length <= next.length &&
    previous.every((message, index) => message === next[index])
  );
}

export function App({ messages, onAction, onSecret, onDataModel }: SpikeProps) {
  const demo = useMemo(() => demoMessages(), []);
  const source = messages ?? demo;
  const handlersRef = useRef<SpikeHandlers>({
    onAction: () => undefined,
    onSecret: () => undefined,
    onDataModel: () => undefined,
    readModel: () => ({}),
  });
  const processorRef = useRef<MessageProcessor | null>(null);
  if (!processorRef.current) {
    processorRef.current = new MessageProcessor([spikeCatalog], (payload) => {
      handlersRef.current.onAction({
        surface_id: payload.surfaceId,
        action: payload.name,
        data: isRecord(payload.context) ? payload.context : {},
      });
    });
  }
  const applied = useRef<readonly Record<string, unknown>[]>([]);
  const [surfaces, setSurfaces] = useState<SpikeSurface[]>([]);
  const [log, setLog] = useState<UiAction[]>([]);
  const stableHandlers = useRef<SpikeHandlers>({
    onAction: (action) => {
      handlersRef.current.onAction(action);
    },
    onSecret: (name, value) => {
      handlersRef.current.onSecret(name, value);
    },
    onDataModel: (model) => {
      handlersRef.current.onDataModel(model);
    },
    readModel: (surfaceId) => handlersRef.current.readModel(surfaceId),
  }).current;

  handlersRef.current = {
    onAction: (action) => {
      setLog((entries) => [...entries, action]);
      onAction?.(action);
    },
    onSecret: (name, value) => {
      onSecret?.(name, value);
    },
    onDataModel: (model) => {
      onDataModel?.(model);
    },
    readModel: (surfaceId) => {
      const surface = processorRef.current?.model.surfacesMap.get(surfaceId);
      return cloneModel(surface?.dataModel.get("/") ?? {});
    },
  };

  useEffect(() => {
    const processor = processorRef.current;
    if (!processor) {
      return;
    }
    const extension = samePrefix(applied.current, source);
    if (!extension) {
      for (const surfaceId of [...processor.model.surfacesMap.keys()]) {
        processor.processMessages([{ version: "v0.9", deleteSurface: { surfaceId } }]);
      }
    }
    const delta = extension ? source.slice(applied.current.length) : source;
    if (delta.length > 0) {
      processor.processMessages(delta as ProcessableMessage[]);
    }
    applied.current = source;
    const next = [...processor.model.surfacesMap.values()] as SpikeSurface[];
    setSurfaces(next);
    for (const surface of next) {
      handlersRef.current.onDataModel(cloneModel(surface.dataModel.get("/")));
    }
  }, [source]);

  useEffect(() => {
    const subscriptions = surfaces.map((surface) =>
      surface.dataModel.subscribe("/", (value) => {
        handlersRef.current.onDataModel(cloneModel(value));
      }),
    );
    return () => {
      for (const subscription of subscriptions) {
        subscription.unsubscribe();
      }
    };
  }, [surfaces]);

  return (
    <HandlersContext.Provider value={stableHandlers}>
      <h1>A2UI spike</h1>
      {unknownNames(source).map((name) => (
        <p key={name}>Unsupported: {name}</p>
      ))}
      {surfaces.map((surface) => (
        <A2uiSurface key={surface.id} surface={surface} />
      ))}
      <section aria-label="Action log">
        <h2>Action log</h2>
        <ol>
          {log.map((entry, index) => (
            <li key={index}>
              {entry.action}{" "}
              {entry.data.secret_submitted === true ? "«redacted»" : JSON.stringify(entry.data)}
            </li>
          ))}
        </ol>
      </section>
    </HandlersContext.Provider>
  );
}
