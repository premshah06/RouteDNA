---
description: Use when wiring a browser/React frontend to a Python (or any) gRPC service via grpc-web + Envoy — covers the protoc-gen-js CommonJS/ESM interop failure modes, how to package generated stubs so Vite's bundler actually handles them, and a working Envoy proxy config. Reach for this whenever a grpc-web client throws "does not provide an export named X" or "require is not defined" in the browser console, or when scaffolding a new Envoy grpc-web listener.
---

# grpc-web frontend integration

Browsers cannot speak native gRPC — they can't read HTTP/2 trailers,
which gRPC's status/trailer-based framing depends on. Something must
sit in front of any gRPC service a browser calls directly, translating
grpc-web wire format to native gRPC. That's Envoy's job here. The
harder, less obvious problem is getting `protoc-gen-js`'s generated
JavaScript to actually load in a modern (Vite/esbuild/native-ESM) dev
server — this skill exists because that took three sequential failed
fixes before landing on the right one.

## The Envoy side (mechanical, gets it right the first time)

```yaml
static_resources:
  listeners:
    - name: grpc_web_listener
      address:
        socket_address: { address: 0.0.0.0, port_value: 8080 }
      filter_chains:
        - filters:
            - name: envoy.filters.network.http_connection_manager
              typed_config:
                "@type": type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager
                stat_prefix: ingress_http
                codec_type: AUTO
                route_config:
                  name: local_route
                  virtual_hosts:
                    - name: my_service
                      domains: ["*"]
                      cors:
                        allow_origin_string_match:
                          - prefix: "*"  # dev only — see gotcha below
                        allow_methods: GET, PUT, DELETE, POST, OPTIONS
                        allow_headers: keep-alive,user-agent,cache-control,content-type,content-transfer-encoding,x-accept-content-transfer-encoding,x-accept-response-streaming,x-user-agent,x-grpc-web,grpc-timeout
                        max_age: "1728000"
                        expose_headers: grpc-status,grpc-message
                      routes:
                        - match: { prefix: "/" }
                          route:
                            cluster: my_grpc_service
                            timeout: 0s
                            max_grpc_timeout: 0s
                # Filter order matters: grpc_web must run before router
                # (to translate the request), cors must run before router
                # too (to short-circuit preflight OPTIONS).
                http_filters:
                  - name: envoy.filters.http.grpc_web
                    typed_config:
                      "@type": type.googleapis.com/envoy.extensions.filters.http.grpc_web.v3.GrpcWeb
                  - name: envoy.filters.http.cors
                    typed_config:
                      "@type": type.googleapis.com/envoy.extensions.filters.http.cors.v3.Cors
                  - name: envoy.filters.http.router
                    typed_config:
                      "@type": type.googleapis.com/envoy.extensions.filters.http.router.v3.Router
  clusters:
    - name: my_grpc_service
      connect_timeout: 5s
      type: STRICT_DNS
      lb_policy: ROUND_ROBIN
      typed_extension_protocol_options:
        # Required for talking native gRPC (HTTP/2) upstream.
        envoy.extensions.upstreams.http.v3.HttpProtocolOptions:
          "@type": type.googleapis.com/envoy.extensions.upstreams.http.v3.HttpProtocolOptions
          explicit_http_config:
            http2_protocol_options: {}
      load_assignment:
        cluster_name: my_grpc_service
        endpoints:
          - lb_endpoints:
              - endpoint:
                  address:
                    socket_address: { address: my-grpc-service, port_value: 50051 }
```

**Gotcha — CORS wildcard**: `allow_origin_string_match: prefix: "*"`
combined with an unauthenticated RPC is an open read API. Fine for a
local dev box where the frontend origin varies by port; before this
proxy is reachable from anywhere else, replace it with an `exact`
match per known frontend origin and leave a `# TODO(prod)` comment so
it isn't silently carried into a real deployment.

## The frontend side (the actual hard part)

Generate with:
```bash
protoc --proto_path=proto --proto_path="$WKT_DIR" \
  --js_out=import_style=commonjs,binary:"$GEN_DIR" \
  --grpc-web_out=import_style=typescript,mode=grpcwebtext:"$GEN_DIR" \
  proto/**/*.proto google/protobuf/timestamp.proto
```

This produces two kinds of generated files with two different problems:

