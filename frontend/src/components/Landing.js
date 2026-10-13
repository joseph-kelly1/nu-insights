import React, { useState } from 'react';

const EXAMPLES = ['cs 3000', 'marketing', 'PHIL'];

export function Wordmark() {
  return (
    <span className="wordmark">
      <span className="wordmark-mark" aria-hidden="true" />
      <span><b>NU</b> Insights</span>
    </span>
  );
}

function Landing({ onEnter }) {
  const [query, setQuery] = useState('');

  return (
    <div className="landing">
      <main className="hero">
        <svg className="orbit" viewBox="0 0 1000 600" preserveAspectRatio="none" aria-hidden="true" focusable="false">
          <path d="M-40 520 C 220 180, 700 40, 1040 120" />
        </svg>
        <h1>NU Insights</h1>
        <p className="hero-tagline">Find the courses that move you forward.</p>
        <form className="hero-search" role="search" onSubmit={(e) => { e.preventDefault(); onEnter(query.trim()); }}>
          <label htmlFor="hero-query" className="sr-only">Search courses</label>
          <input
            id="hero-query"
            className="input"
            autoComplete="off"
            placeholder="Department, course code, or title"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button type="submit" className="btn btn-ink">Search</button>
        </form>
        <p className="hero-try">
          Try{' '}
          {EXAMPLES.map((ex, i) => (
            <React.Fragment key={ex}>
              {i > 0 && ', '}
              <button type="button" className="link-button" onClick={() => onEnter(ex)}>{ex}</button>
            </React.Fragment>
          ))}
        </p>
        <p className="hero-note">
          Descriptions, prerequisites, and NUpath attributes for 6,000+ catalog courses, with a plain-English
          breakdown of any course on request.
        </p>
      </main>

      <footer className="footer">
        <Wordmark />
        <p>
          Not affiliated with Northeastern University. Data from the public{' '}
          <a href="https://catalog.northeastern.edu/" target="_blank" rel="noreferrer">course catalog</a>.
          Breakdowns can be wrong, so confirm with your academic advisor before registering.
        </p>
      </footer>
    </div>
  );
}

export default Landing;
