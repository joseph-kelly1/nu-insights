import { render, screen, act, fireEvent, waitFor, cleanup, within } from '@testing-library/react';
import App from './App';

// react-markdown is ESM-only, which CRA's Jest does not transform.
jest.mock('react-markdown', () => (props) => props.children);
Element.prototype.scrollIntoView = () => {}; // missing in jsdom
window.scrollTo = () => {};
const enterApp = () => fireEvent.click(screen.getByRole('button', { name: 'Start searching' }));

test.each([
  ['a 429 envelope', () => Promise.resolve({ ok: false, json: async () => ({ error: 'Rate limited, try later.', code: 'rate_limited' }) }), 'Rate limited, try later.'],
  ['a network failure', () => Promise.reject(new TypeError('Failed to fetch')), 'Could not reach the server for a breakdown. Check that the API is running, then try again.'],
])('analysis shows a useful error on %s and clears the pending state', async (_, analyze, message) => {
  global.fetch = jest.fn((url) => (url === '/api/analyze' ? analyze() : Promise.resolve({ ok: false })));
  render(<App />);
  expect(screen.getByRole('heading', { level: 1, name: 'NU Insights' })).toBeInTheDocument();
  enterApp(); // the landing page renders immediately, with no startup timer

  const input = screen.getByLabelText('Breakdown by course code');
  fireEvent.change(input, { target: { value: 'CS 3000' } });
  fireEvent.submit(input.closest('form'));

  expect(await screen.findByText(message)).toBeInTheDocument();
  expect(screen.queryByText(/Writing a breakdown/)).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Get breakdown' })).toBeDisabled(); // input was cleared
  expect(screen.getByText('Couldn’t load CS 3000. Check that the API is running, then try again.')).toBeInTheDocument();
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
  window.history.replaceState(null, '', '/'); // the builder route lives in the hash
  routes = {};
});

function startApp() {
  jest.useFakeTimers();
  global.fetch = jest.fn((url, opts) => (routes[url] ? routes[url](opts) : Promise.resolve({ ok: false })));
  render(<App />);
  enterApp();
}

const change = (label, value) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
const bodies = (url) => fetch.mock.calls.filter(([u]) => u === url).map(([, opts]) => JSON.parse(opts.body));
const modelGroups = () => Object.fromEntries([...document.querySelectorAll('#ai-model optgroup')]
  .map((group) => [group.label, [...group.children].map((option) => option.value)]));
const wait = (ms) => act(() => jest.advanceTimersByTime(ms));
const settingsButton = () => screen.getByRole('button', { name: 'Model settings' });
const course = (number, title) => ({
  department_code: 'cs', number, title, credits: 4, description: `${title} description`,
  prerequisites: [], corequisites: [], attributes: [], schedule_context: [],
});

function ask(text) {
  const input = screen.getByLabelText('Breakdown by course code');
  fireEvent.change(input, { target: { value: text } });
  fireEvent.submit(input.closest('form'));
}

function openCustomSettings() {
  fireEvent.click(settingsButton());
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
  routes['/api/course/cs/2500'] = () => json(course('2500', title));
  fireEvent.change(screen.getByLabelText('Search courses'), { target: { value: 'cs' } });
  wait(300);
  const result = await screen.findByText(title);
  await act(async () => fireEvent.click(result)); // course fetch
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Get course breakdown' })));
}

test('default mode keeps the legacy request and attributes OpenRouter', async () => {
  routes['/api/analyze'] = () => json({ analysis: 'Free answer', model: 'free/model' });
  startApp();
  expect(screen.getByText('Using App default (free)')).toBeInTheDocument();
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
  expect(settingsButton()).toHaveAttribute('aria-expanded', 'true');
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
  expect(screen.getByText('Using Anthropic · claude-x')).toBeInTheDocument();
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
  expect(screen.getByText('Using OpenAI · gpt-6-luna · key needed')).toBeInTheDocument();

  ask('CS 3000');
  expect(screen.getByText('Add an API key in Model settings to use OpenAI, or switch to App default.')).toBeInTheDocument();
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
  fireEvent.click(settingsButton());
  expect(screen.queryByText('Clear key')).not.toBeInTheDocument(); // app default has no key
  fireEvent.click(screen.getByLabelText('Use my API key'));

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
  expect(screen.queryByText('Clear key')).not.toBeInTheDocument(); // nothing left to clear
  await act(async () => finishCleared({ top: [], models: [{ id: 'gemini-old', name: 'Old' }] }));
  expect(modelGroups()).toEqual({});

  routes['/api/ai/models'] = () => json({ error: 'Google Gemini rejected your API key.', code: 'invalid_api_key' }, false);
  change('API key', 'sk-gemini-key');
  wait(500);
  expect(await screen.findByText('Google Gemini rejected your API key. You can still enter a model ID.')).toBeInTheDocument();
  typeModelId('gemini-3.5-flash');
  fireEvent.click(screen.getByText('Apply settings'));
  expect(screen.getByText('Using Google Gemini · gemini-3.5-flash')).toBeInTheDocument();
});

