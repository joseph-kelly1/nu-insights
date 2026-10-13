"""Offline regression tests for plan discovery, parsing, and database loading."""

import contextlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup
import db_loader
from json_scrapers import plan_scraper as scraper

URL = 'https://catalog.northeastern.edu/undergraduate/business/business-administration-bsba/'


def page(body='', title='Business Administration, BSBA (Boston)', year='2026-2027'):
    return f'<h2 id="edition">{year} Edition</h2><h1>{title}</h1>{body}'


def grid(rows, terms=('Fall', 'Spring')):
    headers = ''.join(f'<th>{term}</th><th>Hours</th>' for term in terms)
    return ('<table class="sc_plangrid"><tr class="plangridyear"><th colspan="4">Year 1</th></tr>'
            f'<tr class="plangridterm">{headers}</tr>{rows}'
            '<tr class="plangridsum"><td></td><td>16</td><td></td><td>16</td></tr>'
            '<tr class="plangridtotal"><td colspan="4">Total Hours: 128</td></tr></table>')


def plans_page(rows):
    return page('<div id="planofstudytextcontainer"><h3>Four Years, Two Co-ops</h3>'
                + grid(rows) + '</div>')


class DiscoveryTest(unittest.TestCase):
    def test_discovery_includes_campuses_combined_majors_and_deduplicates(self):
        html = page('''<div id="atozindex">
          <a href="/undergraduate/science/biology/biology-bs/">Biology, BS (Boston)</a>
          <a href="/undergraduate/science/biology/biology-bs/#plans">Biology, BS (Boston)</a>
          <a href="/undergraduate/science/biology/biology-bs-oak/">Biology, BS (Oakland)</a>
          <a href="/undergraduate/engineering/combined-bs/">Computer Engineering and Computer Science, BSCmpE (Boston)</a>
          <a href="/undergraduate/science/biology/minor/">Biology, Minor</a>
          <a href="/graduate/science/biology/bs/">Biology, BS (Boston)</a>
          <a href="/professional-studies/biology/">Biology, BS (Online)</a>
          <a href="https://example.org/undergraduate/biology/">Biology, BS</a>
        </div>''')
        results = scraper.discover_programs(BeautifulSoup(html, 'html.parser'), scraper.BASE_URL)
        self.assertEqual(len(results), 3)

    def test_archive_discovery_stays_in_requested_edition(self):
        html = '<div id="atozindex"><a href="/archive/2025-2026/undergraduate/cs/">CS, BS</a><a href="/undergraduate/cs/">CS, BS</a></div>'
        results = scraper.discover_programs(BeautifulSoup(html, 'html.parser'), scraper.BASE_URL + 'archive/2025-2026/')
        self.assertEqual(len(results), 1)
        self.assertIn('/archive/2025-2026/', results[0]['source_url'])

    def test_missing_index_is_failure_not_empty_coverage(self):
        with self.assertRaises(scraper.PlanParseError):
            scraper.discover_programs(BeautifulSoup('<h1>Unavailable</h1>', 'html.parser'), scraper.BASE_URL)


