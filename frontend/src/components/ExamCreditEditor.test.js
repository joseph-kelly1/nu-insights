import React, { useState } from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import ExamCreditEditor from './ExamCreditEditor';

const POLICY = { policy_year: '2026-2027', version: '1234567890abcdef', exams: [
  { id: 'ap:calculus-bc', kind: 'ap', name: 'Calculus BC' },
  { id: 'ib:biology', kind: 'ib', name: 'Biology' },
] };
const COURSES = [
  { code: 'MATH 1341', title: 'Calculus 1', credits: 4, nupath: ['FQ'] },
  { code: 'MATH 1342', title: 'Calculus 2', credits: 4, nupath: ['FQ'] },
];
const response = (body, ok = true) => Promise.resolve({ ok, json: async () => body });
let posted;
beforeEach(() => {
  posted = [];
  global.fetch = jest.fn((url, options) => {
    if (url.startsWith('/api/exams/catalog')) return response({ policies: [POLICY] });
    const { exams } = JSON.parse(options.body);
    posted.push(exams);
    const resolved = exams.map((e) => {
      const subject = POLICY.exams.find((s) => s.id === e.exam_id);
      const qualifies = e.score >= (subject.kind === 'ap' ? 4 : 5) && (subject.kind === 'ap' || e.level === 'HL');
      return { ...e, name: subject.name, kind: subject.kind, equivalents: qualifies ? COURSES : [],
        source_url: 'https://admissions.northeastern.edu/exam-policy.pdf',
        message: qualifies ? '' : 'No credit under this policy for this score and level.' };
    });
    return response({ exams: resolved, awards: [], notes: [],
      awarded_credits: resolved.some((e) => e.state === 'awarded') ? 8 : 0, test_credit_cap: 32 });
  });
});

function Harness({ year = 2026, initial = [] }) {
  const [exams, setExams] = useState(initial);
  return <><ExamCreditEditor plan={{ start: { year, session: 'fall' }, exams }} dispatch={(action) => setExams(action.exams)} />
    <output data-testid="saved-exams">{JSON.stringify(exams)}</output></>;
}

async function chooseExam() {
  await screen.findByRole('option', { name: 'Calculus BC' });
  fireEvent.change(screen.getByLabelText('Exam subject'), { target: { value: 'ap:calculus-bc' } });
  fireEvent.change(screen.getByLabelText('Exam score'), { target: { value: '5' } });
  fireEvent.click(screen.getByRole('button', { name: 'Preview exam credit' }));
  return screen.findByRole('region', { name: 'Exam credit preview' });
}

test('preview leaves plan unchanged; estimate saves exam input and can become awarded', async () => {
  render(<Harness />);
  const preview = await chooseExam();
  expect(within(preview).getByText('MATH 1341')).toBeInTheDocument();
  expect(within(preview).getByText('MATH 1342')).toBeInTheDocument();
  expect(screen.getByTestId('saved-exams')).toHaveTextContent('[]');
  fireEvent.click(within(preview).getByRole('button', { name: 'Save estimate' }));
  await screen.findByText(/Estimated, not counted/);
  expect(screen.getByTestId('saved-exams')).toHaveTextContent('"state":"estimated"');
  expect(screen.getByText('0 of 32 exam credits counted')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Mark credit awarded' }));
  await screen.findByText('8 of 32 exam credits counted');
  expect(screen.getByTestId('saved-exams')).toHaveTextContent('"state":"awarded"');
  expect(posted.at(-1)[0]).toMatchObject({ score: 5, version: POLICY.version, state: 'awarded' });
  expect(posted.at(-1)[0]).not.toHaveProperty('equivalents');
});

test('IB level and low scores produce explicit no-credit preview without award action', async () => {
  render(<Harness />);
  await screen.findByRole('option', { name: 'Calculus BC' });
  fireEvent.change(screen.getByLabelText('Exam type'), { target: { value: 'ib' } });
  fireEvent.change(screen.getByLabelText('Exam subject'), { target: { value: 'ib:biology' } });
  fireEvent.change(screen.getByLabelText('Exam score'), { target: { value: '7' } });
  fireEvent.change(screen.getByLabelText('IB level'), { target: { value: 'SL' } });
  fireEvent.click(screen.getByRole('button', { name: 'Preview exam credit' }));
  const preview = await screen.findByRole('region', { name: 'Exam credit preview' });
  expect(within(preview).getByText(/No credit under this policy/)).toBeInTheDocument();
  expect(within(preview).queryByRole('button', { name: 'Record awarded credit' })).not.toBeInTheDocument();
  expect(posted[0][0]).toMatchObject({ level: 'SL', score: 7 });
});

test('unsupported admission year requires explicit choice; failed catalog load can retry', async () => {
  const real = global.fetch;
  global.fetch = jest.fn().mockImplementationOnce(() => response({ error: 'Policies unavailable' }, false)).mockImplementation(real);
  render(<Harness year={2025} />);
  expect(await screen.findByText('Policies unavailable')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Retry AP/IB policies' }));
  await screen.findByRole('option', { name: '2026-2027' });
  expect(screen.getByLabelText('Admission policy year')).toHaveValue('');
  expect(screen.getByRole('button', { name: 'Preview exam credit' })).toBeDisabled();
});

test('edit, re-preview, and remove use authoritative resolver and preserve pinned policy', async () => {
  const initial = [{ id: 'saved', exam_id: 'ap:calculus-bc', kind: 'ap', name: 'Calculus BC', score: 5,
    policy_year: POLICY.policy_year, version: POLICY.version, state: 'awarded', level: null }];
  render(<Harness initial={initial} />);
  expect(await screen.findByLabelText('Admission policy year')).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Edit Calculus BC' }));
  fireEvent.change(screen.getByLabelText('Exam score'), { target: { value: '3' } });
  fireEvent.click(screen.getByRole('button', { name: 'Preview exam credit' }));
  const preview = await screen.findByRole('region', { name: 'Exam credit preview' });
  fireEvent.click(within(preview).getByRole('button', { name: 'Save estimate' }));
  await waitFor(() => expect(screen.getByTestId('saved-exams')).toHaveTextContent('"score":3'));
  fireEvent.click(screen.getByRole('button', { name: 'Remove Calculus BC' }));
  await waitFor(() => expect(screen.getByTestId('saved-exams')).toHaveTextContent('[]'));
});
