"""Concentration extraction and API integration; no network or AI calls."""

import contextlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from backend import advisor
from backend import db_loader
from json_scrapers import concentration_scraper as scraper, requirements_scraper
from json_scrapers.requirement_courses import browse_sections, course_contexts
from tests.test_requirements_scraper import page, table, course, URL


class ConcentrationCatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        manifest, cls.records = scraper.read_requirements(Path(__file__).resolve().parents[1] / 'data')
        cls.catalog = scraper.build_catalog(cls.records, manifest['catalog_year'], manifest['generation'])
        cls.programs = {p['title']: p for p in cls.catalog['programs']}

    def options(self, title):
        return self.programs[title]['groups'][0]['options']

    def test_campus_specific_lists_are_not_inherited_from_global_index(self):
        self.assertEqual(len(self.options('Computer Science, BSCS (Boston)')), 5)
        self.assertEqual(len(self.options('Computer Science, BSCS (Oakland)')), 3)
        self.assertNotIn('Systems', [o['name'] for o in self.options('Computer Science, BSCS (Oakland)')])
        self.assertEqual(len(self.options('Business Administration, BSBA (Boston)')), 16)
        self.assertEqual(len(self.options('Business Administration, BSBA (Oakland)')), 5)
        self.assertEqual(len(self.options('Bioengineering, BSBioE (Boston)')), 4)

    def test_optional_elective_and_alternative_curriculum_rules_survive(self):
        political = self.programs['Political Science, BA (Boston)']['groups'][0]
        self.assertFalse(political['policy']['required'])
        self.assertEqual(len(political['options']), 8)
        design = self.programs['Design, BFA (Boston)']['groups'][0]
        self.assertFalse(design['policy']['required'])
        self.assertEqual(design['options'][-1]['kind'], 'alternative')
        philosophy = self.options('Philosophy, BA (Boston)')
        self.assertEqual(philosophy[0]['kind'], 'alternative')
        ethics = next(o for o in philosophy if 'Law and Ethics' in o['name'])
        self.assertIn('PHIL 2301', ethics['courses'])
        self.assertNotIn('PHIL 2301', philosophy[0]['courses'])

    def test_fixed_concentrations_and_second_only_are_separate_from_choices(self):
        music = self.programs['Music with Concentration in Music Industry, BS (Boston)']['groups'][0]
        self.assertTrue(music['fixed'])
        self.assertEqual(music['options'][0]['name'], 'Music Industry')
        business = self.programs['Business Administration, BSBA (Boston)']['groups'][0]
        self.assertTrue(business['policy']['required'])
        self.assertEqual(business['policy']['max_selections'], 2)
        international = next(o for o in business['options'] if o['name'] == 'International Business')
        self.assertTrue(international['secondary_only'])

    def test_export_deduplicates_sources_and_retains_review_boundaries(self):
        exported = scraper.export_catalog(self.catalog)
        for p in exported['programs']:
            for group in p['groups']:
                for option in group['options']:
                    self.assertIn(option['requirements_id'], exported['requirements'])
                    self.assertFalse(option['semantics_validated'])
        self.assertEqual(self.catalog['unresolved_options'], [])
        self.assertTrue(self.catalog['unresolved_requirement_links'])  # stale Family Business URL is still reported

    def test_named_anchors_match_when_display_and_heading_labels_differ(self):
        body = ('<h2>Concentrations</h2><p>Choose one concentration.</p>'
                '<ul><li><a href="#first">Display name</a></li></ul>'
                '<a name="first"></a><h3>Different heading</h3>' + table(course('CS 4100'))
                + '<h4>Electives</h4>' + table(course('CS 4120'))
                + '<h3>Unrelated option</h3>' + table(course('CS 4700')))
        record = requirements_scraper.parse_document(page(body), URL, '2026-2027')
        self.assertEqual(record['sections'][1]['anchor_ids'], ['first'])
        catalog = scraper.build_catalog([record], '2026-2027', 'fixture')
        option = catalog['programs'][0]['groups'][0]['options'][0]
        self.assertEqual(option['match_method'], 'anchor')
        self.assertEqual(option['courses'], ['CS 4100', 'CS 4120'])

    def test_or_bundles_remain_complete_choices(self):
        body = table(course('CS 2000 and CS 2001') + course('CS 2100 and CS 2101', alternative=True))
        record = requirements_scraper.parse_document(page(body), URL, '2026-2027')
        contexts = course_contexts(record['sections'])
        self.assertEqual(set(contexts), {'CS 2000', 'CS 2001', 'CS 2100', 'CS 2101'})
        self.assertEqual(contexts['CS 2001'][0]['choice_text'],
                         'Choose one: CS 2000 and CS 2001 or CS 2100 and CS 2101')


class ConcentrationApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(directory.cleanup)
        cls.path = Path(directory.name) / 'courses.db'
        with contextlib.closing(sqlite3.connect(cls.path)) as conn, contextlib.redirect_stdout(io.StringIO()):
            db_loader.create_tables(conn.cursor())
            db_loader.load_plans(conn.cursor())
            db_loader.load_concentrations(conn.cursor())
            conn.executemany('INSERT INTO courses (department_code, number, title, credits) VALUES (?, ?, ?, 4)',
                             [('cs', '4100', 'AI'), ('cs', '4120', 'NLP'), ('cs', '4700', 'Networks'),
                              ('cs', '4730', 'Distributed Systems'), ('ds', '4400', 'Machine Learning'),
                              ('cs', '4991', 'Research'), ('engw', '3302', 'Technical Writing'),
                              ('engw', '3315', 'Interdisciplinary Writing')])
            conn.commit()

    def setUp(self):
        patcher = patch.object(advisor, 'DB_FILE', str(self.path))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.http = advisor.app.test_client()
        self.programs = {p['label']: p for p in advisor.list_programs()}
        self.cs = self.programs['Computer Science, BSCS (Boston)']
        self.catalog = advisor.lookup_concentration_catalog(self.cs['id'])
        self.ai = self.catalog['groups'][0]['options'][0]

    def test_browse_joins_candidates_without_expanding_substitutions_or_requiring_all_options(self):
        res = self.http.get(f"/api/programs/{self.cs['id']}/courses?concentrations={self.ai['id']}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json['concentration_dataset']['catalog_year'], '2026-2027')
        self.assertEqual({r['number'] for r in res.json['results']}, {'4100', '4120', '4400'})
        self.assertNotIn('plan_dataset', res.json)
        narrowed = self.http.get(f"/api/programs/{self.cs['id']}/courses?q=ds&concentrations={self.ai['id']}")
        self.assertEqual(narrowed.json['total'], 1)

    def test_current_choices_keep_the_historical_program_identity(self):
        plans = json.loads((Path(__file__).resolve().parents[1] / 'data/plan_catalog.json').read_text())
        saved_id = next(p['major'] for p in plans['programs'] if p['program_title'] == self.cs['label'])
        self.assertEqual(self.cs['id'], saved_id)
        self.assertEqual(len([p for p in advisor.list_programs() if p['label'] == self.cs['label']]), 1)
        self.assertTrue(self.http.get(f"/api/programs/{saved_id}/concentrations").json['groups'])

    def test_major_writing_alternatives_come_from_current_requirements(self):
        response = self.http.get(f"/api/programs/{self.cs['id']}/courses?q=engw%2033")
        self.assertEqual(response.json['requirement_dataset']['catalog_year'], '2026-2027')
        self.assertEqual({r['number'] for r in response.json['results']}, {'3302', '3315'})
        for row in response.json['results']:
            self.assertEqual(row['requirement_contexts'][0]['choice_text'], 'Choose one: ENGW 3302 or ENGW 3315')
        # An unselected concentration's courses must not become major-wide requirements.
        response = self.http.get(f"/api/programs/{self.cs['id']}/courses?q=cs%204700")
        self.assertEqual(response.json['total'], 0)

    def test_concentration_or_rows_are_both_browsable_and_labeled(self):
        software = next(o for o in self.catalog['groups'][0]['options'] if o['name'] == 'Software')
        response = self.http.get(f"/api/programs/{self.cs['id']}/courses?q=cs%2047&concentrations={software['id']}")
        self.assertEqual({r['number'] for r in response.json['results']}, {'4700', '4730'})
        for row in response.json['results']:
            self.assertTrue(any(c['choice_text'] == 'Choose one: CS 4700 or CS 4730' for c in row['requirement_contexts']))

    def test_major_filter_paginates_alternatives_without_duplicates(self):
        with patch.object(advisor, 'SEARCH_LIMIT', 1):
            first = advisor.search_courses('engw 33', self.cs['id'])
            second = advisor.search_courses('engw 33', self.cs['id'], offset=1)
        self.assertEqual(first['total'], 2)
        self.assertEqual(first['results'][0]['number'], '3302')
        self.assertEqual(second['results'][0]['number'], '3315')

    def test_section_browse_keeps_matching_choice_whole_and_retains_its_header(self):
        with patch.object(advisor, 'SEARCH_LIMIT', 1):
            response = self.http.get(f"/api/programs/{self.cs['id']}/courses?view=sections&q=engw%203302")
        self.assertEqual({r['number'] for r in response.json['results']}, {'3302', '3315'})
        sections = response.json['requirement_sections']
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0]['title'], 'Computer Science Writing Requirement')
        self.assertEqual(sections[0]['entries'][0], {'kind': 'header', 'text': 'Advanced Writing in the Disciplines'})
        choice = sections[0]['entries'][1]
        self.assertEqual(choice['kind'], 'any_of')
        self.assertEqual([c['code'] for c in choice['children']], ['ENGW 3302', 'ENGW 3315'])
        self.assertTrue(all(c['course']['title'] for c in choice['children']))

    def test_selected_concentration_sections_keep_alternative_courses_clickable(self):
        software = next(o for o in self.catalog['groups'][0]['options'] if o['name'] == 'Software')
        response = self.http.get(f"/api/programs/{self.cs['id']}/courses?view=sections&q=cs%204700&concentrations={software['id']}")
        self.assertEqual({r['number'] for r in response.json['results']}, {'4700', '4730'})
        choice = next(node for section in response.json['requirement_sections'] for node in section['entries']
                      if node['kind'] == 'any_of')
        self.assertEqual([c['code'] for c in choice['children']], ['CS 4700', 'CS 4730'])
        self.assertTrue(all(c['course'] for c in choice['children']))

    def test_section_builder_preserves_bundles_and_does_not_guess_ambiguous_operators(self):
        parsed = requirements_scraper.parse_document(page('<h2>Supporting Courses</h2>' + table(
            course('CS 2000 and CS 2001') + course('CS 2100 and CS 2101', alternative=True)
            + course('CS 3000 and CS 3001 or CS 4000'))), URL, '2026-2027')
        sections = browse_sections(parsed['sections'], {}, {'CS 2000'})
        choice = sections[0]['entries'][0]
        self.assertEqual(choice['kind'], 'any_of')
        self.assertEqual([c['kind'] for c in choice['children']], ['all_of', 'all_of'])
        self.assertEqual([c['code'] for c in choice['children'][1]['children']], ['CS 2100', 'CS 2101'])
        self.assertIsNone(choice['children'][0]['children'][0]['course'])
        ambiguous = browse_sections(parsed['sections'], {}, {'CS 3000'})[0]['entries'][0]
        self.assertEqual(ambiguous['kind'], 'unparsed')
        self.assertEqual(len(ambiguous['children']), 3)

    def test_wrong_campus_malformed_and_unknown_choices_are_rejected_before_ai(self):
        oakland = self.programs['Computer Science, BSCS (Oakland)']
        invalid = [None, self.ai['id'], [1], [self.ai['id'], self.ai['id']], ['unknown']]
        with patch.object(advisor, 'generate_analysis') as generate:
            for selected in invalid:
                response = self.http.post('/api/analyze', json={'dept': 'cs', 'number': '4100',
                                                               'major': self.cs['id'], 'concentrations': selected})
                self.assertEqual((response.status_code, response.json['code']), (400, 'invalid_concentration'))
            response = self.http.post('/api/analyze', json={'dept': 'cs', 'number': '4100',
                                                           'major': oakland['id'], 'concentrations': [self.ai['id']]})
            self.assertEqual(response.status_code, 400)
            generate.assert_not_called()

    def test_second_only_and_alternative_combinations_are_validated(self):
        business = self.programs['Business Administration, BSBA (Boston)']
        options = advisor.lookup_concentration_catalog(business['id'])['groups'][0]['options']
        international = next(o for o in options if o['secondary_only'])
        with self.assertRaises(ValueError):
            advisor.resolve_concentrations(business, [international['id']])
        self.assertEqual(len(advisor.resolve_concentrations(business, [options[0]['id'], international['id']])), 2)
        design = self.programs['Design, BFA (Boston)']
        options = advisor.lookup_concentration_catalog(design['id'])['groups'][0]['options']
        with self.assertRaises(ValueError):
            advisor.resolve_concentrations(design, [options[0]['id'], options[-1]['id']])

    def test_default_and_custom_ai_receive_full_source_scope_separate_from_historical_plans(self):
        response = {'analysis': 'test', 'model': 'fixture', 'id': 'fixture', 'elapsed_ms': 1, 'usage': None}
        body = {'dept': 'cs', 'number': '4100', 'major': self.cs['id'], 'concentrations': [self.ai['id']]}
        with patch.object(advisor, 'generate_analysis', return_value=response) as generate:
            self.assertEqual(self.http.post('/api/analyze', json=body).status_code, 200)
        prompt = generate.call_args.args[0]
        self.assertIn('CONCENTRATION REQUIREMENTS (2026-2027)', prompt)
        self.assertIn('Complete two of the following not already taken', prompt)
        self.assertIn('up to one Research', prompt)
        self.assertIn('Sample plan catalog: 2025-2026', prompt)
        with patch.object(advisor.ai_providers, 'generate', return_value={**response, 'provider': 'openai'}) as custom:
            body['ai'] = {'mode': 'custom', 'provider': 'openai', 'api_key': 'sk-test-key', 'model': 'gpt-6-luna'}
            self.assertEqual(self.http.post('/api/analyze', json=body).status_code, 200)
        self.assertEqual(custom.call_args.args[-1], prompt)


if __name__ == '__main__':
    unittest.main()
