import React, { useEffect, useRef, useState } from 'react';

export const PROVIDERS = {
  openai: { name: 'OpenAI', keyUrl: 'https://platform.openai.com/api-keys' },
  anthropic: { name: 'Anthropic', keyUrl: 'https://platform.claude.com/settings/keys' },
  gemini: { name: 'Google Gemini', keyUrl: 'https://aistudio.google.com/apikey' },
  openrouter: { name: 'OpenRouter', keyUrl: 'https://openrouter.ai/keys' },
};

export function aiLabel(ai) {
  if (ai.mode !== 'custom') return 'App default (free)';
  return `${PROVIDERS[ai.provider].name} · ${ai.model || 'no model'}${ai.apiKey ? '' : ' · key needed'}`;
}

const NO_MODELS = { top: [], models: [], loading: false, status: '' };
const MANUAL = '__manual__';

async function fetchModels(provider, apiKey) {
  const failed = { ...NO_MODELS, status: 'Could not load models. Check your key, or enter a model ID.' };
  try {
    const res = await fetch('/api/ai/models', {
      method: 'POST',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      // OpenRouter's catalog is public, so no key is sent for it.
      body: JSON.stringify(apiKey ? { provider, api_key: apiKey } : { provider }),
    });
    const data = await res.json();
    if (!res.ok) return data.error ? { ...failed, status: `${data.error} You can still enter a model ID.` } : failed;
    return { top: data.top, models: data.models, loading: false, status: data.models.length ? '' : 'No compatible models found. Enter a model ID.' };
  } catch {
    return failed;
  }
}

const options = (models) => models.map((m) => <option key={m.id} value={m.id}>{m.name}</option>);

// Draft settings live here and vanish on close, so Cancel restores the applied settings for free.
function AISettings({ ai, onApply, onCancel, onClearKey }) {
  const [mode, setMode] = useState(ai.mode);
  const [provider, setProvider] = useState(ai.provider || 'openai');
  const [apiKey, setApiKey] = useState(ai.apiKey || '');
  const [model, setModel] = useState(ai.model || '');
  const [manual, setManual] = useState(false);
  const [discovery, setDiscovery] = useState(NO_MODELS);
  const loadId = useRef(0);

  // Models load without a button: OpenRouter's public catalog right away, other providers once a key is typed.
  // ponytail: bumping loadId makes in-flight loads stale; no AbortController since the server can't cancel anyway.
  const discoveryKey = provider === 'openrouter' ? '' : apiKey.trim();
  const canLoad = mode === 'custom' && (provider === 'openrouter' || discoveryKey.length >= 8);
  useEffect(() => {
    const id = ++loadId.current;
    if (!canLoad) {
      setDiscovery(NO_MODELS);
      return undefined;
    }
    setDiscovery({ ...NO_MODELS, loading: true });
    const timer = setTimeout(async () => {
      const next = await fetchModels(provider, discoveryKey);
      if (id === loadId.current) setDiscovery(next);
    }, discoveryKey ? 500 : 0); // wait for the user to finish typing a key
    return () => clearTimeout(timer);
  }, [canLoad, provider, discoveryKey]);

  // A model that isn't in the list (typed, remembered, or not loaded yet) shows in the manual field.
  const showManual = manual || (model !== '' && !discovery.models.some((m) => m.id === model));
  const placeholder = discovery.loading ? 'Loading models…'
    : discovery.models.length ? 'Choose a model'
    : canLoad ? 'No models available' : 'Enter your API key to see models';

  const ready = mode === 'default' || (apiKey.trim() && model.trim());
  const apply = (e) => {
    e.preventDefault();
    if (!ready) return;
    onApply(mode === 'custom' ? { mode, provider, apiKey: apiKey.trim(), model: model.trim() } : { mode: 'default' });
  };

  return (
    <form
      id="ai-settings"
      className="settings"
      aria-labelledby="settings-heading"
      onSubmit={apply}
      onKeyDown={(e) => e.key === 'Escape' && onCancel()}
    >
      <h2 id="settings-heading">Model settings</h2>
      <p className="hint">Choose what writes course breakdowns. Search and catalog details work either way.</p>
      <fieldset className="radios">
        <legend className="sr-only">Breakdown source</legend>
        <label>
          <input type="radio" name="ai-mode" checked={mode === 'default'} onChange={() => setMode('default')} />
          App default (free)
        </label>
        <label>
          <input type="radio" name="ai-mode" checked={mode === 'custom'} onChange={() => setMode('custom')} />
          Use my API key
        </label>
      </fieldset>

      {mode === 'custom' && (
        <>
          <div>
            <label htmlFor="ai-provider" className="field-label">Provider</label>
            <select
              id="ai-provider"
              className="input"
              value={provider}
              onChange={(e) => {
                setProvider(e.target.value);
                setApiKey('');
                setModel('');
                setManual(false);
              }}
            >
              {Object.entries(PROVIDERS).map(([id, p]) => <option key={id} value={id}>{p.name}</option>)}
            </select>
          </div>

          <div>
            <div className="label-row">
              <label htmlFor="ai-key" className="field-label">API key</label>
              <a href={PROVIDERS[provider].keyUrl} target="_blank" rel="noreferrer">
                Get a {PROVIDERS[provider].name} key
              </a>
            </div>
            <input id="ai-key" className="input" type="password" autoComplete="off" value={apiKey}
              onChange={(e) => setApiKey(e.target.value)} />
          </div>

          <div>
            <label htmlFor="ai-model" className="field-label">Model</label>
            <select
              id="ai-model"
              className="input"
              value={showManual ? MANUAL : model}
              onChange={(e) => {
                setManual(e.target.value === MANUAL);
                if (e.target.value !== MANUAL) setModel(e.target.value);
              }}
            >
              <option value="" disabled>{placeholder}</option>
              {discovery.top.length > 0 && <optgroup label="Top 10 (newest)">{options(discovery.top)}</optgroup>}
              {discovery.models.length > 0 && (
                <optgroup label={`All models (${discovery.models.length})`}>{options(discovery.models)}</optgroup>
              )}
              <option value={MANUAL}>Enter a model ID…</option>
            </select>
            {showManual && (
              <input aria-label="Model ID" className="input" placeholder="Type a model ID" value={model}
                onChange={(e) => setModel(e.target.value)} />
            )}
          </div>

          <p role="status">{discovery.status}</p>
          <p className="hint">
            Your key is kept in this page's memory and cleared when you reload. It is sent through this app's
            server to your selected provider and is not saved by the app. Your provider may charge for requests
            made with your key; availability and billing are checked when you request a breakdown.
          </p>
        </>
      )}

      <div className="settings-actions">
        <button type="submit" className="btn btn-ink" disabled={!ready}>
          Apply settings
        </button>
        <button type="button" className="btn btn-outline" onClick={onCancel}>Cancel</button>
        {mode === 'custom' && apiKey && (
          <button
            type="button"
            className="btn btn-quiet"
            onClick={() => {
              setApiKey('');
              onClearKey();
            }}
          >
            Clear key
          </button>
        )}
      </div>
    </form>
  );
}

export default AISettings;
