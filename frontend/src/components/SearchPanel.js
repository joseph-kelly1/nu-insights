import React, { useState, useEffect, useRef } from 'react';

const EXAMPLES = ['cs 3000', 'marketing', 'PHIL', 'design'];
const IDLE = { status: 'idle', results: [] };
const LIMIT = 20; // the API returns at most 20 matches

export const courseCode = (c) => `${c.department_code.toUpperCase()} ${c.number}`;
export const credits = (n) => `${Number(n)} ${Number(n) === 1 ? 'credit' : 'credits'}`;

function SearchPanel({ hidden, initialQuery, selectedCode, onSelect }) {
  const [query, setQuery] = useState(initialQuery);
  const [search, setSearch] = useState(IDLE);
  const list = useRef(null);

  // Coming back from a course, return focus to the row that opened it.
  useEffect(() => {
    if (!hidden) list.current?.querySelector('[aria-current="true"]')?.focus();
  }, [hidden]);

  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setSearch(IDLE);
      return undefined;
    }
    let stale = false;
    setSearch((s) => ({ ...s, status: 'loading' })); // keep old rows visible while typing
    const timer = setTimeout(async () => {
      let next = { status: 'error', results: [] };
      try {
        const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
        if (res.ok) next = { status: 'ready', results: await res.json() };
      } catch {
        // network failure: show the error state
      }
      if (!stale) setSearch(next);
    }, 300);
    return () => {
      stale = true;
      clearTimeout(timer);
    };
  }, [query]);

  const { status, results } = search;
  const count = results.length;

  return (
    <section className="rail" aria-label="Course search" hidden={hidden}>
      <label htmlFor="course-search" className="field-label">Search courses</label>
      <input
        id="course-search"
        className="input"
        type="search"
        autoComplete="off"
        placeholder="cs, cs 3000, or a title word"
        aria-describedby="search-hint"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      <p id="search-hint" className="hint">Search by department, course code, or title.</p>

      {!query.trim() && (
        <div className="examples">
          <span className="hint">Try</span>
          {EXAMPLES.map((ex) => (
            <button key={ex} type="button" className="chip" onClick={() => setQuery(ex)}>{ex}</button>
          ))}
        </div>
      )}

      <p className="rail-status" role="status">
        {status === 'loading' ? 'Searching…'
          : status === 'error' ? 'Search is unavailable. Check that the API is running, then try again.'
          : status === 'ready' && !count ? `No courses match “${query.trim()}”. Try a department code like “cs” or a shorter title word.`
          : status === 'ready' ? `${count === LIMIT ? 'First 20' : count} ${count === 1 ? 'match' : 'matches'}${count === LIMIT ? ' · narrow your search to see more' : ''}`
          : ''}
      </p>

      {status !== 'error' && count > 0 && (
        <ul className="results" ref={list}>
          {results.map((course) => {
            const code = courseCode(course);
            return (
              <li key={code}>
                <button
                  type="button"
                  className="result"
                  aria-current={code === selectedCode ? 'true' : undefined}
                  onClick={() => onSelect(course)}
                >
                  <span className="result-code">{code}</span>
                  <span className="result-title">{course.title}</span>
                  <span className="result-credits">{credits(course.credits)}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

export default SearchPanel;
