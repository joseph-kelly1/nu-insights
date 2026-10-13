import React from 'react';
import { render, screen } from '@testing-library/react';
import CourseDetail from './CourseDetail';

const historical = { catalog_year: '2025-2026', current_catalog_year: '2026-2027', historical: true, plan_count: 622 };
const entry = { major_name: 'Computer Science', plan_name: 'Four Years, Two Co-ops', year: 2, term: 'Fall' };

function show({ entries = [], dataset } = {}) {
  render(<CourseDetail detail={{ status: 'ready', code: 'CS 3000', course: {
    title: 'Algorithms and Data', description: 'Algorithms course.', credits: 4,
    prerequisites: [], corequisites: [], attributes: [], schedule_context: entries,
    plan_dataset: dataset,
  } }} onBack={() => {}} onBreakdown={() => {}} />);
}

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
