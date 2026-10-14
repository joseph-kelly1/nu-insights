import React from 'react';
import { termLabel } from '../coursePlan';

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
const joined = (codes) => codes.join(' + ');
const Source = ({ url }) => <>{' '}<a href={url} target="_blank" rel="noreferrer">Source</a></>;

function ReplacementNote({ rule }) {
  const used = [...new Map(rule.courses.filter((c) => c.replacement).map((c) => [c.replacement.id, c.replacement])).values()];
  if (used.length) return used.map((m) => <p key={m.id} className="hint">
    {`${joined(m.replacement)} ${m.replacement.length > 1 ? 'fulfill' : 'fulfills'} the ${joined(m.original)} requirement.`}
    <Source url={m.source_url} /></p>);
  if (rule.status !== 'unsatisfied' || !rule.retired?.length) return null;
  const verified = rule.replacements?.find((m) => m.review === 'verified');
  const candidate = rule.replacements?.find((m) => m.review === 'candidate');
  const retired = `${rule.retired.join(', ')} ${rule.retired.length > 1 ? 'are' : 'is'} no longer in the current catalog.`;
  return <p className="hint">{verified
    ? `${retired} Plan ${joined(verified.replacement)}, which fulfills this requirement.`
    : candidate ? `${retired} Khoury lists ${joined(candidate.replacement)} as replacing ${joined(candidate.original)}, but hasn’t `
      + 'published that it counts for your catalog year. If your advisor approves, add it and use “Counts as another '
      + 'course?” with the approval details.'
      : `${retired} Ask your advisor which current course counts instead, then record it with “Counts as another `
        + 'course?” and the approval details.'}
    {(verified || candidate) && <Source url={(verified || candidate).source_url} />}</p>;
}

function CourseName({ course, onOpenCourse }) {
  return <><button type="button" className="link-button" onClick={() => onOpenCourse(course.code)}>{course.code}</button>
    {course.title && course.title !== course.code && <span className="course-choice-title">{course.title}</span>}</>;
}

function Choices({ rule, onOpenCourse }) {
  const options = rule.remaining?.options;
  if (!options) return <p className="hint">{`${rule.options.length > rule.need ? `Choose ${rule.need}` : 'Take'}: ${rule.options.join(', ')}`}</p>;
  const renderOption = (option, i) => <li key={i} className="course-choice">
    {option.map((bundle, j) => <React.Fragment key={j}>
      {j > 0 && <span className="choice-connector">or</span>}
      <div className="course-bundle">{bundle.length ? bundle.map((course, k) => <React.Fragment key={course.code}>
        {k > 0 && <span className="choice-connector">and</span>}
        <span><CourseName course={course} onOpenCourse={onOpenCourse} />
          {course.credits != null && <span className="hint block">{plural(course.credits, 'credit')}
            {course.available === false && ' · Ask your advisor for a current replacement'}</span>}</span>
      </React.Fragment>) : <span className="hint">Already recorded; check allocation in requirement details.</span>}</div>
    </React.Fragment>)}
  </li>;
  return <><ul className="course-choices">{options.slice(0, 5).map(renderOption)}</ul>
    {options.length > 5 && <details className="report-disclosure"><summary>{`Show all ${options.length} course choices`}</summary>
      <ul className="course-choices">{options.slice(5).map(renderOption)}</ul></details>}</>;
}

