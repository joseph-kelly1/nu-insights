"""Concentration extraction and API integration; no network or AI calls."""

import contextlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import advisor
import db_loader
from json_scrapers import concentration_scraper as scraper, requirements_scraper
from test_requirements_scraper import page, table, course, URL


class ConcentrationCatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        manifest, cls.records = scraper.read_requirements(Path(__file__).parent / 'data')
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
                              ('ds', '4400', 'Machine Learning'), ('cs', '4991', 'Research')])
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
        plans = json.loads((Path(__file__).parent / 'data/plan_catalog.json').read_text())
        saved_id = next(p['major'] for p in plans['programs'] if p['program_title'] == self.cs['label'])
        self.assertEqual(self.cs['id'], saved_id)
        self.assertEqual(len([p for p in advisor.list_programs() if p['label'] == self.cs['label']]), 1)
        self.assertTrue(self.http.get(f"/api/programs/{saved_id}/concentrations").json['groups'])

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
