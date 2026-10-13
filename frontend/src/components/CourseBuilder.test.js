import React from 'react';
import { render, screen, fireEvent, waitFor, within, act } from '@testing-library/react';
import CourseBuilder from './CourseBuilder';
import { newPlan, saveDraft } from '../coursePlan';

const MAJOR = { id: 'bscs', label: 'Computer Science, BSCS (Boston)' };
const CONCENTRATIONS = [{ id: 'ai', name: 'Artificial Intelligence' }];
const CONTEXT = { capability: 'reviewed', fingerprint: 'fp', issues: [], selection_errors: [],
  sample_variants: [1, 2].map((n) => ({ id: `v${n}`, name: `Plan ${n}`, catalog_year: '2025-2026', semesters: [
    { year: 1, term: 'Fall', entries: [{ kind: 'course', text: 'CS 2000 and CS 2001', courses: ['CS 2000', 'CS 2001'] },
      { kind: 'choice', text: 'MATH 1365 or 1465', courses: ['MATH 1365', 'MATH 1465'] },
      ...(n === 1 ? [{ kind: 'course', text: 'CS 2500', courses: ['CS 2500'] }] : [])] }] })),
  course_info: { 'CS 2000': { title: 'Intro to Program Design', credits: 4 }, 'CS 2001': { title: 'Lab for CS 2000', credits: 1 },
    'MATH 1365': { title: 'Mathematical Reasoning', credits: 4 }, 'MATH 1465': { title: 'Intensive Reasoning', credits: 4 } } };
const ok = (body) => Promise.resolve({ ok: true, status: 200, json: async () => body });
const fail = (status, body) => Promise.resolve({ ok: false, status, json: async () => body });
const REPORT = { revision: 0, errors: [{ message: 'CS 3000 in Spring 2027: prerequisites are not met by earlier terms.', term_id: 'spring-2027' }],
  warnings: [], assumptions: ['Planned courses are assumed to be passed.'], issues: [{ id: 'gpa', text: 'Minimum 2.000 GPA required.', source_url: '' }],
  requirements: [{ id: 'r1', title: 'Security Required Course', section: 'Computer Science Requirements', status: 'unsatisfied',
    progress: '0 of 1', review: 'reviewed', kind: 'choose', need: 1, options: ['CY 2550', 'CY 3740'], courses: [] }],
  coverage: 'incomplete', offerings: 'Term offerings are unverified.', sources: [] };

let routes;
let posts;
beforeEach(() => {
  localStorage.clear();
  posts = [];
  routes = {
    'planning-context': () => ok(CONTEXT),
    '/api/course/cs/2000': () => ok({ title: 'Intro to Program Design', credits: 4, credit_options: { values: [4] } }),
    '/api/course/cs/9999': () => fail(404, { error: 'Course not found' }),
  };
  global.fetch = jest.fn((url, opts) => {
    if (opts?.method === 'POST') posts.push({ url, body: JSON.parse(opts.body) });
    const route = Object.keys(routes).find((k) => url.includes(k));
    return route ? routes[route](opts) : fail(404, {});
  });
});

const renderBuilder = (props = {}) => render(<CourseBuilder major={MAJOR} concentrations={CONCENTRATIONS}
  ai={{ mode: 'default' }} aiLabel="App default (free)" onBack={jest.fn()} onOpenCourse={jest.fn()} onCloseCourse={jest.fn()}
  detail={null} {...props} />);

function savedPlan() {
  const plan = newPlan({ programId: 'bscs', catalogYear: '2026-2027', concentrationIds: ['ai'], start: { year: 2025, session: 'fall' },
    current: { year: 2026, session: 'fall' }, target: { year: 2029, session: 'spring' } });
  saveDraft(plan);
  return plan;
}

const proposalBody = (revision) => ({ status: 'complete', coverage: { sample_variant: null }, suggestions: [], generation: { mode: 'deterministic' },
  report: { ...REPORT, errors: [], revision: null, coverage: 'all_modeled_covered' },
  proposal: { revision, dataset: 'fp', diff: { added: [{ code: 'CS 3800', term: 'Spring 2027' }], moved: [], removed: [] },
    attempts: [{ id: 'gen:CS 3800:spring-2027', term_id: 'spring-2027', code: 'CS 3800', credits: 4, status: 'planned', grade: null,
      origin: 'nu', pinned: false, source: 'generated', counts_as: null, evidence: '', placeholder: null, title: 'Theory',
      reason: 'Counts toward Computer Science Required Courses.' }] } });

