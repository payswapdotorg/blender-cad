# ZCode Runtime Compatibility Spike — M1 Evidence

- **Status:** Complete — M1 spike evidence (real install/build/run against the exact pinned tree; TP-CAT-11 companion to the drift check)
- **Owner:** W3 (Agent & skills); recorded for the TL and the M5-entry audit
- **Date:** 2026-10-19 (UTC)
- **Vocabulary:** [docs/GLOSSARY.md](../GLOSSARY.md) (binding)
- **Decisions cited:** [ADR-0004](../30-process/adr/0004-zcode-runtime-interface-first.md) (interface-first sidecar; `packages/rpc` seam), [ADR-0007](../30-process/adr/0007-zcode-fork-realignment.md) (pinned mirror; runtime source of truth = upstream pin)

## 1. Pin identity facts

All commands run in the pinned worktree `/home/z/zcode-pin-wt` (git worktree of
`/home/z/zcode-fork`, remote `origin = payswapdotorg/ZCode`, `upstream = zai-org/ZCode`).

| Fact | Value | Command |
|---|---|---|
| HEAD | `0a1fc56d279fd1001f78387bd81aec1c26767411` | `git rev-parse HEAD` |
| Tag at HEAD | `upstream-pin-0a1fc56` (annotated, immutable per ADR-0007) | `git describe --tags` |
| HEAD commit | `0a1fc56d chore: sync ZCode source` (parent: `aac47556 feat: update to v3.15.1`) | `git log --oneline -2` |
| Fork `main` | `0a1fc56d27…` — **identical to upstream main** | `git rev-parse origin/main upstream/main` |
| `origin/cad-adaptation` | `0a1fc56d27…` — branch at the pin, patch series empty (ADR-0007 §Decision 4) | `git rev-parse origin/cad-adaptation` |
| `origin/gen/archive` | `c3cc34f1d01a059517f13d3dea962c48e49fe309` — legacy program preserved, never a build input | `git rev-parse origin/gen/archive` |
| Worktree registration | `/home/z/zcode-pin-wt  0a1fc56d (detached HEAD)` under `/home/z/zcode-fork` | `git worktree list` |
| Tree size | 18,238 tracked files, 242 MB working tree (pre-install; 277 MB after the build added ~35 MB of `dist/` artifacts) | `git ls-files \| wc -l`, `du -sh --exclude=node_modules .` |

Tree facts (all CONFIRMED present at the pin):

- `apps/zcode-cli`, `apps/dev-docs`
- `packages/`: `client`, `desktop`, `e2e-report`, `formal-proof`, `model-option-map`,
  `provider`, `provider-node`, `rpc`, `server`, `services`, `share-ui`, `shared`,
  `stream-animate`, `ui`, `web`, `web-share`, `zcode-cua`, `zcode-server-cli`
- `.agents/skills/` (11 skills incl. `agent-browser`) + `skills-lock.json` (version 1, github-sourced skills with computed hashes)
- Root `package.json`: `"version": "3.16.1"`, `"packageManager": "pnpm@10.33.2"`, `"engines": {"node": ">=24.0.0"}`
- Workspace file: `pnpm-workspace.yaml` — packages `apps/dev-docs`, `packages/*`, `apps/zcode-cli{,/packages/*,/tools/*}`; `supportedArchitectures` (os/cpu/libc matrix); `allowBuilds` allowlist for native postinstalls (`node-pty`, `electron`, `koffi`, `ssh2` via transitive, `esbuild`, …)
- `.npmrc`: `node-linker=hoisted`, `registry=https://registry.npmjs.org`
- `pnpm-lock.yaml` present at root and **unmodified by the spike** (`git status --porcelain pnpm-lock.yaml` empty; the tree also carries a tracked upstream `package-lock.json` — informational, not used: `packageManager` says pnpm and the spike installed through corepack pnpm only)

## 2. Entry-point inventory (adaptation plan §4.1 — confirmed/adjusted)

