import React from 'react';
import { courseCode, credits } from './courseDisplay';

export function CourseRow({ course, selectedCode, onSelect }) {
  const code = courseCode(course);
  return <button type="button" className="result"
    aria-current={code === selectedCode ? 'true' : undefined} onClick={() => onSelect(course)}>
    <span className="result-code">{code}</span>
    <span className="result-title">{course.title}</span>
    <span className="result-credits">{credits(course.credits)}</span>
  </button>;
}

function RequirementNode({ node, selectedCode, onSelect }) {
  if (node.kind === 'course') return node.course
    ? <CourseRow course={node.course} selectedCode={selectedCode} onSelect={onSelect} />
    : <p className="requirement-missing">{node.code} <span className="hint">Description unavailable in loaded catalog.</span></p>;
  if (node.children) {
    const choice = node.kind === 'any_of';
    const connector = choice ? 'or' : node.kind === 'all_of' ? 'and' : null;
    return <div className={connector ? `requirement-group ${choice ? 'requirement-choice' : 'requirement-bundle'}` : 'requirement-expression'}
      role="group" aria-label={choice ? 'Choose one alternative' : node.kind === 'all_of' ? 'Complete all courses in this option' : 'Catalog course expression'}>
      {node.kind === 'unparsed' && <p className="hint requirement-instruction">{node.text}</p>}
      {node.children.map((child, index) => <React.Fragment key={index}>
        {index > 0 && connector && <div className="requirement-connector"><span>{connector}</span></div>}
        <RequirementNode node={child} selectedCode={selectedCode} onSelect={onSelect} />
      </React.Fragment>)}
    </div>;
  }
  if (node.kind === 'header') return <h3 className="requirement-subheading">{node.text}</h3>;
  return <p className="hint requirement-instruction">{node.text}</p>;
}

export default function RequirementCourseList({ sections, selectedCode, onSelect }) {
  return sections.map((section, index) => <section className="course-requirement-section" key={index}
    aria-labelledby={`requirement-heading-${index}`}>
    {section.owner && section.owner !== section.title && <p className="requirement-owner">{section.owner}</p>}
    <h2 id={`requirement-heading-${index}`}>{section.title}</h2>
    {section.entries.map((node, i) => <RequirementNode key={i} node={node} selectedCode={selectedCode} onSelect={onSelect} />)}
  </section>);
}
