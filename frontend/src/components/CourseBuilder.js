import React, { useEffect, useMemo, useReducer, useRef, useState } from 'react';
import TermEditor from './TermEditor';
import PlanReport from './PlanReport';
import { catalogLabel } from './SearchPanel';
import {
  SESSION_LABELS, YEAR_ORDER, academicYear, buildTerms, coopFor, defaultTarget, loadDraft, newPlan, planReducer,
  readPlan, removalConflicts, saveDraft, draftFrom, shortLabel, skipPlan, termKey, termLabel, termStatus, toPayload, nextTerm,
} from '../coursePlan';

const EDITIONS = ['2026-2027', '2025-2026', '2024-2025', '2023-2024', '2022-2023'];
const STATUS_TEXT = { passed: 'Completed', in_progress: 'In progress', planned: 'Planned', failed: 'Failed',
  withdrawn: 'Withdrawn', incomplete: 'Incomplete' };

function today() {
  const d = new Date();
  const m = d.getMonth();
  const session = m >= 8 ? 'fall' : m <= 3 ? 'spring' : m <= 5 ? 'summer1' : 'summer2';
  return { year: d.getFullYear(), session };
}

function TermPicker({ id, label, value, onChange, hint }) {
  return (
    <fieldset className="term-picker">
      <legend className="field-label">{label}</legend>
      <div className="code-row">
        <label className="sr-only" htmlFor={`${id}-session`}>{`${label}: session`}</label>
        <select id={`${id}-session`} className="input" value={value.session}
          onChange={(e) => onChange({ ...value, session: e.target.value })}>
          {YEAR_ORDER.map((s) => <option key={s} value={s}>{SESSION_LABELS[s]}</option>)}
        </select>
        <label className="sr-only" htmlFor={`${id}-year`}>{`${label}: year`}</label>
        <input id={`${id}-year`} className="input year-input" type="number" min="2000" max="2099" value={value.year}
          onChange={(e) => onChange({ ...value, year: Number(e.target.value) })} />
      </div>
      {hint && <p className="hint">{hint}</p>}
    </fieldset>
  );
}

function Setup({ major, concentrations, previous, onStart }) {
  const now = today();
  const [start, setStart] = useState(now.session === 'fall' ? now : { year: now.year - 1, session: 'fall' });
  const [current, setCurrent] = useState(now);
  const [target, setTarget] = useState(null);
  const [edition, setEdition] = useState('');
  const [interests, setInterests] = useState('');
  const shownTarget = target || defaultTarget(start);
  const suggested = `${academicYear(start)}-${academicYear(start) + 1}`;
  const invalid = termKey(shownTarget) < termKey(start) ? 'Your target graduation term must come after your first term.'
    : termKey(current) < termKey(start) ? 'Your current term can’t be before your first term.'
    : buildTerms(start, shownTarget).length >= 40 ? 'Plans can cover up to 40 terms.' : '';

  const submit = (e) => {
    e.preventDefault();
    if (invalid || !edition) return;
    onStart(newPlan({ programId: major.id, catalogYear: edition, concentrationIds: concentrations.map((o) => o.id),
      start, current, target: shownTarget, interests: interests.trim() }));
  };
  const ids = concentrations.map((o) => o.id);
  return (
    <form className="builder-setup" onSubmit={submit}>
      {previous && <div className="notice">
        <p>{`You have a saved plan for ${catalogLabel(previous.catalog_year)} requirements`
          + `${previous.concentration_ids.join(',') !== ids.join(',') ? ' with different concentration choices' : ''}. `
          + 'Start from it to keep your history, co-ops, and pinned courses; earlier suggestions are cleared.'}</p>
        <button type="button" className="btn btn-outline btn-sm" disabled={!edition}
          onClick={() => onStart(draftFrom(previous, { catalogYear: edition, concentrationIds: ids }))}>
          {edition ? `Start from saved plan with ${catalogLabel(edition)} requirements` : 'Choose a catalog year below first'}</button>
      </div>}
      <h2>Set up your timeline</h2>
      <p className="hint">Start with four years. You can add or remove terms and years at any time.</p>
      <TermPicker id="start" label="First term at Northeastern" value={start} onChange={setStart} />
      <TermPicker id="current" label="Current term (or the next one, if you’re between terms)" value={current}
        onChange={setCurrent} hint="Terms before this are history; this term is in progress; later terms are planned." />
      <TermPicker id="target" label="Target graduation term" value={shownTarget} onChange={setTarget} />
      <div>
        <label className="field-label" htmlFor="edition">Requirements catalog year</label>
        <select id="edition" className="input" value={edition} onChange={(e) => setEdition(e.target.value)} required>
          <option value="">Choose your catalog year</option>
          {EDITIONS.map((y) => <option key={y} value={y}>{`${catalogLabel(y)}${y === suggested ? ' (common for your first term)' : ''}`}</option>)}
        </select>
        <p className="hint">Use the catalog year on your degree audit, or ask your advisor. Your major and concentration use
          the same year. Catalogs cover current first- through fifth-year students.</p>
      </div>
      <div>
        <label className="field-label" htmlFor="interests">Interests or career goals (optional)</label>
        <textarea id="interests" className="input textarea" rows={2} maxLength={500} value={interests}
          onChange={(e) => setInterests(e.target.value)} placeholder="machine learning, health tech, startups" />
        <p className="hint">Only used to rank elective choices when you ask for AI suggestions.</p>
      </div>
      {invalid && <p className="notice-error" role="alert">{invalid}</p>}
      <button type="submit" className="btn btn-ink" disabled={Boolean(invalid) || !edition}>Start my plan</button>
    </form>
  );
}

