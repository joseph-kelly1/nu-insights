"""Archived requirements stay tied to their course and concentration edition."""

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from backend import advisor
from backend import catalog_editions
from backend import db_loader
from backend import planner
from json_scrapers import course_scraper, requirements_scraper
from tests.test_planner import attempt, plan

ROOT = Path(__file__).resolve().parents[1] / 'data'
PROGRAM = {'id': 'bscs', 'major_name': 'Computer Science', 'degree': 'BSCS', 'campus': 'Boston',
           'label': 'Computer Science, BSCS (Boston)'}


class CatalogEditionTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = Path(directory.name) / 'courses.db'
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)
        db_loader.create_tables(self.conn.cursor())
        self.conn.execute('INSERT INTO program_requirements VALUES (?, ?, ?, ?, ?)',
                          ('bscs', '2026-2027', 'https://catalog.northeastern.edu/undergraduate/computer-information-science/computer-science/bscs/', '[]', '[]'))
        self.conn.execute("INSERT INTO dataset_meta VALUES ('fingerprint', 'fixture')")
        self.conn.commit()
        patch = mock.patch.object(catalog_editions, 'data_root', return_value=ROOT)
        patch.start()
        self.addCleanup(patch.stop)

    def context(self, year):
        archive = catalog_editions.program_data(self.conn, self.db, PROGRAM, year)
        groups = archive['groups']
        selected = [next(o for g in groups for o in g['options'] if o['name'] == 'Artificial Intelligence')]
        return planner.planning_context(self.conn, str(self.db), PROGRAM, year, selected, groups)

    def test_all_five_years_available_and_older_cs_requirements_differ(self):
        self.assertEqual(catalog_editions.available(self.conn, self.db, PROGRAM),
                         ['2025-2026', '2024-2025', '2023-2024', '2022-2023'])
        for year in ('2022-2023', '2023-2024', '2024-2025', '2025-2026'):
            with self.subTest(year=year):
                ctx = self.context(year)
                self.assertEqual(ctx['capability'], 'extracted')
                self.assertEqual(len(ctx['available_editions']), 5)
                first_course = 'CS 2000' if year == '2025-2026' else 'CS 2500'
                archive = catalog_editions.program_data(self.conn, self.db, PROGRAM, year)
                self.assertTrue(any(first_course in row.get('courses', []) for section in archive['sections']
                                    for entry in section['entries'] for row in entry.get('rows', [])))
                self.assertTrue(all(f'/archive/{year}/' in s['source_url'] for s in ctx['sources']))
                lab = 'CS 2001' if year == '2025-2026' else 'CS 2501'
                self.assertEqual(ctx['catalog'][lab]['max_credits'], 1)

    def test_retired_courses_count_in_history_and_are_not_auto_scheduled(self):
        ctx = self.context('2024-2025')
        p = plan(ctx, [attempt('lecture', 'fall-2025', 'CS 2500'), attempt('lab', 'fall-2025', 'CS 2501', credits=1)],
                 catalog_year='2024-2025')
        result = planner.validate(p, ctx)
        relevant = [r for r in result['requirements'] if any('CS 2500' in o for o in r.get('options', []))]
        self.assertTrue(relevant)
        self.assertTrue(all(r['status'] == 'satisfied' for r in relevant))
        candidates, _ = planner._candidates(ctx, p, {})
        self.assertNotIn('CS 2500', candidates)
        future = plan(ctx, [attempt('future', 'spring-2027', 'CS 2500', status='planned')], catalog_year='2024-2025')
        self.assertTrue(any('absent from the current course catalog' in e['message'] for e in planner.validate(future, ctx)['errors']))

    def test_archived_course_api_returns_correct_lab_credit_and_search(self):
        with mock.patch.object(advisor, 'DB_FILE', str(self.db)):
            http = advisor.app.test_client()
            response = http.get('/api/course/cs/2501?catalog_year=2024-2025')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['credits'], 1)
            self.assertEqual(response.json['catalog_year'], '2024-2025')
            response = http.get('/api/search?q=cs2501&catalog_year=2024-2025')
            self.assertEqual(response.json[0]['number'], '2501')
            self.assertEqual(response.json[0]['credits'], 1)
        self.assertIsNone(catalog_editions.load(self.db, '../invalid'))

    def test_record_checks_follow_course_term_not_degree_catalog(self):
        ctx = self.context('2024-2025')
        courses = ['DS 3000', 'CS 1210', 'CS 3000', 'CS 3200', 'CY 2550', 'CS 3520', 'CS 3800', 'CS 4530']
        records = [attempt('discrete', 'fall-2025', 'CS 1800'),
                   attempt('fundies', 'fall-2025', 'CS 2100'),
                   attempt('ood', 'spring-2026', 'CS 3100')]
        records += [attempt(code, 'summer1-2026', code, credits=1 if code == 'CS 1210' else 4) for code in courses]
        report = planner.validate(plan(ctx, records, catalog_year='2024-2025'), ctx)
        self.assertFalse(any('prerequisites are not met' in w['message'] and w.get('attempt_id') in courses
                             for w in report['warnings']))
        # The newer prerequisites do not rewrite the older degree requirements.
        fundamentals = [r for r in report['requirements'] if 'CS 2510 + CS 2511' in r.get('options', [])]
        self.assertTrue(fundamentals)
        self.assertEqual(fundamentals[0]['status'], 'unsatisfied')

    def test_spring_and_both_summers_use_previous_fall_edition(self):
        self.assertEqual(planner.course_edition({'year': 2025, 'session': 'fall'}), '2025-2026')
        for session in ('spring', 'summer1', 'summer2'):
            self.assertEqual(planner.course_edition({'year': 2025, 'session': session}), '2024-2025')

    def test_unavailable_term_edition_falls_back_to_existing_metadata(self):
        ctx = self.context('2024-2025')
        a = {'code': 'CS 3500', 'counts_as': None, 'evidence': ''}
        c = planner._record_course(ctx, a, True, {'year': 2021, 'session': 'fall'})
        self.assertEqual(c['title'], 'Object-Oriented Design')

    def test_legacy_letter_codes_preserve_courses_and_requirements(self):
        for subject, number, credits in [('ACCT', '215M', 3), ('BIOL', '13LM', 0)]:
            html = f'<h2 id="edition">2025-2026 Edition</h2><h1>Department ({subject})</h1>'
            html += f'<div class="courseblock"><p class="courseblocktitle"><strong>{subject} {number}. Course. ({credits} Hours)</strong></p><p class="cb_desc">Description.</p></div>'
            errors = []
            data = course_scraper.parse_department(html, 'https://catalog.northeastern.edu/archive/2025-2026/course-descriptions/acct/', errors)
            self.assertEqual(errors, [])
            self.assertEqual(data['courses'][0]['number'], number)
            self.assertEqual(data['courses'][0]['credits'], credits)
        self.assertEqual(requirements_scraper.course_expression('ACCT 215M')['course'], 'ACCT 215M')
        self.assertEqual(course_scraper.format_corequisites('Corequisite(s): ACCT 217M'), ['ACCT 217M'])
        self.assertEqual(course_scraper.format_corequisites('Corequisite(s): BIOL 13LM'), ['BIOL 13LM'])


if __name__ == '__main__':
    unittest.main()
