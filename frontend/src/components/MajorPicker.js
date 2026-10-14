import React, { useState, useEffect } from 'react';

// A native datalist does the type-to-filter; only an exact label match selects, so the
// stored value is always a canonical program id. Labels are unique (see db_loader.program_labels).
function MajorPicker({ programs, major, onChange, onRetry }) {
  const [draft, setDraft] = useState(major?.label || '');
  useEffect(() => setDraft(major?.label || ''), [major]);
  const { status, list } = programs;

  const pick = (value) => {
    setDraft(value);
    const match = list.find((p) => p.label === value);
    if (match && match.id !== major?.id) onChange(match);
  };

  const hint = status === 'idle' || status === 'loading' ? 'Loading majors…'
    : status === 'error' ? 'Majors couldn’t load. Browsing and breakdowns still work without one.'
    : !list.length ? 'Major data isn’t available in this dataset, so browsing covers all courses.'
    : major ? 'Using this major for browsing and planning.'
    : 'Optional. Type to find yours, including combined majors and campus.';

  return (
    <div className="major-picker">
      <label htmlFor="major-input" className="field-label">Your major</label>
      <div className="major-row">
        <input
          id="major-input"
          className="input"
          list="major-options"
          autoComplete="off"
          placeholder="e.g. Computer Science, BSCS (Boston)"
          aria-describedby="major-hint"
          value={draft}
          onChange={(e) => pick(e.target.value)}
          onBlur={() => setDraft(major?.label || '')} // an unfinished search never changes the selection
        />
        {major && (
          <button type="button" className="btn btn-quiet btn-sm" onClick={() => onChange(null)} aria-label={`Clear major ${major.label}`}>
            Clear
          </button>
        )}
      </div>
      <datalist id="major-options">
        {list.map((p) => <option key={p.id} value={p.label} />)}
      </datalist>
      <p id="major-hint" className="hint">
        {hint}
        {status === 'error' && <>{' '}<button type="button" className="link-button" onClick={onRetry}>Try again</button></>}
      </p>
    </div>
  );
}

export default MajorPicker;
