import { render, screen, act, fireEvent, waitFor } from '@testing-library/react';
import App from './App';

// react-markdown is ESM-only, which CRA's Jest does not transform.
jest.mock('react-markdown', () => (props) => props.children);
Element.prototype.scrollIntoView = () => {}; // missing in jsdom

test.each([
  ['a 429 envelope', () => Promise.resolve({ ok: false, json: async () => ({ error: 'Rate limited, try later.', code: 'rate_limited' }) }), 'Rate limited, try later.'],
  ['a network failure', () => Promise.reject(new TypeError('Failed to fetch')), 'Failed to get AI analysis. Is the backend running?'],
])('analysis shows a useful error on %s and clears Thinking', async (_, analyze, message) => {
  jest.useFakeTimers();
  global.fetch = jest.fn((url) => (url === '/api/analyze' ? analyze() : Promise.resolve({ ok: false })));
  render(<App />);
  act(() => jest.advanceTimersByTime(2000));
  fireEvent.click(screen.getAllByText('Get Started')[0]);

  const input = screen.getByPlaceholderText('Type a course code or question...');
  fireEvent.change(input, { target: { value: 'CS 3000' } });
  fireEvent.submit(input.closest('form'));

  expect(await screen.findByText(message)).toBeInTheDocument();
  expect(screen.queryByText('Thinking')).not.toBeInTheDocument();
});

// --- AI settings ---

const json = (body, ok = true) => Promise.resolve({ ok, json: async () => body });
const pending = () => {
  let resolve;
  const promise = new Promise((r) => { resolve = r; });
  return [promise, (body) => resolve({ ok: true, json: async () => body })];
};

let routes;
beforeEach(() => {
  localStorage.clear();
  routes = {};
});

function startApp() {
  jest.useFakeTimers();
  global.fetch = jest.fn((url, opts) => (routes[url] ? routes[url](opts) : Promise.resolve({ ok: false })));
  render(<App />);
  act(() => jest.advanceTimersByTime(2000));
  fireEvent.click(screen.getAllByText('Get Started')[0]);
}

const change = (label, value) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
const bodies = (url) => fetch.mock.calls.filter(([u]) => u === url).map(([, opts]) => JSON.parse(opts.body));
const modelGroups = () => Object.fromEntries([...document.querySelectorAll('#ai-model optgroup')]
  .map((group) => [group.label, [...group.children].map((option) => option.value)]));
const wait = (ms) => act(() => jest.advanceTimersByTime(ms));

function ask(text) {
  const input = screen.getByPlaceholderText('Type a course code or question...');
  fireEvent.change(input, { target: { value: text } });
  fireEvent.submit(input.closest('form'));
}

function openCustomSettings() {
  fireEvent.click(screen.getByText('AI settings'));
  fireEvent.click(screen.getByLabelText('Use my API key'));
}

function typeModelId(model) {
  change('Model', '__manual__');
  change('Model ID', model);
}

function configure({ provider = 'openai', key = 'sk-test-key', model = 'gpt-6-luna' } = {}) {
  openCustomSettings();
  change('Provider', provider);
  change('API key', key);
  typeModelId(model);
  fireEvent.click(screen.getByText('Apply settings'));
}

async function clickSearchResult(title) {
  routes['/api/search?q=cs'] = () => json([{ department_code: 'cs', number: '2500', title, credits: 4 }]);
  fireEvent.change(screen.getByPlaceholderText('Search courses...'), { target: { value: 'cs' } });
  wait(300);
  const result = await screen.findByText(title);
  await act(async () => fireEvent.click(result)); // course fetch, then analysis
}

test('default mode keeps the legacy request and attributes OpenRouter', async () => {
  routes['/api/analyze'] = () => json({ analysis: 'Free answer', model: 'free/model' });
  startApp();
  expect(screen.getByText('AI: App default (free)')).toBeInTheDocument();
  ask('CS 3000');
  expect(await screen.findByText('Free answer')).toBeInTheDocument();
  expect(bodies('/api/analyze')).toEqual([{ dept: 'CS', number: '3000' }]);
  expect(screen.getByText('via OpenRouter · free/model')).toBeInTheDocument();
});

