const RECOMMENDED = [
  'tencent/hy-mt2-30b-a3b', 'tencent/hy-mt2-7b', 'tencent/hy-mt2-1.8b',
  'google/gemma-4-26b-a4b-it', 'google/gemini-2.5-flash-lite',
  'google/gemini-2.5-flash', 'openai/gpt-4.1-mini',
];
const dollars = new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD', maximumSignificantDigits: 3});
export const money = value => dollars.format(value);

export function estimateMinute(model) {
  if (!model || ![model.input_price, model.output_price].every(value => typeof value === 'number' && Number.isFinite(value) && value >= 0)) return null;
  const inputTokens = model.id.startsWith('tencent/hy-mt2-') ? 600 : 3500, outputTokens = 450;
  const minute = inputTokens * model.input_price + outputTokens * model.output_price;
  return {minute, hour: minute * 60, inputTokens, outputTokens};
}

export function rankedModels(models, query = '') {
  const search = query.trim().toLowerCase();
  const rank = model => { const index = RECOMMENDED.indexOf(model.id); return index < 0 ? RECOMMENDED.length : index; };
  return models.filter(model => `${model.name} ${model.id}`.toLowerCase().includes(search))
    .sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
}

function textElement(tag, text, className) {
  const element = document.createElement(tag);
  element.textContent = text;
  if (className) element.className = className;
  return element;
}

export function createModelPicker({provider, model, settings, request}) {
  const find = id => document.getElementById(id);
  const search = find('modelSearch'), list = find('modelResults'), status = find('modelStatus');
  const estimate = find('modelEstimate'), assumptions = find('estimateAssumptions');
  const balance = find('cloudBalance'), balanceStatus = find('balanceStatus');
  const refreshModels = find('refreshModels'), refreshBalance = find('refreshBalance');
  const caches = new Map();
  let models = [], revision = 0, modelAbort, balanceAbort, balanceRevision = 0;

  function renderSelection() {
    const selected = models.find(item => item.id === model.value.trim());
    const cost = estimateMinute(selected);
    estimate.textContent = cost ? `Approx. ${money(cost.minute)} / min · ${money(cost.hour)} / hour` : 'Estimated cost: unavailable for this model';
    find('modelRates').textContent = cost ? `Input ${money(selected.input_price * 1e6)} / 1M tokens · Output ${money(selected.output_price * 1e6)} / 1M tokens` : '';
    assumptions.textContent = cost ? `Estimate: about ${cost.inputTokens.toLocaleString('en-US')} input + ${cost.outputTokens} output tokens per minute of speech. Text translation only; ASR, voices, speech preparation, retries, extra reasoning and cache discounts are excluded. Actual usage varies.` : 'Select a model with published token prices to see an approximate text-translation cost. Unknown pricing is not treated as free.';
    renderList();
  }

  function renderList() {
    const filtered = rankedModels(models, search.value);
    list.replaceChildren();
    for (const item of filtered.slice(0, 60)) {
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'model-option';
      button.setAttribute('aria-pressed', String(item.id === model.value.trim()));
      button.dataset.model = item.id;
      const heading = textElement('span', '', 'model-option-heading');
      heading.append(textElement('strong', item.name));
      const cost = estimateMinute(item);
      heading.append(textElement('span', cost ? `~${money(cost.minute)} / min` : 'Price unavailable', 'model-option-cost'));
      button.append(heading, textElement('span', item.id, 'model-option-id'));
      const badge = item.id.startsWith('tencent/hy-mt2-') ? 'Translation model' : item.id === 'google/gemma-4-26b-a4b-it' ? 'Tested in Synchro' : RECOMMENDED.includes(item.id) ? 'Fast general model · test on your content' : '';
      if (badge) button.append(textElement('span', badge, 'model-option-note'));
      button.onclick = () => { model.value = item.id; model.dispatchEvent(new Event('input')); };
      list.append(button);
    }
    if (!filtered.length && models.length) list.append(textElement('p', 'No matching models. Try a shorter name or enter the model ID below.', 'small'));
    find('modelCount').textContent = models.length ? `${filtered.length} matching models${filtered.length > 60 ? ' · showing the first 60; narrow your search' : ''}` : '';
  }

  function invalidateBalance() {
    balanceRevision++; balanceAbort?.abort();
    balance.textContent = '—'; balanceStatus.textContent = 'Enter a provider key to check the balance.';
    refreshBalance.disabled = false;
  }

  async function loadBalance() {
    if (!['kilo', 'openrouter'].includes(provider())) return;
    invalidateBalance();
    const stamp = balanceRevision;
    let body;
    try { body = settings(); }
    catch { return; }
    balanceAbort = new AbortController();
    refreshBalance.disabled = true; balanceStatus.textContent = 'Checking balance…';
    try {
      const result = await request('/api/translation/balance', body, balanceAbort.signal);
      if (stamp !== balanceRevision) return;
      if (typeof result.balance_usd !== 'number' || !Number.isFinite(result.balance_usd)) throw new Error('Balance is unavailable');
      balance.textContent = new Intl.NumberFormat('en-US', {style:'currency',currency:'USD',minimumFractionDigits:2,maximumFractionDigits:4}).format(result.balance_usd);
      balanceStatus.textContent = `Updated ${new Date(result.fetched_at * 1000).toLocaleTimeString()} · personal account`;
    } catch (error) {
      if (stamp === balanceRevision && error.name !== 'AbortError') balanceStatus.textContent = error.message;
    } finally { if (stamp === balanceRevision) refreshBalance.disabled = false; }
  }

  async function setProvider(force = false) {
    const current = provider(), stamp = ++revision;
    modelAbort?.abort(); invalidateBalance();
    models = []; search.value = ''; list.replaceChildren(); status.textContent = '';
    const priced = ['kilo', 'openrouter'].includes(current);
    find('modelCatalog').hidden = !priced;
    find('balancePanel').hidden = !priced;
    find('modelPricing').hidden = !priced;
    if (!priced) return;
    renderSelection();
    void loadBalance();
    if (force) caches.delete(current);
    refreshModels.disabled = true; list.setAttribute('aria-busy', 'true');
    status.textContent = 'Loading models and current token prices…';
    try {
      modelAbort = new AbortController();
      const result = caches.get(current) || await request('/api/translation/models', {provider:current}, modelAbort.signal);
      if (stamp !== revision) return;
      if (!Array.isArray(result.models)) throw new Error('The model catalog is invalid');
      caches.set(current, result); models = result.models;
      status.textContent = `Translation models first · prices checked ${new Date(result.fetched_at * 1000).toLocaleTimeString()}`;
      renderSelection();
    } catch (error) {
      if (stamp !== revision || error.name === 'AbortError') return;
      status.textContent = `${error.message}. You can still enter a model ID below.`;
      renderSelection();
    } finally {
      if (stamp === revision) { refreshModels.disabled = false; list.setAttribute('aria-busy', 'false'); }
    }
  }

  search.oninput = renderList;
  refreshModels.onclick = () => setProvider(true);
  refreshBalance.onclick = loadBalance;
  return {setProvider, renderSelection, loadBalance, invalidateBalance};
}
