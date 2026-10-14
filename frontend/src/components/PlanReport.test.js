import React from 'react';
import { render, screen, within, fireEvent } from '@testing-library/react';
import PlanReport from './PlanReport';

const plan = { terms: [{ id: 'spring', session: 'spring', year: 2027 }, { id: 'summer', session: 'summer1', year: 2027 }] };
const base = { requirements: [], errors: [], warnings: [], issues: [], assumptions: [], sources: [], coverage: 'incomplete' };
const course = (code, title, credits = 4) => ({ code, title, credits, available: true });
const rule = (extra) => ({ id: 'choice', title: 'Systems electives', section: 'Systems concentration', review: 'reviewed',
  status: 'unsatisfied', kind: 'choose', need: 2, options: ['CS 3520', 'CS 4300', 'CS 4360'], courses: [], ...extra });

test('shows only remaining alternatives, with titles and credit amounts, and keeps completed detail folded', () => {
  const report = { ...base, requirements: [rule({ remaining: { need: 1,
    options: [[[course('CS 4300', 'Computer Graphics')]], [[course('CS 4360', 'Nontraditional Programming')]]] } }),
  rule({ id: 'done', title: 'Completed writing', status: 'satisfied', progress: '1 of 1', options: ['ENGW 1111'],
    courses: [{ code: 'ENGW 1111', label: 'ENGW 1111', attempt_id: 'done' }] })] };
  render(<PlanReport report={report} plan={plan} attempts={[]} onOpenCourse={jest.fn()} onEditTerm={jest.fn()} />);
  const choices = screen.getByRole('region', { name: 'Still to choose' });
  expect(within(choices).getByText(/Choose 1 more course option/)).toBeVisible();
  expect(within(choices).getByText('Computer Graphics')).toBeVisible();
  expect(within(choices).getAllByText('4 credits')).toHaveLength(2);
  expect(within(choices).queryByRole('button', { name: 'CS 3520' })).not.toBeInTheDocument();
  expect(screen.getByText('Completed requirements (1)').closest('details')).not.toHaveAttribute('open');
  expect(screen.getByRole('button', { name: 'ENGW 1111' })).not.toBeVisible();
});

test('deduplicates scheduled courses, shows terms, separates placeholders and opens the right editor', () => {
  const attempts = [
    { id: 'graphics', code: 'CS 4300', title: 'Computer Graphics', credits: 4, term_id: 'spring', status: 'planned' },
    { id: 'elective', title: 'General elective', credits: 4, term_id: 'summer', status: 'planned', placeholder: { rule: 'general' } },
    { id: 'done', code: 'CS 3520', credits: 4, term_id: 'spring', status: 'passed' },
  ];
  const report = { ...base, coverage: 'all_modeled_covered', requirements: [rule({ status: 'planned',
    courses: [{ code: 'CS 4300', title: 'Computer Graphics', label: 'CS 4300', attempt_id: 'graphics' }] }),
  rule({ id: 'nupath', title: 'NUpath writing', status: 'planned', kind: 'nupath', courses: [{ code: 'CS 4300', attempt_id: 'graphics' }] })] };
  const edit = jest.fn();
  render(<PlanReport report={report} plan={plan} attempts={attempts} onOpenCourse={jest.fn()} onEditTerm={edit} />);
  expect(screen.getByText('1 elective slot still needs a course choice')).toBeVisible();
  const scheduled = screen.getByRole('region', { name: 'Already on your timeline' });
  expect(within(scheduled).getAllByRole('button', { name: 'CS 4300' })).toHaveLength(1);
  expect(within(scheduled).getByText('Spring 2027 · 4 credits · Planned')).toBeVisible();
  expect(within(scheduled).queryByRole('button', { name: 'CS 3520' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Choose a course in this term' }));
  expect(edit).toHaveBeenCalledWith('summer');
});

test('renders OR alternatives and AND lab bundles without merging choices', () => {
  const report = { ...base, requirements: [rule({ remaining: { need: 1,
    options: [[[course('EECE 2310', 'Digital Design'), course('EECE 2311', 'Lab for Digital Design', 1)],
      [course('CS 3650', 'Computer Systems')]]] } })] };
  render(<PlanReport report={report} plan={plan} attempts={[]} onOpenCourse={jest.fn()} onEditTerm={jest.fn()} />);
  expect(screen.getByText('and')).toBeVisible();
  expect(screen.getByText('or')).toBeVisible();
  expect(screen.getByText('Lab for Digital Design')).toBeVisible();
  expect(screen.getByText('1 credit')).toBeVisible();
});

test('credit shortfalls and errors stay visible while warnings and catalog rules are folded', () => {
  const report = { ...base, errors: [{ message: 'Spring 2027 exceeds your credit limit.' }],
    warnings: [{ message: 'Historical prerequisite needs review.' }], issues: [{ id: 'gpa', text: 'Confirm GPA.' }],
    requirements: [rule({ kind: 'credits', title: 'General electives', remaining: { credits: 6, count: 2 } })] };
  render(<PlanReport report={report} plan={plan} attempts={[]} onOpenCourse={jest.fn()} onEditTerm={jest.fn()} />);
  expect(screen.getByText('Add 6 credits across at least 2 more courses.')).toBeVisible();
  expect(screen.getByText('Spring 2027 exceeds your credit limit.')).toBeVisible();
  expect(screen.getByText('Warnings (1)').closest('details')).not.toHaveAttribute('open');
  expect(screen.getByText('Catalog rules to confirm (1)').closest('details')).not.toHaveAttribute('open');
});