| Upstream package | Plan decision | Spike finding | Status |
|---|---|---|---|
| `apps/zcode-cli` | reuse-as-is (reference only) | Present; not built in this spike (out of the server-cli filter scope). | present, unexercised |
| `packages/server` | fork-with-patches (sidecar core) | `src/entry-http.ts` (binds host/port via hono), **`src/entry-stdio.ts`** (stdin/stdout RPC: sends `zcode-hello` frame on stdout, all logs redirected to stderr, `--version` exits 0 — sidecar-shaped), `src/remote/` (remote connection handshake), `src/source-server/`. Heavy deps (`node-pty`, `ssh2`, `undici`, `axios`, …). | confirmed, source-audited; built only as bundled `server-core` (below) |
| `packages/zcode-server-cli` | wrap (sidecar launcher entrypoint) | **CONFIRMED as launcher.** `bin: {"zcode": "./dist/server-cli.js"}`; tsup builds `server-cli.js` (1,570,862 B) + `server-core.js` (9,043,727 B); commands: `serve`, `status`, `stop`, `restart`, `running-tasks`, `update`, `uninstall`, `version`/`--version`, `proxy-stdio`/`server proxy-stdio`, `migrate retry` (all confirmed in `src/cli.ts:98-201`); unknown commands delegate to a legacy agent CLI if bundled. | **CONFIRMED — built + run headless (§4)** |
| `packages/rpc` | fork-with-patches (the seam) | **CONFIRMED.** tsc build clean; see §3. | **CONFIRMED — built** |
| `packages/provider`, `provider-node`, `model-option-map` | reuse-as-is / wrap | Present; installed as part of the server-cli closure (via `@zcode/services`), not exercised at runtime in this spike. | present, installed, unexercised |
| `packages/services` | wrap | Present; bundled into `dist/server-cli.js` by tsup (`noExternal: ["@zcode/shared","@zcode/rpc","@zcode/services"]`). | present, bundled |
| `packages/zcode-cua` | wrap + permission-gate | Present; installed as a `@zcode/services` dependency (its closure is what makes the scoped install large — +2505 packages, incl. browser tooling). | present, installed, unexercised |
| `packages/client`, `packages/shared` | wrap / reuse-as-is | Present in the closure. `@zcode/shared` carries the `zcode-hello`/`helloAck` zod schemas (`packages/shared/src/handshake.ts`) + `ZCODE_VERSION`. | present, bundled |
| `.agents/skills` + `skills-lock.json` | reference (conventions) | Present (see §1). | present |
| UI/infra excludes (`web`, `ui`, `web-share`, `share-ui`, `desktop`, `android`, `formal-proof`, `stream-animate`, `e2e-report`) | exclude | Present in the tree; NOT installed under the scoped filter — consistent with the no-UI-merge rule. | excluded in practice |

## 3. RPC seam surface (`packages/rpc` — the ADR-0004 seam)

16 source files under `packages/rpc/src`, exported through a single barrel
(`src/index.ts`) in 7 documented layers (0–6). Build: `pnpm --filter @zcode/rpc build`
(`tsc`) → exit 0, emits `dist/*.js` + `*.d.ts` + maps. Key exported names:

| Layer | Exported surface (names) |
|---|---|
| 0 — infrastructure | `IDisposable`, `toDisposable`, `DisposableStore`, `Event` (ns: `once`, `filter`, `map`, `toPromise`), `Emitter`, `Relay`, `EventMultiplexer`, `CancellationToken`, `CancellationTokenSource`, `VSBuffer` |
| 1 — serialization | `IReader`, `IWriter`, `BufferReader`, `BufferWriter`, `serialize`, `deserialize` (VQL + type tags) |
| 2 — protocol | `IMessagePassingProtocol`, `ISocket`, `ChunkStream`, `SocketProtocol`, `ProtocolMessageType`, `ProtocolMessage`, `MessagePortProtocol`, `createQueuePair`, `PersistentProtocol` |
| 3 — channel RPC | `IChannel`, `IServerChannel`, `IChannelServer`, `IChannelClient`, `ChannelServer`, `ChannelClient`, `getDelayedChannel`, `RequestType`/`ResponseType`/`IRawResponse` (via `channels.shared`) |
| 4 — connection mgmt | `ClientConnectionEvent`, `Client`, `IConnectionHub`, `IClientRouter`, `IPCServer`, `IPCClient`, `StaticRouter` |
| 5 — service proxy | `ProxyChannel` (`fromService` / `toService` — typed service ↔ channel bridging) |
| 6 — remote | `RemoteConnectionType`, `WebSocketRemoteConnection`, `ManagedRemoteConnection`, `RemoteConnection`, `ResolvedAuthority`, `IRemoteAuthorityResolver`, `RemoteAuthorityResolverService`, `ISocketFactory`, `RemoteSocketFactoryService`, `IURITransformer`, `createURITransformer`, `RemoteAgentConnection`, `RemoteConnectionState` |
| middleware | `RPCLogger`, `LoggingChannelServer`, `LoggingChannelClient`, `NetworkTelemetry{Sink,ChannelServer,ChannelClient}`, `setNetworkTelemetrySink`, `emitNetworkTelemetryObservation` |

