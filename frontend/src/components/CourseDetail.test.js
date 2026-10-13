import React from 'react';
import { render, screen, fireEvent, within } from '@testing-library/react';
import CourseDetail from './CourseDetail';

const historical = { catalog_year: '2025-2026', current_catalog_year: '2026-2027', historical: true, plan_count: 622 };
const entry = { major_name: 'Computer Science', plan_name: 'Four Years, Two Co-ops', year: 2, term: 'Fall' };

const detail = (entries, dataset, code = 'CS 3000') => ({ status: 'ready', code, course: {
  title: 'Algorithms and Data', description: 'Algorithms course.', credits: 4,
  prerequisites: [], corequisites: [], attributes: [], schedule_context: entries,
  plan_dataset: dataset,
} });

function show({ entries = [], dataset, major } = {}) {
  return render(<CourseDetail detail={detail(entries, dataset)} major={major} onBack={() => {}} onBreakdown={() => {}} />);
}

const CS = { id: 'cs-bscs', label: 'Computer Science, BSCS (Boston)', status: 'available' };
const DS = { id: 'ds-bs', label: 'Data Science, BS (Boston)', status: 'available' };
const placement = (major, n) => ({ ...entry, major: major.id, program_title: major.label, plan_name: `Plan ${n}` });
const rows = () => within(document.getElementById('plan-rows')).getAllByRole('listitem').map((li) => li.textContent);
const toggle = () => screen.queryByRole('button', { name: /^Show (all|less)/ });

test('historical placements show their edition and distinguish current requirements', () => {
  show({ entries: [entry], dataset: historical });
  expect(screen.getByRole('heading', { name: '2025–2026 sample plan placement' })).toBeInTheDocument();
  expect(screen.getByText(/Historical sample plans\. Requirements and course codes may have changed/)).toBeInTheDocument();
  expect(screen.getByText(/Year 2, Fall · Computer Science/)).toBeInTheDocument();
  expect(screen.queryByText(/No sample-plan placement/)).not.toBeInTheDocument();
});

test('a missing course placement differs from a dataset with no plans', () => {
  show({ dataset: historical });
  expect(screen.getByText('No sample-plan placement is available for this course in the collected 2025–2026 plans.')).toBeInTheDocument();
  expect(screen.queryByText(/No published sample plans are available/)).not.toBeInTheDocument();
});

test('an empty dataset explains missing coverage without claiming the course is absent', () => {
  show({ dataset: { catalog_year: '2026-2027', historical: false, plan_count: 0 } });
  expect(screen.getByText('No published sample plans are available in the 2026–2027 dataset.')).toBeInTheDocument();
  expect(screen.queryByText(/No sample-plan placement/)).not.toBeInTheDocument();
  expect(screen.queryByText(/These do not confirm/)).not.toBeInTheDocument();
});

test('ordinal transfer-track semesters do not invent an academic year', () => {
  show({ dataset: historical, entries: [{ ...entry, major_name: 'Nursing', program_title: 'Nursing, BSN—Transfer Track (Boston)', year: null, term: 'Semester 1' }] });
  expect(screen.getByText(/Semester 1 · Nursing/)).toBeInTheDocument();
  expect(screen.getByText(/Transfer Track \(Boston\)/)).toBeInTheDocument();
  expect(screen.queryByText(/Year null/)).not.toBeInTheDocument();
});

