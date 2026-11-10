export const PROVIDERS = {
  local: {name: 'Local server', model: ''},
  openai: {name: 'OpenAI', model: 'gpt-4.1-mini'},
  kilo: {name: 'Kilo Gateway', model: 'tencent/hy-mt2-1.8b'},
  openrouter: {name: 'OpenRouter', model: 'google/gemma-4-26b-a4b-it'},
};

export function translationSettings(value = {}) {
  const provider = value.provider || 'local';
  if (!Object.hasOwn(PROVIDERS, provider)) throw new Error('Select a supported translation provider');
  if (provider === 'local') return {provider};
  const model = (value.model || PROVIDERS[provider].model).trim();
  const api_key = (value.api_key || '').trim();
  if (!model || model.includes('://') || model.length > 128 || !/^[A-Za-z0-9_./:@+\-]+$/.test(model)) throw new Error('Enter a valid model ID');
  if (api_key.length < 16 || api_key.length > 4096 || !/^[\x21-\x7e]+$/.test(api_key)) throw new Error('Enter the selected provider API key');
  return {provider, model, api_key};
}
