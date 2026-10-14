import React, { useState, useCallback, useEffect, useRef, useMemo } from 'react';
import Landing, { Wordmark } from './components/Landing';
import SearchPanel from './components/SearchPanel';
import CourseDetail from './components/CourseDetail';
import Breakdowns from './components/Breakdowns';
import AISettings, { PROVIDERS, aiLabel } from './components/AISettings';
import MajorPicker from './components/MajorPicker';
import ConcentrationPicker from './components/ConcentrationPicker';
import CourseBuilder from './components/CourseBuilder';

const PREFS_KEY = 'aiPrefs';
const MAJOR_KEY = 'major';
const CONCENTRATIONS_KEY = 'concentrations';
// A tiny hash route so refresh and back/forward keep the builder open, without a router package.
const ROUTES = { landing: '', app: '#/browse', builder: '#/builder' };
const routeView = () => Object.keys(ROUTES).find((view) => ROUTES[view] && ROUTES[view] === window.location.hash) || 'landing';

function loadConcentrations() {
  try {
    const saved = JSON.parse(localStorage.getItem(CONCENTRATIONS_KEY));
    if (saved && Array.isArray(saved.ids)) return saved;
  } catch { /* invalid storage starts undecided */ }
  return { majorId: null, catalogYear: null, ids: [] };
}

// Only non-secret preferences survive a reload; the API key must be entered again.
function loadAIPrefs() {
  try {
    const { mode, provider, model } = JSON.parse(localStorage.getItem(PREFS_KEY)) || {};
    if (mode === 'custom' && PROVIDERS[provider]) return { mode, provider, model: model || '', apiKey: '' };
  } catch {
    // unavailable or corrupt storage: use the app default
  }
  return { mode: 'default' };
}

// The id is the identity; label and status let the UI render before the program list loads.
function loadMajor() {
  try {
    const { id, label, status } = JSON.parse(localStorage.getItem(MAJOR_KEY)) || {};
    if (typeof id === 'string' && typeof label === 'string') return { id, label, status };
  } catch {
    // unavailable or corrupt storage: no major
  }
  return null;
}

