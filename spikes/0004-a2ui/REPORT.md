# Spike S3 — A2UI on React and SwiftUI

Pin: a2ui `d1ba35c41f279d59e438ca029660ea62e0dc8f71`. Python `a2ui-core==0.3.0`. React `@a2ui/react@0.13.0` and `@a2ui/web_core@0.13.0`. Details are in `PINS.md`.

Version choice for 0040 and 0070: **v0.9.1**. The golden payloads and the dotted sevn component names validate and render on that version. The v1.0 candidate is not a drop-in replacement (`v1_rc_compatible: false`).

## Parity

Screenshots are in `screens/`. Web is the Vite demo (`?payload=`). macOS is an offscreen `NSHostingView`. iOS is the same SwiftUI tree in an iPhone 16 simulator app (`iphonesimulator18.5` SDK, simulator runtime 18.6).

| Payload | Web | macOS | iOS | Notes |
| --- | --- | --- | --- | --- |
| p1-form | yes | yes | yes | Text field, mutually exclusive choice (radio list, not a dropdown), date field, Submit |
| p2-table-update | yes | yes | yes | After the update: Ada 9, Grace 2, Lin 3. The previous qty 1 is gone |
| p3-secret | yes | yes | yes | Label, help, link, masked field, Save securely. The value is not in the payload |
| p4-approval | yes | yes | yes | Approve and Deny are separate actions |
| p5-assist | yes | yes | yes | Action text is exactly `Open Computer panel` |

`ChoicePicker` with `mutuallyExclusive` is a radio list on both renderers. `DateTimeInput` is a date control (`DatePicker` on SwiftUI, a date input on the web). `Table` is not in the basic catalog; both spike renderers register it.

## Custom components

Names in the payloads stay `sevn.SecretField`, `sevn.ApprovalCard`, and `sevn.AssistCard` (D4).

React (`@a2ui/react/v0_9` `createComponentImplementation`, catalog composed onto `basicCatalog`): dotted names register directly. `SecretField` is `<input type="password" autocomplete="off">`. The typed value goes only to `onSecret`. The action data is exactly `{secret_submitted: true, name}`. The log line is `«redacted»`. Unknown types that are not in the catalog are rendered by the spike as `Unsupported: <name>` (the stock node view would say `Unknown component type: <name>`).

SwiftUI (`ComponentImplementation` on a catalog built from `BasicCatalogImplementation.makeCatalog(version: .v09)`): the processor rejects `.` in a component type. `UnicodeIdentifierValidator.isValidIdentifier` is UAX #31, and `PayloadValidator` applies it to every component type, not only when identifier enforcement is on. The spike rewrites the three sevn names to `sevn_SecretField`, `sevn_ApprovalCard`, and `sevn_AssistCard` before `processMessages`. Any other dotted name is removed from the component batch and recorded as `Unsupported: <name>`. The stock `ComponentNodeView.fallbackView` is `EmptyView()`, so the text fallback is the spike's, not A2UI's. `SecretField` uses `SecureField`. The value is handed to `onSecret` and is absent from the data model, the action JSON, and the log.

`Table` is registered on both sides. Its `rows` property is a path binding. The row identity used by the tests is the component id (`root`), which stays the same across `updateDataModel`.

## Incremental updates

p2 sends a later `updateDataModel` that changes Ada's qty from 1 to 9 and appends Lin. On React the same table DOM node stays mounted and the rows become Ada 9 / Grace 2 / Lin 3. On SwiftUI the table control id is unchanged, the row count grows, the hierarchy contains `9`, and it does not contain the replaced `1`. Neither path rebuilds the surface from scratch.

## v1.0 candidate

Re-ran the golden payloads against Python `BasicCatalog("v1.0")` and `@a2ui/web_core/v1_0` `MessageProcessor` + `basicCatalog` + strict validation. `@a2ui/react@0.13.0` has no `./v1_0` entry (`./`, `./v0_8`, `./v0_9` only).

Unchanged payloads, only the real v1 catalog registered:

- every payload fails with `Catalog not found: https://a2ui.org/specification/v0_9/catalogs/basic/catalog.json`

The v1 basic catalog id is `https://a2ui.org/specification/v1_0/catalogs/basic/catalog.json` (18 components, no `Table`).

After rewriting `version` to `v1.0`, `catalogId` to the v1 id, and binding keys `path` to `@path`:

- p1 fails because `submit-label` is not a UAX #31 identifier
- p2 fails with `Unrecognized component type 'Table'`
- p3, p4, and p5 fail with `Unrecognized component type 'sevn.SecretField'` (and the other sevn names)

p1 passes on Python v1 only after a further rewrite (`submit-label` → `submitLabel`, text variant `h5` → `body`). `Catalog.from_json` of `sevn_catalog.json` succeeds at `v0.9` and `v0.9.1` and raises `Invalid UAX #31 component identifier: 'sevn.SecretField'` at `v1.0`.

Swift was not executed as a second v1 process. At the pinned commit, `PayloadValidator` rejects a non-identifier component type before catalog lookup (`Invalid component identifier`), and that check is not gated by `enforceIdentifiers`. Dots and hyphens fail `isValidIdentifier`. That is the same rule as the Python v1 catalog error. v1 bindings use `@path`.

## Catalog and `ui.action` for 0040

Stay on protocol **v0.9.1** and the basic catalog, plus the spec §6 components: ApprovalCard, FileCard, BotPicker, Chart, Table, SecretField, SignInCard, AssistCard. This spike implemented SecretField, ApprovalCard, AssistCard, and Table. The other four are not in the basic catalog and were not built here.

`ui.action` shape (D3), same on web and SwiftUI:

```json
{"surface_id": "<id>", "action": "<name>", "data": {}}
```

For SecretField, `data` is exactly `{"secret_submitted": true, "name": "<name>"}`. The secret value never enters the A2UI data model. The host callback is `onSecret(name, value)`; the spike log stores `«redacted»`.

## Risks

- v1 cannot carry the dotted sevn names or hyphenated ids without a rename. A v1 move means new payloads, a new catalog id, `@path` bindings, and aliases or undotted component names on Swift and in the catalog schema.
- Swift's stock unknown-component view is empty. 0040 needs its own fallback if `Unsupported: <name>` is required.
- `ChoicePicker` is not a menu. A compact select, if 0040 wants one, is a different component or variant.
- Spec §6.1 also describes a paste button and saved / replace / remove states. Those belong to the secret store in 0040, not this renderer spike.
- The iOS Simulator hangs in `open()` on a regular file under `~/Documents`. The `A2UISpike` scheme's test pre-action symlinks the payload JSON files to `/tmp/sevn-a2ui-payloads` for the test and restores them afterwards. `swift test` on macOS reads the files directly and does not need that.
- Screenshot capture on iOS needs a real app bundle (a bare executable has no bundle id and UIKit traps). The shot helper is a development tool, not a product surface.