**1. `*_pb.js` (protoc-gen-js, CommonJS, dynamic exports).**
These files call `goog.object.extend(exports, proto.mypackage.v1)` at
runtime to populate their exports, not `exports.Foo = ...` static
assignments. No bundler's CJS→ESM interop — Vite's, webpack's,
anyone's — can statically discover a dynamically-assigned export ahead
of time, because there's nothing to discover until the code actually
runs. Concretely:

```ts
// BREAKS at runtime: "does not provide an export named 'Alert'"
import { Alert } from "./gen/alert_pb";

// CORRECT: namespace import, then destructure at runtime
import * as alertPb from "./gen/alert_pb";
const { Alert } = alertPb;
```

This is the fix, not a workaround — there is no static-import form
that works here, ever, regardless of bundler config.

**2. The remaining problem after namespace imports: `require is not
defined`.** The generated `.js` files also contain literal top-level
`require()` calls (an artifact of `import_style=commonjs`). Native
browser ESM has no `require`. Fixing the import *style* (step 1)
doesn't fix this — it's a separate transformation problem: the file
itself needs to go through a real CJS→ESM conversion, which only
happens for things a bundler's dependency optimizer actually processes.

**The fix that works**: package the generated stubs as a real local
npm dependency, not raw files under `src/`.

```
frontend/proto-gen/           # sibling to src/, NOT inside it
  package.json                # { "name": "@myapp/proto-gen", ... }
  mypackage/v1/*_pb.js
  mypackage/v1/*ServiceClientPb.ts
```//
```bash
npm install ./proto-gen   # creates node_modules/@myapp/proto-gen symlink
```

Why this matters: Vite's CJS interop (via esbuild prebundling) only
reliably triggers for things it treats as genuine dependencies —
`node_modules` entries discovered by its dependency crawler. Arbitrary
files under `src/` never get this treatment no matter what plugins you
install (`@originjs/vite-plugin-commonjs` and similar only govern which
*dependencies* get transformed, not arbitrary source files — confirm
this by reading the plugin's own `include`/`exclude` docs before
reaching for it).

Update imports to package-style:
```ts
import * as alertPb from "@myapp/proto-gen/mypackage/v1/alert_pb";
```

**The crawler still won't catch everything.** Vite's dependency
crawler statically scans your source for bare-specifier imports to
decide what to prebundle. Two things defeat it:

- **Deep sub-path imports with no `package.json` "exports" map** —
  the crawler may simply not discover `@myapp/proto-gen/mypackage/v1/foo_pb`
  as a distinct entry.
- **Relative imports *inside* the generated package itself.** The
  `*ServiceClientPb.ts` file protoc-gen-grpc-web generates imports its
  sibling `_pb.js` file with a *relative* path
  (`'../../mypackage/v1/foo_pb'`), not a bare specifier — Vite's
  crawler doesn't rewrite relative imports to route through the
  optimizer, so this relative import reaches the raw CJS file directly
  under native ESM, bypassing the prebundle even though the parent
  package is correctly installed.

Fix: force every one of these explicitly in `vite.config.ts`,
including the client-stub `.ts` file itself (not just the `_pb.js`
files it transitively imports):

```ts
export default defineConfig({
  optimizeDeps: {
    include: [
      '@myapp/proto-gen/mypackage/v1/common_pb',
      '@myapp/proto-gen/mypackage/v1/alert_pb',
      // The .ts client stub — needed because ITS relative import of
      // alert_pb.js won't be caught by the crawler on its own.
      '@myapp/proto-gen/mypackage/v1/MyServiceServiceClientPb',
    ],
  },
})
```

After any change here: `rm -rf node_modules/.vite` (clear the stale
prebundle cache) before restarting the dev server, or the fix won't
visibly apply.

## Verifying it actually worked

Don't trust "the page loads with no console errors" — a server-
streaming gRPC connection can leave the page in a state where
`--dump-dom`-style headless checks hang forever waiting for network
idle (which a live stream never reaches). Use the Chrome DevTools
Protocol directly instead of `--dump-dom`/`--screenshot`:

```bash
google-chrome --headless=new --disable-gpu --no-sandbox \
  --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-cdp-profile \
  "http://localhost:5173" &
sleep 4
curl -s http://localhost:9222/json | python3 -c "
import json,sys
for t in json.load(sys.stdin):
    if t.get('type') == 'page': print(t['webSocketDebuggerUrl'])
"
```

Then drive `Runtime.evaluate` / `Page.captureScreenshot` over that
websocket (Node 24+ has native `WebSocket`, no `ws` package needed) to
pull real DOM content and a real screenshot without blocking on
network idle.