function App() {
  // Refresh restores the builder; browsing state isn't kept across reloads, so it starts at the landing page.
  const [view, setView] = useState(() => (routeView() === 'builder' ? 'builder' : 'landing')); // 'landing' | 'app' | 'builder'
  const [pane, setPane] = useState('results'); // the left window shows results or one course
  const [initialQuery, setInitialQuery] = useState('');
  const [detail, setDetail] = useState({ status: 'idle' });
  const [breakdowns, setBreakdowns] = useState([]); // newest first
  const [ai, setAI] = useState(loadAIPrefs);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [major, setMajor] = useState(loadMajor);
  const [programs, setPrograms] = useState({ status: 'idle', list: [] });
  const [concentrationCatalog, setConcentrationCatalog] = useState({ status: 'idle', majorId: null });
  const [concentrationSelection, setConcentrationSelection] = useState(loadConcentrations);
  const [concentrationRefresh, setConcentrationRefresh] = useState(0);
  const detailRequest = useRef(0);
  const nextBreakdown = useRef(0);
  const breakdownsRef = useRef(null);
  const settingsButton = useRef(null);
  const pending = breakdowns.some((b) => b.status === 'loading');
  const catalogReady = concentrationCatalog.status === 'ready' && concentrationCatalog.majorId === major?.id;
  const concentrations = useMemo(() => catalogReady ? concentrationCatalog.data.groups.flatMap((group) =>
    group.fixed ? group.options : concentrationSelection.majorId === major?.id
      && concentrationSelection.catalogYear === concentrationCatalog.data.catalog_year
      ? concentrationSelection.ids.map((id) => group.options.find((o) => o.id === id)).filter(Boolean) : []) : [],
    [catalogReady, concentrationCatalog, concentrationSelection, major?.id]);
  const concentrationIds = useMemo(() => concentrations.map((o) => o.id), [concentrations]);

  useEffect(() => {
    const follow = () => setView(routeView());
    window.addEventListener('hashchange', follow);
    return () => window.removeEventListener('hashchange', follow);
  }, []);

  useEffect(() => {
    if (view === 'landing' || !major?.id) return undefined;
    const majorId = major.id;
    let cancelled = false;
    setConcentrationCatalog({ status: 'loading', majorId });
    (async () => {
      try {
        const response = await fetch(`/api/programs/${encodeURIComponent(majorId)}/concentrations`);
        if (!response.ok) throw new Error();
        const data = await response.json();
        if (cancelled) return;
        setConcentrationCatalog({ status: 'ready', majorId, data });
        setConcentrationSelection((saved) => {
          const ids = saved.majorId === majorId && saved.catalogYear === data.catalog_year
            ? data.groups.flatMap((group) => {
              let chosen = [...new Set(saved.ids)].map((id) => group.options.find((o) => o.id === id)).filter(Boolean);
              if (!chosen.some((o) => !o.secondary_only)) chosen = [];
              if (chosen.some((o) => o.kind === 'alternative')) chosen = chosen.filter((o) => o.kind === 'alternative').slice(0, 1);
              if (group.policy.max_selections) chosen = chosen.slice(0, group.policy.max_selections);
              return chosen.map((o) => o.id);
            }) : [];
          return { majorId, catalogYear: data.catalog_year, ids };
        });
      } catch {
        if (!cancelled) setConcentrationCatalog({ status: 'error', majorId });
      }
    })();
    return () => { cancelled = true; };
  }, [view === 'landing', major?.id, concentrationRefresh]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!catalogReady || concentrationSelection.majorId !== major?.id) return;
    try { localStorage.setItem(CONCENTRATIONS_KEY, JSON.stringify(concentrationSelection)); } catch { /* storage unavailable */ }
  }, [catalogReady, concentrationSelection, major?.id]);

  const changeMajor = (next) => {
    setMajor(next);
    setConcentrationSelection({ majorId: next?.id || null, catalogYear: null, ids: [] });
    try { localStorage.removeItem(CONCENTRATIONS_KEY); } catch { /* storage unavailable */ }
  };

  const changeConcentrations = (groupId, ids) => {
    const group = concentrationCatalog.data.groups.find((g) => g.id === groupId);
    setConcentrationSelection((saved) => ({ ...saved,
      ids: [...saved.ids.filter((id) => !group.options.some((o) => o.id === id)), ...ids] }));
  };

  useEffect(() => {
    try {
      localStorage.setItem(PREFS_KEY, JSON.stringify({ mode: ai.mode, provider: ai.provider, model: ai.model }));
    } catch {
      // storage unavailable: preferences just won't persist
    }
  }, [ai.mode, ai.provider, ai.model]);

  useEffect(() => {
    try {
      if (major) localStorage.setItem(MAJOR_KEY, JSON.stringify({ id: major.id, label: major.label, status: major.status }));
      else localStorage.removeItem(MAJOR_KEY);
    } catch {
      // storage unavailable: the major just won't persist
    }
  }, [major]);

  useEffect(() => {
    if (view === 'landing' || programs.status !== 'idle') return;
    setPrograms({ status: 'loading', list: [] });
    (async () => {
      try {
        const res = await fetch('/api/programs');
        if (!res.ok) throw new Error();
        const list = await res.json();
        setPrograms({ status: 'ready', list });
        // A saved major the refreshed data no longer has is dropped rather than sent stale.
        setMajor((m) => (m && list.length ? list.find((p) => p.id === m.id) || null : m));
      } catch {
        setPrograms({ status: 'error', list: [] });
      }
    })();
  }, [view, programs.status]);

  const closeSettings = () => {
    setSettingsOpen(false);
    settingsButton.current?.focus(); // don't strand keyboard focus when the panel unmounts
  };

  const go = (next) => {
    setView(next);
    if (window.location.hash !== ROUTES[next]) window.location.hash = ROUTES[next];
    setPane('results');
    window.scrollTo(0, 0);
  };

  // Only the latest request may fill the detail view, so a slow response never shows under a newer selection.
  const selectCourse = useCallback(async (dept, number, catalogYear) => {
    const id = ++detailRequest.current;
    const base = { dept, number, catalogYear, code: `${dept.toUpperCase()} ${number}` };
    setDetail({ ...base, status: 'loading' });
    setPane('course');
    let next = { ...base, status: 'error' };
    try {
      const res = await fetch(`/api/course/${dept}/${number}${catalogYear ? `?catalog_year=${encodeURIComponent(catalogYear)}` : ''}`);
      if (res.ok) next = { ...base, status: 'ready', course: await res.json() };
      else if (res.status === 404) next.status = 'missing';
    } catch {
      // network failure: keep the error state
    }
    if (id === detailRequest.current) setDetail(next);
  }, []);

  // Both breakdown entry points route through here, and `ai` and `major` are captured per call,
  // so settings or a major changed mid-request only affect later requests.
  const analyze = useCallback(async (dept, number) => {
    const id = ++nextBreakdown.current;
    const code = `${dept.toUpperCase()} ${number}`;
    const forMajor = major ? { major: major.label, concentrations: concentrations.map((o) => o.name) } : {}; // captured per request
    const custom = ai.mode === 'custom';
    const missing = custom && (!ai.apiKey ? 'an API key' : !ai.model && 'a model');
    const section = breakdownsRef.current; // newest entry is at the top, so bring the top into view
    if (section) {
      section.scrollTop = 0;
      section.scrollIntoView({ block: 'start' });
    }
    if (missing) {
      setSettingsOpen(true);
      setBreakdowns((list) => [{
        id, code, ...forMajor, status: 'error',
        text: `Add ${missing} in Model settings to use ${PROVIDERS[ai.provider].name}, or switch to App default.`,
      }, ...list]);
      return;
    }

    setBreakdowns((list) => [{ id, code, ...forMajor, status: 'loading' }, ...list]);
    let result = { status: 'error', text: 'Could not reach the server for a breakdown. Check that the API is running, then try again.' };
    try {
      const res = await fetch('/api/analyze', {
        method: 'POST',
        cache: 'no-store',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          dept,
          number,
          ...(major && { major: major.id }),
          ...(concentrationIds.length > 0 && { concentrations: concentrationIds }),
          ...(custom && { ai: { mode: 'custom', provider: ai.provider, api_key: ai.apiKey, model: ai.model } }),
        }),
      });
      const data = await res.json();
      if (res.ok) result = { status: 'ready', text: data.analysis, provider: custom ? ai.provider : 'openrouter', model: data.model };
      else if (data.error) result.text = data.error;
    } catch {
      // network failure or non-JSON response: keep the generic message
    }
    setBreakdowns((list) => list.map((b) => (b.id === id ? { ...b, ...result } : b)));
  }, [ai, major, concentrations, concentrationIds]);

  const analyzeCode = useCallback((dept, number) => {
    selectCourse(dept, number);
    analyze(dept, number);
  }, [selectCourse, analyze]);

  if (view === 'landing') {
    return <Landing onEnter={(query) => { setInitialQuery(query); setPane('results'); go('app'); }} />;
  }

  const header = (
    <header className="ws-header">
      <button type="button" className="wordmark-button" onClick={() => go('landing')} aria-label="NU Insights home">
        <Wordmark />
      </button>
      <button
        ref={settingsButton}
        type="button"
        className="btn btn-quiet"
        aria-expanded={settingsOpen}
        aria-controls="ai-settings"
        onClick={() => setSettingsOpen((open) => !open)}
      >
        Model settings
      </button>
      {settingsOpen && (
        <AISettings
          ai={ai}
          onApply={(next) => {
            setAI(next);
            closeSettings();
          }}
          onCancel={closeSettings}
          onClearKey={() => setAI((current) => (current.mode === 'custom' ? { ...current, apiKey: '' } : current))}
        />
      )}
    </header>
  );

  if (view === 'builder') {
    const choicesReady = !major || catalogReady || concentrationCatalog.status === 'error';
    return (
      <div className="workspace workspace-builder">
        {header}
        {!major ? (
          <main className="builder">
            <button type="button" className="back" onClick={() => go('app')}>← Back to course browsing</button>
            <h1>Course Builder</h1>
            <p>Choose your major in course browsing first, then come back to build your plan.</p>
          </main>
        ) : !choicesReady ? <main className="builder"><p className="pending">Loading your program…</p></main> : (
          <CourseBuilder
            key={`${major.id}|${concentrationIds.join(',')}`}
            major={major}
            concentrations={concentrations}
            ai={ai}
            aiLabel={aiLabel(ai)}
            onBack={() => go('app')}
            onOpenCourse={selectCourse}
            onCloseCourse={() => setPane('results')}
            detail={pane === 'course' ? (
              <CourseDetail detail={detail} major={major} concentrations={concentrations} backLabel="← Back to plan"
                onBack={() => setPane('results')} onRetry={() => selectCourse(detail.dept, detail.number, detail.catalogYear)} />
            ) : null}
          />
        )}
      </div>
    );
  }

  return (
    <div className="workspace">
      {header}

      <main className="ws-body">
        <div className="pane">
          <div className="program-context">
            <MajorPicker programs={programs} major={major} onChange={changeMajor} onRetry={() => setPrograms({ status: 'idle', list: [] })} />
            {major && <ConcentrationPicker
              catalog={concentrationCatalog.majorId === major.id ? concentrationCatalog : { status: 'loading' }}
              selected={concentrations} onChange={changeConcentrations}
              onRetry={() => setConcentrationRefresh((n) => n + 1)} />}
            {major && <div className="builder-entry">
              <button type="button" className="btn btn-outline btn-sm" onClick={() => go('builder')}>Open Course Builder</button>
            </div>}
          </div>
          <SearchPanel
            hidden={pane === 'course'}
            initialQuery={initialQuery}
            selectedCode={detail.code}
            major={major}
            concentrations={concentrations}
            onSelect={(c) => selectCourse(c.department_code, c.number)}
          />
          {pane === 'course' && (
            <CourseDetail
              detail={detail}
              pending={pending}
              major={major}
              concentrations={concentrations}
              onBack={() => setPane('results')}
              onRetry={() => selectCourse(detail.dept, detail.number)}
              onBreakdown={() => analyze(detail.dept, detail.number)}
            />
          )}
        </div>
        <Breakdowns
          ref={breakdownsRef}
          breakdowns={breakdowns}
          pending={pending}
          source={aiLabel(ai)}
          onCode={analyzeCode}
          onClear={() => setBreakdowns([])}
        />
      </main>
    </div>
  );
}

export default App;