test('models load once a key is typed, newest 10 first, and both flows send the applied config', async () => {
  routes['/api/ai/models'] = () => json({
    provider: 'anthropic',
    top: [{ id: 'claude-x', name: 'Claude X' }],
    models: [{ id: 'claude-w', name: 'Claude W' }, { id: 'claude-x', name: 'Claude X' }],
  });
  routes['/api/analyze'] = () => json({ analysis: 'Custom answer', model: 'claude-x-2026', provider: 'anthropic' });
  startApp();

  openCustomSettings();
  expect(screen.getByText('AI settings')).toHaveAttribute('aria-expanded', 'true');
  change('Provider', 'anthropic');
  expect(screen.getByRole('option', { name: 'Enter your API key to see models' })).toBeInTheDocument();
  expect(screen.queryByText('Load models')).not.toBeInTheDocument();
  change('API key', 'sk-test-ke');
  wait(100); // still typing
  change('API key', '  sk-test-key ');
  wait(500);
  await waitFor(() => expect(modelGroups()).toEqual({
    'Top 10 (newest)': ['claude-x'],
    'All models (2)': ['claude-w', 'claude-x'],
  }));
  expect(bodies('/api/ai/models')).toEqual([{ provider: 'anthropic', api_key: 'sk-test-key' }]); // debounced
  expect(fetch.mock.calls.find(([u]) => u === '/api/ai/models')[1].cache).toBe('no-store');
  change('Model', 'claude-x');
  fireEvent.click(screen.getByText('Apply settings'));
  expect(screen.getByText('AI: Anthropic · claude-x')).toBeInTheDocument();
  expect(screen.queryByLabelText('API key')).not.toBeInTheDocument();

  ask('CS 3000');
  await screen.findByText('Custom answer');
  await clickSearchResult('Fundies');
  await waitFor(() => expect(screen.getAllByText('Custom answer')).toHaveLength(2));

  const ai = { mode: 'custom', provider: 'anthropic', api_key: 'sk-test-key', model: 'claude-x' };
  expect(bodies('/api/analyze')).toEqual([{ dept: 'CS', number: '3000', ai }, { dept: 'cs', number: '2500', ai }]);
  expect(screen.getAllByText('via Anthropic · claude-x-2026')).toHaveLength(2);
  expect(fetch.mock.calls.filter(([u]) => !['/api/analyze', '/api/ai/models'].includes(u))
    .every(([, opts]) => !JSON.stringify(opts || {}).includes('sk-test-key'))).toBe(true);
  expect(JSON.parse(localStorage.getItem('aiPrefs'))).toEqual({ mode: 'custom', provider: 'anthropic', model: 'claude-x' });
});

test('OpenRouter models preload without a key and are not refetched as the key is typed', async () => {
  routes['/api/ai/models'] = () => json({
    provider: 'openrouter',
    top: [{ id: 'openai/gpt-6.1-sol', name: 'OpenAI: GPT-6.1 Sol' }],
    models: [{ id: 'openai/gpt-6.1-sol', name: 'OpenAI: GPT-6.1 Sol' }, { id: 'z/text', name: 'Zed: Text' }],
  });
  startApp();
  openCustomSettings();
  change('Provider', 'openrouter');
  wait(0);
  await waitFor(() => expect(modelGroups()['Top 10 (newest)']).toEqual(['openai/gpt-6.1-sol']));
  expect(bodies('/api/ai/models')).toEqual([{ provider: 'openrouter' }]);

  change('API key', 'sk-or-key-123');
  wait(500);
  expect(bodies('/api/ai/models')).toHaveLength(1);
});

