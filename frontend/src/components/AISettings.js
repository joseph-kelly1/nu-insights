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
const field = 'w-full mt-1 h-9 px-3 rounded-lg bg-white/5 border border-white/10 text-[#F3F4F6] text-[12px] outline-none focus:border-[#FF3B30]/40';
const button = 'px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/5 font-bold text-gray-300 disabled:opacity-40 disabled:cursor-default';

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
function SettingsForm({ ai, onApply, onCancel, onClearKey }) {
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
    <form id="ai-settings" className="mt-3 space-y-3" onSubmit={apply}>
      <fieldset className="flex flex-wrap gap-x-5 gap-y-2">
        <legend className="sr-only">AI source</legend>
        <label className="flex items-center gap-2">
          <input type="radio" name="ai-mode" checked={mode === 'default'} onChange={() => setMode('default')} />
          App default (free)
        </label>
        <label className="flex items-center gap-2">
          <input type="radio" name="ai-mode" checked={mode === 'custom'} onChange={() => setMode('custom')} />
          Use my API key
        </label>
      </fieldset>

      {mode === 'custom' && (
        <>
          <div>
            <label htmlFor="ai-provider">Provider</label>
            <select
              id="ai-provider"
              className={`${field} [color-scheme:dark]`}
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
            <div className="flex justify-between">
              <label htmlFor="ai-key">API key</label>
              <a className="text-[#FF3B30] hover:underline" href={PROVIDERS[provider].keyUrl} target="_blank" rel="noreferrer">
                Get a {PROVIDERS[provider].name} key
              </a>
            </div>
            <input id="ai-key" className={field} type="password" autoComplete="off" value={apiKey}
              onChange={(e) => setApiKey(e.target.value)} />
          </div>

          <div>
            <label htmlFor="ai-model">Model</label>
            <select
              id="ai-model"
              className={`${field} [color-scheme:dark]`}
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
              <input aria-label="Model ID" className={field} placeholder="Type a model ID" value={model}
                onChange={(e) => setModel(e.target.value)} />
            )}
          </div>

          <p role="status" className="text-gray-300">{discovery.status}</p>
          <p className="text-gray-500">
            Your key is kept in this page's memory and cleared when you reload. It is sent through this app's
            server to your selected provider and is not saved by the app. Your provider may charge for requests
            made with your key; availability and billing are checked when you request an analysis.
          </p>
        </>
      )}

      <div className="flex flex-wrap gap-2">
        <button type="submit" className={`${button} bg-[#FF3B30]/20 hover:bg-[#FF3B30]/30 text-white`} disabled={!ready}>
          Apply settings
        </button>
        <button type="button" className={button} onClick={onCancel}>Cancel</button>
        <button
          type="button"
          className={button}
          onClick={() => {
            setApiKey('');
            onClearKey();
          }}
        >
          Clear key
        </button>
      </div>
    </form>
  );
}

function AISettings({ ai, open, onToggle, onApply, onClearKey }) {
  return (
    <div className="px-6 py-3 border-b border-white/5 text-[12px] text-gray-400">
      <div className="flex items-center justify-between gap-3">
        <span className="truncate">{`AI: ${aiLabel(ai)}`}</span>
        <button className={`${button} flex-shrink-0`} aria-expanded={open} aria-controls="ai-settings" onClick={onToggle}>
          AI settings
        </button>
      </div>
      {open && <SettingsForm ai={ai} onApply={onApply} onCancel={onToggle} onClearKey={onClearKey} />}
    </div>
  );
}

export default AISettings;