class ParserTest(unittest.TestCase):
    def test_colspan_labs_and_coop_can_share_semester(self):
        html = plans_page('''
          <tr><td>CS 2100 and CS 2101</td><td>5</td><td colspan="2"></td></tr>
          <tr><td>Co-op</td><td>0</td><td>Vacation</td><td></td></tr>
        ''')
        record = scraper.parse_program(html, URL, '2026-2027')
        fall, spring = record['plans'][0]['semesters']
        self.assertEqual(fall['courses'], ['CS 2100', 'CS 2101'])
        self.assertTrue(fall['is_coop'])
        self.assertEqual(fall['entries'][0]['credits'], '5')
        self.assertEqual(spring['notes'], ['Vacation'])
        self.assertEqual(record['degree'], 'BSBA')
        self.assertEqual(record['campus'], 'Boston')

    def test_alternatives_and_indented_choice_groups_are_not_mandatory(self):
        html = plans_page('''
          <tr><td>Take two:</td><td>8</td><td>ECON 1115 or 1116</td><td>4</td></tr>
          <tr><td><div style="margin-left: 20px">ACCT 1201</div></td><td></td><td colspan="2"></td></tr>
          <tr><td><div style="margin-left: 20px">MGSC 2301</div></td><td></td><td colspan="2"></td></tr>
          <tr><td>ENGW 1111</td><td>4</td><td>Concentration course</td><td>4</td></tr>
        ''')
        fall, spring = scraper.parse_program(html, URL, '2026-2027')['plans'][0]['semesters']
        self.assertEqual(fall['courses'], ['ENGW 1111'])
        self.assertEqual(spring['courses'], [])
        self.assertEqual(spring['entries'][0]['courses'], ['ECON 1115', 'ECON 1116'])
        self.assertEqual(len(fall['entries'][0]['options']), 2)
        self.assertIn('ACCT 1201', fall['notes'][0])
        self.assertEqual(spring['notes'][1], 'Concentration course')

    def test_different_plan_variants_and_empty_semesters(self):
        table = grid('<tr><td>CS 3000</td><td>4</td><td colspan="2"></td></tr>')
        html = page(f'<div id="planofstudytextcontainer"><h2>Spring Co-op</h2>{table}<h3>Fall Co-op</h3>{table}</div>')
        plans = scraper.parse_program(html, URL, '2026-2027')['plans']
        self.assertEqual([p['plan_name'] for p in plans], ['Spring Co-op', 'Fall Co-op'])
        self.assertEqual(len(plans[0]['semesters']), 1)

    def test_indented_lab_inside_course_bundle_is_mandatory(self):
        html = plans_page('<tr><td>CS 2100<span style="margin-left:20px">and CS 2101</span></td><td>5</td><td colspan="2"></td></tr>')
        semester = scraper.parse_program(html, URL, '2026-2027')['plans'][0]['semesters'][0]
        self.assertEqual(semester['courses'], ['CS 2100', 'CS 2101'])
        self.assertEqual(semester['entries'][0]['kind'], 'course')

    def test_numbered_semester_lists_preserve_bundles_and_or_rows(self):
        html = page('''<div id="planofstudytextcontainer"><h2>Sample Plan of Study</h2>
          <table class="sc_courselist"><tbody>
            <tr class="areaheader"><td colspan="2">SEMESTER 1</td><td></td></tr>
            <tr><td>NRSG 2222<span style="margin-left:20px">and NRSG 2221</span></td><td>Course and lab</td><td>5</td></tr>
            <tr class="areaheader"><td colspan="2">SEMESTER 2</td><td></td></tr>
            <tr><td>ENGW 3306</td><td>Advanced Writing</td><td>4</td></tr>
            <tr class="orclass"><td>or ENGW 3315</td><td colspan="2">Interdisciplinary Writing</td></tr>
            <tr><td>NRSG 3320 and NRSG 3321</td><td>Course and clinical</td><td>6</td></tr>
            <tr class="listsum"><td colspan="2">Total Hours</td><td>15</td></tr>
          </tbody></table></div>''')
        first, second = scraper.parse_program(html, URL, '2026-2027')['plans'][0]['semesters']
        self.assertIsNone(first['year'])
        self.assertEqual(first['term'], 'Semester 1')
        self.assertEqual(first['courses'], ['NRSG 2222', 'NRSG 2221'])
        self.assertEqual(second['courses'], ['NRSG 3320', 'NRSG 3321'])
        self.assertEqual([option['courses'] for option in second['entries'][0]['options']], [['ENGW 3306'], ['ENGW 3315']])
        self.assertIn('ENGW 3315', second['notes'][0])

    def test_supplementary_course_tables_are_preserved_without_extra_placements(self):
        html = plans_page('<tr><td>PHYS 2303</td><td>4</td><td colspan="2"></td></tr>')
        reference = '<h3>Additional course options</h3><table class="sc_courselist"><tbody><tr><td>BIOL 2301</td><td>Genetics</td><td>4</td></tr></tbody></table>'
        html = html.replace('</div>', reference + '</div>')
        record = scraper.parse_program(html, URL, '2026-2027')
        self.assertEqual(len(record['plans']), 1)
        self.assertEqual(record['plans'][0]['semesters'][0]['courses'], ['PHYS 2303'])
        self.assertIn('BIOL 2301', record['notes'][0])

    def test_missing_plan_is_explicit_and_wrong_year_is_failure(self):
        record = scraper.parse_program(page(), URL, '2026-2027')
        self.assertEqual(record['status'], 'no_published_plan')
        self.assertEqual(record['plans'], [])
        with self.assertRaises(scraper.PlanParseError):
            scraper.parse_program(page(year='2025-2026'), URL, '2026-2027')

    def test_unsupported_and_malformed_plan_sections_fail(self):
        for html in [page('<div id="planofstudytextcontainer"><p>See advisor</p></div>'),
                     plans_page('<tr><td>CS 3000</td><td>4</td></tr>')]:
            with self.subTest(html=html), self.assertRaises(scraper.PlanParseError):
                scraper.parse_program(html, URL, '2026-2027')