test('mid-request settings changes, Cancel, Clear breakdowns, and Clear key only affect later requests', async () => {
  const [analysis, finish] = pending();
  routes['/api/analyze'] = () => analysis;
  startApp();
  configure({ model: 'gpt-6-luna' });

  ask('CS 3000');
  configure({ model: 'gpt-6-sol' });
  await act(async () => finish({ analysis: 'First answer', model: 'gpt-6-luna', provider: 'openai' }));
  expect(screen.getByText('via OpenAI · gpt-6-luna')).toBeInTheDocument();
  expect(bodies('/api/analyze').map((b) => b.ai.model)).toEqual(['gpt-6-luna']);

  fireEvent.click(settingsButton());
  change('Model ID', 'draft-only');
  fireEvent.click(screen.getByText('Cancel'));
  fireEvent.click(screen.getByText('Clear breakdowns'));
  expect(screen.queryByText('First answer')).not.toBeInTheDocument();
  expect(screen.getByText('Using OpenAI · gpt-6-sol')).toBeInTheDocument();

  fireEvent.click(settingsButton());
  fireEvent.click(screen.getByText('Clear key'));
  expect(screen.getByText('Using OpenAI · gpt-6-sol · key needed')).toBeInTheDocument();
  ask('CS 3000');
  expect(screen.getByText(/^Add an API key/)).toBeInTheDocument();
  expect(bodies('/api/analyze')).toHaveLength(1);
  expect(await screen.findByText('Details unavailable')).toBeInTheDocument(); // browsing still works
});

test('a slow course response never replaces a newer selection', async () => {
  const [slow, finishSlow] = pending();
  routes['/api/search?q=cs'] = () => json([course('2100', 'First course'), course('3000', 'Second course')]);
  routes['/api/course/cs/2100'] = () => slow;
  routes['/api/course/cs/3000'] = () => json(course('3000', 'Second course'));
  startApp();
  fireEvent.change(screen.getByLabelText('Search courses'), { target: { value: 'cs' } });
  wait(300);
  fireEvent.click(await screen.findByText('First course'));
  expect(screen.getByText('Loading catalog details for CS 2100…')).toBeInTheDocument();
  expect(screen.getByLabelText('Search courses')).not.toBeVisible(); // the results window became the course
  fireEvent.click(screen.getByText('← Back to results'));
  expect(screen.getByLabelText('Search courses')).toHaveValue('cs');
  await act(async () => fireEvent.click(screen.getByText('Second course')));
  await act(async () => finishSlow(course('2100', 'First course')));
  expect(screen.getByRole('heading', { level: 2, name: 'Second course' })).toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: 'First course' })).not.toBeInTheDocument();
});

test('invalid codes are explained without a request, and finished breakdowns copy to the clipboard', async () => {
  const writeText = jest.fn(() => Promise.resolve());
  Object.assign(navigator, { clipboard: { writeText } });
  routes['/api/analyze'] = () => json({ analysis: 'Copy me', model: 'free/model' });
  startApp();
  ask('algorithms please');
  expect(screen.getByLabelText('Breakdown by course code')).toHaveAttribute('aria-invalid', 'true');
  expect(bodies('/api/analyze')).toEqual([]);

  ask('cs3000');
  await screen.findByText('Copy me');
  const copy = screen.getByRole('button', { name: 'Copy CS 3000 breakdown' });
  await act(async () => fireEvent.click(copy));
  expect(writeText).toHaveBeenCalledWith('Copy me');
  expect(copy).toHaveTextContent('Copied');
});

