# Codex desktop and local model deployment

This fork retains the upstream server and adds a compact third-party Codex tool
catalog plus support for the `X-Codex-Local-Gateway` client credential. It uses
native CLIProxyAPI provider routing, Responses translation and Codex OAuth.

The production endpoint is `http://127.0.0.1:18474/v1` and the dashboard is
`http://127.0.0.1:18474/management.html`. The existing Codex provider ID `gw`
is retained so saved chats do not need metadata edits. Model IDs and aliases
remain stable. Cloud and local models have distinct IDs and zero request
retries; there is no configured local-to-paid-cloud fallback.

Instance configuration, OAuth credentials, keys, binaries and logs live under
the checkout's ignored `.local/` directory. Never commit that directory.
Use `providers.example.json` as a starting point for `.local/providers.json`.
Each source can define explicit `routes` with `model`, `id`, `displayName`,
`contextWindow` and optional `aliases`; other models are discovered from its
`/models` endpoint. Source URLs belong in the instance file, not source code.
The deployed instance uses vMLX and oMLX. LM Studio is excluded.

Run with the Node executable bundled with ChatGPT.app:

```sh
node deploy/macos/sync-providers.mjs
python3 deploy/macos/install-service.py
cliproxyctl status
codex-cliproxy
```

`sync-providers.mjs` regenerates `.local/config.production.json` from the live
sources; restart the service after syncing. Discovery is explicit rather than
periodic. Runtime configuration and dashboard edits are regenerated from that
file on service restart; maintain persistent changes in the instance sources
or production configuration. The launcher reads keys directly from `.local`
and publishes the existing Codex client environment variable at startup.
The dashboard uses the separate `.local/management-key`, restricted to localhost.

`codex-gateway` and `codex-gatewayctl` are compatibility symlinks to the new
wrappers. They do not start the retired gateway. `cliproxyctl` supports
`start`, `stop`, `restart` and `status`; there is no legacy rollback route.

Enable `features.code_mode_only_strict_3p_tools = true` in Codex together with
`client.codex.third-party-tool-mode: code_mode_only` in CLIProxyAPI. This prevents
large direct tool schemas from exhausting local model context/memory. Ten-second
SSE keepalives are enabled, including during prefill, without bootstrap retries.
Only configured explicit models advertise large context windows. Model listing
alone does not qualify image/audio input or tool reliability for every model.

```sh
node deploy/macos/smoke-proxy.mjs
```

The smoke test checks authentication, model IDs, invalid-model rejection and
streaming tool calls with non-streaming result replay across the three sources.
It makes synthetic inference requests, including small OpenAI requests against
the configured ChatGPT allowance, and saves `.local/state/smoke-results.json`.

DeviceCheck timeout maintenance is separate from model routing; see
`diagnostics/DEVICECHECK_AUTOPATCH.md`. Its original-module backups are private
under `.local/devicecheck-swap-backups`. Unknown future module implementations
are left untouched. No account tokens or app bundle binaries are published.
