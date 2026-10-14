import React from 'react';
import { catalogLabel } from './SearchPanel';

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
      {data.groups.map((group) => {
        const compact = group.title === 'Computer Science Concentrations';
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
            <legend className={`field-label${compact ? ' sr-only' : ''}`}>{group.title}</legend>
            {!compact && group.policy.text && <p className="hint concentration-policy">{group.policy.text}</p>}
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
          </fieldset>
        );
      })}
    </div>
  );
}

export default ConcentrationPicker;
