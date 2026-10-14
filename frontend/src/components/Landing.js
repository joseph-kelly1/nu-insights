import React from 'react';

const FEATURES = [
  ['Explore 6,000+ courses', 'See descriptions, prerequisites, credits, and NUpath attributes. Get plain-English AI breakdowns of skills and career relevance using free default models or your own provider key.'],
  ['Understand your requirements', 'Explore majors and concentrations for your catalog year, with historical sample plans for context. Preview AP/IB equivalents and keep estimated credit separate from awarded credit.'],
  ['Build your semester plan', 'Arrange courses around co-op, terms off, and graduation goals. Keep completed courses and pinned choices in place. Drafts save in your browser, with export, import, and printing.'],
  ['Fill gaps and check your plan', 'Suggest remaining courses, with optional AI ranking based on your interests. Review changes before applying them, and check prerequisites, credit targets, and modeled requirement progress.'],
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
        <p className="hero-tagline">Explore your courses. Plan your semesters.</p>
        <div className="hero-start">
          <button type="button" className="btn btn-ink" onClick={() => onEnter('')}>
            Start searching <span className="arrow" aria-hidden="true">→</span>
          </button>
          <p>No account needed. Browse and plan without AI.</p>
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
          <a href="https://catalog.northeastern.edu/" target="_blank" rel="noreferrer">academic catalog</a>
          {' '}and published AP/IB policies. This is a planning aid, not an official degree audit.
          Some requirements and semester offerings need review with your academic advisor.
        </p>
      </footer>
    </div>
  );
}

export default Landing;
