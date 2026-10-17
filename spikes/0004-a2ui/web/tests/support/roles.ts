function implicitRole(element: Element): string | null {
  const explicit = element.getAttribute("role");
  if (explicit) {
    return explicit.split(/\s+/)[0] ?? explicit;
  }
  const tag = element.tagName.toLowerCase();
  if (tag === "button") {
    return "button";
  }
  if (tag === "textarea") {
    return "textbox";
  }
  if (tag === "select") {
    return "combobox";
  }
  if (tag === "a" && element.hasAttribute("href")) {
    return "link";
  }
  if (tag === "table") {
    return "table";
  }
  if (tag === "tr") {
    return "row";
  }
  if (tag === "input") {
    const type = (element.getAttribute("type") || "text").toLowerCase();
    if (type === "hidden") {
      return null;
    }
    if (type === "radio") {
      return "radio";
    }
    if (type === "checkbox") {
      return "checkbox";
    }
    return "textbox";
  }
  return null;
}

function walk(node: Node, visit: (element: Element) => void): void {
  if (node instanceof Element) {
    visit(node);
    if (node.shadowRoot) {
      walk(node.shadowRoot, visit);
    }
  }
  for (const child of node.childNodes) {
    walk(child, visit);
  }
}

export function textOf(node: Node): string {
  if (node instanceof HTMLSlotElement) {
    const assigned = node.assignedNodes({ flatten: true });
    if (assigned.length > 0) {
      return assigned.map((child) => textOf(child)).join("");
    }
  }
  if (node instanceof Element && node.shadowRoot) {
    return textOf(node.shadowRoot);
  }
  let text = "";
  for (const child of node.childNodes) {
    if (child.nodeType === Node.TEXT_NODE) {
      text += child.textContent ?? "";
    } else {
      text += textOf(child);
    }
  }
  return text;
}

export function accessibleName(element: Element): string {
  const labelled = element.getAttribute("aria-label");
  if (labelled) {
    return labelled.trim();
  }
  return textOf(element).replace(/\s+/g, " ").trim();
}

export function queryAllByRole(root: ParentNode, role: string): HTMLElement[] {
  const found: HTMLElement[] = [];
  walk(root, (element) => {
    if (implicitRole(element) === role && element instanceof HTMLElement) {
      found.push(element);
    }
  });
  return found;
}

export function buttonsNamed(root: ParentNode, pattern: RegExp): HTMLElement[] {
  return queryAllByRole(root, "button").filter((element) =>
    pattern.test(accessibleName(element)),
  );
}

export function buttonNamed(root: ParentNode, pattern: RegExp): HTMLElement | undefined {
  const matches = buttonsNamed(root, pattern);
  return matches.find((element) => element.tagName === "BUTTON") ?? matches[0];
}

export function textControls(root: ParentNode): Array<HTMLInputElement | HTMLTextAreaElement> {
  return queryAllByRole(root, "textbox").filter(
    (element): element is HTMLInputElement | HTMLTextAreaElement => {
      if (element instanceof HTMLTextAreaElement) {
        return true;
      }
      if (!(element instanceof HTMLInputElement)) {
        return false;
      }
      const type = (element.getAttribute("type") || "text").toLowerCase();
      return type !== "password" && type !== "date" && type !== "datetime-local" && type !== "hidden";
    },
  );
}

export function dateInputs(root: ParentNode): HTMLInputElement[] {
  const found: HTMLInputElement[] = [];
  walk(root, (element) => {
    if (!(element instanceof HTMLInputElement)) {
      return;
    }
    const type = (element.getAttribute("type") || "").toLowerCase();
    if (type === "date" || type === "datetime-local") {
      found.push(element);
    }
  });
  return found;
}

export function passwordInputs(root: ParentNode): HTMLInputElement[] {
  const found: HTMLInputElement[] = [];
  walk(root, (element) => {
    if (
      element instanceof HTMLInputElement &&
      (element.getAttribute("type") || "").toLowerCase() === "password"
    ) {
      found.push(element);
    }
  });
  return found;
}

export function hrefs(root: ParentNode): string[] {
  const found: string[] = [];
  walk(root, (element) => {
    const href = element.getAttribute("href");
    if (href) {
      found.push(href);
    }
  });
  return found;
}

export function tableElement(root: ParentNode): HTMLElement | undefined {
  return queryAllByRole(root, "table")[0];
}

export function rowCount(root: ParentNode): number {
  return queryAllByRole(root, "row").length;
}

export function typeInto(control: HTMLInputElement | HTMLTextAreaElement, value: string): void {
  const prototype =
    control instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
  const descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
  descriptor?.set?.call(control, value);
  control.dispatchEvent(new Event("input", { bubbles: true, composed: true }));
  control.dispatchEvent(new Event("change", { bubbles: true, composed: true }));
}

export function chooseChoice(root: ParentNode, value: string): void {
  const radio = queryAllByRole(root, "radio").find(
    (element): element is HTMLInputElement =>
      element instanceof HTMLInputElement && element.value === value,
  );
  if (radio) {
    radio.click();
    return;
  }
  const combo = queryAllByRole(root, "combobox").find(
    (element): element is HTMLSelectElement => element instanceof HTMLSelectElement,
  );
  if (!combo) {
    throw new Error(`no choice control for ${value}`);
  }
  combo.value = value;
  combo.dispatchEvent(new Event("input", { bubbles: true, composed: true }));
  combo.dispatchEvent(new Event("change", { bubbles: true, composed: true }));
}

export async function flush(root: ParentNode): Promise<void> {
  for (let pass = 0; pass < 5; pass += 1) {
    await new Promise<void>((resolve) => {
      setTimeout(resolve, 0);
    });
    const pending: Promise<unknown>[] = [];
    walk(root, (element) => {
      const host = element as Element & { updateComplete?: Promise<unknown> };
      if (host.updateComplete) {
        pending.push(host.updateComplete);
      }
    });
    if (pending.length > 0) {
      await Promise.all(pending);
    }
  }
}
