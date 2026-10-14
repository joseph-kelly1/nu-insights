"""AP/IB policy, parser, API, and planner integration; no network calls."""

import unittest
from unittest import mock

from backend import advisor
from backend import exam_credit
from backend import planner
from json_scrapers import exam_scraper
from tests.test_planner import attempt, choose, context, course, nupath, plan, pool


def exam(name, kind='ap', score=5, level=None, state='awarded', id_=None):
    policy = exam_credit.catalog()['policies'][0]
    subject = next(e for e in policy['exams'] if e['name'] == name and e['kind'] == kind)
    return {'id': id_ or subject['id'], 'exam_id': subject['id'], 'policy_year': policy['policy_year'],
            'version': policy['version'], 'score': score, 'level': level, 'state': state}


class ExamCreditTest(unittest.TestCase):
    def test_thresholds_standard_level_and_excluded_subjects(self):
        for item in [exam('Biology', score=3, state='estimated'),
                     exam('Biology', kind='ib', score=7, level='SL', state='estimated'),
                     exam('Biology', kind='ib', score=4, level='HL', state='estimated'),
                     exam('Research', state='estimated'),
                     exam('English B', kind='ib', score=7, level='HL', state='estimated')]:
            with self.subTest(item=item):
                result = exam_credit.resolve([item])
                self.assertEqual(result['awards'], [])
                self.assertEqual(result['exams'][0]['equivalents'], [])
                with self.assertRaises(exam_credit.ExamCreditError):
                    exam_credit.resolve([{**item, 'state': 'awarded'}])

    def test_biology_bundle_and_unknown_catalog_elective(self):
        result = exam_credit.resolve([exam('Biology'), exam('Computer Science A')])
        self.assertEqual(result['awarded_credits'], 14)
        awards = {a['code']: a['credits'] for a in result['awards']}
        self.assertEqual(awards, {'BIOL 1111': 4, 'BIOL 1112': 1, 'BIOL 1113': 4, 'BIOL 1114': 1, 'CS 1990': 4})

    def test_overlap_and_mixed_ap_ib_awards_count_once(self):
        result = exam_credit.resolve([exam('Calculus AB'), exam('Calculus BC'),
                                     exam('Mathematics: Analysis and Approaches', 'ib', 6, 'HL')])
        self.assertEqual(result['awarded_credits'], 8)
        self.assertEqual(len(result['awards']), 2)
        self.assertEqual(result['notes'], [])

    def test_language_variants_and_combination_dependencies(self):
        result = exam_credit.resolve([exam('French B', 'ib', 6, 'HL')])
        self.assertEqual({a['code'] for a in result['awards']}, {'FRNH 1101', 'FRNH 1102'})
        self.assertEqual(result['awarded_credits'], 8)
        language = exam('Spanish Language and Culture')
        literature = exam('Spanish Literature and Culture', state='estimated')
        result = exam_credit.resolve([language, literature])
        self.assertEqual(result['awarded_credits'], 4)
        self.assertEqual(result['estimated_credits'], 8)
        result = exam_credit.resolve([language, {**literature, 'state': 'awarded'}])
        self.assertEqual(result['awarded_credits'], 8)

    def test_credit_cap_and_invalid_inputs(self):
        records = [exam(n) for n in ['Biology', 'Calculus BC', 'Chemistry', 'Physics C: Mechanics',
                                    'Physics C: Electricity and Magnetism']]
        with self.assertRaisesRegex(exam_credit.ExamCreditError, 'at most 32'):
            exam_credit.resolve(records)
        original = exam('Biology')
        for bad in [{**original, 'score': True}, {**original, 'score': 6}, {**original, 'version': '../bad'},
                    {**original, 'exam_id': 'ap:invented'}, {**original, 'state': 'passed'}]:
            with self.subTest(bad=bad), self.assertRaises(exam_credit.ExamCreditError):
                exam_credit.resolve([bad])
        with self.assertRaisesRegex(exam_credit.ExamCreditError, 'already recorded'):
            exam_credit.resolve([original, {**original, 'id': 'another'}])

    def test_api_catalog_saved_version_resolution_and_error(self):
        http = advisor.app.test_client()
        item = exam('Calculus BC')
        response = http.get('/api/exams/catalog', query_string={'policy_year': item['policy_year'], 'version': item['version']})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['policies'][0]['version'], item['version'])
        response = http.post('/api/exams/resolve', json={'exams': [item]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['awarded_credits'], 8)
        self.assertEqual(http.post('/api/exams/resolve', json={}).status_code, 400)
        with mock.patch.object(exam_credit, 'DATA_DIR', exam_credit.DATA_DIR / 'missing'):
            self.assertEqual(http.get('/api/exams/catalog').status_code, 503)


class ExamPlannerTest(unittest.TestCase):
    def test_estimates_do_not_satisfy_prerequisites_or_requirements(self):
        ctx = context([course('MATH 1341'), course('MATH 1342', prereq={'course': 'MATH 1341'})],
                      [choose('calculus', 1, [['MATH 1341']])])
        item = exam('Calculus AB', state='estimated')
        p = plan(ctx, [attempt('next', 'spring-2027', 'MATH 1342', status='planned')], exams=[item])
        result = planner.validate(p, ctx)
        self.assertEqual(result['requirements'][0]['status'], 'unsatisfied')
        self.assertTrue(any('prerequisites are not met' in e['message'] for e in result['errors']))
        p = plan(ctx, [attempt('next', 'spring-2027', 'MATH 1342', status='planned')], exams=[{**item, 'state': 'awarded'}])
        result = planner.validate(p, ctx)
        self.assertEqual(result['requirements'][0]['status'], 'satisfied')
        self.assertEqual(result['errors'], [])

    def test_elective_allocates_without_catalog_entry_and_duplicates_do_not_inflate(self):
        ctx = context([], [pool('cs-elective', 4, filters=[{'subject': 'CS', 'minimum_number': '1000', 'maximum_number': '1999'}])])
        p = plan(ctx, exams=[exam('Computer Science A')])
        result = planner.validate(p, ctx)
        self.assertEqual(result['errors'], [])
        self.assertFalse(any('not in the current catalog' in w['message'] for w in result['warnings']))
        self.assertEqual(result['requirements'][0]['status'], 'satisfied')
        p = plan(ctx, [attempt('manual', None, 'CS 1990', origin='ap')], exams=[exam('Computer Science A')])
        self.assertEqual(sum(i['credits'] for i in planner._items(p, ctx)) / planner.SCALE, 4)
        self.assertTrue(any('duplicate counted' in e['message'] for e in planner.validate(p, ctx)['errors']))

    def test_chart_attributes_override_catalog_and_generation_preserves_exam_inputs(self):
        ctx = context([course('MATH 1341', attrs=['NUpath Analyzing/Using Data']), course('MATH 1342')],
                      [choose('calculus', 1, [['MATH 1341']]), nupath('FQ'), nupath('AD')])
        p = plan(ctx, exams=[exam('Calculus AB')])
        result = planner.validate(p, ctx)
        states = {r['id']: r['status'] for r in result['requirements']}
        self.assertEqual(states['nupath:FQ'], 'satisfied')
        self.assertEqual(states['nupath:AD'], 'unsatisfied')
        result = planner.generate(p, ctx)
        self.assertFalse(any(a['id'].startswith('exam-credit:') for a in result['proposal']['attempts']))
        self.assertFalse(any(a['code'] == 'MATH 1341' for a in result['proposal']['attempts']))
        self.assertEqual(p['exams'][0]['exam_id'], 'ap:calculus-ab')


class ExamParserTest(unittest.TestCase):
    def test_shorthand_explicit_credit_splits_and_uncertain_rows(self):
        self.assertEqual(exam_scraper.course_codes('BIOL1111/1112 & BIOL1113/1114'),
                         ['BIOL 1111', 'BIOL 1112', 'BIOL 1113', 'BIOL 1114'])
        row = ['2-D Art and Design', 'ARTF 1220 (2SH)\nARTF 1990 (2SH)', 'Art', '(EI)', '4SH']
        parsed = exam_scraper.parse_row('ap', row, 1, {})[0]
        self.assertEqual([a['credits'] for a in parsed['awards']], [2, 2])
        with self.assertRaises(exam_scraper.ExamParseError):
            exam_scraper.parse_row('ap', ['Exam', 'ZZZZ1000 & 1001', 'Unknown', 'N/A', '8SH'], 1, {})

    def test_snapshot_retains_merged_language_rows_and_all_awards_have_totals(self):
        policy = exam_credit.catalog()['policies'][0]
        data = exam_credit.snapshot(policy['policy_year'], policy['version'])
        names = {e['name'] for e in data['exams']}
        self.assertTrue({'French B', 'Arabic B', 'English A: Language and Literature', 'United States Government and Politics'} <= names)
        for rule in data['rules']:
            self.assertEqual(sum(a['credits'] for a in rule['awards']), rule['total_credits'])
            self.assertTrue(rule['source_url'].startswith('https://admissions.northeastern.edu/'))


if __name__ == '__main__':
    unittest.main()
