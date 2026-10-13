import React from 'react';

const FEATURES = [
  ['Search 6,000+ courses', 'Look up any course by department, code, or title word, with its description, credits, and NUpath attributes.'],
  ['Read prerequisites clearly', 'Prerequisite rules appear as “All of” and “One of” groups, so required courses stand apart from alternatives.'],
  ['See where a course fits', 'Choose your major to see where its 2025–26 sample plans place a course, and browse the courses those plans name.'],
  ['Get a plain-English breakdown', 'Ask for a short take on what a course covers, who usually takes it, and how it connects to co-op, written from catalog data.'],
];

export function Wordmark() {
  return (
    <span className="wordmark">
      <span className="wordmark-mark" aria-hidden="true" />
      <span><b>NU</b> Insights</span>
    </span>
  );
}

function Landing({ onEnter }) {
  return (
    <div className="landing">
      <main className="hero">
        <svg className="orbit" viewBox="0 0 1000 600" preserveAspectRatio="none" aria-hidden="true" focusable="false">
          <path d="M-40 520 C 220 180, 700 40, 1040 120" />
        </svg>
        <h1>NU Insights</h1>
        <p className="hero-tagline">Find the courses that move you forward.</p>
        <div className="hero-start">
          <button type="button" className="btn btn-ink" onClick={() => onEnter('')}>
            Start searching <span className="arrow" aria-hidden="true">→</span>
          </button>
          <p>No account needed. Breakdowns use free models by default.</p>
        </div>
      </main>

      <section className="about" aria-labelledby="about-heading">
        <h2 id="about-heading">What you can do here</h2>
        <dl>
          {FEATURES.map(([term, text]) => (
            <div key={term}>
              <dt>{term}</dt>
              <dd>{text}</dd>
            </div>
          ))}
        </dl>
      </section>

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
