import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { PROVIDERS } from './AISettings';

const CODE = /^([a-zA-Z]{2,4})\s*(\d{4})$/;
const HEADINGS = { h1: 'h4', h2: 'h4', h3: 'h4' }; // keep the page's heading order under each h3

function Breakdown({ item }) {
  const [copied, setCopied] = useState('');
  const copy = () => Promise.resolve()
    .then(() => navigator.clipboard.writeText(item.text))
    .then(() => 'Copied', () => 'Copy failed')
    .then((label) => {
      setCopied(label);
      setTimeout(() => setCopied(''), 2000);
    });

  return (
    <article className="breakdown" aria-labelledby={`breakdown-${item.id}`}>
      <header className="breakdown-head">
        <div>
          <h3 id={`breakdown-${item.id}`}>{item.code}</h3>
          {item.major && <p className="breakdown-major">{`For ${item.major}`}</p>}
          {item.concentrations?.length > 0 && <p className="hint">{item.concentrations.join(', ')}</p>}
        </div>
        {item.status === 'ready' && (
          <button type="button" className="btn btn-quiet btn-sm" onClick={copy} aria-label={`Copy ${item.code} breakdown`}>
            {copied || 'Copy'}
          </button>
        )}
        <span className="sr-only" role="status">{copied}</span>
      </header>
      {item.status === 'loading' ? (
        <p className="pending">Writing a breakdown for {item.code}. This can take up to a minute.</p>
      ) : item.status === 'error' ? (
        <p className="notice-error">{item.text}</p>
      ) : (
        <>
          <div className="prose"><ReactMarkdown components={HEADINGS}>{item.text}</ReactMarkdown></div>
          <p className="attribution">{`via ${PROVIDERS[item.provider].name} · ${item.model}`}</p>
        </>
      )}
    </article>
  );
}

function Breakdowns({ ref, breakdowns, pending, source, onCode, onClear }) {
  const [code, setCode] = useState('');
  const [invalid, setInvalid] = useState(false);
  const latest = breakdowns[0];

  const submit = (e) => {
    e.preventDefault();
    const match = code.trim().match(CODE);
    setInvalid(!match);
    if (!match || pending) return;
    setCode('');
    onCode(match[1], match[2]);
  };

  return (
    <section className="breakdowns" ref={ref} aria-labelledby="breakdowns-heading">
      <div className="breakdowns-head">
        <h2 id="breakdowns-heading">Breakdowns</h2>
        <p className="hint">
          Written by a language model from catalog data, so check with your advisor before registering. <span className="source">{`Using ${source}`}</span>
        </p>
      </div>

      <form className="code-form" onSubmit={submit} noValidate>
        <label htmlFor="code-entry" className="field-label">Breakdown by course code</label>
        <div className="code-row">
          <input
            id="code-entry"
            className="input"
            placeholder="e.g. CS 3000"
            autoComplete="off"
            value={code}
            aria-invalid={invalid}
            aria-describedby={invalid ? 'code-hint' : undefined}
            onChange={(e) => setCode(e.target.value)}
          />
          <button type="submit" className="btn btn-ink" disabled={!code.trim() || pending}>Get breakdown</button>
        </div>
        {invalid && <p id="code-hint" className="hint notice-error">Enter a code like CS 3000: department letters, then the 4-digit number.</p>}
      </form>

      <p className="sr-only" role="status">
        {!latest ? '' : latest.status === 'loading' ? `Writing breakdown for ${latest.code}.`
          : latest.status === 'ready' ? `Breakdown for ${latest.code} is ready.` : `Breakdown for ${latest.code} did not finish.`}
      </p>

      {breakdowns.length ? (
        <>
          <div className="breakdown-list">{breakdowns.map((item) => <Breakdown key={item.id} item={item} />)}</div>
          <button type="button" className="btn btn-outline" onClick={onClear} disabled={pending}>Clear breakdowns</button>
        </>
      ) : (
        <p className="empty">Open a course and choose <strong>Get course breakdown</strong>, or enter a code above.</p>
      )}
    </section>
  );
}

export default Breakdowns;
