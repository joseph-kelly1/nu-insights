import React from 'react';
import { catalogLabel } from './SearchPanel';

export function RequirementSections({ sections }) {
  return sections.map((section, index) => (
    <div className="requirement-section" key={index}>
      <h3>{section.title}</h3>
      {section.entries.map((entry, i) => entry.kind === 'course_table' ? (
        <ul className="requirement-rows" key={i}>
          {entry.rows.map((row, j) => (
            <li key={j} className={`requirement-${row.kind}`}
              style={row.indent ? { paddingInlineStart: `${Math.min(row.indent, 120)}px` } : undefined}>
              {row.kind === 'header' ? <strong>{row.text}</strong> : row.text}
              {row.credits_text && <span className="hint">{` (${row.credits_text} credits)`}</span>}
            </li>
          ))}
        </ul>
      ) : <p key={i}>{entry.text}</p>)}
    </div>
  ));
}

function ConcentrationPicker({ catalog, selected, onChange, onRetry }) {
  const { status, data } = catalog;
  if (status !== 'ready') {
    return (
      <div className="concentration-picker">
        <p className="hint" role="status">{status === 'error'
          ? 'Concentrations couldn’t load. Course browsing still works.' : 'Loading concentration choices…'}</p>
        {status === 'error' && <button className="link-button" type="button" onClick={onRetry}>Retry concentrations</button>}
      </div>
    );
  }
  if (!data.groups.length) return (
    <div className="concentration-picker"><p className="hint">{data.available
      ? `No concentration choices were found in this major’s ${catalogLabel(data.catalog_year)} catalog requirements.`
      : 'Concentration data is not loaded for this major yet.'}</p></div>
  );

  return (
    <div className="concentration-picker">
      <p className="hint">{`Concentration requirements: ${catalogLabel(data.catalog_year)} catalog.`}</p>
      {data.groups.map((group) => {
        const chosen = selected.filter((option) => group.options.some((o) => o.id === option.id));
        const primary = chosen[0];
        const ids = chosen.map((o) => o.id);
        const slots = group.fixed ? [] : [...ids, ...(ids.length < (group.policy.max_selections || group.options.length)
          && !chosen.some((o) => o.kind === 'alternative') ? [''] : [])];
        const setSlot = (index, value) => {
          const next = [...ids];
          next[index] = value;
          const option = group.options.find((o) => o.id === value);
          onChange(group.id, option?.kind === 'alternative' ? [value] : next.filter((id) => id &&
            (index !== 0 || value || !group.options.find((o) => o.id === id)?.secondary_only)));
        };
        return (
          <fieldset className="concentration-group" key={group.id}>
            <legend className="field-label">{group.title}</legend>
            {group.policy.text && <p className="hint concentration-policy">{group.policy.text}</p>}
            {group.fixed ? <p>{primary?.name}</p> : slots.map((value, index) => (
              <div className="concentration-slot" key={index}>
                <label className="field-label" htmlFor={`concentration-${group.id}-${index}`}>
                  {index === 0 ? 'Concentration' : `Additional concentration ${index}`}
                </label>
                <select id={`concentration-${group.id}-${index}`} className="input" value={value}
                  onChange={(event) => setSlot(index, event.target.value)}>
                  <option value="">{index === 0 ? 'Choose a concentration or leave undecided' : 'None'}</option>
                  {group.options.filter((o) => o.id === value || (!ids.includes(o.id) && (index > 0 || !o.secondary_only)
                    && (index === 0 || o.kind !== 'alternative'))).map((o) => (
                    <option key={o.id} value={o.id}>{o.name}{o.secondary_only ? ' (second concentration only)' : ''}</option>
                  ))}
                </select>
              </div>
            ))}
            {chosen.map((option) => (
              <details className="concentration-requirements" key={option.id}>
                <summary>{`View ${option.name} requirements`}</summary>
                {option.notes.filter((note) => note !== option.name).map((note, index) => <p className="hint" key={index}>{note}</p>)}
                <p className="hint">Course rows can be choices or electives. Read the instructions for each group.</p>
                <RequirementSections sections={option.sections} />
                <a href={option.source_url} target="_blank" rel="noreferrer">Open catalog requirements</a>
              </details>
            ))}
          </fieldset>
        );
      })}
    </div>
  );
}

export default ConcentrationPicker;
