import React, { useEffect, useRef, useState } from 'react';
import ExamCreditEditor from './ExamCreditEditor';
import { academicYear, coopFor, nextTerm, parseCodes, shortLabel, termKey, termLabel, termStatus } from '../coursePlan';

const RESULTS = {
  past: [['passed', 'Passed'], ['failed', 'Failed'], ['withdrawn', 'Withdrawn'], ['incomplete', 'Incomplete']],
  current: [['in_progress', 'In progress'], ['passed', 'Passed'], ['failed', 'Failed'], ['withdrawn', 'Withdrawn'],
    ['incomplete', 'Incomplete']],
  future: [['planned', 'Planned']],
};
const ORIGINS = [['nu', 'Northeastern'], ['ap', 'AP'], ['ib', 'IB'], ['transfer', 'Transfer'], ['substitution', 'Approved substitution']];
const MAX_LOOKUPS = 20;

const minCredits = (course) => {
  const options = course.credit_options;
  if (options?.values) return options.values[0];
  if (options?.min !== undefined) return options.min;
  return Number(course.credits);
};

async function lookup(code, catalogYear) {
  const [dept, number] = code.split(' ');
  try {
    const res = await fetch(`/api/course/${dept.toLowerCase()}/${number}${catalogYear ? `?catalog_year=${encodeURIComponent(catalogYear)}` : ''}`);
    if (res.ok) return { code, found: true, course: await res.json() };
    return { code, found: false, missing: res.status === 404 };
  } catch {
    return { code, found: false };
  }
}

