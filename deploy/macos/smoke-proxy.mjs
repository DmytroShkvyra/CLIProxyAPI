import fs from 'node:fs';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../.local');
const base = `http://127.0.0.1:${Number(process.env.CPA_PORT || 18474)}`;
const key = fs.readFileSync(path.join(root, 'client-key'), 'utf8').trim();
const managementKey = fs.readFileSync(path.join(root, 'management-key'), 'utf8').trim();
const results = [];
async function check(name, fn) {
  const started = Date.now();
  try {
    const details = await fn();
    const result = { name, pass: true, ms: Date.now() - started, ...details };
    results.push(result); console.log(JSON.stringify(result));
  } catch (error) {
    const result = { name, pass: false, ms: Date.now() - started, error: error.message };
    results.push(result); console.log(JSON.stringify(result));
  }
}
async function request(url, credential, body) {
  return fetch(base + url, {
    headers: { 'Content-Type': 'application/json', ...(credential || {}) },
    ...(body ? { method: 'POST', body: JSON.stringify(body) } : {}),
    signal: AbortSignal.timeout(60000),
  });
}
const headers = { 'X-Codex-Local-Gateway': key };
async function response(body, stream) {
  const r = await request('/v1/responses', headers, { ...body, stream, store: false });
  assert.equal(r.status, 200, `HTTP ${r.status}`);
  if (!stream) return r.json();
  const data = await r.text();
  const events = data.split('\n').filter(line => line.startsWith('data: {')).map(line => JSON.parse(line.slice(6)));
  const terminal = events.filter(event => event.type === 'response.completed');
  assert.equal(terminal.length, 1, 'Expected exactly one response.completed');
  assert(!events.some(event => ['error', 'response.failed'].includes(event.type)), 'Stream contained an error');
  return terminal[0].response;
}
await check('authentication', async () => {
  for (const credential of [{}, { 'X-Codex-Local-Gateway': 'invalid-key' }]) {
    const r = await request('/v1/models', credential);
    assert.equal(r.status, 401); await r.body.cancel();
  }
  for (const [credential, expected] of [[{}, 401], [{ Authorization: `Bearer ${managementKey}` }, 200]]) {
    const r = await request('/v8/management/config', credential);
    assert.equal(r.status, expected); await r.body.cancel();
  }
});
await check('catalog', async () => {
  const r = await request('/v1/models?client_version=0.167.0', headers);
  assert.equal(r.status, 200);
  const { models } = await r.json();
  const ids = models.map(model => model.slug);
  assert.equal(models.find(model => model.slug === 'experimental/qwen3.8-27b-omlx-1m')?.tool_mode, 'code_mode_only');
  for (const id of ['gpt-6.1-sol', 'gpt-reserve', 'lmstudio-community/Qwen3.8-27B-MLX-8bit', 'experimental/qwen3.8-27b-omlx-1m', 'local/mimo-v2.6-9b-omlx']) assert(ids.includes(id), `Missing ${id}`);
  assert(!ids.some(id => id.startsWith('lmstudio/')), 'LM Studio source present');
  return { models: ids.length };
});
await check('unknown-model-rejected', async () => {
  const r = await request('/v1/responses', headers, { model: 'omlx/nonexistent-smoke-model', input: 'Reply OK', stream: false });
  assert.equal(r.status, 400);
  assert.equal((await r.json()).error.code, 'model_not_found');
});
const tool = { type: 'function', name: 'echo', description: 'Return the supplied text.', parameters: { type: 'object', properties: { text: { type: 'string' } }, required: ['text'], additionalProperties: false } };
for (const model of ['gpt-6.1-terra', 'experimental/qwen3.8-27b-omlx-1m', 'lmstudio-community/Qwen3.8-27B-MLX-8bit']) {
  await check(`tool-roundtrip:${model}`, async () => {
    const common = { model, tools: [tool], max_output_tokens: 300, reasoning: { effort: model.startsWith('gpt') ? 'low' : 'none' } };
    const input = [{ role: 'user', content: 'Call echo with text PROXY_OK. After its result, reply only PROXY_OK.' }];
    const first = await response({ ...common, input, tool_choice: 'required' }, true);
    const calls = first.output.filter(item => item.type === 'function_call');
    assert.equal(calls.length, 1); assert.equal(calls[0].name, 'echo');
    assert.equal(JSON.parse(calls[0].arguments).text, 'PROXY_OK'); assert(calls[0].call_id);
    const second = await response({ ...common, input: [...input, ...first.output, { type: 'function_call_output', call_id: calls[0].call_id, output: 'PROXY_OK' }], tool_choice: 'none' }, false);
    const reply = second.output.flatMap(item => item.content || []).filter(item => item.type === 'output_text').map(item => item.text).join('').trim();
    assert.equal(reply, 'PROXY_OK');
    return { streamingToolCall: true, nonStreamingReplay: true };
  });
}
fs.writeFileSync(path.join(root, 'state/smoke-results.json'), JSON.stringify(results, null, 2) + '\n', { mode: 0o600 });
if (results.some(result => !result.pass)) process.exitCode = 1;