test('Start searching opens an empty, focused search, and the landing page explains the site', async () => {
  routes['/api/search?q=phil'] = () => json([course('1101', 'Introduction to Philosophy')]);
  render(<App />);
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument(); // no search field on the landing page
  expect(screen.getByRole('heading', { name: 'What you can do here' })).toBeInTheDocument();
  expect(screen.getByText('See where a course fits')).toBeInTheDocument();
  cleanup();
  startApp();
  expect(screen.getByLabelText('Search courses')).toHaveValue('');
  expect(screen.getByLabelText('Search courses')).toHaveFocus();
  change('Search courses', 'phil');
  wait(300);
  expect(await screen.findByText('Introduction to Philosophy')).toBeInTheDocument();
});

test('a failed major list can be retried without reloading', async () => {
  startApp(); // /api/programs fails, like an API started before the endpoint existed
  const retry = await screen.findByRole('button', { name: 'Try again' });
  routes['/api/programs'] = () => json([{ id: 'p1', label: 'Physics, BS (Boston)', status: 'available' }]); // API restarted
  fireEvent.click(retry);
  await waitFor(() => expect(document.querySelectorAll('#major-options option')).toHaveLength(1));
  expect(screen.queryByText(/Majors couldn’t load/)).not.toBeInTheDocument();
});

// --- Major selection ---

const PROGRAM_LIST = [
  { id: 'cs-bscs-1', label: 'Computer Science, BSCS (Boston)', status: 'available' },
  { id: 'cs-bscs-2', label: 'Computer Science, BSCS (Oakland)', status: 'available' },
  { id: 'ds-bs-3', label: 'Data Science, BS (Boston)', status: 'available' },
  { id: 'film-4', label: 'Film and Creative Media, BA (Boston)', status: 'no_published_plan' },
];
const [CS_BOS, , DS] = PROGRAM_LIST;
const programCourses = (id, q = '', offset = 0) => `/api/programs/${id}/courses?q=${q}&offset=${offset}&view=sections`;
const page = (results, total, program = CS_BOS) => json({ program, plan_dataset: { catalog_year: '2025-2026' }, results, total });
const majorInput = () => screen.getByLabelText('Your major');
const savedMajor = () => JSON.parse(localStorage.getItem('major'));

async function startWithPrograms() {
  routes['/api/programs'] = () => json(PROGRAM_LIST);
  startApp();
  await waitFor(() => expect(document.querySelectorAll('#major-options option')).toHaveLength(PROGRAM_LIST.length));
}

const chooseMajor = (program) => change('Your major', program.label);

test('the major picker lists catalog programs, selects only exact labels, persists, and clears', async () => {
  localStorage.setItem('major', '{not json');
  await startWithPrograms();
  expect(majorInput()).toHaveValue('');
  expect([...document.querySelectorAll('#major-options option')].map((o) => o.value)).toContain('Computer Science, BSCS (Oakland)');

  change('Your major', 'Computer Sci'); // still typing: nothing selected
  expect(localStorage.getItem('major')).toBeNull();
  fireEvent.blur(majorInput());
  expect(majorInput()).toHaveValue('');

  chooseMajor(CS_BOS);
  expect(savedMajor()).toEqual(CS_BOS);
  cleanup(); // reload
  await startWithPrograms();
  expect(majorInput()).toHaveValue('Computer Science, BSCS (Boston)');
  expect(screen.getByRole('radio', { name: 'All courses' })).toBeChecked(); // browsing starts unchanged

  fireEvent.click(screen.getByRole('button', { name: 'Clear major Computer Science, BSCS (Boston)' }));
  expect(majorInput()).toHaveValue('');
  expect(localStorage.getItem('major')).toBeNull();
  expect(screen.queryByRole('radio', { name: 'My major' })).not.toBeInTheDocument();
});

