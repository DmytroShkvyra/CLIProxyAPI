// Exercise the real Codex SSE decoder against a deliberately slow local fixture.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import net from 'node:net';
import { spawn } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const binary = process.env.CPA_TEST_BINARY || path.join(root, '.local/bin/cli-proxy-api');
const cli = path.join(os.homedir(), '.local/bin/codex');
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'cpa-heartbeat-'));
const key = randomBytes(24).toString('hex');
let requests = 0;
let proxy, client;
const upstream = http.createServer((req, res) => {
  req.resume();
  if (req.url !== '/v1/chat/completions') { res.writeHead(404).end(); return; }
  requests++;
  res.writeHead(200, { 'Content-Type': 'text/event-stream' });
  res.flushHeaders();
  const emit = (delta, finish = null) => res.write(`data: ${JSON.stringify({ id: 'chatcmpl-heartbeat', object: 'chat.completion.chunk', created: 1, model: 'fixture', choices: [{ index: 0, delta, finish_reason: finish }] })}\n\n`);
  const timers = [
    setTimeout(() => emit({ role: 'assistant', content: 'HEARTBEAT_' }), 4500),
    setTimeout(() => { emit({ content: 'OK' }); emit({}, 'stop'); res.end('data: [DONE]\n\n'); }, 9000),
  ];
  res.on('close', () => timers.forEach(clearTimeout));
});
try {
  await new Promise(resolve => upstream.listen(0, '127.0.0.1', resolve));
  const reservation = net.createServer();
  await new Promise(resolve => reservation.listen(0, '127.0.0.1', resolve));
  const port = reservation.address().port;
  await new Promise(resolve => reservation.close(resolve));
  const config = {
    'config-version': 8,
    server: { host: '127.0.0.1', port, 'kv-store': { disabled: true } },
    access: { 'api-keys': [key] },
    management: { 'disable-control-panel': true },
    oauth: { 'auth-dir': path.join(temporary, 'auth') },
    client: { codex: { 'third-party-tool-mode': 'code_mode_only' } },
    requests: { streaming: { 'keepalive-seconds': 1, 'send-keepalive-before-ft': true, 'bootstrap-retries': 0 } },
    routing: { retry: { 'request-retry': 0, 'max-retry-credentials': 0 } },
    'api-keys': { 'openai-compatibility': [{ name: 'heartbeat-fixture', 'base-url': `http://127.0.0.1:${upstream.address().port}/v1`, models: [{ name: 'fixture', alias: 'heartbeat-test', thinking: { levels: ['none'] } }], keys: [{ 'api-key': 'fixture' }] }] },
  };
  const configPath = path.join(temporary, 'config.yaml');
  fs.writeFileSync(configPath, JSON.stringify(config), { mode: 0o600 });
  proxy = spawn(binary, ['-config', configPath, '-local-model'], { cwd: temporary, stdio: 'ignore' });
  let ready = false;
  for (let attempt = 0; attempt < 50; attempt++) {
    try {
      const r = await fetch(`http://127.0.0.1:${port}/v1/models`, { headers: { 'X-Codex-Local-Gateway': key } });
      await r.arrayBuffer();
      if (r.ok) { ready = true; break; }
    } catch {}
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  if (!ready) throw new Error('Fixture proxy did not start');
  let stdout = '', stderr = '';
  const started = Date.now();
  client = spawn(cli, ['exec', '--ephemeral', '--json', '--skip-git-repo-check', '--sandbox', 'read-only', '-C', temporary,
    '-m', 'heartbeat-test', '-c', 'model_reasoning_effort="none"',
    '-c', `model_providers.gw.base_url="http://127.0.0.1:${port}/v1"`,
    '-c', `model_providers.gw.model_catalog_url="http://127.0.0.1:${port}/v1/models"`,
    '-c', 'model_providers.gw.stream_idle_timeout_ms=2000',
    'Reply HEARTBEAT_OK. Do not call tools.'],
  { env: { ...process.env, RUST_LOG: 'error', CODEX_LOCAL_GATEWAY_TOKEN: key }, stdio: ['ignore', 'pipe', 'pipe'] });
  client.stdout.on('data', data => { stdout += data; });
  client.stderr.on('data', data => { stderr += data; });
  const deadline = setTimeout(() => client.kill('SIGTERM'), 30000);
  const code = await new Promise(resolve => client.once('exit', resolve));
  clearTimeout(deadline);
  const events = stdout.split('\n').filter(line => line.startsWith('{')).map(line => JSON.parse(line));
  const completed = events.some(event => event.type === 'turn.completed');
  const reply = events.filter(event => event.item?.type === 'agent_message').map(event => event.item.text).join('');
  const errors = events.filter(event => event.type === 'turn.failed' || event.type === 'error');
  const pass = code === 0 && completed && reply === 'HEARTBEAT_OK' && requests === 1;
  console.log(JSON.stringify({ pass, code, completed, reply, inferenceRequests: requests, idleTimeoutMs: 2000, firstTokenDelayMs: 4500, midStreamDelayMs: 4500, elapsedMs: Date.now() - started, errors, stderr: pass ? undefined : stderr.slice(-1000) }));
  if (!pass) process.exitCode = 1;
} finally {
  client?.kill('SIGTERM'); proxy?.kill('SIGTERM');
  upstream.closeAllConnections();
  await new Promise(resolve => upstream.close(resolve));
  fs.rmSync(temporary, { recursive: true, force: true });
}
