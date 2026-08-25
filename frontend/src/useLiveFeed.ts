import { useEffect, useState } from "react";
import { LiveFeedServiceClient } from "@thing-transfer/proto-gen/packagepb/v1/Live_feed_serviceServiceClientPb";
// Named imports don't work here: protoc-gen-js emits CommonJS with
// exports assigned dynamically at runtime (goog.object.extend(exports,
// proto.packagepb.v1)), not static `exports.Foo = ...` assignments —
// no bundler's CJS->ESM interop can discover dynamically-created named
// exports ahead of time, regardless of plugin. Namespace import +
// runtime destructuring is the correct fix, not a workaround.
import * as liveFeedPb from "@thing-transfer/proto-gen/packagepb/v1/live_feed_service_pb";
import type { ClientReadableStream } from "grpc-web";
import * as commonPb from "@thing-transfer/proto-gen/packagepb/v1/common_pb";
import * as alertPb from "@thing-transfer/proto-gen/packagepb/v1/alert_pb";

const { SubscribeRequest } = liveFeedPb;
type LiveFeedEvent = InstanceType<typeof liveFeedPb.LiveFeedEvent>;
type StationType = commonPb.StationType;
type AlertProto = InstanceType<typeof alertPb.Alert>;

export interface PackagePosition {
  packageId: string;
  station: StationType;
  updatedAtMs: number;
  itemName: string;
  itemCategory: number;
  damageDetected: boolean;
}

export interface AlertItem {
  alertId: string;
  packageId: string;
  alertType: number;
  severity: number;
  station: StationType;
  message: string;
  detectedAtMs: number;
}

export type ConnectionStatus = "connecting" | "open" | "error" | "closed";

const LIVE_FEED_URL = import.meta.env.VITE_LIVE_FEED_URL ?? "http://localhost:8090";
// Cap the alert feed shown in the UI — this is a live view, not the
// system of record (that's the warehouse from Checkpoint 6); an
// unbounded list here would just be a memory leak in the browser tab.
const MAX_ALERTS = 100;
// The protocol has no "package exited the facility" signal, so a
// position we haven't heard about in a while is presumed gone (dispatched
// and out for delivery) rather than tracked forever — this is a kiosk-style
// view meant to stay open for hours/days, so unbounded growth here is a
// real leak, not a theoretical one.
const POSITION_STALE_MS = 30 * 60 * 1000;
const EVICTION_SWEEP_MS = 60 * 1000;

/** Subscribes to LiveFeedService.Subscribe over grpc-web and exposes
 * the current package positions + recent alerts as React state.
 * Reconnects automatically on stream error/close, since a gRPC
 * server-streaming call over grpc-web is not itself resilient to a
 * dropped connection — the browser has to notice and retry. */
export function useLiveFeed() {
  const [positions, setPositions] = useState<Map<string, PackagePosition>>(new Map());
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [status, setStatus] = useState<ConnectionStatus>("connecting");

  useEffect(() => {
    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    let activeStream: ClientReadableStream<LiveFeedEvent> | undefined;

    function connect() {
      if (cancelled) return;
      setStatus("connecting");

      const client = new LiveFeedServiceClient(LIVE_FEED_URL);
      const stream = client.subscribe(new SubscribeRequest(), {});
      activeStream = stream;

      stream.on("data", (event: LiveFeedEvent) => {
        setStatus("open");
        if (event.hasPositionUpdate()) {
          const p = event.getPositionUpdate()!;
          const packageId = p.getPackageId();
          const updatedAt = p.getUpdatedAt();
          setPositions((prev) => {
            const next = new Map(prev);
            next.set(packageId, {
              packageId,
              station: p.getStation(),
              updatedAtMs: updatedAt ? updatedAt.getSeconds() * 1000 + updatedAt.getNanos() / 1e6 : Date.now(),
              itemName: p.getItemName(),
              itemCategory: p.getItemCategory(),
              damageDetected: p.getDamageDetected(),
            });
            return next;
          });
        } else if (event.hasAlert()) {
          const a: AlertProto = event.getAlert()!;
          const detectedAt = a.getDetectedAt();
          const item: AlertItem = {
            alertId: a.getAlertId(),
            packageId: a.getPackageId(),
            alertType: a.getAlertType(),
            severity: a.getSeverity(),
            station: a.getStation(),
            message: a.getMessage(),
            detectedAtMs: detectedAt ? detectedAt.getSeconds() * 1000 + detectedAt.getNanos() / 1e6 : Date.now(),
          };
          setAlerts((prev) => [item, ...prev].slice(0, MAX_ALERTS));
        }
      });

      function scheduleReconnect(nextStatus: ConnectionStatus) {
        if (cancelled) return;
        setStatus(nextStatus);
        // error and end can both fire for the same underlying failure;
        // clearing any pending timer before scheduling a new one keeps
        // this to a single reconnect instead of two overlapping streams.
        if (retryTimer) clearTimeout(retryTimer);
        retryTimer = setTimeout(connect, 2000);
      }

      stream.on("error", () => scheduleReconnect("error"));
      stream.on("end", () => scheduleReconnect("closed"));
    }

    connect();

    const evictionInterval = setInterval(() => {
      const cutoff = Date.now() - POSITION_STALE_MS;
      setPositions((prev) => {
        let changed = false;
        const next = new Map(prev);
        for (const [packageId, position] of prev) {
          if (position.updatedAtMs < cutoff) {
            next.delete(packageId);
            changed = true;
          }
        }
        return changed ? next : prev;
      });
    }, EVICTION_SWEEP_MS);

    return () => {
      cancelled = true;
      if (retryTimer) clearTimeout(retryTimer);
      clearInterval(evictionInterval);
      activeStream?.cancel();
    };
  }, []);

  return { positions, alerts, status };
}