Assessment for ADR-0004: the seam is exactly what the plan assumed — a VS Code-style
IPC framework where a typed service can be exposed over a channel via
`ProxyChannel.fromService` and consumed via `toService`, over stdio (`PersistentProtocol`
on `process.stdin/stdout`) or sockets. `agent-runtime-interface/v1` can be carried as a
new service registration through this seam with no upstream breakage.

## 4. Install / build / run evidence (the core compatibility record)

Environment: Node v24.21.0, corepack 0.36.0, pnpm activated via
`COREPACK_ENABLE_DOWNLOAD_PROMPT=0 corepack pnpm …` (pnpm **10.33.2** per `packageManager`).
Sandbox: 2 cores / 3 GB RAM / 5.8 GB free disk, registry.npmjs.org reachable (HTTP 200).

| # | Command (scoped to the server-cli closure) | Exit | Duration | Notes |
|---|---|---|---|---|
| 0 | `corepack pnpm --version` | 0 | ~15 s (activation/download) | `10.33.2` |
| 1 | `corepack pnpm install --filter @zcode/server-cli... --reporter=append-only` | **1** | 54 s (14:14:13Z→14:15:07Z) | Scope **8 of 53** workspace projects, **+2505** packages, lockfile up-to-date (resolution skipped). All dependency postinstalls that ran **succeeded** (e.g. ssh2 optional crypto binding compiled via node-gyp/make). Failed ONLY at the root `prepare` script: `husky && pnpm build:cua` → `sh: 1: pnpm: not found` (`ELIFECYCLE`). |
| 2 | `corepack pnpm install --filter @zcode/server-cli... --ignore-scripts --reporter=append-only` | **0** | 16 s (pnpm: "Done in 7.8s") | Same closure, scripts skipped. **Scoped install SUCCEEDS.** `--ignore-scripts` cost: no native postinstall products (ssh2 falls back to pure-JS crypto; node-pty uses `@lydell` prebuilds resolved at runtime). |
| 3 | `corepack pnpm --filter @zcode/server-cli build` (tsup) | **0** | ~4 s (tsup: 2304 ms) | `dist/server-cli.js` 1,570,862 B (1.50 MiB) + `dist/server-core.js` 9,043,727 B (8.61 MiB) (+ sourcemaps; byte sizes re-verified by re-run). Workspace deps bundled via `noExternal`; native/heavy deps left external. |
| 4 | `corepack pnpm --filter @zcode/rpc build` (tsc) | **0** | ~2 s | `dist/` with `.js`, `.d.ts`, `.map` per module. |
| 5 | `node packages/zcode-server-cli/dist/server-cli.js --version` | **0** | <1 s | stdout `3.16.1`, stderr empty. |
| 6 | `node packages/zcode-server-cli/dist/server-cli.js version` | **0** | <1 s | stdout `3.16.1`. |
| 7 | `node packages/zcode-server-cli/dist/server-cli.js version --json` | **0** | <1 s | stdout `{"product":"zcode-server","version":"3.16.1"}`. |
| 8 | `node packages/zcode-server-cli/dist/server-cli.js status` | **0** | <1 s | Structured status with no server running: `{"protocolVersion":1,"state":"stopped","pid":null,"port":null,"host":null,"version":"3.16.1",…}` — graceful, no crash, no files created. |
| 9 | `node packages/zcode-server-cli/dist/server-cli.js definitely-not-a-command` | **1** | <1 s | stdout `Unknown command: definitely-not-a-command`, stderr empty — clean rejection. |

`serve` (port-binding server start) was deliberately NOT run — not required at M1
(mission rule); the spike proves the pinned tree installs, builds, and its entry point
executes headlessly.

Honest notes:

- Engine warning during install: `apps/zcode-cli WARN Unsupported engine: wanted
  {"node":"24.14.0"} (current 24.21.0)` — warning only; root `engines` wants `>=24.0.0`.
- The root `prepare` (`husky && pnpm build:cua`) is a dev-checkout convenience; it is
  not needed to build/run the server-cli, and the package's own `stage` script exists
  for release packaging. In a fuller environment the fix is a global pnpm shim
  (`corepack enable`) or `--ignore-scripts` for scoped installs — recorded, not worked
  around by lockfile edits (lockfile untouched throughout).