test('a saved major missing from refreshed data is dropped; a failed program list keeps browsing', async () => {
  localStorage.setItem('major', JSON.stringify({ id: 'retired', label: 'Retired Program, BS', status: 'available' }));
  await startWithPrograms();
  await waitFor(() => expect(majorInput()).toHaveValue(''));
  expect(localStorage.getItem('major')).toBeNull();

  cleanup();
  delete routes['/api/programs']; // the list fails to load
  startApp();
  expect(await screen.findByText('Majors couldn’t load. Browsing and breakdowns still work without one.')).toBeInTheDocument();
  expect(screen.getByLabelText('Search courses')).toBeEnabled();
});

test('My major browses without a query, pages to the rest, narrows with search, and explains empties', async () => {
  const first = Array.from({ length: 20 }, (_, i) => course(`${1100 + i}`, `Plan course ${i}`));
  routes[programCourses(CS_BOS.id)] = () => page(first, 23);
  routes[programCourses(CS_BOS.id, '', 20)] = () => page([first[0], course('4100', 'Late A'), course('4200', 'Late B'), course('4300', 'Late C')], 23);
  routes[programCourses(CS_BOS.id, 'algo')] = () => page([course('3000', 'Algorithms and Data')], 1);
  routes[programCourses(CS_BOS.id, 'zzz')] = () => page([], 0);
  routes['/api/search?q=zzz'] = () => json([]);
  await startWithPrograms();
  chooseMajor(CS_BOS);
  fireEvent.click(screen.getByRole('radio', { name: 'My major' }));
  wait(300);
  expect(await screen.findByText('Showing 20 of 23 courses')).toBeInTheDocument();
  expect(screen.getByText(/Courses that appear in the collected 2025–2026 sample plans for Computer Science, BSCS \(Boston\)/)).toBeInTheDocument();
  expect(screen.getByText(/Current requirements are not loaded for this major/)).toBeInTheDocument();

  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Show 3 more' })));
  expect(screen.getByText('Showing 23 of 23 courses')).toBeInTheDocument(); // the repeated row was not added twice
  expect(screen.getByText('Late C')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /more$/ })).not.toBeInTheDocument();

  change('Search courses', 'algo');
  wait(300);
  expect(await screen.findByText('Showing 1 of 1 course')).toBeInTheDocument();
  change('Search courses', 'zzz');
  wait(300);
  expect(await screen.findByText('No courses in the Computer Science, BSCS (Boston) sample plans match “zzz”. Try a shorter word, or switch to All courses.')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('radio', { name: 'All courses' }));
  wait(300);
  expect(await screen.findByText('No courses match “zzz”. Try a department code like “cs” or a shorter title word.')).toBeInTheDocument();
  expect(fetch).not.toHaveBeenCalledWith('/api/programs/film-4/courses?q=zzz&offset=0');

  routes[programCourses('film-4')] = () => page([], 0, PROGRAM_LIST[3]);
  change('Search courses', '');
  chooseMajor(PROGRAM_LIST[3]);
  fireEvent.click(screen.getByRole('radio', { name: 'My major' }));
  wait(300);
  expect(await screen.findByText('Film and Creative Media, BA (Boston) has no published sample plan in this dataset, so there are no plan courses to list.')).toBeInTheDocument();
});

test('a slow response for an earlier major never replaces a newer major', async () => {
  const [slow, finishSlow] = pending();
  routes[programCourses(CS_BOS.id)] = () => slow;
  routes[programCourses(DS.id)] = () => page([course('3000', 'Data course')], 1, DS);
  await startWithPrograms();
  chooseMajor(CS_BOS);
  fireEvent.click(screen.getByRole('radio', { name: 'My major' }));
  wait(300);
  chooseMajor(DS);
  wait(300);
  expect(await screen.findByText('Data course')).toBeInTheDocument();
  await act(async () => finishSlow({ program: CS_BOS, results: [course('2500', 'Stale CS course')], total: 1 }));
  expect(screen.queryByText('Stale CS course')).not.toBeInTheDocument();
  expect(screen.getByText('Data course')).toBeInTheDocument();
});

