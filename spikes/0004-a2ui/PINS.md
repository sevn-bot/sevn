# A2UI pins (W0)

D1: try protocol v0.9.1 first, then the v1.0 candidate, on the same payloads.
There is no `v0.9.1` or `v1.0-rc` git tag. Tags `v0.8` and `v0.9` both point at
`19919ef4c8ad` and predate v0.9.1. Both specs live on `main`.

| | v0.9.1 (current production) | v1.0 (candidate) |
| --- | --- | --- |
| Repo | https://github.com/a2ui-project/a2ui | same |
| Commit | `d1ba35c41f279d59e438ca029660ea62e0dc8f71` (2026-10-16) | same commit |
| Spec | `specification/v0_9_1` (Status: Current Production) | `specification/v1_0` (Status: Candidate) |

## Packages

| Surface | Pin |
| --- | --- |
| Python | `a2ui-core==0.3.0`, tag `python/a2ui-core/v0.3.0` → commit `6175393bc0684a2d92baf66f572196addb04c27b` (2026-10-08). `BasicCatalog` accepts `v0.9.1` and `v1.0`. |
| React | `@a2ui/react@0.13.0` and `@a2ui/web_core@0.13.0` (published 2026-10-09). v0.9 entry is `@a2ui/react/v0_9` and `@a2ui/web_core/v0_9`. |
| Swift | No semver tag. Products `A2UISwiftUI` and `BasicCatalogSwiftUI` from the repo commit above (`Package.swift` at the repo root, `swift-tools-version: 6.1`). |

`@a2ui/react@0.13.0` exports `.`, `./v0_8`, and `./v0_9` only. `@a2ui/web_core@0.13.0` also exports `./v1_0`. The v1.0 React renderer is not a separate entry point in this package.

## Custom component APIs

Paths are relative to `a2ui-project/a2ui` at the commit above.

React (v0.9 family, the path for v0.9.1):

- `typescript/renderers/react/src/adapter.tsx` — `createComponentImplementation`, `createBinderlessComponentImplementation`
- `typescript/renderers/react/src/v0_9/index.ts` — re-exports those and `A2uiSurface`
- `typescript/renderers/react/README.md` — catalog composition: `new Catalog(id, "v0.9", [components], [functions])` from `@a2ui/web_core/v0_9`
- `typescript/core/web_core/src/v0_9/basic_catalog/catalog.ts` — `basicCatalog`
- Unknown type: `typescript/renderers/react/src/node-view.tsx` renders `Unknown component type: <type>` when `node.state === "unknown-type"`
- Legacy v0.8 registry (not the v0.9 path): `typescript/renderers/react/src/v0_8/registry/ComponentRegistry.ts` (`register`)

SwiftUI:

- `swift/swiftui/Sources/A2UISwiftUI/ComponentImplementation.swift` — `ComponentImplementation` (`name`, JSON schema, view builder)
- `swift/core/Sources/A2UICore/Catalogs/Catalog.swift` — `Catalog(id:protocolVersion:components:functions:)`
- `swift/swiftui/Sources/BasicCatalog/BasicCatalogImplementation.swift` — `makeCatalog(version:)` for `.v09` / `.v091` and `.v10`
- `swift/swiftui/Sources/A2UISwiftUI/Surface.swift` — `Surface(viewModel:catalogs:)`
- `swift/swiftui/Sources/A2UISwiftUI/A2UICatalogsKey.swift` — `\.a2uiCatalogs`
- Missing builder: `swift/swiftui/Sources/A2UISwiftUI/ComponentNodeView.swift` `fallbackView` prints a log line and returns `EmptyView()`

Python (payloads and catalog schemas):

- `python/a2ui_core/src/a2ui/core/basic_catalog/__init__.py` — `BasicCatalog(protocol_version)`
- `python/a2ui_core/src/a2ui/core/catalog/catalog.py` — `Catalog`

Basic catalog component names at this pin: Text, Image, Icon, Video, AudioPlayer, Row, Column, List, Card, Tabs, Modal, Divider, Button, TextField, CheckBox, ChoicePicker, Slider, DateTimeInput.