function TermCard({ term, plan, attempts, onEdit, onOpenCourse, problems, previewing }) {
  const status = termStatus(term, plan.current_term);
  const coop = coopFor(plan, term.id);
  const credits = attempts.filter((a) => a.status !== 'withdrawn').reduce((sum, a) => sum + Number(a.credits || 0), 0);
  const mode = coop ? 'Co-op' : term.mode === 'off' ? (status === 'future' ? 'Off' : 'Not enrolled')
    : term.mode === 'fixed' ? 'Fully fixed' : null;
  const headingId = `term-${term.id}`;
  return (
    <section className={`term-card term-${status}${coop ? ' term-coop' : ''}${term.mode === 'off' ? ' term-off' : ''}`}
      aria-labelledby={headingId}>
      <header>
        <h4 id={headingId}>{termLabel(term)}</h4>
        <p className="term-meta">{[term.mode !== 'off' && { past: 'Completed term', current: 'Current term' }[status], mode]
          .filter(Boolean).join(' · ')}</p>
      </header>
      {!coop && term.mode !== 'off' && <p className="term-credits">{`${credits} credits`}
        {status !== 'past' && <span className="hint">{` · target ${term.credit_target}, limit ${term.credit_cap}`}</span>}</p>}
      {attempts.length > 0 && <ul className="term-courses">
        {attempts.map((a) => {
          const tags = [previewing && a.source === 'generated' ? 'Suggested' : STATUS_TEXT[a.status], a.pinned && 'Pinned',
            a.placeholder && 'Choose a course',
            !a.term_id && 'Transfer'].filter(Boolean);
          return <li key={a.id}>
            {a.code ? <button type="button" className="link-button course-link" onClick={() => onOpenCourse(a.code)}>{a.code}</button>
              : <span className="placeholder-name">{a.title}</span>}
            <span className="course-credits">{Number(a.credits)}</span>
            {tags.length > 0 && <span className="course-tags">{tags.join(' · ')}</span>}
          </li>;
        })}
      </ul>}
      {problems.length > 0 && <p className="term-problem">{`${problems.length} ${problems.length === 1 ? 'problem' : 'problems'}: `
        + problems[0].message}</p>}
      {!previewing && <button type="button" className="btn btn-quiet btn-sm" onClick={onEdit}
        aria-label={`Edit ${termLabel(term)}`}>Edit</button>}
    </section>
  );
}

