import React, { useState, useCallback, useEffect, useRef } from 'react';
import Landing, { Wordmark } from './components/Landing';
import SearchPanel from './components/SearchPanel';
import CourseDetail from './components/CourseDetail';
import Breakdowns from './components/Breakdowns';
import AISettings, { PROVIDERS, aiLabel } from './components/AISettings';

const PREFS_KEY = 'aiPrefs';

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

function App() {
  const [view, setView] = useState('landing'); // 'landing' | 'app'
  const [pane, setPane] = useState('results'); // the left window shows results or one course
  const [initialQuery, setInitialQuery] = useState('');
  const [detail, setDetail] = useState({ status: 'idle' });
  const [breakdowns, setBreakdowns] = useState([]); // newest first
  const [ai, setAI] = useState(loadAIPrefs);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const detailRequest = useRef(0);
  const nextBreakdown = useRef(0);
  const breakdownsRef = useRef(null);
  const settingsButton = useRef(null);
  const pending = breakdowns.some((b) => b.status === 'loading');

  useEffect(() => {
    try {
      localStorage.setItem(PREFS_KEY, JSON.stringify({ mode: ai.mode, provider: ai.provider, model: ai.model }));
    } catch {
      // storage unavailable: preferences just won't persist
    }
  }, [ai.mode, ai.provider, ai.model]);

  const closeSettings = () => {
    setSettingsOpen(false);
    settingsButton.current?.focus(); // don't strand keyboard focus when the panel unmounts
  };

  const go = (next) => {
    setView(next);
    window.scrollTo(0, 0);
  };

  // Only the latest request may fill the detail view, so a slow response never shows under a newer selection.
  const selectCourse = useCallback(async (dept, number) => {
    const id = ++detailRequest.current;
    const base = { dept, number, code: `${dept.toUpperCase()} ${number}` };
    setDetail({ ...base, status: 'loading' });
    setPane('course');
    let next = { ...base, status: 'error' };
    try {
      const res = await fetch(`/api/course/${dept}/${number}`);
      if (res.ok) next = { ...base, status: 'ready', course: await res.json() };
      else if (res.status === 404) next.status = 'missing';
    } catch {
      // network failure: keep the error state
    }
    if (id === detailRequest.current) setDetail(next);
  }, []);

  // Both breakdown entry points route through here, and `ai` is captured per call,
  // so settings changed mid-request only affect later requests.
  const analyze = useCallback(async (dept, number) => {
    const id = ++nextBreakdown.current;
    const code = `${dept.toUpperCase()} ${number}`;
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
        id, code, status: 'error',
        text: `Add ${missing} in Model settings to use ${PROVIDERS[ai.provider].name}, or switch to App default.`,
      }, ...list]);
      return;
    }

    setBreakdowns((list) => [{ id, code, status: 'loading' }, ...list]);
    let result = { status: 'error', text: 'Could not reach the server for a breakdown. Check that the API is running, then try again.' };
    try {
      const res = await fetch('/api/analyze', {
        method: 'POST',
        cache: 'no-store',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(custom
          ? { dept, number, ai: { mode: 'custom', provider: ai.provider, api_key: ai.apiKey, model: ai.model } }
          : { dept, number }),
      });
      const data = await res.json();
      if (res.ok) result = { status: 'ready', text: data.analysis, provider: custom ? ai.provider : 'openrouter', model: data.model };
      else if (data.error) result.text = data.error;
    } catch {
      // network failure or non-JSON response: keep the generic message
    }
    setBreakdowns((list) => list.map((b) => (b.id === id ? { ...b, ...result } : b)));
  }, [ai]);

  const analyzeCode = useCallback((dept, number) => {
    selectCourse(dept, number);
    analyze(dept, number);
  }, [selectCourse, analyze]);

  if (view === 'landing') {
    return <Landing onEnter={(query) => { setInitialQuery(query); setPane('results'); go('app'); }} />;
  }

  return (
    <div className="workspace">
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

      <main className="ws-body">
        <div className="pane">
          <SearchPanel
            hidden={pane === 'course'}
            initialQuery={initialQuery}
            selectedCode={detail.code}
            onSelect={(c) => selectCourse(c.department_code, c.number)}
          />
          {pane === 'course' && (
            <CourseDetail
              detail={detail}
              pending={pending}
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