test('open course placements follow the selected major, even for a course opened by code', async () => {
  const placement = (program, plan) => ({ major: program.id, program_title: program.label, plan_name: plan, year: 2, term: 'Fall' });
  routes['/api/course/CS/3000'] = () => json({ ...course('3000', 'Algorithms and Data'),
    plan_dataset: { catalog_year: '2025-2026', plan_count: 2 },
    schedule_context: [placement(CS_BOS, 'CS plan'), placement(DS, 'DS plan')] });
  routes['/api/analyze'] = () => json({ analysis: 'Tailored', model: 'free/model' });
  await startWithPrograms();
  chooseMajor(CS_BOS);
  ask('CS 3000');
  expect(await screen.findByText(/CS plan$/)).toBeInTheDocument();
  expect(screen.queryByText(/DS plan$/)).not.toBeInTheDocument();

  chooseMajor(DS);
  expect(screen.getByText(/DS plan$/)).toBeInTheDocument();
  expect(screen.queryByText(/CS plan$/)).not.toBeInTheDocument();
  expect(fetch.mock.calls.filter(([u]) => u === '/api/course/CS/3000')).toHaveLength(1); // no refetch to race

  fireEvent.click(screen.getByRole('button', { name: 'Clear major Data Science, BS (Boston)' }));
  expect(screen.getByText(/CS plan$/)).toBeInTheDocument();
  expect(screen.getByText(/DS plan$/)).toBeInTheDocument();
});

test('both breakdown paths send the major captured at request start, for default and custom AI', async () => {
  const [analysis, finish] = pending();
  routes['/api/analyze'] = () => analysis;
  await startWithPrograms();
  chooseMajor(CS_BOS);
  ask('CS 3000');
  expect(screen.getByText('For Computer Science, BSCS (Boston)')).toBeInTheDocument();
  chooseMajor(DS); // mid-generation: only later requests change
  await act(async () => finish({ analysis: 'CS answer', model: 'free/model' }));
  expect(screen.getByText('CS answer')).toBeInTheDocument();
  expect(screen.getByText('For Computer Science, BSCS (Boston)')).toBeInTheDocument();

  routes['/api/analyze'] = () => json({ analysis: 'DS answer', model: 'free/model' });
  await clickSearchResult('Fundies'); // the course detail button
  expect(await screen.findByText('DS answer')).toBeInTheDocument();
  expect(screen.getByText('For Data Science, BS (Boston)')).toBeInTheDocument();

  routes['/api/analyze'] = () => json({ analysis: 'Custom DS', model: 'gpt-6-luna', provider: 'openai' });
  configure();
  ask('CS 3000');
  expect(await screen.findByText('Custom DS')).toBeInTheDocument();

  expect(bodies('/api/analyze')).toEqual([
    { dept: 'CS', number: '3000', major: CS_BOS.id },
    { dept: 'cs', number: '2500', major: DS.id },
    { dept: 'CS', number: '3000', major: DS.id, ai: { mode: 'custom', provider: 'openai', api_key: 'sk-test-key', model: 'gpt-6-luna' } },
  ]);
});

// Concentrations are current requirement choices, independent of historical plans.
const concentrationUrl = (program) => `/api/programs/${program.id}/concentrations`;
const option = (id, name, courses = ['CS 4100']) => ({ id, name, courses, notes: [], kind: 'concentration',
  secondary_only: false, catalog_year: '2026-2027', source_url: 'https://catalog.northeastern.edu/example/',
  sections: [{ title: name, entries: [{ kind: 'text', text: 'Complete two elective courses.' }] }] });
const AI = option('ai-option', 'Artificial Intelligence');
const SYSTEMS = option('systems-option', 'Systems', ['CS 4700']);
const concentrationData = (options = [AI, SYSTEMS], year = '2026-2027') => ({ available: true, catalog_year: year,
  groups: [{ id: 'cs-group', title: 'Computer Science Concentrations', fixed: false,
    policy: { required: true, max_selections: 1, text: 'Choose one concentration.' }, options }] });