test('reload restores only preferences; an incomplete setup blocks both flows but not browsing', async () => {
  localStorage.setItem('aiPrefs', JSON.stringify({ mode: 'custom', provider: 'openai', model: 'gpt-6-luna' }));
  startApp();
  expect(screen.getByText('AI: OpenAI · gpt-6-luna · key needed')).toBeInTheDocument();

  ask('CS 3000');
  expect(screen.getByText('Add an API key in AI settings to use OpenAI, or switch to App default.')).toBeInTheDocument();
  expect(screen.getByLabelText('API key')).toHaveValue('');
  expect(screen.getByLabelText('Model ID')).toHaveValue('gpt-6-luna');
  expect(screen.getByText('Apply settings')).toBeDisabled();

  fireEvent.click(screen.getByText('Cancel'));
  await clickSearchResult('Fundies');
  await waitFor(() => expect(screen.getAllByText(/^Add an API key/)).toHaveLength(2));
  expect(fetch).toHaveBeenCalledWith('/api/course/cs/2500');
  expect(bodies('/api/analyze')).toEqual([]);
});

test('stale model lists are ignored after provider change or Clear key; failures keep manual entry', async () => {
  startApp();
  openCustomSettings();

  const [oldLoad, finishOld] = pending();
  routes['/api/ai/models'] = () => oldLoad;
  change('API key', 'sk-openai-key');
  wait(500);
  change('Provider', 'gemini');
  expect(screen.getByLabelText('API key')).toHaveValue('');
  await act(async () => finishOld({ top: [{ id: 'gpt-old', name: 'Old' }], models: [{ id: 'gpt-old', name: 'Old' }] }));
  expect(modelGroups()).toEqual({});

  const [clearedLoad, finishCleared] = pending();
  routes['/api/ai/models'] = () => clearedLoad;
  change('API key', 'sk-gemini-key');
  wait(500);
  fireEvent.click(screen.getByText('Clear key'));
  expect(screen.getByLabelText('API key')).toHaveValue('');
  await act(async () => finishCleared({ top: [], models: [{ id: 'gemini-old', name: 'Old' }] }));
  expect(modelGroups()).toEqual({});

  routes['/api/ai/models'] = () => json({ error: 'Google Gemini rejected your API key.', code: 'invalid_api_key' }, false);
  change('API key', 'sk-gemini-key');
  wait(500);
  expect(await screen.findByText('Google Gemini rejected your API key. You can still enter a model ID.')).toBeInTheDocument();
  typeModelId('gemini-3.5-flash');
  fireEvent.click(screen.getByText('Apply settings'));
  expect(screen.getByText('AI: Google Gemini · gemini-3.5-flash')).toBeInTheDocument();
});

test('mid-request settings changes, Cancel, New Chat, and Clear key only affect later requests', async () => {
  const [analysis, finish] = pending();
  routes['/api/analyze'] = () => analysis;
  startApp();
  configure({ model: 'gpt-6-luna' });

  ask('CS 3000');
  configure({ model: 'gpt-6-sol' });
  await act(async () => finish({ analysis: 'First answer', model: 'gpt-6-luna', provider: 'openai' }));
  expect(screen.getByText('via OpenAI · gpt-6-luna')).toBeInTheDocument();
  expect(bodies('/api/analyze').map((b) => b.ai.model)).toEqual(['gpt-6-luna']);

  fireEvent.click(screen.getByText('AI settings'));
  change('Model ID', 'draft-only');
  fireEvent.click(screen.getByText('Cancel'));
  fireEvent.click(screen.getByText('New Chat'));
  expect(screen.queryByText('First answer')).not.toBeInTheDocument();
  expect(screen.getByText('AI: OpenAI · gpt-6-sol')).toBeInTheDocument();

  fireEvent.click(screen.getByText('AI settings'));
  fireEvent.click(screen.getByText('Clear key'));
  expect(screen.getByText('AI: OpenAI · gpt-6-sol · key needed')).toBeInTheDocument();
  ask('CS 3000');
  expect(screen.getByText(/^Add an API key/)).toBeInTheDocument();
  expect(bodies('/api/analyze')).toHaveLength(1);
});
