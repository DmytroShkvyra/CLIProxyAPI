import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const instance = path.join(root, '.local');
const sources = JSON.parse(fs.readFileSync(path.join(instance, 'providers.json'), 'utf8'));
const providers = await Promise.all(sources.map(async provider => {
  const response = await fetch(`${provider.baseUrl}/models`, { signal: AbortSignal.timeout(10000) });
  if (!response.ok) throw new Error(`${provider.provider}: HTTP ${response.status}`);
  const { data } = await response.json();
  if (!Array.isArray(data) || !data.length) throw new Error(`Empty catalog: ${provider.provider}`);
  const models = [];
  const add = (name, alias, displayName, context = 32768) => models.push({
    name, alias, 'display-name': displayName, 'max-context-length': context,
    thinking: { levels: ['none'] },
  });
  const explicit = provider.routes || [];
  for (const route of explicit) {
    add(route.model, route.id, route.displayName, route.contextWindow);
    for (const alias of route.aliases || []) add(route.model, alias, route.displayName, route.contextWindow);
  }
  for (const model of data) {
    if (!explicit.some(route => route.model === model.id)) {
      add(model.id, `${provider.provider}/${model.id}`, `${provider.displayName} · ${model.id}`);
    }
  }
  return { name: provider.provider, 'base-url': provider.baseUrl, 'request-retry': 0, models,
    keys: [{ 'api-key': `${provider.provider}-local` }] };
}));

// JSON is valid YAML and avoids adding a YAML dependency to the launcher.
const config = {
  'config-version': 8,
  server: { host: '127.0.0.1', port: 18474, 'kv-store': { disabled: true }, 'response-compression': { enabled: false } },
  access: { 'api-keys': ['__CLIENT_KEY__'] },
  client: { codex: { 'third-party-tool-mode': 'code_mode_only' } },
  routing: { strategy: 'fill-first', retry: { 'request-retry': 0, 'max-retry-credentials': 0, 'max-retry-interval': 0 } },
  requests: { streaming: { 'keepalive-seconds': 10, 'bootstrap-retries': 0, 'send-keepalive-before-ft': true }, payload: {
    default: providers.map(provider => ({
      models: provider.models.map(model => ({ name: model.name, protocol: 'openai' })),
      params: { temperature: 0.1 },
    })),
    override: providers.map(provider => ({
      models: provider.models.map(model => ({ name: model.name, protocol: 'openai' })),
      params: provider.name === 'omlx'
        ? { 'chat_template_kwargs.enable_thinking': false }
        : { enable_thinking: false },
    })),
  } },
  oauth: { 'auth-dir': path.join(instance, 'auth'), 'model-alias': { codex: [{ name: 'gpt-6.1-sol', alias: 'gpt-reserve', fork: true, 'display-name': 'GPT-Reserve' }] } },
  'api-keys': { 'openai-compatibility': providers },
};
const target = path.join(instance, 'config.production.json');
if (fs.existsSync(target)) fs.copyFileSync(target, `${target}.before-sync-${Date.now()}`);
fs.writeFileSync(target, JSON.stringify(config, null, 2) + '\n');
console.log(JSON.stringify(providers.map(p => ({ provider: p.name, models: p.models.length }))));
