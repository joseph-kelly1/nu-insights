import React, { useState } from 'react';
import { credits, catalogLabel } from './SearchPanel';

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

const PREVIEW_ROWS = 5;

// With a major, only that program's rows count; there is never a silent fallback to other majors.
// Filtering happens before dedupe and the five-row preview, so the count and toggle match what can be shown.
function PlanPlacement({ code, entries, dataset, major }) {
  const [expanded, setExpanded] = useState(false);
  const label = catalogLabel(dataset?.catalog_year);
  const emptyDataset = dataset && dataset.plan_count === 0;
  const matching = major ? entries.filter((e) => e.major === major.id) : entries;
  const rows = [...new Set(matching.map((e) => {
    const program = [e.degree, e.campus].filter(Boolean).join(', ');
    const name = e.program_title || `${e.major_name || e.major}${program ? ` (${program})` : ''}`;
    return `${e.year != null ? `Year ${e.year}, ` : ''}${e.term} · ${[name, e.plan_name].filter(Boolean).join(', ')}`;
  }))];
  const shown = expanded ? rows : rows.slice(0, PREVIEW_ROWS);
  const noPlan = major?.status && major.status !== 'available';
  const inLabel = label ? ` ${label}` : '';

  return (
    <section className="course-section">
      <h3>{label ? `${label} sample plan placement` : 'Sample plan placement'}</h3>
      {!emptyDataset && (
        <p className="hint">{dataset?.historical
          ? 'Historical sample plans. Requirements and course codes may have changed. These do not confirm current course offerings or your eligibility.'
          : 'From published sample plans of study. These do not confirm live sections or your eligibility.'}</p>
      )}
      {major && !emptyDataset && <p className="hint">{`Showing ${major.label} only.`}</p>}
      {rows.length ? (
        <>
          <ul className="plan-list" id="plan-rows">{shown.map((r) => <li key={r}>{r}</li>)}</ul>
          {rows.length > PREVIEW_ROWS && (
            <button
              type="button"
              className="btn btn-quiet btn-sm disclosure"
              aria-expanded={expanded}
              aria-controls="plan-rows"
              aria-label={expanded ? `Show less: first ${PREVIEW_ROWS} placements` : `Show all (${rows.length}) placements`}
              onClick={() => setExpanded((open) => !open)}
            >
              <span className="chevron" aria-hidden="true" />
              {expanded ? 'Show less' : `Show all (${rows.length})`}
            </button>
          )}
        </>
      ) : (
        <p>{emptyDataset
          ? `No published sample plans are available in the ${label ? `${label} ` : ''}dataset.`
          : noPlan ? `${major.label} has no published sample plan in the collected${inLabel} plans, so no placement can be shown for it.`
          : major ? `${code} doesn’t appear in the collected${inLabel} sample plans for ${major.label}. Other majors’ placements are hidden while a major is selected.`
          : `No sample-plan placement is available for this course in the collected${inLabel} plans.`}</p>
      )}
    </section>
  );
}

function CourseDetail({ detail, pending, major, concentrations = [], onBack, onRetry, onBreakdown }) {
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

        {concentrations.length > 0 && <section className="course-section">
          <h3>Your concentration choices</h3>
          <p className="hint">Concentration requirements do not determine semester placement or confirm eligibility.</p>
          <ul className="plan-list">{concentrations.map((option) => <li key={option.id}>
            <strong>{option.name}</strong>{` (${catalogLabel(option.catalog_year)})`}
            <p>{option.courses.includes(code)
              ? 'Listed in an explicit course row. It may be required, an alternative, or an elective option; read the full requirements above.'
              : 'No explicit course row lists this course. Elective ranges or approved substitutions may still apply.'}</p>
            <a href={option.source_url} target="_blank" rel="noreferrer">Open catalog requirements</a>
          </li>)}</ul>
        </section>}

        {/* the key resets the expanded state for each course and major */}
        <PlanPlacement
          key={`${code}|${major?.id || ''}`}
          code={code}
          entries={course.schedule_context || []}
          dataset={course.plan_dataset}
          major={major}
        />
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
