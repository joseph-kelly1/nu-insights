// Course plan state: timeline math, the one reducer for coupled edits, and local persistence.
// Kept free of React so the academic edge cases (spring starts, removed terms, co-op spans) test directly.

export const SCHEMA_VERSION = 1;
export const YEAR_ORDER = ['fall', 'spring', 'summer1', 'summer2']; // one academic year, as shown
const CALENDAR = ['spring', 'summer1', 'summer2', 'fall']; // order within a calendar year
export const SESSION_LABELS = { fall: 'Fall', spring: 'Spring', summer1: 'Summer 1 / Session A', summer2: 'Summer 2 / Session B' };
export const DEFAULT_LOAD = { fall: [16, 20], spring: [16, 20], summer1: [8, 10], summer2: [8, 10] }; // [target, limit]
export const LIMITS = { terms: 40, attempts: 300 };

export const termKey = ({ year, session }) => year * 4 + CALENDAR.indexOf(session);
const fromKey = (key) => ({ year: Math.floor(key / 4), session: CALENDAR[key % 4] });
export const termId = ({ year, session }) => `${session}-${year}`;
export const termLabel = (t) => `${SESSION_LABELS[t.session]} ${t.year}`;
export const shortLabel = (t) => `${SESSION_LABELS[t.session].split(' /')[0]} ${t.year}`;
export const academicYear = (t) => (t.session === 'fall' ? t.year : t.year - 1); // fall Y → spring Y+1 → summers Y+1
export const termStatus = (term, current) => {
  const a = termKey(term);
  const b = termKey(current);
  return a < b ? 'past' : a === b ? 'current' : 'future';
};

// Four academic years by default. A fall start ends before the final summer;
// a spring or summer start keeps its calendar year and ends the fall four years on.
export function defaultTarget(start) {
  const ay = academicYear(start) + 4;
  return start.session === 'fall' ? { year: ay, session: 'spring' } : { year: ay, session: 'fall' };
}

export function buildTerms(start, target, existing = []) {
  const kept = new Map(existing.map((t) => [t.id, t]));
  const terms = [];
  for (let key = termKey(start); key <= termKey(target) && terms.length < LIMITS.terms; key += 1) {
    const t = fromKey(key);
    const id = termId(t);
    const [target_, cap] = DEFAULT_LOAD[t.session];
    terms.push(kept.get(id) || { id, ...t, mode: 'open', credit_target: target_, credit_cap: cap });
  }
  return terms;
}

export const nextTerm = (t) => fromKey(termKey(t) + 1);

export function newPlan({ programId, catalogYear, concentrationIds, start, current, target, interests = '' }) {
  return {
    schema_version: SCHEMA_VERSION,
    id: `plan-${Date.now().toString(36)}`,
    revision: 0,
    program_id: programId,
    catalog_year: catalogYear,
    concentration_ids: concentrationIds,
    start,
    current_term: current,
    target,
    terms: buildTerms(start, target),
    attempts: [],
    exams: [],
    experiences: [],
    preferences: { interests },
    sample_variant: null,
    updated_at: new Date().toISOString(),
  };
}

let counter = 0;
const newId = (prefix) => `${prefix}-${Date.now().toString(36)}-${(counter += 1)}`;

// Entries a shorter horizon would drop, so the UI can ask before discarding anything.
export function removalConflicts(plan, target) {
  const removed = new Set(plan.terms.filter((t) => termKey(t) > termKey(target)).map((t) => t.id));
  return {
    terms: plan.terms.filter((t) => removed.has(t.id)),
    attempts: plan.attempts.filter((a) => removed.has(a.term_id)),
    coops: plan.experiences.filter((e) => e.term_ids.some((id) => removed.has(id))),
  };
}

export const coopFor = (plan, id) => plan.experiences.find((e) => e.term_ids.includes(id));

