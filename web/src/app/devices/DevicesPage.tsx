import { DevicesList } from "./DevicesList.tsx";
import { PairingCard } from "./PairingCard.tsx";

/** Settings → Devices on the host that serves this page (plan 0055 D9). */
export function DevicesPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-lg font-medium">Settings → Devices</h1>
      <PairingCard />
      <DevicesList />
    </div>
  );
}