// One course record: result, credit source, pin, move, remove. Credits come from the catalog and
// grades aren't collected (the transcript has them). Every control is a native, labeled form control.
function AttemptRow({ attempt, plan, status, dispatch, onOpenCourse, problems }) {
  const update = (changes) => dispatch({ type: 'updateAttempt', id: attempt.id, changes });
  const name = attempt.code || attempt.title;
  const external = !attempt.term_id || attempt.origin !== 'nu';
  const [showMapping, setShowMapping] = useState(Boolean(attempt.counts_as || attempt.origin === 'substitution'));
  const id = (field) => `${attempt.id}-${field}`;
  return (
    <li className="attempt-edit">
      <div className="attempt-edit-head">
        {attempt.code
          ? <button type="button" className="link-button attempt-code" onClick={() => onOpenCourse(attempt.code)}>{attempt.code}</button>
          : <strong>{attempt.title}</strong>}
        <span className="hint">{`${attempt.code ? attempt.title : 'Placeholder: choose a specific course later'} · `
          + `${attempt.credits} ${attempt.credits === 1 ? 'credit' : 'credits'}`}</span>
      </div>
      {attempt.reason && <p className="hint">{attempt.reason}</p>}
      {problems.map((p) => <p className="attempt-problem" key={p}>{p}</p>)}
      <div className="attempt-fields">
        {attempt.term_id && <label htmlFor={id('status')}>Result
          <select id={id('status')} className="input input-sm" value={attempt.status}
            onChange={(e) => update({ status: e.target.value })}>
            {RESULTS[status].map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>}
        {(external || status === 'past') && <label htmlFor={id('origin')}>Credit source
          <select id={id('origin')} className="input input-sm" value={attempt.origin}
            onChange={(e) => update({ origin: e.target.value })}>
            {ORIGINS.filter(([v]) => attempt.term_id || v !== 'nu').map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>}
        <label htmlFor={id('move')}>Move to
          <select id={id('move')} className="input input-sm" value={attempt.term_id || ''}
            onChange={(e) => dispatch({ type: 'moveAttempt', id: attempt.id, termId: e.target.value || null })}>
            <option value="">Credit before enrollment</option>
            {plan.terms.map((t) => <option key={t.id} value={t.id}>{termLabel(t)}</option>)}
          </select>
        </label>
      </div>
      <div className="attempt-actions">
        {status === 'future' && <label className="check">
          <input type="checkbox" checked={Boolean(attempt.pinned)} onChange={(e) => update({ pinned: e.target.checked })} />
          {` Keep ${name} in this term`}
        </label>}
        {attempt.code && !showMapping && <button type="button" className="link-button" onClick={() => setShowMapping(true)}>
          Counts as another course?</button>}
        <button type="button" className="link-button" onClick={() => dispatch({ type: 'removeAttempts', ids: [attempt.id] })}
          aria-label={`Remove ${name}`}>Remove</button>
      </div>
      {showMapping && <div className="attempt-fields">
        <label htmlFor={id('counts')}>Counts as (Northeastern course)
          <input id={id('counts')} className="input input-sm" value={attempt.counts_as || ''} placeholder="CS 2100"
            onChange={(e) => update({ counts_as: e.target.value.trim().toUpperCase() || null })} />
        </label>
        <label htmlFor={id('evidence')} className="wide">Approval details (who approved it, when)
          <input id={id('evidence')} className="input input-sm" value={attempt.evidence || ''} maxLength={500}
            onChange={(e) => update({ evidence: e.target.value })} />
        </label>
        <p className="hint wide">It counts only with approval details. Never guessed from a similar title.</p>
      </div>}
    </li>
  );
}

const SAMPLE_TERMS = { fall: 'Fall', spring: 'Spring', summer1: 'Summer 1', summer2: 'Summer 2' };

const sameCodes = (a, b) => a.length === b.length && a.every((c) => b.includes(c));

// What sample plans place in this year of study and session: one unit per entry, so a lecture and
// its lab add together and each side of an "or" choice is its own option. In a future term, a retired
// bundle with a verified replacement is offered as that current bundle instead.
export function commonCourses(context, plan, term) {
  const variants = context?.sample_variants || [];
  const year = academicYear(term) - academicYear(plan.start) + 1;
  const future = termStatus(term, plan.current_term) !== 'past';
  const verified = future ? (context?.replacements || []).filter((r) => r.review === 'verified') : [];
  const units = new Map();
  for (const variant of variants) {
    const seen = new Set();
    for (const semester of variant.semesters) {
      if (semester.year !== year || semester.term !== SAMPLE_TERMS[term.session]) continue;
      for (const entry of semester.entries || []) {
        const groups = entry.kind === 'choice' ? entry.courses.map((c) => [c]) : entry.courses.length ? [entry.courses] : [];
        for (const listed of groups) {
          const replacement = verified.find((r) => sameCodes(r.original, listed));
          const codes = replacement ? replacement.replacement : listed;
          const key = codes.join(' + ');
          if (seen.has(key)) continue;
          seen.add(key);
          const unit = units.get(key) || { key, codes, count: 0, choice: entry.kind === 'choice' ? entry.text : '' };
          if (replacement) unit.replaces = replacement.original.join(' + ');
          unit.count += 1;
          units.set(key, unit);
        }
      }
    }
  }
  return { total: variants.length, units: [...units.values()].sort((a, b) => b.count - a.count).slice(0, 14) };
}

function CommonCourses({ context, plan, term, onAdd }) {
  const { total, units } = commonCourses(context, plan, term);
  if (!total) return null;
  const info = context.course_info || {};
  const taken = new Set(plan.attempts.map((a) => a.code));
  const year = academicYear(term) - academicYear(plan.start) + 1;
  const edition = context.sample_variants[0]?.catalog_year?.replace('-', '–');
  return (
    <section className="common-courses" aria-labelledby="common-heading">
      <h3 id="common-heading" className="editor-subhead">{`Common in year ${year}, ${SAMPLE_TERMS[term.session]}`}</h3>
      <p className="hint">{`From ${total} ${edition} sample ${total === 1 ? 'plan' : 'plans'} for your major. Older plans can list courses `
        + 'that have since changed; check your own record.'}</p>
      {units.length ? <ul className="search-adds">
        {units.map((u) => {
          const known = u.codes.every((c) => info[c] && (!info[c].historical_only || termStatus(term, plan.current_term) === 'past'));
          const added = u.codes.every((c) => taken.has(c));
          return <li key={u.key}>
            <span><strong>{u.key}</strong>{` ${u.codes.map((c) => info[c]?.title).filter(Boolean).join(' / ')}`}
              <span className="hint block">{`${u.count} of ${total} plans${u.choice ? ` · option in “${u.choice}”` : ''}`
                + `${u.replaces ? ` · current replacement for ${u.replaces}` : ''}`
                + `${known ? '' : ' · not in the current catalog'}`}</span></span>
            <button type="button" className="btn btn-quiet btn-sm" disabled={!known || added} aria-label={`Add ${u.key}`}
              onClick={() => onAdd(u.codes.map((c) => ({ code: c, title: info[c].title, credits: info[c].credits })))}>
              {added ? 'Added' : 'Add'}</button>
          </li>;
        })}
      </ul> : <p className="hint">The sample plans list no specific courses for this term (electives or co-op).</p>}
    </section>
  );
}

function AddCourses({ termName, future, onAdd, identify, catalogYear }) {
  const [text, setText] = useState('');
  const [preview, setPreview] = useState(null); // {rows, message}
  const [chosen, setChosen] = useState(new Set());
  const [q, setQ] = useState('');
  const [search, setSearch] = useState({ status: 'idle', results: [] });
  const searchId = useRef(0);

  // Live title search, like the main course search: debounced, and only the newest query may answer.
  useEffect(() => {
    const id = ++searchId.current;
    const query = q.trim();
    if (query.length < 2) {
      setSearch({ status: 'idle', results: [] });
      return undefined;
    }
    setSearch((s) => ({ ...s, status: 'loading' }));
    const timer = setTimeout(async () => {
      let next = { status: 'error', results: [] };
      try {
        const res = await fetch(`/api/search?q=${encodeURIComponent(query)}${catalogYear ? `&catalog_year=${encodeURIComponent(catalogYear)}` : ''}`);
        if (res.ok) next = { status: 'ready', results: await res.json() };
      } catch { /* keep the error state */ }
      if (id === searchId.current) setSearch(next);
    }, 300);
    return () => clearTimeout(timer);
  }, [q, catalogYear]);

  // Codes resolve directly; anything else is a name the AI matches against your program's courses.
  const check = async (e) => {
    e.preventDefault();
    const phrases = [...new Set(text.split(/[,;\n]+/).map((p) => p.trim()).filter(Boolean))].slice(0, MAX_LOOKUPS);
    if (!phrases.length) {
      setPreview({ rows: [], message: 'Type course codes or names, separated by commas or new lines.' });
      return;
    }
    const codes = phrases.flatMap(parseCodes);
    const names = phrases.filter((p) => !parseCodes(p).length);
    setPreview({ rows: [], message: names.length ? 'Checking codes and asking the AI to match course names…' : 'Checking codes…' });
    const [found, guessed] = await Promise.all([Promise.all(codes.map((code) => lookup(code, catalogYear))), names.length ? identify(names) : null]);
    const rows = [...found];
    let message = '';
    if (guessed?.matches) {
      for (const m of guessed.matches) {
        rows.push(m.code ? { code: m.code, found: true, guess: m.input, reason: m.reason,
          course: { title: m.title, credits: m.credits } } : { code: m.input, found: false, unmatched: true });
      }
    } else if (guessed) {
      message = `${guessed.error || 'Course names couldn’t be matched.'} Use the title search below instead.`;
      setQ(names[0]);
    }
    setPreview({ rows, message });
    setChosen(new Set(rows.filter((r) => r.found || (!future && r.missing)).map((r) => r.code)));
  };
  const toggle = (code) => setChosen((set) => {
    const next = new Set(set);
    if (next.has(code)) next.delete(code); else next.add(code);
    return next;
  });
  const addable = (preview?.rows || []).filter((r) => chosen.has(r.code) && (r.found || (!future && r.missing)));
  const add = () => {
    onAdd(addable.map((r) => (r.found
      ? { code: r.code, title: r.course.title, credits: minCredits(r.course) }
      : { code: r.code, title: 'Not in the current catalog', credits: 4 })));
    setText('');
    setPreview(null);
  };

  return (
    <div className="add-courses">
      <form onSubmit={check}>
        <label className="field-label" htmlFor="add-codes">{`Add courses to ${termName}`}</label>
        <textarea id="add-codes" className="input textarea" rows={2} value={text}
          placeholder="CS 2500, Fundamentals of Computer Science 2, intro to discrete math"
          onChange={(e) => { setText(e.target.value); setPreview(null); }} />
        <p className="hint">Course codes or names, separated by commas or new lines. Names are matched by the AI using your
          major and its sample plans; you choose what to add.</p>
        <button type="submit" className="btn btn-outline btn-sm">Find courses</button>
      </form>
      {preview && <div className="code-preview" role="status">
        {preview.message && <p className="hint">{preview.message}</p>}
        {preview.rows.length > 0 && <ul>
          {preview.rows.map((r) => {
            const selectable = r.found || (!future && r.missing);
            const label = r.found ? `${r.code} · ${r.course.title} · ${minCredits(r.course)} credits`
              : r.unmatched ? `No match for “${r.code}”. Try the title search below.`
              : r.missing ? `${r.code} · ${future ? 'Not in the current catalog, so it can’t be planned.'
                : 'Not in the current catalog. It will stay in your history.'}` : `${r.code} · Couldn’t check this code. Try again.`;
            return <li key={r.code}>
              {selectable ? <label className="check"><input type="checkbox" checked={chosen.has(r.code)}
                onChange={() => toggle(r.code)} />{` ${label}`}</label> : <span>{label}</span>}
              {r.guess && <span className="hint block">{`Best guess for “${r.guess}”${r.reason ? `: ${r.reason}` : ''}`}</span>}
            </li>;
          })}
        </ul>}
        {addable.length > 0 && <button type="button" className="btn btn-ink btn-sm" onClick={add}>
          {`Add ${addable.length} ${addable.length === 1 ? 'course' : 'courses'}`}</button>}
      </div>}
      <div className="title-search">
        <label className="field-label" htmlFor="add-search">Search by title or code</label>
        <input id="add-search" className="input" type="search" autoComplete="off" value={q}
          onChange={(e) => setQ(e.target.value)} placeholder="machine learning, cs 3000" />
      </div>
      <p className="sr-only" role="status">{search.status === 'loading' ? 'Searching…'
        : search.status === 'ready' ? `${search.results.length} results` : ''}</p>
      {search.status === 'error' && <p className="notice-error">Search is unavailable right now.</p>}
      {search.status === 'ready' && !search.results.length && <p className="hint">{`No courses match “${q.trim()}”.`}</p>}
      {search.results.length > 0 && <ul className="search-adds">
        {search.results.map((c) => {
          const code = `${c.department_code.toUpperCase()} ${c.number}`;
          return <li key={code}>
            <span><strong>{code}</strong> {c.title}</span>
            <button type="button" className="btn btn-quiet btn-sm" aria-label={`Add ${code}`}
              onClick={() => onAdd([{ code, title: c.title, credits: Number(c.credits) }])}>Add</button>
          </li>;
        })}
      </ul>}
    </div>
  );
}

// Editor for one term, or for credit earned before enrollment (term = null).
function TermEditor({ plan, term, context, dispatch, onOpenCourse, onClose, problems, identify }) {
  const [conflict, setConflict] = useState(null);
  const status = term ? termStatus(term, plan.current_term) : 'past';
  const attempts = plan.attempts.filter((a) => a.term_id === (term ? term.id : null));
  const coop = term && coopFor(plan, term.id);
  const name = term ? termLabel(term) : 'Credit before enrollment';
  const following = term && plan.terms.find((t) => termKey(t) === termKey(nextTerm(term)));

  const setMode = (mode) => {
    if (mode === 'off' && coop) {
      setConflict({ mode, message: `${name} is part of a co-op. Remove the co-op first.` });
      return;
    }
    if (mode === 'off' && attempts.length) {
      setConflict({ mode, message: `${name} has ${attempts.length} ${attempts.length === 1 ? 'course' : 'courses'}. `
        + 'Nothing is removed unless you choose to.' });
      return;
    }
    setConflict(null);
    dispatch({ type: 'setTerm', id: term.id, changes: { mode } });
  };
  // Every add path goes through here: same-term companions (corequisites, and labs/recitations/seminars
  // the catalog titles "for" a course) come along, and the student is told which ones did.
  const [addedNote, setAddedNote] = useState('');
  const add = async (courses) => {
    const termId = term ? term.id : null;
    const present = new Set(plan.attempts.filter((a) => a.term_id === termId).map((a) => a.code));
    const picked = courses.filter((c) => !present.has(c.code));
    const extra = [];
    if (term) { // awarded credit before enrollment is recorded exactly as awarded
      const seen = new Set([...present, ...picked.map((c) => c.code)]);
      for (const r of await Promise.all(picked.map((c) => lookup(c.code, status === 'past' ? plan.catalog_year : null)))) {
        for (const c of (r.found && r.course.companions) || []) {
          if (seen.has(c.code)) continue;
          seen.add(c.code);
          extra.push(c);
        }
      }
    }
    dispatch({ type: 'addAttempts', termId,
      courses: [...picked, ...extra.map((c) => ({ code: c.code, title: c.title, credits: Number(c.credits) }))] });
    setAddedNote(extra.length ? `Also added ${extra.map((c) => `${c.code} (${c.why})`).join(', ')}. `
      + 'Remove any your program doesn’t need.' : '');
  };
  const coopLabel = coop && coop.term_ids.map((id) => shortLabel(plan.terms.find((t) => t.id === id))).join(' – ');

  return (
    <section className="term-editor" aria-label={`Edit ${name}`}>
      <div className="editor-head">
        <h2 id="term-editor-heading">{name}</h2>
        <button type="button" className="btn btn-quiet btn-sm" onClick={onClose}>Done</button>
      </div>
      {!term && <ExamCreditEditor plan={plan} dispatch={dispatch} />}
      {term && <fieldset className="radios">
        <legend className="field-label">{status === 'future' ? 'This term' : 'Enrollment'}</legend>
        {(status === 'future' ? [['open', 'Open for planning'], ['fixed', 'Fully fixed'], ['off', 'Off']]
          : [['open', 'Enrolled'], ['off', 'Did not enroll']]).map(([value, label]) => (
            <label key={value}><input type="radio" name="term-mode" checked={term.mode === value}
              onChange={() => setMode(value)} />{` ${label}`}</label>))}
      </fieldset>}
      {term && status === 'future' && <p className="hint">{term.mode === 'fixed'
        ? 'Fully fixed: exactly these courses, and nothing will be added.'
        : term.mode === 'off' ? 'Off: no courses or co-op will be planned.'
        : 'Open: suggestions can fill any room left after your pinned courses.'}</p>}
      {conflict && <div className="notice" role="alert">
        <p>{conflict.message}</p>
        {!coop && <button type="button" className="btn btn-outline btn-sm" onClick={() => {
          dispatch({ type: 'removeAttempts', ids: attempts.map((a) => a.id) });
          dispatch({ type: 'setTerm', id: term.id, changes: { mode: conflict.mode } });
          setConflict(null);
        }}>{`Remove ${attempts.length} and mark ${status === 'future' ? 'off' : 'not enrolled'}`}</button>}
        <button type="button" className="link-button" onClick={() => setConflict(null)}>Keep everything</button>
      </div>}
      {term && <div className="coop-controls">
        {coop ? <>
          <p><strong>Co-op</strong>{` · ${coopLabel}`}</p>
          <div className="button-row">
            {following && !coopFor(plan, following.id) && <button type="button" className="btn btn-outline btn-sm"
              onClick={() => dispatch({ type: 'extendCoop', id: coop.id })}>{`Continue into ${shortLabel(following)}`}</button>}
            {coop.term_ids.length > 1 && <button type="button" className="btn btn-quiet btn-sm"
              onClick={() => dispatch({ type: 'shortenCoop', id: coop.id })}>Shorten by one term</button>}
            <button type="button" className="btn btn-quiet btn-sm" onClick={() => dispatch({ type: 'removeCoop', id: coop.id })}>
              Remove co-op</button>
          </div>
        </> : term.mode !== 'off' && <button type="button" className="btn btn-outline btn-sm"
          onClick={() => dispatch({ type: 'addCoop', termId: term.id })}>Mark as co-op</button>}
      </div>}
      {term && status !== 'past' && <div className="attempt-fields">
        <label htmlFor="term-target">Target credits
          <input id="term-target" className="input input-sm" type="number" min="0" max="40" value={term.credit_target}
            onChange={(e) => dispatch({ type: 'setTerm', id: term.id, changes: { credit_target: Number(e.target.value) } })} />
        </label>
        <label htmlFor="term-cap">Credit limit
          <input id="term-cap" className="input input-sm" type="number" min="0" max="40" value={term.credit_cap}
            onChange={(e) => dispatch({ type: 'setTerm', id: term.id, changes: { credit_cap: Number(e.target.value) } })} />
        </label>
        <p className="hint wide">Your preferences, not university limits. Suggestions never exceed your limit.</p>
      </div>}
      <h3 className="editor-subhead">{!term ? 'Enter awarded course codes' : attempts.length ? `Courses (${attempts.length})` : 'No courses yet'}</h3>
      {!term && <p className="hint">Already know your awarded Northeastern equivalents? Enter them exactly as shown on your record.</p>}
      <p className="hint" role="status">{addedNote}</p>
      <ul className="attempt-list">
        {attempts.map((a) => <AttemptRow key={a.id} attempt={a} plan={plan} status={status} dispatch={dispatch}
          onOpenCourse={onOpenCourse} problems={problems.filter((p) => p.attempt_id === a.id).map((p) => p.message)} />)}
      </ul>
      {(!term || term.mode !== 'off') && <>
        {term && !coop && <CommonCourses context={context} plan={plan} term={term} onAdd={add} />}
        <AddCourses termName={name} future={status === 'future'} catalogYear={status === 'past' ? plan.catalog_year : null}
          identify={(names) => identify(names, name)} onAdd={add} />
      </>}
    </section>
  );
}

export default TermEditor;