// Which future terms of one summer session can be skipped, and why the others can't.
export function skipPlan(plan, session) {
  return plan.terms.filter((t) => t.session === session && termStatus(t, plan.current_term) === 'future' && t.mode !== 'off')
    .map((t) => {
      const courses = plan.attempts.filter((a) => a.term_id === t.id).length;
      const reason = coopFor(plan, t.id) ? 'has a co-op' : courses ? `has ${courses} course${courses === 1 ? '' : 's'}` : '';
      return { term: t, reason };
    });
}

function defaultsFor(plan, termId_) {
  const term = plan.terms.find((t) => t.id === termId_);
  const status = term ? termStatus(term, plan.current_term) : 'past';
  if (!term) return { status: 'passed', origin: 'ap', pinned: false };
  return { status: { past: 'passed', current: 'in_progress', future: 'planned' }[status], origin: 'nu', pinned: status === 'future' };
}

export function planReducer(plan, action) {
  const next = (changes) => ({ ...plan, ...changes, revision: plan.revision + 1, updated_at: new Date().toISOString() });
  switch (action.type) {
    case 'replace':
      return action.plan;
    case 'setTarget': {
      if (termKey(action.target) < Math.max(termKey(plan.current_term), termKey(plan.start))) return plan;
      const gone = removalConflicts(plan, action.target);
      if ((gone.attempts.length || gone.coops.length) && !action.discard) return plan; // the UI asks first
      const ids = new Set(gone.terms.map((t) => t.id));
      return next({
        target: action.target,
        terms: buildTerms(plan.start, action.target, plan.terms),
        attempts: plan.attempts.filter((a) => !ids.has(a.term_id)),
        experiences: plan.experiences.filter((e) => !e.term_ids.some((id) => ids.has(id))),
      });
    }
    case 'setCurrent':
      return next({ current_term: action.current });
    case 'setTerm':
      return next({ terms: plan.terms.map((t) => (t.id === action.id ? { ...t, ...action.changes } : t)) });
    case 'skipSession': {
      const ids = new Set(skipPlan(plan, action.session).filter((s) => !s.reason).map((s) => s.term.id));
      return next({ terms: plan.terms.map((t) => (ids.has(t.id) ? { ...t, mode: 'off' } : t)) });
    }
    case 'addAttempts': {
      const defaults = defaultsFor(plan, action.termId);
      const added = action.courses.map((c) => ({
        id: newId('c'), term_id: action.termId, code: c.code, title: c.title || '', credits: c.credits,
        grade: null, source: 'user', counts_as: null, evidence: '', placeholder: null, ...defaults,
      }));
      return next({ attempts: [...plan.attempts, ...added].slice(0, LIMITS.attempts) });
    }
    case 'updateAttempt':
      return next({ attempts: plan.attempts.map((a) => (a.id === action.id ? { ...a, ...action.changes } : a)) });
    case 'setExams':
      return next({ exams: action.exams });
    case 'setConcentrations':
      return next({ concentration_ids: action.ids, sample_variant: null,
        attempts: plan.attempts.filter((a) => a.source !== 'generated' || a.pinned) });
    case 'setCatalogYear':
      return next({ catalog_year: action.year, sample_variant: null,
        attempts: plan.attempts.filter((a) => a.source !== 'generated' || a.pinned) });
    case 'moveAttempt': {
      const defaults = defaultsFor(plan, action.termId);
      return next({ attempts: plan.attempts.map((a) => (a.id !== action.id ? a : {
        ...a, term_id: action.termId, status: defaults.status, pinned: defaults.pinned,
        grade: defaults.status === 'planned' ? null : a.grade,
        origin: action.termId || a.origin !== 'nu' ? a.origin : 'transfer' })) });
    }
    case 'removeAttempts': {
      const ids = new Set(action.ids);
      return next({ attempts: plan.attempts.filter((a) => !ids.has(a.id)) });
    }
    case 'addCoop':
      if (coopFor(plan, action.termId)) return plan;
      return next({ experiences: [...plan.experiences, { id: newId('coop'), kind: 'coop', term_ids: [action.termId] }],
        terms: plan.terms.map((t) => (t.id === action.termId ? { ...t, mode: 'open' } : t)) });
    case 'extendCoop': {
      const exp = plan.experiences.find((e) => e.id === action.id);
      const last = plan.terms.find((t) => t.id === exp.term_ids[exp.term_ids.length - 1]);
      const following = plan.terms.find((t) => termKey(t) === termKey(last) + 1);
      if (!following || coopFor(plan, following.id)) return plan; // never two experiences in one term
      return next({ experiences: plan.experiences.map((e) => (e.id === exp.id ? { ...e, term_ids: [...e.term_ids, following.id] } : e)) });
    }
    case 'shortenCoop':
      return next({ experiences: plan.experiences.map((e) => (e.id === action.id ? { ...e, term_ids: e.term_ids.slice(0, -1) } : e))
        .filter((e) => e.term_ids.length) });
    case 'removeCoop':
      return next({ experiences: plan.experiences.filter((e) => e.id !== action.id) });
    case 'setPreferences':
      return next({ preferences: { ...plan.preferences, ...action.preferences } });
    case 'setSample':
      return next({ sample_variant: action.id });
    case 'applyProposal':
      return next({ attempts: action.attempts });
    default:
      throw new Error(`Unknown plan action ${action.type}`);
  }
}

