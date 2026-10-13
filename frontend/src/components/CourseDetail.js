import React from 'react';
import { credits } from './SearchPanel';

// Renders the catalog's AND/OR tree as nested groups, so the logic reads exactly as stored.
export function PrereqTree({ node }) {
  if (Array.isArray(node)) return <PrereqTree node={{ type: 'AND', courses: node }} />;
  if (node.course) return <span className="req-course">{node.course}</span>;
  if (node.admission_requirement) return <span className="req-note">{node.admission_requirement}</span>;
  if (node.type && node.courses) {
    return (
      <div className={`req-group req-${node.type.toLowerCase()}`}>
        <p className="req-label">{node.type === 'AND' ? 'All of' : 'One of'}</p>
        <ul>
          {node.courses.map((child, i) => <li key={i}><PrereqTree node={child} /></li>)}
        </ul>
      </div>
    );
  }
  return <span className="req-note">{String(node)}</span>;
}

const hasPrereqs = (p) => (Array.isArray(p) ? p.length > 0 : Boolean(p));

function PlanPlacement({ entries }) {
  const rows = [...new Set(entries.map((e) => `Year ${e.year}, ${e.term} · ${[e.major_name || e.major, e.plan_name].filter(Boolean).join(', ')}`))];
  return (
    <section className="course-section">
      <h3>Sample plan placement</h3>
      <p className="hint">From published sample plans of study. Not live sections or a check of your eligibility.</p>
      {rows.length ? (
        <ul className="plan-list">{rows.map((r) => <li key={r}>{r}</li>)}</ul>
      ) : (
        <p>No published sample plan in this dataset includes this course.</p>
      )}
    </section>
  );
}

function CourseDetail({ detail, pending, onBack, onRetry, onBreakdown }) {
  const { status, code, course } = detail;
  let body;

  if (status !== 'ready') {
    const message = {
      loading: `Loading catalog details for ${code}…`,
      missing: `${code} isn’t in this catalog dataset. Check the code, or search by title instead.`,
      error: `Couldn’t load ${code}. Check that the API is running, then try again.`,
    }[status];
    body = (
      <div className="course-empty">
        <p className="course-code">{code}</p>
        <h2 id="course-heading">{status === 'loading' ? 'Loading…' : status === 'missing' ? 'Course not found' : 'Details unavailable'}</h2>
        <p role={status === 'loading' ? 'status' : 'alert'}>{message}</p>
        {status === 'error' && <button type="button" className="btn btn-outline" onClick={onRetry}>Try again</button>}
      </div>
    );
  } else {
    body = (
      <>
        <header className="course-head">
          <p className="course-code">{code} · {credits(course.credits)}</p>
          <h2 id="course-heading">{course.title}</h2>
          <button type="button" className="btn btn-ink" disabled={pending} onClick={onBreakdown}>
            {pending ? 'Writing breakdown…' : 'Get course breakdown'}
          </button>
        </header>

        <section className="course-section">
          <h3 className="sr-only">Description</h3>
          <p className="measure">{course.description || 'The catalog lists no description for this course.'}</p>
        </section>

        <dl className="facts">
          <div>
            <dt>Credits</dt>
            <dd>{Number(course.credits)}</dd>
          </div>
          <div>
            <dt>NUpath attributes</dt>
            <dd>{course.attributes?.length ? course.attributes.map((a) => a.replace(/^NUpath /, '')).join(', ') : 'None listed'}</dd>
          </div>
          <div>
            <dt>Corequisites</dt>
            <dd>{course.corequisites?.length ? course.corequisites.join(', ') : 'None listed'}</dd>
          </div>
        </dl>

        <section className="course-section">
          <h3>Prerequisites</h3>
          {hasPrereqs(course.prerequisites)
            ? <PrereqTree node={course.prerequisites} />
            : <p>None listed in the catalog.</p>}
        </section>

        <PlanPlacement entries={course.schedule_context || []} />
      </>
    );
  }

  return (
    <section className="course" aria-labelledby="course-heading">
      {/* eslint-disable-next-line jsx-a11y/no-autofocus -- the result that had focus just disappeared */}
      <button type="button" className="back" onClick={onBack} autoFocus>← Back to results</button>
      {body}
    </section>
  );
}

export default CourseDetail;
