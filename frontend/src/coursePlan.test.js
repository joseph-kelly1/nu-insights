import {
  buildTerms, defaultTarget, draftFrom, newPlan, parseCodes, planReducer, readPlan, removalConflicts, termLabel, toPayload,
} from './coursePlan';

const base = (start = { year: 2025, session: 'fall' }, target = defaultTarget(start)) => newPlan({
  programId: 'bscs', catalogYear: '2026-2027', concentrationIds: ['ai'], start, current: { year: 2026, session: 'fall' }, target,
});
const run = (plan, ...actions) => actions.reduce(planReducer, plan);

test('legacy archived course codes can be entered without guessing names', () => {
  expect(parseCodes('biol 13lm, acct215m')).toEqual(['BIOL 13LM', 'ACCT 215M']);
});

test('edition-specific concentration changes preserve history and pinned choices', () => {
  const original = { ...base(), attempts: [
    { id: 'history', source: 'user', status: 'passed' },
    { id: 'keep', source: 'generated', pinned: true },
    { id: 'old-suggestion', source: 'generated', pinned: false },
  ] };
  const updated = run(original, { type: 'setConcentrations', ids: ['archived-ai'] });
  expect(updated.concentration_ids).toEqual(['archived-ai']);
  expect(updated.attempts.map((a) => a.id)).toEqual(['history', 'keep']);
  expect(updated.catalog_year).toBe(original.catalog_year);
  const older = run(original, { type: 'setCatalogYear', year: '2024-2025' });
  expect(older.catalog_year).toBe('2024-2025');
  expect(older.attempts.map((a) => a.id)).toEqual(['history', 'keep']);
  expect(older.exams).toEqual(original.exams);
});

test('AP/IB inputs survive import, export, changed requirements, and applied proposals', () => {
  const exams = [{ id: 'ap-math', exam_id: 'ap:calculus-bc', score: 5, level: null,
    policy_year: '2026-2027', version: '1234567890abcdef', state: 'awarded', name: 'Calculus BC',
    equivalents: [{ code: 'MATH 1341', credits: 4 }] }];
  const saved = run(base(), { type: 'setExams', exams }, { type: 'applyProposal', attempts: [] });
  const imported = readPlan(JSON.stringify(saved));
  expect(imported.exams[0]).toMatchObject({ exam_id: 'ap:calculus-bc', score: 5, state: 'awarded' });
  expect(imported.exams[0]).not.toHaveProperty('equivalents');
  expect(toPayload(imported).exams[0]).not.toHaveProperty('equivalents');
  expect(toPayload(imported).exams[0]).toMatchObject({ exam_id: 'ap:calculus-bc', score: 5, state: 'awarded' });
  expect(draftFrom(imported, { catalogYear: '2027-2028', concentrationIds: [] }).exams).toEqual(imported.exams);
  const old = base(); delete old.exams;
  expect(readPlan(JSON.stringify(old)).exams).toEqual([]);
  expect(() => readPlan(JSON.stringify({ ...old, exams: 'bad' }))).toThrow(/AP\/IB exams are invalid/);
});

test('a spring start keeps calendar years and runs four years by default', () => {
  const start = { year: 2026, session: 'spring' };
  const terms = buildTerms(start, defaultTarget(start));
  expect(terms.slice(0, 5).map(termLabel)).toEqual(['Spring 2026', 'Summer 1 / Session A 2026', 'Summer 2 / Session B 2026',
    'Fall 2026', 'Spring 2027']);
  expect(termLabel(terms[terms.length - 1])).toBe('Fall 2029');
  expect(termLabel(defaultTarget({ year: 2025, session: 'fall' }))).toBe('Spring 2029'); // final year ends before summer
});

test('a three-year plan can grow a year and shrink only with an explicit discard', () => {
  const start = { year: 2025, session: 'fall' };
  let plan = base(start, { year: 2028, session: 'spring' });
  plan = run(plan, { type: 'addAttempts', termId: 'fall-2025', courses: [{ code: 'CS 2000', credits: 4 }] },
    { type: 'setTarget', target: { year: 2030, session: 'spring' } },
    { type: 'addAttempts', termId: 'fall-2029', courses: [{ code: 'CS 4100', credits: 4 }] });
  expect(plan.terms).toHaveLength(18); // fall 2025 through spring 2030
  expect(plan.attempts.map((a) => a.code)).toEqual(['CS 2000', 'CS 4100']); // history survives growing
  const shorter = { year: 2029, session: 'spring' };
  expect(removalConflicts(plan, shorter).attempts.map((a) => a.code)).toEqual(['CS 4100']);
  expect(run(plan, { type: 'setTarget', target: shorter })).toBe(plan); // nothing is dropped silently
  const shortened = run(plan, { type: 'setTarget', target: shorter, discard: true });
  expect(shortened.attempts.map((a) => a.code)).toEqual(['CS 2000']);
  expect(run(plan, { type: 'setTarget', target: { year: 2025, session: 'fall' } })).toBe(plan); // can't cut history
});