test('setup builds a four-year timeline and courses are added from a previewed pasted list', async () => {
  renderBuilder();
  fireEvent.change(screen.getByLabelText('First term at Northeastern: year'), { target: { value: '2025' } });
  fireEvent.change(screen.getByLabelText('First term at Northeastern: session'), { target: { value: 'fall' } });
  fireEvent.change(screen.getByLabelText('Current term (or the next one, if you’re between terms): year'), { target: { value: '2026' } });
  fireEvent.change(screen.getByLabelText('Current term (or the next one, if you’re between terms): session'), { target: { value: 'fall' } });
  expect(screen.getByRole('button', { name: 'Start my plan' })).toBeDisabled(); // the catalog year is never assumed
  fireEvent.change(screen.getByLabelText('Requirements catalog year'), { target: { value: '2026-2027' } });
  fireEvent.click(screen.getByRole('button', { name: 'Start my plan' }));

  expect(await screen.findByRole('heading', { name: 'Fall 2025' })).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Spring 2029' })).toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: 'Summer 1 / Session A 2029' })).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: 'Edit Fall 2025' }));
  fireEvent.change(screen.getByLabelText('Add courses to Fall 2025'), { target: { value: 'cs 2000\nCS 9999' } });
  fireEvent.click(screen.getByRole('button', { name: 'Find courses' }));
  expect(await screen.findByText(/CS 2000 · Intro to Program Design · 4 credits/)).toBeInTheDocument();
  expect(screen.getByText(/Not in the current catalog. It will stay in your history/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Add 2 courses' }));
  const fall = screen.getByRole('region', { name: 'Fall 2025' });
  expect(await within(fall).findByRole('button', { name: 'CS 2000' })).toBeInTheDocument();
  expect(within(fall).getByRole('button', { name: 'CS 9999' })).toBeInTheDocument();
  expect(within(fall).getByText('8 credits')).toBeInTheDocument();
  expect(screen.getByText('Saved in this browser.')).toBeInTheDocument();
  expect(JSON.parse(localStorage.getItem('coursePlan:v1:bscs:2026-2027:ai')).attempts).toHaveLength(2);
});

test('checking a plan shows problems next to the term and the full report without any AI call', async () => {
  savedPlan();
  routes['/api/planner/validate'] = () => ok(REPORT);
  renderBuilder();
  fireEvent.click(await screen.findByRole('button', { name: 'Check my plan' }));
  expect(await screen.findByText('Not yet met')).toBeInTheDocument();
  expect(posts.map((p) => p.url)).toEqual(['/api/planner/validate']);
  expect(posts[0].body.plan).not.toHaveProperty('api_key');
  expect(within(screen.getByRole('region', { name: 'Spring 2027' })).getByText(/1 problem: CS 3000/)).toBeInTheDocument();
  expect(screen.getByText('Minimum 2.000 GPA required.')).toBeInTheDocument();
  expect(screen.getByText(/not an official degree audit/)).toBeInTheDocument();
});

test('a proposal is previewed, then applied; the saved plan is unchanged until Apply', async () => {
  savedPlan();
  routes['/api/planner/generate'] = () => ok(proposalBody(0));
  renderBuilder();
  await screen.findByText(/were reviewed against the catalog/);
  fireEvent.click(screen.getByRole('button', { name: 'Fill without AI' }));
  expect(await screen.findByRole('heading', { name: 'Suggested plan' })).toBeInTheDocument();
  expect(posts[0].body).toMatchObject({ mode: 'deterministic', dataset: 'fp' });
  const spring = screen.getByRole('region', { name: 'Spring 2027' });
  expect(within(spring).getByText('Suggested')).toBeInTheDocument();
  expect(JSON.parse(localStorage.getItem('coursePlan:v1:bscs:2026-2027:ai')).attempts).toHaveLength(0);
  fireEvent.click(screen.getByRole('button', { name: 'Apply suggestions' }));
  expect(screen.queryByRole('heading', { name: 'Suggested plan' })).not.toBeInTheDocument();
  expect(JSON.parse(localStorage.getItem('coursePlan:v1:bscs:2026-2027:ai')).attempts.map((a) => a.code)).toEqual(['CS 3800']);
});

test('a late proposal for an older revision cannot be applied', async () => {
  savedPlan();
  let resolve;
  routes['/api/planner/generate'] = () => new Promise((r) => { resolve = r; });
  renderBuilder();
  await screen.findByText(/were reviewed against the catalog/);
  fireEvent.click(screen.getByRole('button', { name: 'Fill without AI' }));
  fireEvent.click(screen.getByText('Timeline and preferences'));
  fireEvent.change(screen.getByLabelText('Interests or career goals'), { target: { value: 'robotics' } }); // edit while pending
  await act(async () => resolve({ ok: true, status: 200, json: async () => proposalBody(0) }));
  expect(await screen.findByText(/changed while this was being built/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Apply suggestions' })).toBeDisabled();
  expect(within(screen.getByRole('region', { name: 'Spring 2027' })).queryByText('CS 3800')).not.toBeInTheDocument();
});

test('an AI failure keeps the draft and offers generation without AI', async () => {
  savedPlan();
  routes['/api/planner/generate'] = (opts) => (JSON.parse(opts.body).mode === 'ai'
    ? fail(502, { error: 'The AI returned an unusable ranking (unknown or repeated course).', code: 'ai_bad_ranking', deterministic_available: true })
    : ok(proposalBody(0)));
  renderBuilder();
  await screen.findByText(/were reviewed against the catalog/);
  fireEvent.click(screen.getByRole('button', { name: 'Fill remaining courses' }));
  expect(await screen.findByText(/unusable ranking/)).toBeInTheDocument();
  expect(screen.getByText('Your plan hasn’t changed.')).toBeInTheDocument();
  fireEvent.click(within(screen.getByRole('alert')).getByRole('button', { name: 'Fill without AI' }));
  await screen.findByRole('heading', { name: 'Suggested plan' });
  expect(posts.map((p) => p.body.mode)).toEqual(['ai', 'deterministic']); // one AI call, no automatic retry
});

test('a custom provider without a key never sends a request', async () => {
  savedPlan();
  renderBuilder({ ai: { mode: 'custom', provider: 'openai', model: 'gpt-x', apiKey: '' } });
  await screen.findByText(/were reviewed against the catalog/);
  fireEvent.click(screen.getByRole('button', { name: 'Fill remaining courses' }));
  expect(screen.getByText(/Add your API key and model/)).toBeInTheDocument();
  expect(posts).toEqual([]);
});

test('off terms explain conflicts instead of deleting courses; blocked storage keeps the draft usable', async () => {
  const plan = savedPlan();
  saveDraft({ ...plan, attempts: [{ id: 'p1', term_id: 'spring-2027', code: 'CS 3800', credits: 4, status: 'planned', pinned: true,
    origin: 'nu', source: 'user', grade: null, counts_as: null, evidence: '', placeholder: null, title: 'Theory' }] });
  const setItem = jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota'); });
  renderBuilder();
  fireEvent.click(await screen.findByRole('button', { name: 'Edit Spring 2027' }));
  fireEvent.click(screen.getByRole('radio', { name: 'Off' }));
  expect(screen.getByText(/has 1 course\. Nothing is removed unless you choose to/)).toBeInTheDocument();
  expect(screen.getByRole('radio', { name: 'Open for planning' })).toBeChecked();
  fireEvent.click(screen.getByRole('button', { name: 'Keep everything' }));
  expect(within(screen.getByRole('region', { name: 'Spring 2027' })).getByRole('button', { name: 'CS 3800' })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Move to'), { target: { value: 'fall-2027' } }); // keyboard-usable move menu
  await waitFor(() => expect(screen.getByText(/Not saved: this browser blocked storage/)).toBeInTheDocument());
  expect(within(screen.getByRole('region', { name: 'Fall 2027' })).getByRole('button', { name: 'CS 3800' })).toBeInTheDocument();
  setItem.mockRestore();
});

test('a term offers its common sample-plan courses; a lecture and lab add together', async () => {
  savedPlan();
  renderBuilder();
  fireEvent.click(await screen.findByRole('button', { name: 'Edit Fall 2025' }));
  const common = screen.getByRole('region', { name: 'Common in year 1, Fall' });
  expect(within(common).getByText(/From 2 2025–2026 sample plans/)).toBeInTheDocument();
  expect(within(common).getByText(/1 of 2 plans · not in the current catalog/)).toBeInTheDocument(); // CS 2500
  expect(within(common).getByRole('button', { name: 'Add CS 2500' })).toBeDisabled();
  expect(within(common).getAllByText(/option in “MATH 1365 or 1465”/)).toHaveLength(2); // each side of the choice
  fireEvent.click(within(common).getByRole('button', { name: 'Add CS 2000 + CS 2001' }));
  const fall = screen.getByRole('region', { name: 'Fall 2025' });
  expect(await within(fall).findByRole('button', { name: 'CS 2001' })).toBeInTheDocument();
  expect(within(fall).getByText('5 credits')).toBeInTheDocument();
  expect(within(common).getByRole('button', { name: 'Add CS 2000 + CS 2001' })).toHaveTextContent('Added');
  fireEvent.click(screen.getByRole('button', { name: 'Edit Fall 2026' }));
  expect(screen.getByText('The sample plans list no specific courses for this term (electives or co-op).')).toBeInTheDocument();
});

test('course names go to the AI as suggestions the student confirms; codes resolve directly', async () => {
  savedPlan();
  routes['/api/planner/identify'] = () => ok({ model: 'm', matches: [
    { input: 'discrete math', code: 'CS 1800', title: 'Discrete Structures', credits: 4, reason: 'Year 1 fall in your plans' },
    { input: 'underwater basket weaving', code: null, reason: '' }] });
  renderBuilder();
  fireEvent.click(await screen.findByRole('button', { name: 'Edit Fall 2025' }));
  fireEvent.change(screen.getByLabelText('Add courses to Fall 2025'), { target: { value: 'cs 2000, discrete math\nunderwater basket weaving' } });
  fireEvent.click(screen.getByRole('button', { name: 'Find courses' }));
  expect(await screen.findByText(/Best guess for “discrete math”: Year 1 fall in your plans/)).toBeInTheDocument();
  expect(screen.getByText(/No match for “underwater basket weaving”/)).toBeInTheDocument();
  expect(posts[0]).toEqual({ url: '/api/planner/identify', body: { program_id: 'bscs', phrases: ['discrete math', 'underwater basket weaving'],
    term: 'Fall 2025' } });
  fireEvent.click(screen.getByRole('checkbox', { name: /CS 2000 · Intro/ })); // the student can decline any match
  fireEvent.click(screen.getByRole('button', { name: 'Add 1 course' }));
  const fall = screen.getByRole('region', { name: 'Fall 2025' });
  expect(await within(fall).findByRole('button', { name: 'CS 1800' })).toBeInTheDocument();
  expect(within(fall).queryByRole('button', { name: 'CS 2000' })).not.toBeInTheDocument();
});

test('a failed name match falls back to the title search', async () => {
  savedPlan();
  routes['/api/planner/identify'] = () => fail(503, { error: 'No free AI model is available right now.', code: 'ai_unavailable' });
  routes['/api/search'] = () => ok([{ department_code: 'cs', number: '1800', title: 'Discrete Structures', credits: 4 }]);
  renderBuilder();
  fireEvent.click(await screen.findByRole('button', { name: 'Edit Fall 2025' }));
  fireEvent.change(screen.getByLabelText('Add courses to Fall 2025'), { target: { value: 'discrete structures' } });
  fireEvent.click(screen.getByRole('button', { name: 'Find courses' }));
  expect(await screen.findByText(/No free AI model is available right now. Use the title search below instead/)).toBeInTheDocument();
  expect(screen.getByLabelText('Search by title or code')).toHaveValue('discrete structures');
  expect(await screen.findByRole('button', { name: 'Add CS 1800' })).toBeInTheDocument();
});

test('title search updates live as you type, and only the newest query answers', async () => {
  savedPlan();
  const answers = {};
  routes['/api/search'] = (opts) => new Promise((resolve) => { answers[fetch.mock.calls.at(-1)[0]] = resolve; });
  renderBuilder();
  fireEvent.click(await screen.findByRole('button', { name: 'Edit Fall 2025' }));
  const box = screen.getByLabelText('Search by title or code');
  fireEvent.change(box, { target: { value: 'mach' } });
  await waitFor(() => expect(answers['/api/search?q=mach']).toBeDefined());
  fireEvent.change(box, { target: { value: 'machine learning' } });
  await waitFor(() => expect(answers['/api/search?q=machine%20learning']).toBeDefined());
  await act(async () => answers['/api/search?q=machine%20learning']({ ok: true, json: async () => [
    { department_code: 'ds', number: '4400', title: 'Machine Learning', credits: 4 }] }));
  await act(async () => answers['/api/search?q=mach']({ ok: true, json: async () => [
    { department_code: 'me', number: '1000', title: 'Machining', credits: 4 }] }));
  expect(screen.getByRole('button', { name: 'Add DS 4400' })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Add ME 1000' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Search' })).not.toBeInTheDocument(); // no button needed
});

test('adding a lecture brings its lab and seminar, even when the catalog lists only one as a corequisite', async () => {
  savedPlan();
  routes['/api/course/phys/1151'] = () => ok({ title: 'Physics for Engineering 1', credits: 3, credit_options: { values: [3] },
    companions: [{ code: 'PHYS 1152', title: 'Lab for PHYS 1151', credits: 1, why: 'Lab for PHYS 1151' },
      { code: 'PHYS 1153', title: 'Interactive Learning Seminar for PHYS 1151', credits: 1, why: 'listed corequisite' }] });
  renderBuilder();
  fireEvent.click(await screen.findByRole('button', { name: 'Edit Spring 2027' }));
  fireEvent.change(screen.getByLabelText('Add courses to Spring 2027'), { target: { value: 'PHYS 1151' } });
  fireEvent.click(screen.getByRole('button', { name: 'Find courses' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Add 1 course' }));
  const spring = screen.getByRole('region', { name: 'Spring 2027' });
  expect(await within(spring).findByRole('button', { name: 'PHYS 1152' })).toBeInTheDocument();
  expect(within(spring).getByRole('button', { name: 'PHYS 1153' })).toBeInTheDocument();
  expect(within(spring).getByText('5 credits')).toBeInTheDocument();
  expect(screen.getByText('Also added PHYS 1152 (Lab for PHYS 1151), PHYS 1153 (listed corequisite). '
    + 'Remove any your program doesn’t need.')).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: 'Done' }));
  fireEvent.click(screen.getByRole('button', { name: 'Add AP, IB, or transfer credit' }));
  fireEvent.change(screen.getByLabelText('Add courses to Credit before enrollment'), { target: { value: 'PHYS 1151' } });
  fireEvent.click(screen.getByRole('button', { name: 'Find courses' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Add 1 course' }));
  await screen.findByText(/PHYS 1151 \(3\)/); // awarded credit is recorded exactly, without companions
  expect(screen.queryByText(/PHYS 1152 \(1\)/)).not.toBeInTheDocument();
});

test('choosing Edit while course details are open shows the term editor', async () => {
  savedPlan();
  function WithDetails() {
    const [open, setOpen] = React.useState(true);
    return <CourseBuilder major={MAJOR} concentrations={CONCENTRATIONS} ai={{ mode: 'default' }} aiLabel="App default (free)"
      onBack={jest.fn()} onOpenCourse={() => setOpen(true)} onCloseCourse={() => setOpen(false)}
      detail={open ? <p>CS 3000 details</p> : null} />;
  }
  render(<WithDetails />);
  expect(await screen.findByText('CS 3000 details')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Edit Spring 2027' }));
  expect(screen.queryByText('CS 3000 details')).not.toBeInTheDocument();
  expect(screen.getByRole('region', { name: 'Edit Spring 2027' })).toBeInTheDocument();
});