class RefreshTest(unittest.TestCase):
    def test_failed_refresh_preserves_active_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            active = Path(directory) / 'plan_catalog.json'
            active.write_text('{"previous": true}')
            index = page(f'<div id="atozindex"><a href="{URL}">Business Administration, BSBA (Boston)</a></div>')
            def fetch(session, url):
                if url.endswith('undergraduate/'):
                    return page()
                if url.endswith('azindex/'):
                    return index
                return page(year='2025-2026')
            with patch.object(scraper, 'fetch', side_effect=fetch), contextlib.redirect_stdout(io.StringIO()):
                result = scraper.main(['--output-dir', directory, '--delay', '0'])
            self.assertEqual(result, 1)
            self.assertEqual(json.loads(active.read_text()), {'previous': True})
            report = json.loads((Path(directory) / 'plan_scrape_report.json').read_text())
            self.assertFalse(report['complete'])
            self.assertEqual(len(report['errors']), 1)

    def test_refresh_retains_selected_edition_until_current_catalog_is_requested(self):
        with tempfile.TemporaryDirectory() as directory:
            active = Path(directory) / 'plan_catalog.json'
            active.write_text(json.dumps({'catalog_year': '2025-2026'}))
            def fetch(session, url):
                year = '2025-2026' if '/archive/' in url else '2026-2027'
                root = scraper.BASE_URL + ('archive/2025-2026/' if '/archive/' in url else '')
                if url.endswith('azindex/'):
                    return page(f'<div id="atozindex"><a href="{root}undergraduate/cs/">CS, BS (Boston)</a></div>', year=year)
                return page(year=year)
            with patch.object(scraper, 'fetch', side_effect=fetch), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(scraper.main(['--output-dir', directory, '--delay', '0']), 0)
                self.assertEqual(json.loads(active.read_text())['catalog_year'], '2025-2026')
                self.assertEqual(scraper.main(['--output-dir', directory, '--delay', '0', '--current-catalog']), 0)
                self.assertEqual(json.loads(active.read_text())['catalog_year'], '2026-2027')

    def test_current_empty_catalog_excludes_legacy_plans_from_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'plans').mkdir()
            (root / 'plans' / 'legacy.json').write_text(json.dumps({'major': 'OLD', 'major_name': 'Old', 'plans': [{'plan_name': 'Old', 'semesters': [{'year': 1, 'term': 'Fall', 'courses': ['CS 2500']}]}]}))
            (root / 'plan_catalog.json').write_text(json.dumps({'complete': True, 'catalog_year': '2026-2027', 'programs_without_plans': 1, 'programs': [{'status': 'no_published_plan'}]}))
            with contextlib.closing(sqlite3.connect(':memory:')) as conn, patch.object(db_loader, 'DEPARTMENTS_FILE', str(root / 'departments.json')), contextlib.redirect_stdout(io.StringIO()):
                db_loader.create_tables(conn.cursor())
                db_loader.create_tables(conn.cursor())
                db_loader.load_plans(conn.cursor())
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM plan_entries').fetchone()[0], 0)

    def test_loader_keeps_classes_during_coop_and_choice_notes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plans = root / 'plans' / '2026-2027'
            plans.mkdir(parents=True)
            record = scraper.parse_program(plans_page('<tr><td>Co-op</td><td>0</td><td colspan="2"></td></tr><tr><td>CS 2100</td><td>4</td><td colspan="2"></td></tr><tr><td>ECON 1115 or 1116</td><td>4</td><td colspan="2"></td></tr>'), URL, '2026-2027')
            (plans / 'business.json').write_text(json.dumps(record))
            (root / 'plan_catalog.json').write_text(json.dumps({'complete': True, 'catalog_year': '2026-2027', 'programs_without_plans': 0, 'programs': [{'status': 'available', 'file': 'plans/2026-2027/business.json'}]}))
            with contextlib.closing(sqlite3.connect(':memory:')) as conn, patch.object(db_loader, 'DEPARTMENTS_FILE', str(root / 'departments.json')), contextlib.redirect_stdout(io.StringIO()):
                db_loader.create_tables(conn.cursor())
                db_loader.load_plans(conn.cursor())
                rows = conn.execute('SELECT course_code, is_coop, note FROM plan_entries').fetchall()
                self.assertIn(('CS 2100', 0, None), rows)
                self.assertIn((None, 1, None), rows)
                self.assertIn((None, 0, 'ECON 1115 or 1116'), rows)
                self.assertEqual(len(rows), 3)


if __name__ == '__main__':
    unittest.main()