test('courses default to the term: history passed, current in progress, future planned and pinned', () => {
  const plan = run(base(), ...['fall-2025', 'fall-2026', 'spring-2027', null].map((termId) => (
    { type: 'addAttempts', termId, courses: [{ code: 'CS 3000', credits: 4 }] })));
  expect(plan.attempts.map((a) => [a.status, a.pinned, a.origin])).toEqual([
    ['passed', false, 'nu'], ['in_progress', false, 'nu'], ['planned', true, 'nu'], ['passed', false, 'ap']]);
  const moved = run(plan, { type: 'moveAttempt', id: plan.attempts[0].id, termId: 'spring-2027' });
  expect(moved.attempts[0]).toMatchObject({ term_id: 'spring-2027', status: 'planned', pinned: true, grade: null });
});

test('a co-op is one continuous experience and never overlaps another', () => {
  let plan = run(base(), { type: 'addCoop', termId: 'spring-2027' });
  const [coop] = plan.experiences;
  plan = run(plan, { type: 'extendCoop', id: coop.id });
  expect(plan.experiences[0].term_ids).toEqual(['spring-2027', 'summer1-2027']);
  plan = run(plan, { type: 'addCoop', termId: 'summer2-2027' }, { type: 'extendCoop', id: coop.id });
  expect(plan.experiences.map((e) => e.term_ids)).toEqual([['spring-2027', 'summer1-2027'], ['summer2-2027']]);
  expect(run(plan, { type: 'addCoop', termId: 'summer1-2027' }).experiences).toHaveLength(2);
});

test('skipping summers keeps terms that hold courses or a co-op', () => {
  const plan = run(base(), { type: 'addCoop', termId: 'summer1-2027' },
    { type: 'addAttempts', termId: 'summer1-2028', courses: [{ code: 'CS 3800', credits: 4 }] },
    { type: 'skipSession', session: 'summer1' });
  const modes = Object.fromEntries(plan.terms.filter((t) => t.session === 'summer1').map((t) => [t.id, t.mode]));
  expect(modes).toEqual({ 'summer1-2026': 'open', 'summer1-2027': 'open', 'summer1-2028': 'open' }); // 2026 is history
  const later = run(base({ year: 2025, session: 'fall' }, { year: 2030, session: 'spring' }), { type: 'skipSession', session: 'summer1' });
  expect(later.terms.find((t) => t.id === 'summer1-2029').mode).toBe('off');
});

test('imports and saved drafts are validated and stripped of anything unexpected', () => {
  const plan = run(base(), { type: 'addAttempts', termId: 'fall-2025', courses: [{ code: 'CS 2000', credits: 4 }] });
  const tampered = JSON.stringify({ ...plan, api_key: 'sk-secret', prompt: 'x' });
  const read = readPlan(tampered, 'bscs');
  expect(read).not.toHaveProperty('api_key');
  expect(read.attempts).toHaveLength(1);
  expect(() => readPlan('{nope', 'bscs')).toThrow('isn’t a saved course plan');
  expect(() => readPlan(tampered, 'other')).toThrow('different major');
  expect(() => readPlan(JSON.stringify({ ...plan, terms: [{ id: 'x', year: 1, session: 'winter' }] }), 'bscs')).toThrow('terms');
  expect(Object.keys(toPayload(plan)).sort()).toEqual(['attempts', 'catalog_year', 'concentration_ids', 'current_term',
    'exams', 'experiences', 'preferences', 'program_id', 'revision', 'sample_variant', 'schema_version', 'terms']);
});

test('a new draft for other requirements keeps history and pins but drops suggestions', () => {
  const plan = { ...base(), attempts: [{ id: 'h', code: 'CS 2000', source: 'user' }, { id: 'g', code: 'CS 4100', source: 'generated' },
    { id: 'p', code: 'CS 4120', source: 'generated', pinned: true }] };
  const next = draftFrom(plan, { catalogYear: '2025-2026', concentrationIds: [] });
  expect(next.attempts.map((a) => a.id)).toEqual(['h', 'p']);
  expect([next.catalog_year, next.revision]).toEqual(['2025-2026', 0]);
});

test('pasted lists become unique, normalized codes', () => {
  expect(parseCodes('cs2500, CS 2510\nmath 1341; cs 2500 and CIS 201M')).toEqual(['CS 2500', 'CS 2510', 'MATH 1341', 'CIS 201M']);
});