function PlanSettings({ plan, context, dispatch }) {
  const [pending, setPending] = useState(null); // a horizon change that would discard entries
  const [skipped, setSkipped] = useState('');
  const last = plan.terms[plan.terms.length - 1];
  const changeTarget = (target) => {
    const gone = removalConflicts(plan, target);
    if (gone.attempts.length || gone.coops.length) setPending({ target, ...gone });
    else dispatch({ type: 'setTarget', target });
  };
  const skip = (session) => {
    const results = skipPlan(plan, session);
    dispatch({ type: 'skipSession', session });
    const kept = results.filter((r) => r.reason);
    setSkipped(results.length ? `${results.length - kept.length} ${SESSION_LABELS[session]} terms marked off.`
      + kept.map((r) => ` ${shortLabel(r.term)} kept: ${r.reason}.`).join('') : `No open ${SESSION_LABELS[session]} terms left.`);
  };
  const canShorten = termKey(last) > Math.max(termKey(plan.current_term), termKey(plan.start));
  const selectConcentrations = (group, chosen) => {
    const allowed = new Set(context.concentration_groups.flatMap((g) => g.options.map((o) => o.id)));
    dispatch({ type: 'setConcentrations', ids: [...plan.concentration_ids.filter((id) => allowed.has(id)
      && !group.options.some((o) => o.id === id)), ...chosen] });
  };
  return (
    <details className="plan-settings">
      <summary>Timeline and preferences</summary>
      <div className="settings-grid">
        <div>
          <label className="field-label" htmlFor="plan-catalog-year">Requirements catalog year</label>
          <select id="plan-catalog-year" className="input" value={plan.catalog_year}
            onChange={(e) => dispatch({ type: 'setCatalogYear', year: e.target.value })}>
            {[...new Set([...(context?.available_editions || EDITIONS), plan.catalog_year])].sort().reverse()
              .map((year) => <option key={year} value={year}>{catalogLabel(year)}</option>)}
          </select>
          <p className="hint">Use the year on your degree audit. History and pinned courses stay saved; unpinned suggestions are cleared.</p>
        </div>
        {(context?.concentration_groups || []).filter((g) => !g.fixed).map((group) => {
          const selected = group.options.filter((o) => plan.concentration_ids.includes(o.id)).map((o) => o.id);
          const multiple = group.policy.max_selections !== 1;
          return <fieldset key={group.id}>
            <legend className="field-label">{`${group.title} (${catalogLabel(plan.catalog_year)})`}</legend>
            {multiple ? group.options.map((o) => <label className="check" key={o.id}>
              <input type="checkbox" checked={selected.includes(o.id)} onChange={(e) => selectConcentrations(group,
                e.target.checked ? [...selected, o.id] : selected.filter((id) => id !== o.id))} />{o.name}
            </label>) : <select className="input" aria-label={`${group.title} for ${plan.catalog_year}`}
              value={selected[0] || ''} onChange={(e) => selectConcentrations(group, e.target.value ? [e.target.value] : [])}>
              <option value="">Choose an option or leave undecided</option>
              {group.options.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
            </select>}
          </fieldset>;
        })}
        <div>
          <p className="field-label">{`Target graduation: ${termLabel(plan.target)}`}</p>
          <div className="button-row">
            <button type="button" className="btn btn-outline btn-sm" disabled={plan.terms.length >= 40}
              onClick={() => changeTarget(nextTerm(plan.target))}>Add a term</button>
            <button type="button" className="btn btn-outline btn-sm" disabled={plan.terms.length + 4 > 40}
              onClick={() => changeTarget({ year: plan.target.year + 1, session: plan.target.session })}>Add a year</button>
            <button type="button" className="btn btn-quiet btn-sm" disabled={!canShorten}
              onClick={() => changeTarget({ year: Math.floor((termKey(last) - 1) / 4),
                session: ['spring', 'summer1', 'summer2', 'fall'][(termKey(last) - 1) % 4] })}>Remove last term</button>
          </div>
          {pending && <div className="notice" role="alert">
            <p>{`Removing ${pending.terms.map(shortLabel).join(', ')} would discard ${pending.attempts.length} course `
              + `${pending.attempts.length === 1 ? 'entry' : 'entries'}${pending.coops.length ? ' and a co-op' : ''}.`}</p>
            <div className="button-row">
              <button type="button" className="btn btn-outline btn-sm" onClick={() => {
                dispatch({ type: 'setTarget', target: pending.target, discard: true });
                setPending(null);
              }}>Discard and remove</button>
              <button type="button" className="btn btn-quiet btn-sm" onClick={() => setPending(null)}>Keep them</button>
            </div>
          </div>}
        </div>
        <div>
          <p className="field-label">Summers</p>
          <div className="button-row">
            <button type="button" className="btn btn-outline btn-sm" onClick={() => skip('summer1')}>Skip remaining Summer 1 terms</button>
            <button type="button" className="btn btn-outline btn-sm" onClick={() => skip('summer2')}>Skip remaining Summer 2 terms</button>
          </div>
          <p className="hint" role="status">{skipped}</p>
        </div>
        <TermPicker id="plan-current" label="Current term" value={plan.current_term}
          onChange={(current) => dispatch({ type: 'setCurrent', current })} />
        {context?.sample_variants?.length > 0 && <div>
          <label className="field-label" htmlFor="sample">Timing guide</label>
          <select id="sample" className="input" value={plan.sample_variant || ''}
            onChange={(e) => dispatch({ type: 'setSample', id: e.target.value || null })}>
            <option value="">Best match for your co-op terms</option>
            {context.sample_variants.map((v) => <option key={v.id} value={v.id}>{`${v.name} (${catalogLabel(v.catalog_year)})`}</option>)}
          </select>
          <p className="hint">Published sample plans only suggest timing. Their course lists may be older than your requirements.</p>
        </div>}
        <div>
          <label className="field-label" htmlFor="plan-interests">Interests or career goals</label>
          <textarea id="plan-interests" className="input textarea" rows={2} maxLength={500}
            value={plan.preferences.interests} onChange={(e) => dispatch({ type: 'setPreferences', preferences: { interests: e.target.value } })} />
        </div>
      </div>
    </details>
  );
}

function download(plan) {
  const blob = new Blob([JSON.stringify(plan, null, 2)], { type: 'application/json' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = `course-plan-${plan.program_id}-${plan.updated_at.slice(0, 10) || 'draft'}.json`;
  link.click();
  URL.revokeObjectURL(link.href);
}

function CourseBuilder({ major, concentrations, ai, aiLabel, onBack, onOpenCourse, onCloseCourse, detail }) {
  const ids = useMemo(() => concentrations.map((o) => o.id), [concentrations]);
  const [loaded] = useState(() => loadDraft(major.id, ids));
  const [plan, dispatch] = useReducer((state, action) => planReducer(state, action), loaded.plan);
  const [saved, setSaved] = useState(true);
  const [context, setContext] = useState({ status: 'idle' });
  const [report, setReport] = useState({ status: 'idle' });
  const [proposal, setProposal] = useState(null); // {status, data?, error?, revision}
  const [editing, setEditing] = useState(null); // term id, or 'pre' for credit before enrollment
  const [importing, setImporting] = useState(null);
  const [notice, setNotice] = useState(loaded.error || '');
  const request = useRef({ id: 0, controller: null });
  const fileInput = useRef(null);

  useEffect(() => {
    if (plan) setSaved(saveDraft(plan));
  }, [plan]);

  const planKey = plan && `${plan.program_id}|${plan.catalog_year}|${plan.concentration_ids.join(',')}`;
  useEffect(() => {
    if (!plan) return undefined;
    let cancelled = false;
    setContext({ status: 'loading' });
    const params = `catalog_year=${encodeURIComponent(plan.catalog_year)}&concentrations=${encodeURIComponent(plan.concentration_ids.join(','))}`;
    fetch(`/api/programs/${encodeURIComponent(plan.program_id)}/planning-context?${params}`)
      .then(async (res) => {
        // An API started before the Course Builder existed answers with an HTML 404, not JSON.
        const data = await res.json().catch(() => ({ error: res.status === 404
          ? 'The running API doesn’t have the Course Builder yet. Restart it (with the virtual environment active).'
          : `The planner returned an unexpected response (HTTP ${res.status}).` }));
        if (!cancelled) setContext(res.ok ? { status: 'ready', data } : { status: 'error', message: data.error });
      })
      .catch(() => !cancelled && setContext({ status: 'error', message: 'Planning data couldn’t load. Check that the API is running.' }));
    return () => { cancelled = true; };
  }, [planKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // Only the newest request may report back, and only while the plan is the revision it was sent with.
  const send = async (url, body, onDone) => {
    request.current.controller?.abort();
    const controller = new AbortController();
    const id = ++request.current.id;
    request.current.controller = controller;
    const revision = plan.revision;
    try {
      const res = await fetch(url, { method: 'POST', cache: 'no-store', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body), signal: controller.signal });
      const data = await res.json();
      if (id === request.current.id) onDone(res, data, revision);
    } catch (error) {
      if (error.name !== 'AbortError' && id === request.current.id) {
        onDone({ ok: false, status: 0 }, { error: 'Couldn’t reach the planner. Check that the API is running, then try again.' }, revision);
      }
    }
  };

  const validate = () => {
    setReport({ status: 'loading' });
    send('/api/planner/validate', { plan: toPayload(plan) }, (res, data, revision) =>
      setReport(res.ok ? { status: 'ready', data, revision } : { status: 'error', message: data.error }));
  };

  const generate = (mode) => {
    const custom = ai.mode === 'custom';
    if (mode === 'ai' && custom && (!ai.apiKey || !ai.model)) {
      setProposal({ status: 'error', error: 'Add your API key and model in Model settings, or fill without AI.', deterministic: true });
      return;
    }
    setProposal({ status: 'loading', mode });
    const body = { plan: toPayload(plan), mode, dataset: context.data?.fingerprint,
      ...(mode === 'ai' && custom && { ai: { mode: 'custom', provider: ai.provider, api_key: ai.apiKey, model: ai.model } }) };
    send('/api/planner/generate', body, (res, data, revision) => {
      if (res.status === 409) setContext({ status: 'idle' });
      if (!res.ok) setProposal({ status: 'error', error: data.error, details: data.details, deterministic: data.deterministic_available });
      else if (!data.proposal) setProposal({ status: 'error', error: data.message, deterministic: false });
      else {
        setProposal({ status: 'ready', data, revision });
        setReport({ status: 'ready', data: data.report, revision: null });
      }
    });
  };

  const cancel = () => {
    request.current.controller?.abort();
    request.current.id += 1;
    setProposal(null);
  };

  const apply = () => {
    if (proposal.data.proposal.dataset !== context.data?.fingerprint) {
      setNotice('Course data was reloaded after these suggestions were made. Fill your plan again.');
      setProposal(null);
      return;
    }
    dispatch({ type: 'applyProposal', attempts: proposal.data.proposal.attempts });
    setProposal(null);
    setReport({ status: 'idle' });
  };

  // Course-name matching uses the same model settings as plan filling; suggestions are never added automatically.
  const identify = async (phrases, term) => {
    const custom = ai.mode === 'custom';
    if (custom && (!ai.apiKey || !ai.model)) return { error: 'Add your API key and model in Model settings to match course names.' };
    try {
      const res = await fetch('/api/planner/identify', { method: 'POST', cache: 'no-store',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ program_id: plan.program_id, phrases, term,
          ...(custom && { ai: { mode: 'custom', provider: ai.provider, api_key: ai.apiKey, model: ai.model } }) }) });
      const data = await res.json().catch(() => ({ error: `Course names couldn’t be matched (HTTP ${res.status}).` }));
      return res.ok ? data : { error: data.error };
    } catch {
      return { error: 'Couldn’t reach the server to match course names.' };
    }
  };

  // The side panel shows one thing; choosing a term to edit replaces any open course details.
  const edit = (id) => {
    setEditing(id);
    onCloseCourse();
  };

  const openCourse = (code) => {
    const [dept, number] = code.split(' ');
    const attempt = plan.attempts.find((a) => a.code === code);
    const term = attempt && plan.terms.find((t) => t.id === attempt.term_id);
    const year = term && termStatus(term, plan.current_term) === 'past' ? `${academicYear(term)}-${academicYear(term) + 1}`
      : context.data?.course_info?.[code]?.historical_only ? plan.catalog_year : null;
    onOpenCourse(dept.toLowerCase(), number, year);
  };

  const startImport = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    try {
      const imported = readPlan(await file.text(), major.id);
      setImporting(imported);
      setNotice('');
    } catch (error) {
      setNotice(error.message || 'This file couldn’t be imported.');
    }
  };

  if (!plan) {
    return (
      <main className="builder" id="builder">
        <BuilderHead major={major} concentrations={concentrations} onBack={onBack} />
        {notice && <p className="notice" role="alert">{`${notice} Starting a new draft.`}</p>}
        <Setup major={major} concentrations={concentrations} previous={loaded.previous}
          onStart={(p) => dispatch({ type: 'replace', plan: p })} />
      </main>
    );
  }

  const previewing = proposal?.status === 'ready';
  const proposalStale = previewing && proposal.revision !== plan.revision;
  const shown = previewing && !proposalStale ? proposal.data.proposal.attempts : plan.attempts;
  const currentReport = report.status === 'ready' ? report.data : null;
  const problems = currentReport ? [...currentReport.errors, ...currentReport.warnings] : [];
  const problemsFor = (termId) => (currentReport?.errors || []).filter((p) => p.term_id === termId
    || shown.some((a) => a.id === p.attempt_id && a.term_id === termId));
  const ctx = context.data;
  const years = [];
  for (const term of plan.terms) {
    const ay = academicYear(term);
    if (!years.length || years[years.length - 1].ay !== ay) years.push({ ay, terms: [] });
    years[years.length - 1].terms.push(term);
  }
  const editingTerm = editing && editing !== 'pre' ? plan.terms.find((t) => t.id === editing) : null;
  const pre = shown.filter((a) => !a.term_id);
  const canGenerate = ctx && !['unavailable', 'needs_selection'].includes(ctx.capability);

  return (
    <main className="builder" id="builder">
      <BuilderHead major={major} concentrations={context.data?.concentrations || concentrations} onBack={onBack} edition={plan.catalog_year}
        saved={saved} onExport={() => download(plan)} />
      {notice && <p className="notice" role="alert">{notice}</p>}
      {importing && <div className="notice" role="alert">
        <p>{`Replace your current draft with the imported plan (${importing.terms.length} terms, ${importing.attempts.length} courses)?`}</p>
        <div className="button-row">
          <button type="button" className="btn btn-outline btn-sm" onClick={() => {
            dispatch({ type: 'replace', plan: { ...importing, revision: plan.revision + 1 } });
            setImporting(null);
            setReport({ status: 'idle' });
            setProposal(null);
          }}>Replace draft</button>
          <button type="button" className="btn btn-quiet btn-sm" onClick={() => setImporting(null)}>Cancel</button>
        </div>
      </div>}
      <CapabilityNote context={context} />

      <div className="builder-toolbar">
        <button type="button" className="btn btn-ink" disabled={!canGenerate || proposal?.status === 'loading'}
          onClick={() => generate('ai')}>Fill remaining courses</button>
        <button type="button" className="btn btn-outline" disabled={!canGenerate || proposal?.status === 'loading'}
          onClick={() => generate('deterministic')}>Fill without AI</button>
        <button type="button" className="btn btn-outline" disabled={report.status === 'loading'} onClick={validate}>
          {report.status === 'loading' ? 'Checking…' : 'Check my plan'}</button>
        <span className="toolbar-gap" />
        <button type="button" className="btn btn-quiet btn-sm" onClick={() => fileInput.current?.click()}>Import</button>
        <input ref={fileInput} type="file" accept="application/json,.json" hidden onChange={startImport} />
        <button type="button" className="btn btn-quiet btn-sm" onClick={() => window.print()}>Print</button>
      </div>
      <p className="hint toolbar-hint">{`Fill remaining courses uses ${aiLabel} to rank electives by your interests; the schedule `
        + 'itself is computed and checked by the planner. Your completed, current, pinned, fixed, off, and co-op terms never change.'}</p>
      <p className="sr-only" role="status">{proposal?.status === 'loading' ? 'Building suggestions…'
        : previewing ? 'Suggestions ready to review.' : report.status === 'ready' ? 'Plan check finished.' : ''}</p>

      {proposal && <ProposalPanel proposal={proposal} stale={proposalStale} onApply={apply} onDiscard={cancel}
        onDeterministic={() => generate('deterministic')} />}

      <PlanSettings plan={plan} context={ctx} dispatch={dispatch} />

      <div className="builder-body">
        <div className="timeline" aria-label="Timeline">
          <section className="year-row pre-enrollment" aria-labelledby="pre-heading">
            <div className="year-head"><h3 id="pre-heading">Credit before enrollment</h3>
              {!previewing && <button type="button" className="btn btn-quiet btn-sm" onClick={() => edit('pre')}>
                {pre.length || plan.exams?.length ? 'Edit' : 'Add AP / IB credit'}</button>}</div>
            {pre.length > 0 && <p className="hint">{pre.map((a) => `${a.code || a.title} (${a.credits})`).join(', ')}</p>}
            {(plan.exams || []).map((e) => <p className="hint" key={e.id}>
              {`${e.kind?.toUpperCase() || 'Exam'} ${e.name || e.exam_id} · ${e.score}${e.level ? ` ${e.level}` : ''} · `
                + (e.state === 'awarded' ? 'Awarded' : 'Estimated, not counted')}
            </p>)}
          </section>
          {years.map(({ ay, terms }, index) => (
            <section className="year-row" key={ay} aria-labelledby={`year-${ay}`}>
              <div className="year-head"><h3 id={`year-${ay}`}>{`${ay}–${ay + 1}`}<span className="hint">{` · Year ${index + 1}`}</span></h3></div>
              <div className="term-grid">
                {terms.map((term) => <TermCard key={term.id} term={term} plan={plan} previewing={previewing && !proposalStale}
                  attempts={shown.filter((a) => a.term_id === term.id)} problems={problemsFor(term.id)}
                  onEdit={() => edit(term.id)} onOpenCourse={openCourse} />)}
              </div>
            </section>
          ))}
        </div>
        <aside className="builder-aside">
          {detail}
          {!detail && editing && <TermEditor key={editing} plan={plan} term={editingTerm} context={ctx} identify={identify}
            dispatch={dispatch} onOpenCourse={openCourse}
            onClose={() => setEditing(null)} problems={problems} />}
          {!detail && !editing && report.status === 'loading' && <p className="pending">Checking your plan…</p>}
          {!detail && !editing && report.status === 'error' && <p className="notice-error" role="alert">{report.message}</p>}
          {!detail && !editing && <PlanReport report={currentReport} plan={plan} attempts={shown} onOpenCourse={openCourse} onEditTerm={edit}
            stale={report.revision != null && report.revision !== plan.revision} />}
          {!detail && !editing && report.status === 'idle' && <p className="hint">Choose a term’s Edit button to add courses,
            mark co-ops, or take a term off. Check my plan reviews prerequisites, credits, and requirement progress.</p>}
        </aside>
      </div>
    </main>
  );
}

function BuilderHead({ major, concentrations, onBack, edition, saved, onExport }) {
  return (
    <div className="builder-head">
      <button type="button" className="back" onClick={onBack}>← Back to course browsing</button>
      <h1>Course Builder</h1>
      <p className="builder-program">{major.label}{concentrations.length > 0 && ` · ${concentrations.map((o) => o.name).join(', ')}`}
        {edition && ` · ${catalogLabel(edition)} requirements`}</p>
      {edition && <p className={`save-state${saved ? '' : ' unsaved'}`} role="status">{saved
        ? 'Saved in this browser. ' : 'Not saved: this browser blocked storage. '}
        <button type="button" className="link-button" onClick={onExport}>{saved ? 'Export a copy' : 'Export to keep it'}</button></p>}
    </div>
  );
}

function CapabilityNote({ context }) {
  if (context.status === 'loading' || context.status === 'idle') return <p className="hint">Loading requirements…</p>;
  if (context.status === 'error') return <p className="notice-error" role="alert">{context.message}</p>;
  const { capability, unavailable_reason: reason, selection_errors: errors, issues } = context.data;
  const text = capability === 'unavailable' ? reason
    : capability === 'needs_selection' ? `${errors.join(' ')} Choose it in Timeline and preferences to fill your plan automatically.`
    : capability === 'reviewed' ? `Requirement rules for this program were reviewed against the catalog. ${issues.length} `
      + `catalog rule${issues.length === 1 ? '' : 's'} still need${issues.length === 1 ? 's' : ''} your review.`
    : 'Requirement rules for this program were extracted automatically and haven’t been reviewed yet. Treat suggestions as a draft '
      + 'and check them against the catalog.';
  return <p className={capability === 'reviewed' ? 'hint' : 'notice'}>{text}</p>;
}

function ProposalPanel({ proposal, stale, onApply, onDiscard, onDeterministic }) {
  if (proposal.status === 'loading') {
    return <div className="proposal"><p className="pending">{proposal.mode === 'ai'
      ? 'Ranking electives and building a schedule. This can take up to a minute.' : 'Building a schedule…'}</p>
      <button type="button" className="btn btn-quiet btn-sm" onClick={onDiscard}>Cancel</button></div>;
  }
  if (proposal.status === 'error') {
    return <div className="proposal notice-block" role="alert">
      <p>{proposal.error}</p>
      {proposal.details?.length > 0 && <ul className="report-list">{proposal.details.map((d) => <li key={d}>{d}</li>)}</ul>}
      <p className="hint">Your plan hasn’t changed.</p>
      <div className="button-row">
        {proposal.deterministic && <button type="button" className="btn btn-outline btn-sm" onClick={onDeterministic}>Fill without AI</button>}
        <button type="button" className="btn btn-quiet btn-sm" onClick={onDiscard}>Dismiss</button>
      </div>
    </div>;
  }
  const { data } = proposal;
  const { added, moved, removed } = data.proposal.diff;
  // Older responses carry no ranking_status; a model then meant the ranking was used.
  const status = data.generation?.ranking_status;
  const ranked = data.generation?.model && (status === 'applied' || !status);
  const summary = [added.length && `${added.length} added`, moved.length && `${moved.length} moved`,
    removed.length && `${removed.length} removed`].filter(Boolean).join(', ') || 'No changes';
  return (
    <div className="proposal" aria-labelledby="proposal-heading">
      <h2 id="proposal-heading">{data.status === 'complete' ? 'Suggested plan' : 'Partial suggestion'}</h2>
      <p>{`${summary}. Suggestions are shown in the timeline; nothing is saved until you apply them.`}</p>
      {data.status === 'partial' && <><p className="notice">Some requirements still can’t fit in your terms. Nothing was
        changed to make room. You could:</p><ul className="report-list">{data.suggestions.map((s) => <li key={s}>{s}</li>)}</ul></>}
      {data.coverage.sample_variant && <p className="hint">{`Timing guided by ${data.coverage.sample_variant.name} `
        + `(${catalogLabel(data.coverage.sample_variant.catalog_year)} sample plan).`}</p>}
      {ranked && <p className="hint">{`Electives ranked by ${data.generation.model}.`}</p>}
      {data.generation?.message && <p className="hint">{data.generation.message}</p>}
      {stale && <p className="notice">Your plan changed while this was being built, so it can’t be applied. Generate again.</p>}
      <details><summary>Show changes</summary><ul className="report-list">
        {added.map((a, i) => <li key={`a${i}`}>{`Add ${a.code} in ${a.term}`}</li>)}
        {moved.map((a, i) => <li key={`m${i}`}>{`Move ${a.code} from ${a.from} to ${a.to}`}</li>)}
        {removed.map((a, i) => <li key={`r${i}`}>{`Remove ${a.code} from ${a.term}`}</li>)}
      </ul></details>
      <div className="button-row">
        <button type="button" className="btn btn-ink" onClick={onApply} disabled={stale}>Apply suggestions</button>
        <button type="button" className="btn btn-outline" onClick={onDiscard}>Discard</button>
      </div>
    </div>
  );
}

export default CourseBuilder;