function MissingRequirement({ rule, onOpenCourse }) {
  const remaining = rule.remaining;
  const fixed = remaining?.options?.length === 1 && remaining.options[0].length === 1;
  const instruction = rule.kind === 'choose' ? fixed ? 'Take the remaining courses below.'
    : `Choose ${plural(remaining?.need ?? rule.need, 'more course option')}. Take every course in a bundle.`
    : ['credits', 'total_credits', 'residency'].includes(rule.kind) && remaining
      ? `${remaining.credits > 0 ? `Add ${plural(remaining.credits, 'credit')}` : 'Add qualifying courses'}${rule.kind === 'residency' ? ' taken at Northeastern' : ''}${remaining.count ? ` across at least ${plural(remaining.count, 'more course')}` : ''}.`
      : rule.kind === 'nupath' ? `Choose ${plural(remaining?.need ?? rule.need, 'more course')} carrying this NUpath designation.`
        : 'Confirm a qualifying experience with your advisor.';
  return <li className="remaining-requirement">
    <div className="remaining-heading"><strong>{rule.title}</strong><span className="req-state">Not yet met</span></div>
    <p className="hint">{rule.section}</p>
    <p>{instruction}</p>
    {rule.kind === 'choose' && <Choices rule={rule} onOpenCourse={onOpenCourse} />}
    {rule.kind === 'credits' && rule.remaining?.options?.length > 0 && <>
      <p className="hint">Choose courses not already used by another major or concentration requirement.
        Check prerequisites and required labs before adding a course.</p>
      {rule.remaining.filters?.length > 0 && <p className="hint">{rule.remaining.filters.map((f) =>
        `${f.subject} ${f.minimum_number || 'any level'}${f.maximum_number ? ` through ${f.maximum_number}` : f.minimum_number ? ' or higher' : ''}${f.excluded_courses?.length ? ` (except ${f.excluded_courses.join(', ')})` : ''}`
      ).join('; ')}</p>}
      <details className="report-disclosure"><summary>Browse eligible elective courses</summary>
        <Choices rule={rule} onOpenCourse={onOpenCourse} /></details>
    </>}
    {rule.courses.length > 0 && <p className="hint">{`Already counting here: ${rule.courses.map((c) => c.code || c.label).join(', ')}.`}</p>}
    <ReplacementNote rule={rule} />
    {rule.source_url && <p className="hint"><Source url={rule.source_url} /></p>}
  </li>;
}

function RequirementDetails({ rules, onOpenCourse }) {
  const groups = {};
  for (const rule of rules) (groups[rule.section || 'Requirements'] ||= []).push(rule);
  return Object.entries(groups).map(([section, group]) => <div key={section} className="report-group">
    <h3>{section}</h3><ul className="report-list requirement-details">
      {group.map((rule) => <li key={rule.id}><strong>{rule.title}</strong><p className="hint">{rule.progress}</p>
        {rule.kind === 'choose' && <p className="hint">{`${rule.options.length > rule.need ? `Choose ${rule.need}` : 'Take'}: ${rule.options.join(', ')}`}</p>}
        {rule.courses.map((c, i) => <React.Fragment key={c.attempt_id || i}>
          {i > 0 && ', '}{c.code ? <button type="button" className="link-button" onClick={() => onOpenCourse(c.code)}>{c.code}</button> : c.label}
        </React.Fragment>)}<ReplacementNote rule={rule} />
      </li>)}
    </ul></div>);
}

