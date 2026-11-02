import { useMemo } from "react";
import { encode } from "uqr";

/** A QR code as inline SVG (no data: URL, so the page CSP needs nothing extra). */
export function QrCode({ value, label }: { value: string; label: string }) {
  const { size, path } = useMemo(() => {
    const qr = encode(value, { ecc: "M", border: 2 });
    const parts: string[] = [];
    qr.data.forEach((row, y) => {
      row.forEach((dark, x) => {
        if (dark) {
          parts.push(`M${x} ${y}h1v1h-1z`);
        }
      });
    });
    return { size: qr.size, path: parts.join("") };
  }, [value]);
  return (
    <svg
      role="img"
      aria-label={label}
      viewBox={`0 0 ${size} ${size}`}
      className="h-56 w-56 rounded bg-white"
      shapeRendering="crispEdges"
    >
      <rect width={size} height={size} fill="#fff" />
      <path d={path} fill="#000" />
    </svg>
  );
}
