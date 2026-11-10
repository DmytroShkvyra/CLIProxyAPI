# macOS Codex deployment branch

`macos-codex` is the deployed branch of this fork. Its tested upstream base is
the CLIProxyAPI v8.0.57 commit, rather than the latest upstream main branch.
The fork's `main` branch remains available for tracking upstream updates.

The local additions provide the Codex desktop client credential header,
opt-in compact third-party tool metadata, a macOS LaunchAgent deployment,
provider catalog synchronization and separate DeviceCheck timeout maintenance.
See [deployment instructions](deploy/macos/README.md) and
[timeout maintenance](diagnostics/DEVICECHECK_AUTOPATCH.md).

Instance data is intentionally excluded from Git: `.local/` contains credentials,
private provider endpoints, generated configuration, binaries and backups.
No former custom gateway is required by this deployment. The `gw` provider ID
and the client header/environment names remain compatible with existing Codex
chat metadata and desktop credentials.

Updates should be merged from `upstream/main` into this branch, tested, rebuilt
and deployed explicitly. Do not replace the deployed binary with an upstream
release that lacks the compact-tool catalog option without requalification.