export default function PlanReport({ report, stale, plan, attempts, onOpenCourse, onEditTerm }) {
  if (!report) return null;
  const rules = report.requirements || [];
  const missing = rules.filter((r) => r.status === 'unsatisfied');
  const completed = rules.filter((r) => r.status === 'satisfied');
  const planned = rules.filter((r) => r.status === 'planned');
  const review = rules.filter((r) => r.status === 'review');
  const remaining = attempts.filter((a) => ['planned', 'in_progress'].includes(a.status));
  const placeholders = remaining.filter((a) => a.placeholder);
  const courses = remaining.filter((a) => !a.placeholder);
  const terms = new Map(plan.terms.map((t) => [t.id, t]));
  courses.sort((a, b) => plan.terms.findIndex((t) => t.id === a.term_id) - plan.terms.findIndex((t) => t.id === b.term_id));
  const courseDetails = new Map(rules.flatMap((r) => r.courses).map((c) => [c.attempt_id, c]));
  const headline = report.coverage === 'unavailable' ? 'Degree requirements could not be checked'
    : missing.length ? `${plural(missing.length, 'requirement')} still ${missing.length === 1 ? 'needs' : 'need'} courses`
      : review.length ? 'Some requirements need advisor confirmation'
      : placeholders.length ? `${plural(placeholders.length, 'elective slot')} still ${placeholders.length === 1 ? 'needs' : 'need'} a course choice`
        : report.errors.length ? 'Fix schedule problems below'
          : courses.length ? 'Remaining requirements are on your timeline' : 'All checked requirements are complete';
  const schedule = (a) => terms.has(a.term_id) ? termLabel(terms.get(a.term_id)) : 'Credit before enrollment';
  return <section className="plan-report" aria-labelledby="report-heading">
    <h2 id="report-heading">What you have left</h2>
    {stale && <p className="notice" role="alert">Your plan changed after this check. Check it again for current results.</p>}
    <p className="report-headline">{headline}</p>
    {report.message && <p>{report.message}</p>}
    {report.coverage !== 'unavailable' && <>
      <section aria-labelledby="choices-heading"><h3 id="choices-heading">Still to choose</h3>
        {missing.length > 0 && placeholders.length > 0 && <p className="hint">A qualifying course in an empty elective slot can also meet a requirement below.</p>}
        {!missing.length && !placeholders.length && <p className="hint">No course choices are missing from the checked requirements.</p>}
        <ul className="remaining-list">{missing.map((r) => <MissingRequirement key={r.id} rule={r} onOpenCourse={onOpenCourse} />)}
          {placeholders.map((a) => <li key={a.id} className="remaining-requirement">
            <strong>{a.title || 'Elective course'}</strong><p>Choose a specific course for this slot.</p>
            <p className="hint">{`${schedule(a)} · ${plural(a.credits, 'credit')}`}</p>
            <button type="button" className="link-button" onClick={() => onEditTerm(a.term_id || 'pre')}>Choose a course in this term</button>
          </li>)}
        </ul>
      </section>
    </>}
    <section aria-labelledby="scheduled-heading"><h3 id="scheduled-heading">Already on your timeline</h3>
      <p className="hint">{courses.length ? `${plural(courses.length, 'course')} left to pass. Planned courses count only if you complete them.`
        : 'No specific courses are planned or in progress.'}</p>
      <ul className="remaining-list scheduled-courses">{courses.map((a) => {
        const title = courseDetails.get(a.id)?.title || a.title;
        const countsFor = [...new Set(rules.filter((r) => r.courses.some((c) => c.attempt_id === a.id))
          .filter((r) => !['total_credits', 'residency'].includes(r.kind)).map((r) => r.title))];
        return <li key={a.id}><CourseName course={{ code: a.code, title }} onOpenCourse={onOpenCourse} />
          <p className="scheduled-term">{`${schedule(a)} · ${plural(a.credits, 'credit')} · ${a.status === 'in_progress' ? 'In progress' : 'Planned'}`}</p>
          {countsFor.length > 0 && <p className="hint">{`Counts toward: ${countsFor.join('; ')}`}</p>}
          <button type="button" className="link-button" onClick={() => onEditTerm(a.term_id || 'pre')}>Edit term</button>
        </li>;
      })}</ul>
    </section>
    {report.errors.length > 0 && <section><h3>Schedule problems to fix</h3><ul className="report-list problems">
      {report.errors.map((e, i) => <li key={i}>{e.message}</li>)}</ul></section>}
    {review.length > 0 && <section><h3>Confirm with your advisor</h3><RequirementDetails rules={review} onOpenCourse={onOpenCourse} /></section>}
    {completed.length > 0 && <details className="report-disclosure"><summary>{`Completed requirements (${completed.length})`}</summary>
      <RequirementDetails rules={completed} onOpenCourse={onOpenCourse} /></details>}
    {planned.length > 0 && <details className="report-disclosure"><summary>How planned courses meet requirements</summary>
      <RequirementDetails rules={planned} onOpenCourse={onOpenCourse} /></details>}
    {report.warnings.length > 0 && <details className="report-disclosure"><summary>{`Warnings (${report.warnings.length})`}</summary>
      <ul className="report-list">{report.warnings.map((e, i) => <li key={i}>{e.message}</li>)}</ul></details>}
    {report.issues.length > 0 && <details className="report-disclosure"><summary>{`Catalog rules to confirm (${report.issues.length})`}</summary>
      <p className="hint">These rules aren’t checked automatically. Review them with your advisor.</p>
      <ul className="report-list">{report.issues.map((i) => <li key={i.id}>{i.text}{i.source_url && <Source url={i.source_url} />}</li>)}</ul></details>}
    {report.assumptions.length > 0 && <details className="report-disclosure"><summary>Assumptions behind this check</summary>
      <ul className="report-list">{report.assumptions.map((a) => <li key={a}>{a}</li>)}</ul></details>}
    <p className="hint">This is a planning aid, not an official degree audit. Northeastern advising confirms graduation.</p>
    <p className="hint">{report.offerings}</p>
    {report.sources?.length > 0 && <details className="report-disclosure"><summary>Catalog sources</summary><ul className="report-list">
      {report.sources.map((s) => <li key={s.key}><a href={s.source_url} target="_blank" rel="noreferrer">{s.title}</a>
        {` · ${s.review === 'reviewed' ? 'Reviewed' : 'Not yet reviewed'}`}</li>)}</ul></details>}
  </section>;
}