test('placements show five unique rows, then expand and collapse in order', () => {
  const entries = [1, 2, 3, 4, 5, 6, 7].map((n) => placement(CS, n));
  show({ dataset: historical, entries: [...entries, entries[0]] }); // a duplicate never counts
  expect(rows()).toHaveLength(5);
  expect(rows()[0]).toMatch(/Plan 1$/);
  const button = toggle();
  expect(button).toHaveTextContent('Show all (7)');
  expect(button).toHaveAccessibleName('Show all (7) placements');
  expect(button).toHaveAttribute('aria-expanded', 'false');
  expect(button).toHaveAttribute('aria-controls', 'plan-rows');
  expect(button.tagName).toBe('BUTTON'); // native button: Enter and Space work from the keyboard

  fireEvent.click(button);
  expect(rows().map((r) => r.slice(-6))).toEqual(['Plan 1', 'Plan 2', 'Plan 3', 'Plan 4', 'Plan 5', 'Plan 6', 'Plan 7']);
  expect(button).toHaveTextContent('Show less');
  expect(button).toHaveAttribute('aria-expanded', 'true');
  fireEvent.click(button);
  expect(rows()).toHaveLength(5);
});

test('five or fewer rows have no toggle', () => {
  show({ dataset: historical, entries: [1, 2, 3, 4, 5].map((n) => placement(CS, n)) });
  expect(rows()).toHaveLength(5);
  expect(toggle()).not.toBeInTheDocument();
});

test('the selected major filters before counting and truncating, with no fallback', () => {
  const entries = [...[1, 2, 3, 4, 5, 6].map((n) => placement(DS, n)), ...[1, 2, 3].map((n) => placement(CS, n))];
  const view = show({ dataset: historical, entries, major: CS });
  expect(rows()).toHaveLength(3);
  expect(rows().every((r) => r.includes('Computer Science'))).toBe(true);
  expect(toggle()).not.toBeInTheDocument();
  expect(screen.getByText('Showing Computer Science, BSCS (Boston) only.')).toBeInTheDocument();

  view.rerender(<CourseDetail detail={detail(entries, historical)} major={DS} onBack={() => {}} onBreakdown={() => {}} />);
  expect(rows()).toHaveLength(5);
  fireEvent.click(toggle());
  expect(rows()).toHaveLength(6);
  // changing course or major resets the expansion
  view.rerender(<CourseDetail detail={detail(entries, historical, 'CS 3001')} major={DS} onBack={() => {}} onBreakdown={() => {}} />);
  expect(rows()).toHaveLength(5);
  fireEvent.click(toggle());
  view.rerender(<CourseDetail detail={detail(entries, historical, 'CS 3001')} major={{ ...DS, id: 'other' }} onBack={() => {}} onBreakdown={() => {}} />);
  expect(screen.getByText(/CS 3001 doesn’t appear in the collected 2025–2026 sample plans for Data Science/)).toBeInTheDocument();
  expect(document.getElementById('plan-rows')).not.toBeInTheDocument();
});

test('a major without a matching placement says so, distinct from a major or dataset with no plans', () => {
  show({ dataset: historical, entries: [placement(DS, 1)], major: CS });
  expect(screen.getByText('CS 3000 doesn’t appear in the collected 2025–2026 sample plans for Computer Science, BSCS (Boston). Other majors’ placements are hidden while a major is selected.')).toBeInTheDocument();
  expect(screen.queryByText(/Data Science/)).not.toBeInTheDocument();
  expect(screen.getByRole('heading', { name: '2025–2026 sample plan placement' })).toBeInTheDocument();
  expect(screen.getByText(/Historical sample plans/)).toBeInTheDocument();
});

test('a major with no published plan and an empty dataset get their own messages', () => {
  const film = { id: 'film', label: 'Film and Creative Media, BA (Boston)', status: 'no_published_plan' };
  const view = show({ dataset: historical, major: film });
  expect(screen.getByText('Film and Creative Media, BA (Boston) has no published sample plan in the collected 2025–2026 plans, so no placement can be shown for it.')).toBeInTheDocument();
  view.unmount();
  show({ dataset: { catalog_year: '2026-2027', historical: false, plan_count: 0 }, major: CS });
  expect(screen.getByText('No published sample plans are available in the 2026–2027 dataset.')).toBeInTheDocument();
  expect(screen.queryByText(/doesn’t appear/)).not.toBeInTheDocument();
});