test('concentration selection persists, browses current options, and clears when major changes', async () => {
  routes[concentrationUrl(CS_BOS)] = () => json(concentrationData());
  routes[concentrationUrl(DS)] = () => json({ available: true, catalog_year: '2026-2027', groups: [] });
  routes[`${programCourses(CS_BOS.id)}&concentrations=ai-option`] = () => json({
    results: [course('4100', 'Principles of AI')], total: 1, concentration_dataset: { catalog_year: '2026-2027' } });
  await startWithPrograms();
  chooseMajor(CS_BOS);
  const select = await screen.findByLabelText('Concentration');
  fireEvent.change(select, { target: { value: AI.id } });
  expect(JSON.parse(localStorage.getItem('concentrations')).ids).toEqual([AI.id]);
  fireEvent.click(screen.getByText('View Artificial Intelligence requirements'));
  expect(screen.getByText('Complete two elective courses.')).toBeVisible();
  fireEvent.click(screen.getByRole('radio', { name: 'My concentrations' }));
  wait(300);
  expect(await screen.findByText('Principles of AI')).toBeInTheDocument();
  expect(screen.getByText(/selected 2026–2027 concentration requirements/)).toBeInTheDocument();

  cleanup();
  await startWithPrograms();
  await waitFor(() => expect(screen.getByLabelText('Concentration')).toHaveValue(AI.id));
  chooseMajor(DS);
  expect(screen.queryByRole('radio', { name: 'My concentrations' })).not.toBeInTheDocument();
  expect(await screen.findByText(/No concentration choices were found/)).toBeInTheDocument();
  expect(JSON.parse(localStorage.getItem('concentrations')).ids).toEqual([]);
});

test('breakdown captures selected concentration and course context follows later changes', async () => {
  routes[concentrationUrl(CS_BOS)] = () => json(concentrationData());
  routes['/api/course/CS/4100'] = () => json(course('4100', 'Principles of AI'));
  const [slow, finish] = pending();
  routes['/api/analyze'] = () => slow;
  await startWithPrograms();
  chooseMajor(CS_BOS);
  await screen.findByLabelText('Concentration');
  change('Concentration', AI.id);
  ask('CS 4100');
  await screen.findByRole('heading', { name: 'Your concentration choices' });
  expect(screen.getByText(/Listed in an explicit course row/)).toBeInTheDocument();
  change('Concentration', SYSTEMS.id);
  expect(screen.getByText(/No explicit course row lists this course/)).toBeInTheDocument();
  await act(async () => finish({ analysis: 'AI course answer', model: 'fixture' }));
  expect(bodies('/api/analyze')[0].concentrations).toEqual([AI.id]);
  expect(screen.getByText('Artificial Intelligence', { selector: '.breakdown .hint' })).toBeInTheDocument();
});

test('old catalog selections and slow responses cannot select another major’s concentrations', async () => {
  localStorage.setItem('major', JSON.stringify(CS_BOS));
  localStorage.setItem('concentrations', JSON.stringify({ majorId: CS_BOS.id, catalogYear: '2025-2026', ids: [AI.id] }));
  routes[concentrationUrl(CS_BOS)] = () => json(concentrationData());
  await startWithPrograms();
  await waitFor(() => expect(screen.getByLabelText('Concentration')).toHaveValue(''));
  expect(screen.queryByRole('radio', { name: 'My concentrations' })).not.toBeInTheDocument();
  const [slow, finish] = pending();
  routes[concentrationUrl(DS)] = () => slow;
  chooseMajor(DS);
  chooseMajor(CS_BOS);
  await screen.findByLabelText('Concentration');
  await act(async () => finish(concentrationData([option('stale', 'Wrong concentration')])));
  expect(screen.queryByRole('option', { name: 'Wrong concentration' })).not.toBeInTheDocument();
});

test('second-only options require primary selection and keep their slot when source order differs', async () => {
  const international = { ...option('international', 'International Business'), secondary_only: true };
  const management = option('management', 'Management');
  const data = concentrationData([international, management]);
  data.groups[0].policy.max_selections = 2;
  routes[concentrationUrl(CS_BOS)] = () => json(data);
  await startWithPrograms();
  chooseMajor(CS_BOS);
  await screen.findByLabelText('Concentration');
  expect(screen.queryByRole('option', { name: /International Business/ })).not.toBeInTheDocument();
  change('Concentration', management.id);
  change('Additional concentration 1', international.id);
  expect(screen.getByLabelText('Concentration')).toHaveValue(management.id);
  expect(screen.getByLabelText('Additional concentration 1')).toHaveValue(international.id);
  change('Concentration', '');
  expect(screen.getByLabelText('Concentration')).toHaveValue('');
  expect(screen.queryByRole('radio', { name: 'My concentrations' })).not.toBeInTheDocument();
});

const leaf = (course) => ({ kind: 'course', code: `${course.department_code.toUpperCase()} ${course.number}`, course });