// What the server sees: no UI-only fields and never any AI credentials.
export function toPayload(plan) {
  const pick = (o, keys) => Object.fromEntries(keys.filter((k) => o[k] !== undefined).map((k) => [k, o[k]]));
  return {
    schema_version: SCHEMA_VERSION,
    revision: plan.revision,
    program_id: plan.program_id,
    catalog_year: plan.catalog_year,
    concentration_ids: plan.concentration_ids,
    current_term: plan.current_term,
    terms: plan.terms.map((t) => pick(t, ['id', 'year', 'session', 'mode', 'credit_target', 'credit_cap'])),
    attempts: plan.attempts.map((a) => pick(a, ['id', 'term_id', 'code', 'credits', 'status', 'grade', 'origin', 'pinned',
      'source', 'counts_as', 'evidence', 'placeholder', 'title', 'reason', 'preference'])),
    exams: (plan.exams || []).map((e) => pick(e, ['id', 'exam_id', 'score', 'level', 'policy_year', 'version', 'state'])),
    experiences: plan.experiences.map((e) => pick(e, ['id', 'kind', 'term_ids'])),
    preferences: plan.preferences,
    sample_variant: plan.sample_variant,
  };
}

export const parseCodes = (text) => [...new Set((text.toUpperCase().match(/[A-Z]{2,5}\s*\d{2}[0-9A-Z]{2}\b/g) || [])
  .map((c) => c.replace(/^([A-Z]+)\s*/, '$1 ')))];

// --- Persistence: one draft per program, requirements edition, and concentration selection ---

export const storageKey = (programId, catalogYear, ids) => `coursePlan:v1:${programId}:${catalogYear}:${[...ids].sort().join(',')}`;
const lastKey = (programId) => `coursePlan:last:${programId}`;

// The draft for this selection, or else the program's most recent draft (another catalog year or
// concentration), which setup can offer as a starting point so history is never retyped.
export function loadDraft(programId, ids) {
  try {
    const last = localStorage.getItem(lastKey(programId));
    const catalogYear = last && JSON.parse(last).catalog_year;
    const exact = catalogYear && localStorage.getItem(storageKey(programId, catalogYear, ids));
    if (exact) return { plan: readPlan(exact, programId) };
    const previous = last && localStorage.getItem(JSON.parse(last).key);
    return { plan: null, previous: previous ? readPlan(previous, programId) : null };
  } catch (error) {
    return { plan: null, error: error instanceof PlanFileError ? error.message : 'Your saved plan couldn’t be read.' };
  }
}

// A new draft for a different requirements edition or concentration: history, co-ops, and pinned
// courses carry over; earlier suggestions are dropped because they were chosen for other rules.
export function draftFrom(previous, { catalogYear, concentrationIds }) {
  return { ...previous, id: `plan-${Date.now().toString(36)}`, revision: 0, catalog_year: catalogYear,
    concentration_ids: concentrationIds, sample_variant: null, updated_at: new Date().toISOString(),
    attempts: previous.attempts.filter((a) => a.source !== 'generated' || a.pinned) };
}

