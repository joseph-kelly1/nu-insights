import React, { useState, useCallback, useEffect } from 'react';
import SearchPanel from './components/SearchPanel';
import ChatPanel from './components/ChatPanel';
import AISettings, { PROVIDERS } from './components/AISettings';
import './App.css';

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
  const [view, setView] = useState('loading'); // 'loading' | 'landing' | 'app'
  const [messages, setMessages] = useState([]);
  const [selectedCourse, setSelectedCourse] = useState(null);
  const [ai, setAI] = useState(loadAIPrefs);
  const [settingsOpen, setSettingsOpen] = useState(false);

  useEffect(() => {
    try {
      localStorage.setItem(PREFS_KEY, JSON.stringify({ mode: ai.mode, provider: ai.provider, model: ai.model }));
    } catch {
      // storage unavailable: preferences just won't persist
    }
  }, [ai.mode, ai.provider, ai.model]);

  useEffect(() => {
    const timer = setTimeout(() => setView('landing'), 2000);
    return () => clearTimeout(timer);
  }, []);

  const addMessage = useCallback((message) => {
    setMessages((prev) => [...prev, message]);
  }, []);

  // Both analysis entry points route through here, and `ai` is captured per call,
  // so settings changed mid-request only affect later requests.
  const analyzeCourse = useCallback(async (dept, number) => {
    const custom = ai.mode === 'custom';
    const missing = custom && (!ai.apiKey ? 'an API key' : !ai.model && 'a model');
    if (missing) {
      setSettingsOpen(true);
      addMessage({
        role: 'system',
        content: `Add ${missing} in AI settings to use ${PROVIDERS[ai.provider].name}, or switch to App default.`,
      });
      return;
    }

    addMessage({ role: 'system', content: 'Thinking...' });
    let reply = { role: 'system', content: 'Failed to get AI analysis. Is the backend running?' };

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
      if (res.ok) {
        reply = { role: 'assistant', content: data.analysis, provider: custom ? ai.provider : 'openrouter', model: data.model };
      } else if (data.error) reply.content = data.error;
    } catch {
      // network failure or non-JSON response: keep the generic message
    }

    setMessages((prev) => [...prev.filter((m) => !(m.role === 'system' && m.content === 'Thinking...')), reply]);
  }, [addMessage, ai]);

  const handleCourseClick = useCallback(async (course) => {
    try {
      const res = await fetch(`/api/course/${course.department_code}/${course.number}`);
      if (res.ok) {
        setSelectedCourse(await res.json());
      }
    } catch {
      // silently fail on detail fetch
    }

    const code = `${course.department_code.toUpperCase()} ${course.number}`;
    addMessage({ role: 'user', content: `Analyze ${code}` });
    analyzeCourse(course.department_code, course.number);
  }, [addMessage, analyzeCourse]);

  const handleSendMessage = useCallback(async (text) => {
    addMessage({ role: 'user', content: text });

    const match = text.match(/^([a-zA-Z]{2,4})\s*(\d{4})$/);
    if (match) {
      analyzeCourse(match[1], match[2]);

      try {
        const courseRes = await fetch(`/api/course/${match[1]}/${match[2]}`);
        if (courseRes.ok) setSelectedCourse(await courseRes.json());
      } catch {
        // ignore
      }
    } else {
      addMessage({
        role: 'system',
        content: 'Type a course code like "CS 3000" to analyze it, or click a course from the search results.',
      });
    }
  }, [addMessage, analyzeCourse]);

  const handleNewChat = useCallback(() => {
    setMessages([]);
  }, []);

  if (view === 'loading') {
    return (
      <div className="loading-screen">
        <div className="loading-logo">N</div>
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      </div>
    );
  }

  if (view === 'landing') {
    return (
      <div className="landing antialiased flex flex-col bg-[#1A1A2E]">
        {/* TopNavBar */}
        <nav className="fixed top-0 w-full z-50 bg-[#1A1A2E]/80 backdrop-blur-xl border-b border-white/5">
          <div className="flex justify-between items-center px-12 py-6 max-w-screen-2xl mx-auto">
            <div className="text-xl font-bold tracking-tighter text-[#F3F4F6]">NEU Insights</div>
            <div className="flex items-center space-x-6">
              <button
                className="primary-cta px-6 py-2.5 rounded-lg text-sm font-semibold text-white shadow-lg active:scale-90 transition-transform"
                onClick={() => setView('app')}
              >
                Get Started
              </button>
            </div>
          </div>
        </nav>

        <main className="flex-grow flex items-center relative px-12 pt-12">
          <div className="max-w-7xl mx-auto w-full grid grid-cols-1 lg:grid-cols-12 gap-12 items-center">
            {/* Hero Content */}
            <div className="lg:col-span-7 space-y-6">
              <h1 className="text-6xl md:text-7xl font-extrabold tracking-tighter text-[#F3F4F6] leading-[1.1]">
                <span className="text-[#FF3B30]">AI-Powered</span> NEU Course Insight.
              </h1>
              <p className="text-xl text-[#6B7280] max-w-lg leading-relaxed">
                Cut through course descriptions. Get instant, student-focused breakdowns of every Northeastern course, prerequisites, and career connections.
              </p>
              <div className="flex flex-col sm:flex-row gap-4">
                <button
                  className="primary-cta px-10 py-4 rounded-lg text-lg font-bold text-white shadow-2xl hover:brightness-110 transition-all flex items-center justify-center gap-2"
                  onClick={() => setView('app')}
                >
                  Get Started
                  <span className="material-symbols-outlined">arrow_forward</span>
                </button>
              </div>
            </div>

            {/* Hero Graphic (Glass Card Dashboard) */}
            <div className="lg:col-span-5 relative hidden lg:block">
              <div className="aspect-square hero-glass-card rounded-3xl ghost-border p-10 flex flex-col justify-center items-center relative z-10">
                <div className="absolute inset-0 hero-gradient-anim rounded-3xl"></div>
                <div className="w-full space-y-8 relative z-20">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl bg-[#FF3B30] flex items-center justify-center">
                      <span className="material-symbols-outlined text-white">psychology</span>
                    </div>
                    <div>
                      <div className="h-2 w-24 bg-[#FF3B30] rounded-full mb-2"></div>
                      <div className="h-1.5 w-16 bg-white/20 rounded-full"></div>
                    </div>
                  </div>
                  <div className="space-y-4">
                    <div className="h-4 w-full bg-white/10 rounded-full"></div>
                    <div className="h-4 w-5/6 bg-white/10 rounded-full"></div>
                    <div className="h-4 w-4/6 bg-white/10 rounded-full"></div>
                  </div>
                  <div className="grid grid-cols-2 gap-4 pt-4">
                    <div className="h-20 rounded-2xl bg-white/5 border border-white/5 flex flex-col justify-center px-4">
                      <div className="h-1.5 w-1/2 bg-[#FF3B30]/50 rounded-full mb-2"></div>
                      <div className="h-3 w-3/4 bg-white/20 rounded-full"></div>
                    </div>
                    <div className="h-20 rounded-2xl bg-white/5 border border-white/5 flex flex-col justify-center px-4">
                      <div className="h-1.5 w-1/2 bg-[#FF3B30]/50 rounded-full mb-2"></div>
                      <div className="h-3 w-3/4 bg-white/20 rounded-full"></div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </main>
      </div>
    );
  }

  return (
    <main className="flex h-screen w-full bg-[#1A1A2E] text-[#e2e0fc] font-body overflow-hidden">
      <SearchPanel
        onCourseClick={handleCourseClick}
        selectedCourse={selectedCourse}
        onBackToResults={() => setSelectedCourse(null)}
      />
      <ChatPanel
        messages={messages}
        onSend={handleSendMessage}
        onNewChat={handleNewChat}
        aiSettings={
          <AISettings
            ai={ai}
            open={settingsOpen}
            onToggle={() => setSettingsOpen((open) => !open)}
            onApply={(next) => {
              setAI(next);
              setSettingsOpen(false);
            }}
            onClearKey={() => setAI((current) => (current.mode === 'custom' ? { ...current, apiKey: '' } : current))}
          />
        }
      />
    </main>
  );
}

export default App;
