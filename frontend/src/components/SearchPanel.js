import React, { useState, useEffect, useRef } from 'react';

const EXAMPLES = ['cs 3000', 'marketing', 'PHIL', 'design'];
const IDLE = { status: 'idle', results: [] };
const LIMIT = 20; // the API returns at most 20 matches per request

export const courseCode = (c) => `${c.department_code.toUpperCase()} ${c.number}`;
export const credits = (n) => `${Number(n)} ${Number(n) === 1 ? 'credit' : 'credits'}`;
export const catalogLabel = (year) => (year ? year.replace('-', '–') : null);

const programUrl = (id, q, offset, concentrations) => `/api/programs/${encodeURIComponent(id)}/courses?q=${encodeURIComponent(q)}&offset=${offset}`
  + (concentrations ? `&concentrations=${encodeURIComponent(concentrations)}` : '');

function SearchPanel({ hidden, initialQuery, selectedCode, major, concentrations = [], onSelect }) {
  const [query, setQuery] = useState(initialQuery);
  const [scope, setScope] = useState('all'); // 'all' | 'major'
  const [search, setSearch] = useState(IDLE);
  const list = useRef(null);
  const input = useRef(null);
  const request = useRef(0); // only the newest query, scope, and major may fill the list
  const lastKey = useRef('');
  const majorId = major?.id;
  const inMajor = scope === 'major' && Boolean(majorId);
  const concentrationKey = concentrations.map((o) => o.id).join(',');
  const inConcentrations = scope === 'concentrations' && Boolean(majorId && concentrationKey);
  const filtered = inMajor || inConcentrations;
  const q = query.trim();

  useEffect(() => input.current?.focus(), []); // arriving from the landing page, start typing right away

  // Coming back from a course, return focus to the row that opened it.
  useEffect(() => {
    if (!hidden) list.current?.querySelector('[aria-current="true"]')?.focus();
  }, [hidden]);

  useEffect(() => {
    const id = ++request.current;
    if (!q && !filtered) {
      setSearch(IDLE);
      return undefined;
    }
    // Keep old rows while typing, but never show one major's courses under another.
    const key = filtered ? `${majorId}|${inConcentrations ? concentrationKey : 'plans'}` : '';
    const keep = key === lastKey.current;
    lastKey.current = key;
    setSearch((s) => ({ ...s, results: keep ? s.results : [], status: 'loading' }));
    const timer = setTimeout(async () => {
      let next = { status: 'error', results: [] };
      try {
        const res = await fetch(filtered ? programUrl(majorId, q, 0, inConcentrations ? concentrationKey : '') : `/api/search?q=${encodeURIComponent(q)}`);
        if (res.ok) {
          const data = await res.json();
          next = filtered
            ? { status: 'ready', results: data.results, total: data.total, dataset: data.concentration_dataset || data.plan_dataset }
            : { status: 'ready', results: data };
        } else if (filtered && res.status === 404) next.status = 'unknown';
      } catch {
        // network failure: show the error state
      }
      if (id === request.current) setSearch(next);
    }, 300);
    return () => clearTimeout(timer);
  }, [q, filtered, inConcentrations, concentrationKey, majorId]);

  const showMore = async () => {
    const id = request.current;
    setSearch((s) => ({ ...s, status: 'more' }));
    let page = null;
    try {
      const res = await fetch(programUrl(majorId, q, search.results.length, inConcentrations ? concentrationKey : ''));
      if (res.ok) page = await res.json();
    } catch {
      // network failure: keep the rows and offer the button again
    }
    if (id !== request.current) return;
    setSearch((s) => {
      if (!page) return { ...s, status: 'ready', moreFailed: true };
      const seen = new Set(s.results.map(courseCode));
      return { ...s, status: 'ready', moreFailed: false, total: page.total,
        results: [...s.results, ...page.results.filter((c) => !seen.has(courseCode(c)))] };
    });
  };

  const { status, results, total } = search;
  const count = results.length;
  const year = catalogLabel(search.dataset?.catalog_year);
  const noPlan = major?.status && major.status !== 'available';

  let message = '';
  if (status === 'loading') message = filtered && !q ? `Loading courses for ${major.label}…` : 'Searching…';
  else if (status === 'error') message = 'Search is unavailable. Check that the API is running, then try again.';
  else if (status === 'unknown') message = 'This major isn’t in the loaded data. Choose your major again or clear it.';
  else if (filtered && (status === 'ready' || status === 'more')) {
    message = count ? `Showing ${count} of ${total} ${total === 1 ? 'course' : 'courses'}`
      : inConcentrations ? 'No explicit course rows match your selected concentration choices. Check the catalog requirements for elective ranges and other options.'
      : noPlan ? `${major.label} has no published sample plan in this dataset, so there are no plan courses to list.`
      : q ? `No courses in the ${major.label} sample plans match “${q}”. Try a shorter word, or switch to All courses.`
      : `No catalog courses were found in the ${major.label} sample plans.`;
    if (search.moreFailed) message += '. More courses couldn’t load; try again.';
  } else if (status === 'ready') {
    message = !count ? `No courses match “${q}”. Try a department code like “cs” or a shorter title word.`
      : `${count === LIMIT ? 'First 20' : count} ${count === 1 ? 'match' : 'matches'}${count === LIMIT ? ' · narrow your search to see more' : ''}`;
  }

  return (
    <section className="rail" aria-label="Course search" hidden={hidden}>
      {major && (
        <fieldset className="radios scope">
          <legend className="field-label">Browse</legend>
          <label><input type="radio" name="scope" checked={!filtered} onChange={() => setScope('all')} /> All courses</label>
          <label><input type="radio" name="scope" checked={inMajor} onChange={() => setScope('major')} /> My major</label>
          {concentrationKey && <label><input type="radio" name="scope" checked={inConcentrations}
            onChange={() => setScope('concentrations')} /> My concentrations</label>}
        </fieldset>
      )}
      {inMajor && (
        <p className="hint scope-hint">
          {`Courses that appear in the collected ${year ? `${year} ` : ''}sample plans for ${major.label}. `}
          This is not a complete or current requirements list, and electives the plans leave open aren’t included.
        </p>
      )}
      {inConcentrations && <p className="hint scope-hint">
        {`Explicit course rows in your selected ${year ? `${year} ` : ''}concentration requirements, including alternatives and electives. `}
        These are course options, not a list of courses you must take. Elective ranges are shown in the catalog requirements above.
      </p>}

      <label htmlFor="course-search" className="field-label">Search courses</label>
      <input
        ref={input}
        id="course-search"
        className="input"
        type="search"
        autoComplete="off"
        placeholder={filtered ? 'Narrow by cs, cs 3000, or a title word' : 'cs, cs 3000, or a title word'}
        aria-describedby="search-hint"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      <p id="search-hint" className="hint">Search by department, course code, or title.</p>

      {!q && !filtered && (
        <div className="examples">
          <span className="hint">Try</span>
          {EXAMPLES.map((ex) => (
            <button key={ex} type="button" className="chip" onClick={() => setQuery(ex)}>{ex}</button>
          ))}
        </div>
      )}

      <p className="rail-status" role="status">{message}</p>

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

      {filtered && count > 0 && count < total && (
        <button type="button" className="btn btn-outline more" disabled={status !== 'ready'} onClick={showMore}>
          {status === 'more' ? 'Loading…' : `Show ${Math.min(LIMIT, total - count)} more`}
        </button>
      )}
    </section>
  );
}

export default SearchPanel;
