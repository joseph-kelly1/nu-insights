import React, { useEffect, useRef, useState } from 'react';
import { academicYear } from '../coursePlan';

const storedInput = (exam) => Object.fromEntries(['id', 'exam_id', 'score', 'level', 'policy_year', 'version', 'state']
  .map((key) => [key, exam[key]]));
const EMPTY = [];

async function resolve(exams) {
  const response = await fetch('/api/exams/resolve', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ exams: exams.map(storedInput) }),
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || 'AP/IB credit could not be checked. Try again.');
  return body;
}

function Equivalents({ exams }) {
  const awards = new Map();
  for (const exam of exams) for (const award of exam.equivalents || []) awards.set(award.code, award);
  return awards.size ? <ul className="exam-equivalents">
    {[...awards.values()].map((a) => <li key={a.code}><strong>{a.code}</strong>{` · ${a.title} · ${a.credits} credits`}
      {a.nupath.length > 0 && <span className="hint block">{`NUpath: ${a.nupath.join(', ')}`}</span>}</li>)}
  </ul> : null;
}

export default function ExamCreditEditor({ plan, dispatch }) {
  const records = plan.exams || EMPTY;
  const savedYear = records[0]?.policy_year;
  const savedVersion = records[0]?.version;
  const [catalog, setCatalog] = useState(null);
  const [loadError, setLoadError] = useState('');
  const [retry, setRetry] = useState(0);
  const [year, setYear] = useState(records[0]?.policy_year || '');
  const [kind, setKind] = useState('ap');
  const [subject, setSubject] = useState('');
  const [score, setScore] = useState('');
  const [level, setLevel] = useState('HL');
  const [preview, setPreview] = useState(null);
  const [summary, setSummary] = useState(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(null);
  const requestId = useRef(0);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; requestId.current += 1; };
  }, []);
  useEffect(() => {
    let active = true;
    setLoadError('');
    const query = savedYear ? `?policy_year=${encodeURIComponent(savedYear)}&version=${encodeURIComponent(savedVersion)}` : '';
    fetch(`/api/exams/catalog${query}`).then(async (response) => {
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || 'AP/IB policies could not be loaded.');
      if (active) {
        setCatalog(body);
        const suggested = `${academicYear(plan.start)}-${academicYear(plan.start) + 1}`;
        setYear((old) => old || (body.policies.some((p) => p.policy_year === suggested) ? suggested : ''));
      }
    }).catch((error) => { if (active) setLoadError(error.message || 'AP/IB policies could not be loaded.'); });
    return () => { active = false; };
  }, [retry, plan.start, savedYear, savedVersion]);
  useEffect(() => {
    let active = true;
    setSummary(null);
    if (records.length) resolve(records).then((body) => { if (active) setSummary(body); })
      .catch((error) => { if (active) setMessage(error.message); });
    return () => { active = false; };
  }, [records]); // old plans need no migration

  const policy = catalog?.policies.find((p) => p.policy_year === year);
  const changed = (setter, value) => {
    requestId.current += 1;
    setter(value); setPreview(null); setMessage(''); setBusy(false);
  };
  const input = () => ({ id: editing || `exam-${Date.now().toString(36)}`, exam_id: subject, score: Number(score),
    level: kind === 'ib' ? level : null, policy_year: year,
    version: editing ? records.find((e) => e.id === editing).version : records[0]?.version || policy.version, state: 'estimated' });
  const check = async (event) => {
    event.preventDefault();
    const token = ++requestId.current;
    setBusy(true); setMessage(''); setPreview(null);
    const next = input();
    try {
      const body = await resolve([...records.filter((e) => e.id !== next.id), next]);
      if (mounted.current && token === requestId.current) setPreview({ input: next, body });
    } catch (error) { if (mounted.current && token === requestId.current) setMessage(error.message); }
    finally { if (mounted.current && token === requestId.current) setBusy(false); }
  };
  const commit = async (next) => {
    const token = ++requestId.current;
    setBusy(true); setMessage('');
    try {
      const body = await resolve(next);
      if (!mounted.current || token !== requestId.current) return;
      dispatch({ type: 'setExams', exams: body.exams });
      setSummary(body); setPreview(null); setEditing(null); setSubject(''); setScore('');
      setMessage('AP/IB exam saved. Only awarded credit counts toward your plan.');
    } catch (error) { if (mounted.current && token === requestId.current) setMessage(error.message); }
    finally { if (mounted.current && token === requestId.current) setBusy(false); }
  };
  const save = (state) => commit([...records.filter((e) => e.id !== preview.input.id), { ...preview.input, state }]);
  const edit = (exam) => {
    requestId.current += 1;
    setEditing(exam.id); setYear(exam.policy_year); setKind(exam.kind); setSubject(exam.exam_id);
    setScore(String(exam.score)); setLevel(exam.level || 'HL'); setPreview(null); setMessage('');
  };
  const selected = preview?.body.exams.find((e) => e.id === preview.input.id);
  const displayRecords = summary?.exams || records;
  return <section className="exam-credit" aria-labelledby="exam-heading">
    <h3 id="exam-heading" className="editor-subhead">AP / IB exams</h3>
    <p className="hint">Choose your exam and score to see Northeastern equivalents. Estimates stay saved;
      only credit already awarded by Northeastern counts toward your plan.</p>
    {records.length > 0 && <>
      {summary && <p className="hint">{`${summary.awarded_credits} of 32 exam credits counted`}</p>}
      <ul className="attempt-list">
        {displayRecords.map((exam) => <li key={exam.id} className="exam-record">
          <strong>{`${exam.kind?.toUpperCase() || exam.exam_id.split(':')[0].toUpperCase()} ${exam.name || exam.exam_id}`}</strong>
          <span className="hint block">{`Score ${exam.score}${exam.level ? ` · ${exam.level}` : ''} · ${exam.policy_year} · `
            + (exam.state === 'awarded' ? 'Awarded' : 'Estimated, not counted')}</span>
          <Equivalents exams={[exam]} />
          {exam.message && <p className="hint">{exam.message}</p>}
          {exam.source_url && <p className="hint"><a href={exam.source_url} target="_blank" rel="noreferrer">
            Northeastern {exam.policy_year} policy</a></p>}
          <div className="button-row">
            <button type="button" className="btn btn-quiet btn-sm" disabled={busy} onClick={() => edit(exam)}
              aria-label={`Edit ${exam.name || exam.exam_id}`}>Edit exam</button>
            {exam.state === 'estimated' && <button type="button" className="btn btn-quiet btn-sm" disabled={busy || !exam.equivalents?.length}
              onClick={() => commit(records.map((e) => e.id === exam.id ? { ...e, state: 'awarded' } : e))}>
              Mark credit awarded</button>}
            {exam.state === 'awarded' && <button type="button" className="btn btn-quiet btn-sm" disabled={busy}
              onClick={() => commit(records.map((e) => e.id === exam.id ? { ...e, state: 'estimated' } : e))}>
              Change to estimate</button>}
            <button type="button" className="btn btn-quiet btn-sm" disabled={busy}
              onClick={() => commit(records.filter((e) => e.id !== exam.id))} aria-label={`Remove ${exam.name || exam.exam_id}`}>
              Remove exam</button>
          </div>
        </li>)}
      </ul>
      {summary?.notes.map((note) => <p className="hint" key={note}>{note}</p>)}
    </>}
    {loadError ? <div role="alert"><p className="notice-error">{loadError}</p>
      <button type="button" className="btn btn-outline btn-sm" onClick={() => setRetry((n) => n + 1)}>Retry AP/IB policies</button>
    </div> : !catalog ? <p className="hint" role="status">Loading AP/IB policies…</p> : <form onSubmit={check}>
      <div className="attempt-fields">
        <label htmlFor="exam-year">Admission policy year
          <select id="exam-year" className="input input-sm" value={year} disabled={records.length > 0}
            onChange={(e) => { changed(setYear, e.target.value); setSubject(''); }}>
            <option value="">Choose your admission year</option>
            {catalog.policies.map((p) => <option key={p.policy_year} value={p.policy_year}>{p.policy_year}</option>)}
            {year && !policy && <option value={year}>{year} (saved policy)</option>}
          </select>
        </label>
        <label htmlFor="exam-kind">Exam type
          <select id="exam-kind" className="input input-sm" value={kind}
            onChange={(e) => { changed(setKind, e.target.value); setSubject(''); setScore(''); }}>
            <option value="ap">AP</option><option value="ib">IB</option>
          </select>
        </label>
        <label htmlFor="exam-subject" className="wide">Exam subject
          <select id="exam-subject" className="input input-sm" value={subject} disabled={!policy}
            onChange={(e) => changed(setSubject, e.target.value)}>
            <option value="">Choose an exam</option>
            {policy?.exams.filter((e) => e.kind === kind).map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
          </select>
        </label>
        <label htmlFor="exam-score">Exam score
          <select id="exam-score" className="input input-sm" value={score} onChange={(e) => changed(setScore, e.target.value)}>
            <option value="">Choose a score</option>
            {Array.from({ length: kind === 'ap' ? 5 : 7 }, (_, i) => i + 1).map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
        {kind === 'ib' && <label htmlFor="exam-level">IB level
          <select id="exam-level" className="input input-sm" value={level} onChange={(e) => changed(setLevel, e.target.value)}>
            <option value="HL">Higher Level (HL)</option><option value="SL">Standard Level (SL)</option>
          </select>
        </label>}
      </div>
      {!year && <p className="hint">Select a published policy matching your admission year. Another year’s rules may differ.</p>}
      <button className="btn btn-outline btn-sm" disabled={!policy || !subject || !score || busy}>
        {busy ? 'Checking…' : 'Preview exam credit'}</button>
      {editing && <button type="button" className="btn btn-quiet btn-sm" onClick={() => {
        changed(setEditing, null); setSubject(''); setScore('');
      }}>Cancel edit</button>}
    </form>}
    {selected && <section className="exam-preview" aria-label="Exam credit preview">
      <p><strong>{selected.name}</strong>{` · Score ${selected.score}${selected.level ? ` · ${selected.level}` : ''}`}</p>
      <Equivalents exams={[selected]} />
      {selected.message && <p className="hint">{selected.message}</p>}
      <p className="hint"><a href={selected.source_url} target="_blank" rel="noreferrer">Northeastern {selected.policy_year} {kind.toUpperCase()} policy</a></p>
      <div className="button-row">
        <button type="button" className="btn btn-outline btn-sm" disabled={busy} onClick={() => save('estimated')}>Save estimate</button>
        {selected.equivalents.length > 0 && <button type="button" className="btn btn-ink btn-sm" disabled={busy}
          onClick={() => save('awarded')}>Record awarded credit</button>}
      </div>
    </section>}
    <p className="hint" role="status">{message}</p>
  </section>;
}
