import { useEffect, useRef } from "react";
import { type PairLink, parsePairUri } from "../../client/pairing.ts";

type Detected = { rawValue: string };
type Detector = { detect: (source: HTMLVideoElement) => Promise<Detected[]> };
type DetectorClass = new (options?: { formats: string[] }) => Detector;

const SCAN_MS = 250;

function detectorClass(): DetectorClass | null {
  const value: unknown = Reflect.get(globalThis, "BarcodeDetector");
  return typeof value === "function" ? (value as DetectorClass) : null;
}

/** Whether this browser can scan a QR code with the camera (`BarcodeDetector`). */
export function scannerAvailable(): boolean {
  return detectorClass() !== null;
}

/** Scan a `sevn://pair` QR code with the camera; other QR codes are ignored. */
export function QrScanner({
  onLink,
  onCancel,
  onFail,
}: {
  onLink: (link: PairLink) => void;
  onCancel: () => void;
  onFail: (message: string) => void;
}) {
  const video = useRef<HTMLVideoElement | null>(null);
  const callbacks = useRef({ onLink, onFail });
  callbacks.current = { onLink, onFail };

  useEffect(() => {
    const Detector = detectorClass();
    if (Detector === null || navigator.mediaDevices === undefined) {
      callbacks.current.onFail(
        "This browser cannot use the camera here; enter the short code.",
      );
      return;
    }
    let stream: MediaStream | null = null;
    let timer: ReturnType<typeof setInterval> | undefined;
    let alive = true;
    const detector = new Detector({ formats: ["qr_code"] });
    const stop = (): void => {
      alive = false;
      if (timer !== undefined) {
        clearInterval(timer);
      }
      for (const track of stream?.getTracks() ?? []) {
        track.stop();
      }
    };
    void navigator.mediaDevices
      .getUserMedia({ video: { facingMode: "environment" } })
      .then(async (media) => {
        stream = media;
        const element = video.current;
        if (!alive || element === null) {
          stop();
          return;
        }
        element.srcObject = media;
        await element.play();
        let busy = false;
        timer = setInterval(() => {
          if (busy || !alive) {
            return;
          }
          busy = true;
          void detector
            .detect(element)
            .then((codes) => {
              for (const code of codes) {
                let link: PairLink;
                try {
                  link = parsePairUri(code.rawValue);
                } catch {
                  continue;
                }
                stop();
                callbacks.current.onLink(link);
                return;
              }
            })
            .catch(() => undefined)
            .finally(() => {
              busy = false;
            });
        }, SCAN_MS);
      })
      .catch((error: unknown) => {
        if (alive) {
          stop();
          callbacks.current.onFail(
            `Camera unavailable (${error instanceof Error ? error.message : String(error)}); enter the short code.`,
          );
        }
      });
    return stop;
  }, []);

  return (
    <div className="space-y-2">
      <video
        ref={video}
        muted
        playsInline
        className="w-full max-w-sm rounded bg-black"
      />
      <button
        type="button"
        className="rounded border border-zinc-700 px-3 py-1.5 text-sm"
        onClick={onCancel}
      >
        Stop camera
      </button>
    </div>
  );
}
