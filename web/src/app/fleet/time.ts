const minute = 60_000;
const hour = 60 * minute;
const day = 24 * hour;

export const staleAfterMs = day;

/** "5m", "3h", "2d" between ``fromIso`` and ``toIso``. Under a minute is "<1m". */
export function age(fromIso: string, toIso: string): string {
  const elapsed = Math.max(Date.parse(toIso) - Date.parse(fromIso), 0);
  if (elapsed < minute) {
    return "<1m";
  }
  if (elapsed < hour) {
    return `${Math.floor(elapsed / minute)}m`;
  }
  if (elapsed < day) {
    return `${Math.floor(elapsed / hour)}h`;
  }
  return `${Math.floor(elapsed / day)}d`;
}

export function olderThan(
  fromIso: string,
  toIso: string,
  limitMs: number,
): boolean {
  return Date.parse(toIso) - Date.parse(fromIso) > limitMs;
}

/** Local "HH:MM". */
export function clock(iso: string): string {
  const when = new Date(iso);
  const hours = String(when.getHours()).padStart(2, "0");
  const minutes = String(when.getMinutes()).padStart(2, "0");
  return `${hours}:${minutes}`;
}

/** "HH:MM" today, otherwise "Oct 29 HH:MM". */
export function stamp(iso: string, nowIso: string): string {
  const when = new Date(iso);
  const now = new Date(nowIso);
  if (when.toDateString() === now.toDateString()) {
    return clock(iso);
  }
  const date = when.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
  return `${date} ${clock(iso)}`;
}

/** "due in 3h" or "overdue 2h", measured from ``nowIso``. */
export function dueLabel(dueIso: string, nowIso: string): string {
  if (Date.parse(dueIso) >= Date.parse(nowIso)) {
    return `due in ${age(nowIso, dueIso)}`;
  }
  return `overdue ${age(dueIso, nowIso)}`;
}