export function saveDraft(plan) {
  try {
    const key = storageKey(plan.program_id, plan.catalog_year, plan.concentration_ids);
    localStorage.setItem(key, JSON.stringify(plan));
    localStorage.setItem(lastKey(plan.program_id), JSON.stringify({ key, catalog_year: plan.catalog_year }));
    return true;
  } catch {
    return false; // quota or blocked storage: the in-memory draft stays usable
  }
}

export class PlanFileError extends Error {}

const SESSION_SET = new Set(YEAR_ORDER);
const isTerm = (t) => t && Number.isInteger(t.year) && t.year > 1990 && t.year < 2100 && SESSION_SET.has(t.session);

// Imports and saved drafts are untrusted: check shape and sizes; the server re-checks everything else.
export function readPlan(text, programId) {
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    throw new PlanFileError('This file isn’t a saved course plan.');
  }
  if (!data || data.schema_version !== SCHEMA_VERSION) throw new PlanFileError('This plan was saved by a different version.');
  if (programId && data.program_id !== programId) throw new PlanFileError('This plan is for a different major.');
  if (!isTerm(data.start) || !isTerm(data.target) || !isTerm(data.current_term)) throw new PlanFileError('This plan’s terms are invalid.');
  if (!Array.isArray(data.terms) || !data.terms.length || data.terms.length > LIMITS.terms
    || !data.terms.every((t) => isTerm(t) && t.id === termId(t))) throw new PlanFileError('This plan’s terms are invalid.');
  if (!Array.isArray(data.attempts) || data.attempts.length > LIMITS.attempts
    || !data.attempts.every((a) => a && typeof a.id === 'string' && typeof a.credits === 'number'))
    throw new PlanFileError('This plan’s courses are invalid.');
  if (!Array.isArray(data.experiences) || !Array.isArray(data.concentration_ids) || typeof data.catalog_year !== 'string')
    throw new PlanFileError('This plan is incomplete.');
  if (data.exams !== undefined && (!Array.isArray(data.exams) || data.exams.length > 50
    || !data.exams.every((e) => e && typeof e.id === 'string' && /^[A-Za-z0-9:_-]{1,80}$/.test(e.id)
      && typeof e.exam_id === 'string' && /^(ap|ib):[a-z0-9-]+$/.test(e.exam_id)
      && Number.isInteger(e.score) && e.score >= 1 && e.score <= (e.exam_id.startsWith('ap:') ? 5 : 7)
      && ['estimated', 'awarded'].includes(e.state)
      && (e.exam_id.startsWith('ap:') || ['HL', 'SL'].includes(e.level))
      && typeof e.policy_year === 'string' && /^\d{4}-\d{4}$/.test(e.policy_year)
      && typeof e.version === 'string' && /^[a-f0-9]{16}$/.test(e.version))))
    throw new PlanFileError('This plan’s AP/IB exams are invalid.');
  const exams = (data.exams || []).map((e) => ({ id: e.id, exam_id: e.exam_id, score: e.score,
    level: e.exam_id.startsWith('ib:') ? e.level : null, policy_year: e.policy_year, version: e.version, state: e.state,
    kind: e.exam_id.split(':')[0], name: typeof e.name === 'string' ? e.name.slice(0, 200) : e.exam_id }));
  const { schema_version, id, revision, program_id, catalog_year, concentration_ids, start, current_term, target, terms,
    attempts, experiences, preferences, sample_variant, updated_at } = data; // drop anything else, such as stray keys
  return { schema_version, id: String(id || 'imported'), revision: Number.isInteger(revision) ? revision : 0, program_id,
    catalog_year, concentration_ids, start, current_term, target, terms, attempts, experiences, exams,
    preferences: { interests: String(preferences?.interests || '').slice(0, 500) }, sample_variant: sample_variant || null,
    updated_at: String(updated_at || '') };
}
