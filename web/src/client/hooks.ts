import { QueryClient, useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect } from "react";
import {
  call,
  type HostClient,
  type MethodName,
  type MethodParams,
  onEvent,
  onTick,
  type ProtocolEvent,
} from "./connection.ts";

/** The serving host: the app's module-level connection. */
export const servingHostClient: HostClient = { call, onEvent, onTick };

/** The host a subtree talks to; the serving host unless a provider says otherwise. */
export const HostClientContext = createContext<HostClient>(servingHostClient);

export function useHostClient(): HostClient {
  return useContext(HostClientContext);
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        refetchOnWindowFocus: false,
        retry: (failureCount, error) =>
          failureCount < 20 &&
          error instanceof Error &&
          error.message === "not connected",
        retryDelay: 40,
      },
    },
  });
}

export function useCall<M extends MethodName>(
  method: M,
  params: MethodParams[M],
) {
  const host = useHostClient();
  return useQuery({
    queryKey: [method, params],
    queryFn: () => host.call(method, params),
  });
}

function tickKey(kind: string): readonly ["tick", string] {
  return ["tick", kind];
}

export function useTicks(kind: string): Record<string, unknown>[] {
  const client = useQueryClient();
  const host = useHostClient();
  const query = useQuery({
    queryKey: tickKey(kind),
    queryFn: () =>
      Promise.resolve(
        client.getQueryData<Record<string, unknown>[]>(tickKey(kind)) ?? [],
      ),
    initialData: [] as Record<string, unknown>[],
    staleTime: Number.POSITIVE_INFINITY,
    refetchOnMount: false,
    refetchOnReconnect: false,
    refetchOnWindowFocus: false,
  });
  useEffect(() => {
    return host.onTick(kind, (data) => {
      client.setQueryData<Record<string, unknown>[]>(
        tickKey(kind),
        (current) => [...(current ?? []), data],
      );
    });
  }, [client, host, kind]);
  return query.data ?? [];
}

const eventsKey = ["events"] as const;

export function useEvents(): ProtocolEvent[] {
  const client = useQueryClient();
  const host = useHostClient();
  const query = useQuery({
    queryKey: eventsKey,
    queryFn: () =>
      Promise.resolve(client.getQueryData<ProtocolEvent[]>(eventsKey) ?? []),
    initialData: [] as ProtocolEvent[],
    staleTime: Number.POSITIVE_INFINITY,
    refetchOnMount: false,
    refetchOnReconnect: false,
    refetchOnWindowFocus: false,
  });
  useEffect(() => {
    return host.onEvent((event) => {
      client.setQueryData<ProtocolEvent[]>(eventsKey, (current) => [
        ...(current ?? []),
        event,
      ]);
    });
  }, [client, host]);
  return query.data ?? [];
}