- The +2505-package closure is dominated by `@zcode/zcode-cua` (browser/computer-use
  tooling) pulled in by `@zcode/services`. M5 packaging should apply the §4.3
  excluded-packages boundary check to trim it; the spike installed it unmodified.

## 5. Security-relevant observations

1. **Startup wiring (`packages/zcode-server-cli/src/runtime/agentWiring.ts`,
   `resolveBundledAgentWiring(entryDir, env)`):** before parsing commands, the CLI
   checks for a `zcode.cjs` bundle next to `dist/server-cli.js`; if present it
   injects `ZCODE_AGENT_SERVER_COMMAND=<node> <dir>/zcode.cjs app-server --stdio` +
   `ZCODE_AGENT_SERVER_ARGS_JSON`. An explicit `ZCODE_AGENT_SERVER_COMMAND` in the
   environment **always wins** (checked FIRST — the bundled wiring is skipped) — a
   clean host-control point for the M5 sidecar. (Source lines re-verified at the pin.)
2. **Filesystem assumptions:** data root = `$ZCODE_DATA_BASE_DIR` or
   `~/.zcode/server` (`runtime/paths.ts`); `status`/`version` runs created **no**
   files. Lifecycle commands take locks (`DataRootLock`) under that root. Uninstall
   paths are guarded (`outside-server-root` / `home-directory` / `non-absolute`
   rejection reasons are first-class) — good hygiene to keep in the fork.
3. **Network:** `serve` binds a host/port (hono; `serverStatusSchema.port/host`).
   The stdio entry (`packages/server/src/entry-stdio.ts`) is port-free: stdout is
   reserved for RPC frames, all console logging is redirected to stderr, and the
   first frame is a typed `zcode-hello` handshake (schema in
   `packages/shared/src/handshake.ts`, acked with `helloAckMessageSchema`).
   `proxy-stdio` on the CLI exposes the same stdio path without a listener.
4. **Native code in the closure:** `node-pty` (via `@lydell` prebuilds), `ssh2`
   (optional C++ crypto binding — builds with a working node-gyp/make toolchain),
   `koffi` (allowlisted in `allowBuilds`), `yauzl/yazl`. M5 audit must record these
   as the sidecar's native surface (ADR-0004 checklist item c).
5. **Lockfile discipline held:** `pnpm-lock.yaml` used as-is ("Lockfile is up to
   date, resolution step is skipped") — the spike did not modify any pinned
   dependency resolution.

## 6. Verdict

- **The pinned tree installs, builds, and its launcher entry point executes at the
  exact pin** — scoped to `@zcode/server-cli` (8 workspace projects), exit 0 at every
  stage that matters (install with `--ignore-scripts`, tsup build, tsc build of the
  rpc seam, headless `version`/`status` runs). Confidence: **high** (direct commands +
  exit codes recorded above; environment limits: 2-core/3 GB sandbox, single run each).
- **M5 sidecar entry points (recommended, subject to the M5-entry source audit):**
  1. `packages/zcode-server-cli` (`bin zcode` → `dist/server-cli.js`) as the launcher
     surface — plan §4.1 "wrap" decision CONFIRMED.
  2. `packages/rpc` as the control-channel seam — plan §2 "control: JSON-RPC 2.0 over
     stdio" maps directly onto `IPCServer/IPCClient` + `PersistentProtocol` over
     stdio; `agent-runtime-interface/v1` rides as a typed service via `ProxyChannel`.
  3. `packages/server/src/entry-stdio.ts` (+ `proxy-stdio` on the CLI) as the
     port-free server mode — already speaks a hello/ack handshake over stdio; preferred
     over the port-binding `serve` mode for the in-app sidecar (no sockets per plan §3
     option B).
- **Blockers: none at spike level.** Watch items for M5: (a) root `prepare` script
  expects a `pnpm` shim (use `--ignore-scripts` for scoped installs or enable corepack
  shims); (b) trim the zcode-cua closure via the excluded-packages build check; (c)
  node engine floor 24.x (`apps/zcode-cli` wants exactly 24.14.0 — currently a warning);
  (d) native modules listed in §5.4 need an audit record.
- Failures recorded honestly: attempt #1 (plain install) failed at the root
  `prepare` script (`pnpm: not found`) after all dependency install scripts had already
  succeeded — evidence, not a blocker; attempt #2 with `--ignore-scripts` succeeded.
