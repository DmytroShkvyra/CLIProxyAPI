import fs from 'node:fs';
import path from 'node:path';
import { spawn, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const instance = path.join(root, '.local');
const port = Number(process.env.CPA_PORT || 18474);
if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('Invalid CPA_PORT');
const readKey = name => {
  const filename = path.join(instance, name);
  const key = fs.readFileSync(filename, 'utf8').trim();
  if (key.length < 24 || /[\r\n]/.test(key)) throw new Error(`Invalid ${name}`);
  fs.chmodSync(filename, 0o600);
  return key;
};
const clientKey = readKey('client-key');
const managementKey = readKey('management-key');
const published = spawnSync('/bin/launchctl', ['setenv', 'CODEX_LOCAL_GATEWAY_TOKEN', clientKey]);
if (published.status !== 0) throw new Error('Cannot publish the Codex client credential');
const config = JSON.parse(fs.readFileSync(path.join(instance, 'config.production.json'), 'utf8'));
config.server.port = port;
config.access['api-keys'] = [clientKey];
config.management = { ...config.management, 'allow-remote': false, 'secret-key': managementKey };
const runtime = path.join(instance, 'state', `config-${port}.yaml`);
fs.mkdirSync(path.dirname(runtime), { recursive: true, mode: 0o700 });
fs.writeFileSync(runtime, JSON.stringify(config, null, 2), { mode: 0o600 });
fs.chmodSync(runtime, 0o600);
const child = spawn(path.join(instance, 'bin/cli-proxy-api'), ['-config', runtime], {
  cwd: instance, stdio: 'inherit',
  env: { ...process.env, MANAGEMENT_STATIC_PATH: path.join(instance, 'state/static') },
});
for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, () => child.kill(signal));
child.on('error', error => { console.error(error.message); process.exitCode = 1; });
child.on('exit', (code, signal) => process.exit(code ?? (signal ? 1 : 0)));