test('My major groups writing alternatives under requirement headings and opens either description', async () => {
  const technical = { ...course('3302', 'Advanced Writing in the Technical Professions'), department_code: 'engw' };
  const interdisciplinary = { ...course('3315', 'Interdisciplinary Advanced Writing in the Disciplines'), department_code: 'engw' };
  routes[programCourses(CS_BOS.id, 'writing')] = () => json({
    program: CS_BOS, requirement_dataset: { available: true, catalog_year: '2026-2027' },
    results: [technical, interdisciplinary], total: 2,
    requirement_sections: [{ title: 'Computer Science Writing Requirement', entries: [
      { kind: 'header', text: 'Advanced Writing in the Disciplines' },
      { kind: 'any_of', children: [leaf(technical), leaf(interdisciplinary)] }] }] });
  routes['/api/course/engw/3302'] = () => json(technical);
  routes['/api/course/engw/3315'] = () => json(interdisciplinary);
  await startWithPrograms();
  chooseMajor(CS_BOS);
  fireEvent.click(screen.getByRole('radio', { name: 'My major' }));
  change('Search courses', 'writing');
  wait(300);
  expect(await screen.findByRole('heading', { name: 'Computer Science Writing Requirement' })).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Advanced Writing in the Disciplines' })).toBeInTheDocument();
  const group = screen.getByRole('group', { name: 'Choose one alternative' });
  expect(group).toHaveClass('requirement-choice');
  expect(within(group).getByText('or')).toBeInTheDocument();
  expect(within(group).getAllByRole('button')).toHaveLength(2);
  expect(screen.queryByText(/Choose one: ENGW/)).not.toBeInTheDocument();
  expect(screen.getByText(/2026–2027 major requirements/)).toBeInTheDocument();
  for (const c of [technical, interdisciplinary]) {
    fireEvent.click(screen.getByRole('button', { name: new RegExp(c.title) }));
    expect(await screen.findByText(c.description)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Back to results/ }));
    expect(screen.getByRole('button', { name: new RegExp(c.title) })).toHaveFocus();
  }
});

test('My concentrations preserves section headings and AND bundles inside outlined OR choices', async () => {
  routes[concentrationUrl(CS_BOS)] = () => json(concentrationData([SYSTEMS]));
  const network = course('4700', 'Network Fundamentals');
  const lab = course('4701', 'Network Lab');
  const distributed = course('4730', 'Distributed Systems');
  routes[`${programCourses(CS_BOS.id)}&concentrations=systems-option`] = () => json({
    results: [network, lab, distributed], total: 3,
    requirement_sections: [{ title: 'Security Required Courses', owner: 'Systems', entries: [
      { kind: 'instruction', text: 'Complete one of the following:' },
      { kind: 'any_of', children: [{ kind: 'all_of', children: [leaf(network), leaf(lab)] }, leaf(distributed)] }] },
    { title: 'Supporting Courses', entries: [{ kind: 'text', text: 'Complete 4 credits of electives.' }] }],
    concentration_dataset: { catalog_year: '2026-2027' } });
  routes['/api/course/cs/4730'] = () => json(distributed);
  await startWithPrograms();
  chooseMajor(CS_BOS);
  await screen.findByLabelText('Concentration');
  change('Concentration', SYSTEMS.id);
  fireEvent.click(screen.getByRole('radio', { name: 'My concentrations' }));
  wait(300);
  expect(await screen.findByRole('heading', { name: 'Security Required Courses' })).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Supporting Courses' })).toBeInTheDocument();
  expect(screen.getByText('Complete one of the following:')).toBeInTheDocument();
  const group = screen.getByRole('group', { name: 'Choose one alternative' });
  expect(within(group).getAllByRole('button')).toHaveLength(3);
  expect(within(group).getByText('or')).toBeInTheDocument();
  const bundle = within(group).getByRole('group', { name: 'Complete all courses in this option' });
  expect(within(bundle).getAllByRole('button')).toHaveLength(2);
  expect(within(bundle).getByText('and')).toBeInTheDocument();
  fireEvent.click(within(group).getByRole('button', { name: /Distributed Systems/ }));
  expect(await screen.findByText(distributed.description)).toBeInTheDocument();
});
