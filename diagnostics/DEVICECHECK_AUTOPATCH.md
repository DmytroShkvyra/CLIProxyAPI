# DeviceCheck timeout maintenance

The per-user LaunchAgent `local.codex.devicecheck-autopatch` checks the installed
`/Applications/ChatGPT.app` every 15 seconds, at login and after bundle changes.
Source code stays in this project. No root service, account tokens, gateway
routes or security settings are changed.

Updates can replace the patched native module. The watcher locates the original
one-second timeout in the ARM64 executable text section, verifies the calls to
`generateTokenWithCompletionHandler:`, `dispatch_time` and
`dispatch_semaphore_wait`, and requires exactly one matching implementation.
Offsets may change. The original module must carry a valid OpenAI signature.
An unknown architecture, changed implementation or ambiguous match is left
untouched and recorded as an error. This cannot guarantee compatibility with
every future app release.

The watcher never terminates ChatGPT/Codex. It waits for the app to be closed
and unchanged across two checks before installing the ten-second timeout.
After an update that immediately relaunches the app, fully quit it with Cmd-Q
and leave it closed for about 30 seconds before opening again. There is no
recurring manual patch command. An already patched module is left untouched.
The install rechecks app state, version and original hash immediately before
the atomic file replacement; there remains a small launch/update race, so do
not manually reopen while installation is underway.

Original modules and rollback manifests are saved under the project's
`.local/devicecheck-swap-backups`. The patch retains genuine token generation
and changes only the two timeout instructions, followed by an ad-hoc module
signature. As with manual installation, this invalidates the bundle signature.
Future updates may restore both the signature and the one-second timeout.

The service is installed for the logged-in user; run these without sudo:

```sh
python3 '/path/to/CLIProxyAPI/diagnostics/devicecheck-autopatch.py' status
python3 '/path/to/CLIProxyAPI/diagnostics/devicecheck-autopatch.py' disable
python3 '/path/to/CLIProxyAPI/diagnostics/devicecheck-autopatch.py' enable
```

Disable the watcher before restoring an original module, otherwise it will
patch that original again when the app is closed. Use the exact rollback command
from the selected backup manifest with `manage-devicecheck-patch.py`.
Rollback refuses backups for a different app version or module hash.

Runtime status, locking and transition logs are in
`~/Library/Application Support/CodexDeviceCheckAutopatch/`. The LaunchAgent is
`~/Library/LaunchAgents/local.codex.devicecheck-autopatch.plist`. The project
volume must be mounted; macOS file protection and permissions still apply.

Eight unit tests cover relocated instructions, already-patched modules,
unsupported/truncated binaries, ambiguous matches, incorrect call context,
waiting for app exit, the stable-idle delay, idempotence and signature rejection:

```sh
cd '/path/to/CLIProxyAPI/diagnostics'
python3 -m unittest -v test_devicecheck_autopatch.py
```

The live check recognized app build 25894 as already patched. No real app update
was forced and no running app was closed during setup.
