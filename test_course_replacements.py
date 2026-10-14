"""Retired-course replacements: registry validation, exact-bundle fulfillment, and a real archived BSCS plan.

Fixture registries are written to temporary files; the real registry is read only
where a test says so, and never the developer's courses.db.
"""

import contextlib
import copy
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

import advisor
import catalog_editions
import course_replacements as cr
import db_loader
import planner
from test_planner import attempt, choose, context, course, messages, nupath, placed, plan, pool, timeline

ROOT = Path(__file__).resolve().parent / 'data'
URL = 'https://www.khoury.northeastern.edu/example/'
PROGRAM = {'id': 'bscs', 'campus': 'Boston'}


def record(rid='ood', original=('CS 3500', 'CS 3501'), replacement=('CS 3100', 'CS 3101'), status='verified',
           years=('2024-2025',), programs=('bscs',), term=(2025, 'fall'), **restrictions):
    out = {'id': rid, 'original': list(original), 'replacement': list(replacement),
           'direction': 'replacement_fulfills_original', 'purpose': 'degree_requirement',
           'scope': {'program_ids': list(programs), 'campus': 'Boston', 'catalog_years': list(years)},
           'effective_term': {'year': term[0], 'session': term[1]}, 'restrictions': {'origins': ['nu'], **restrictions},
           'evidence': [{'url': URL, 'retrieved_on': '2026-10-13', 'sha256': '0' * 64}], 'rationale': 'Fixture.',
           'review': {'status': status, 'reviewed_on': '2026-10-13'}}
    if status == 'candidate':
        out['review']['gap'] = 'Degree-catalog applicability is not published.'
    return out


def registry(*records):
    return {'schema_version': 1, 'registry_version': 'test', 'records': list(records)}


COURSES = [
    course('CS 2100'), course('CS 2101', 1, coreqs=['CS 2100']),
    course('CS 2510', prereq=None), course('CS 2511', 1),
    course('CS 3100', prereq={'type': 'OR', 'courses': [{'course': 'CS 2100'}, {'course': 'CS 2510'}]}, coreqs=['CS 3101']),
    course('CS 3101', 1, coreqs=['CS 3100']),
    {**course('CS 3500', attrs=['NUpath Writing Intensive']), 'historical_only': True},
    {**course('CS 3501', 1), 'historical_only': True},
    course('CS 4100'),
]
OOD = choose('OOD', 1, [['CS 3500', 'CS 3501']])


def expanded(rules, *records, year='2024-2025'):
    ctx = context(copy.deepcopy(COURSES), [])
    verified, candidates = cr.resolve({'records': cr.validate(registry(*records))}, PROGRAM, year)
    ctx['rules'], gaps = cr.expand(rules, verified, candidates)
    ctx['issues'] = gaps
    return ctx


def report(ctx, attempts, **extra):
    return planner.validate(plan(ctx, attempts, catalog_year='2024-2025', **extra), ctx)


def bundle(term='spring-2026', lecture='CS 3100', lab='CS 3101', **extra):
    return [attempt('lec', term, lecture, **extra), attempt('lab', term, lab, 1)]


class RegistryTest(unittest.TestCase):
    def test_rejects_malformed_unsupported_and_conflicting_records(self):
        bad = [
            {**record(), 'original': ['CS3500']},
            {**record(), 'original': ['CS 3500', 'CS 3500']},
            {**record(), 'replacement': ['CS 3500']},
            {**record(), 'direction': 'equivalent'},
            {**record(), 'purpose': 'prerequisite'},
            {**record(), 'scope': {'program_ids': [], 'campus': 'Boston', 'catalog_years': ['2024-2025']}},
            {**record(), 'scope': {'program_ids': ['bscs'], 'campus': 'Boston', 'catalog_years': ['2024']}},
            {**record(), 'effective_term': {'year': 2025, 'session': 'autumn'}},
            {**record(), 'restrictions': {'mixed_labs': True}},
            {**record(), 'evidence': [{'url': 'http://example.com', 'retrieved_on': '2026-10-13', 'sha256': '0' * 64}]},
            {**record(), 'review': {'status': 'approved', 'reviewed_on': '2026-10-13'}},
            {**record(status='candidate'), 'review': {'status': 'candidate', 'reviewed_on': '2026-10-13'}},
            {**record(), 'extra': 1},
        ]
        for r in bad:
            with self.subTest(record=r), self.assertRaises(cr.RegistryError):
                cr.validate(registry(r))
        with self.assertRaises(cr.RegistryError):
            cr.validate(registry(record(), record()))  # duplicate ID
        with self.assertRaises(cr.RegistryError):  # ambiguous: two verified answers for one course
            cr.validate(registry(record('a'), record('b', replacement=['CS 4100'])))
        cr.validate(registry(record('a'), record('b', replacement=['CS 4100'], years=['2023-2024'])))
        cr.validate(registry(record('a'), record('b', replacement=['CS 4100'], status='candidate')))

    def test_scope_is_explicit_and_missing_registry_is_empty(self):
        reg = {'records': cr.validate(registry(record()))}
        self.assertEqual(len(cr.resolve(reg, PROGRAM, '2024-2025')[0]), 1)
        for program, year in ((PROGRAM, '2025-2026'), ({'id': 'bscs-oak', 'campus': 'Oakland'}, '2024-2025'),
                              ({'id': 'bscs', 'campus': 'Oakland'}, '2024-2025'), ({'id': 'cs-math'}, '2024-2025')):
            self.assertEqual(cr.resolve(reg, program, year), ([], []))
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(cr.load(Path(directory) / 'courses.db'), {'version': None, 'records': []})

    def test_real_registry_keeps_unproven_mappings_as_candidates(self):
        records = cr.load(ROOT.parent / 'courses.db')['records']
        self.assertEqual({tuple(r['original']): tuple(r['replacement']) for r in records}, {
            ('CS 2500', 'CS 2501'): ('CS 2000', 'CS 2001'), ('CS 2510', 'CS 2511'): ('CS 2100', 'CS 2101'),
            ('CS 3500', 'CS 3501'): ('CS 3100', 'CS 3101')})
        self.assertTrue(all(r['review']['status'] == 'candidate' and r['review']['gap'] for r in records))
        self.assertTrue(all(r['scope']['program_ids'] == ['bscs-2bc732ab'] for r in records))


class FulfillmentTest(unittest.TestCase):
    def test_current_bundle_fulfills_exact_original_with_actual_codes_and_source(self):
        ctx = expanded([OOD], record())
        r = report(ctx, bundle())
        req = r['requirements'][0]
        self.assertEqual(req['status'], 'satisfied')
        self.assertEqual(req['options'], ['CS 3500 + CS 3501'])  # source wording kept
        self.assertEqual(sorted(c['code'] for c in req['courses']), ['CS 3100', 'CS 3101'])
        self.assertEqual({c['replacement']['id'] for c in req['courses']}, {'ood'})
        self.assertEqual(req['courses'][0]['replacement']['source_url'], URL)
        self.assertEqual(r['errors'], [])
        self.assertFalse(any('CS 3500' in m or 'approv' in m for m in [*messages(r, 'warnings').split(' | '), *r['assumptions']]))

    def test_missing_failed_lab_low_grade_scope_term_and_candidate_do_not_satisfy(self):
        ctx = expanded([OOD], record(min_grade='C'))
        cases = {
            'missing lab': [attempt('lec', 'spring-2026', 'CS 3100')],
            'failed lab': [attempt('lec', 'spring-2026', 'CS 3100'), attempt('lab', 'spring-2026', 'CS 3101', 1, status='failed')],
            'low lecture grade': bundle(grade='D'),
            'before effective term': bundle('spring-2025'),
            'mixed old lab': bundle(lab='CS 3501'),
            'transfer origin': bundle(origin='transfer'),
        }
        for name, attempts in cases.items():
            with self.subTest(name):
                terms = timeline(start=(2024, 'fall'), count=12)
                self.assertEqual(report(ctx, attempts, terms=terms)['requirements'][0]['status'], 'unsatisfied')
        for ctx in (expanded([OOD], record(years=['2023-2024'])), expanded([OOD], record(programs=['bscs-oak'])),
                    expanded([OOD], record(status='candidate'))):
            self.assertEqual(report(ctx, bundle())['requirements'][0]['status'], 'unsatisfied')
        candidate = report(expanded([OOD], record(status='candidate')), [])['requirements'][0]
        self.assertEqual(candidate['replacements'][0]['review'], 'candidate')

    def test_original_courses_still_count_and_mixed_sequences_use_published_prerequisites(self):
        ctx = expanded([OOD], record())
        ctx['archived'] = {'CS 3500': ctx['catalog']['CS 3500'], 'CS 3501': ctx['catalog']['CS 3501']}
        req = report(ctx, bundle('fall-2025', 'CS 3500', 'CS 3501'))['requirements'][0]
        self.assertEqual(req['status'], 'satisfied')
        self.assertNotIn('replacement', req['courses'][0])
        mixed = report(ctx, [attempt('f2', 'fall-2025', 'CS 2510'), attempt('f2l', 'fall-2025', 'CS 2511', 1),
                             attempt('lec', 'spring-2027', 'CS 3100', status='planned'),
                             attempt('lab', 'spring-2027', 'CS 3101', 1, status='planned')])
        self.assertEqual(mixed['errors'], [])
        self.assertEqual(mixed['requirements'][0]['status'], 'planned')

    def test_bundles_cannot_fill_two_slots_or_two_exclusive_rules(self):
        two = choose('Pick two', 2, [['CS 3500', 'CS 3501']], [['CS 4100']])
        ctx = expanded([two], record())
        both = bundle() + [attempt('o1', 'fall-2025', 'CS 3500'), attempt('o2', 'fall-2025', 'CS 3501', 1)]
        self.assertEqual(report(ctx, both)['requirements'][0]['progress'], '1 of 2')
        ctx = expanded([OOD, choose('Again', 1, [['CS 3500', 'CS 3501']])], record())
        statuses = sorted(r['status'] for r in report(ctx, bundle())['requirements'])
        self.assertEqual(statuses, ['satisfied', 'unsatisfied'])

    def test_unsupported_slot_shapes_are_gaps_not_guesses(self):
        lecture_only = choose('Lecture', 1, [['CS 3500']])
        listed = choose('Listed', 1, [['CS 3500', 'CS 3501']], [['CS 3100']])
        ctx = expanded([lecture_only, listed], record())
        self.assertEqual(len(ctx['issues']), 2)
        self.assertEqual([r['options'] for r in ctx['rules']], [lecture_only['options'], listed['options']])

    def test_attributes_pools_and_exam_credit_are_never_inherited(self):
        ctx = expanded([OOD, nupath('WI', need=1), pool('Old pool', 4, courses=['CS 3500'])], record())
        statuses = {r['id']: r['status'] for r in report(ctx, bundle())['requirements']}
        self.assertEqual(statuses, {'OOD': 'satisfied', 'nupath:WI': 'unsatisfied', 'Old pool': 'unsatisfied'})
        ap = report(ctx, [attempt('ap', None, 'CS 3100', origin='ap'), attempt('lab', 'spring-2026', 'CS 3101', 1)])
        self.assertEqual(ap['requirements'][0]['status'], 'unsatisfied')

    def test_reported_approval_path_still_works_for_candidates_with_actual_course_metadata(self):
        ctx = expanded([OOD], record(status='candidate'))
        approved = [attempt('lec', 'spring-2027', 'CS 3100', status='planned', counts_as='CS 3500', evidence='Advisor, 2026'),
                    attempt('lab', 'spring-2027', 'CS 3101', 1, status='planned', counts_as='CS 3501', evidence='Advisor, 2026'),
                    attempt('f2', 'fall-2025', 'CS 2510')]
        r = report(ctx, approved)
        self.assertEqual(r['errors'], [])  # CS 3100's own prerequisites and corequisite, not the retired course's
        self.assertEqual(r['requirements'][0]['status'], 'planned')
        self.assertTrue(any('reported approval' in a for a in r['assumptions']))
        self.assertNotIn('replacement', r['requirements'][0]['courses'][0])

    def test_past_records_use_archived_metadata_and_future_ones_current(self):
        ctx = expanded([], record())
        ctx['archived'] = {'CS 4100': course('CS 4100', 3)}
        self.assertEqual(report(ctx, [attempt('old', 'fall-2025', 'CS 4100', 3)])['errors'], [])
        self.assertIn('offered for 4 credits', messages(report(ctx, [attempt('new', 'spring-2027', 'CS 4100', 3, status='planned')])))


class GenerationTest(unittest.TestCase):
    def test_generates_current_bundle_in_order_without_retired_codes(self):
        ctx = expanded([OOD, choose('Intro', 1, [['CS 2510', 'CS 2511']])], record(),
                       record('f2', ['CS 2510', 'CS 2511'], ['CS 2100', 'CS 2101']))
        ctx['catalog']['CS 2510']['historical_only'] = ctx['catalog']['CS 2511']['historical_only'] = True
        history = [attempt('pin', 'fall-2025', 'CS 4100')]
        p = plan(ctx, history, catalog_year='2024-2025')
        result = planner.generate(p, ctx)
        self.assertEqual(result['status'], 'complete')
        where = placed(result)
        self.assertEqual(set(where), {'CS 2100', 'CS 2101', 'CS 3100', 'CS 3101'})
        order = {t['id']: t['key'] for t in p['terms']}
        self.assertLess(order[where['CS 2100']], order[where['CS 3100']])
        self.assertEqual(where['CS 3100'], where['CS 3101'])
        self.assertIn('in place of CS 3500 + CS 3501', next(a['reason'] for a in result['proposal']['attempts']
                                                           if a['code'] == 'CS 3100'))
        self.assertEqual([a['id'] for a in result['proposal']['attempts'] if a['source'] == 'user'], ['pin'])
        self.assertEqual(result['report']['errors'], [])

    def test_history_meeting_requirement_and_prerequisites_adds_no_intro_courses(self):
        ctx = expanded([OOD, choose('Intro', 1, [['CS 2510', 'CS 2511']])], record(),
                       record('f2', ['CS 2510', 'CS 2511'], ['CS 2100', 'CS 2101']))
        history = [attempt('f2', 'fall-2025', 'CS 2510'), attempt('f2l', 'fall-2025', 'CS 2511', 1)]
        result = planner.generate(plan(ctx, history, catalog_year='2024-2025'), ctx)
        self.assertEqual(set(placed(result)), {'CS 3100', 'CS 3101'})


class ArchivedBSCSTest(unittest.TestCase):
    """The checked-in 2024-25 BSCS archive against the current catalog snapshot."""

    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(directory.cleanup)
        cls.dir = Path(directory.name)
        cls.path = cls.dir / 'courses.db'
        with contextlib.closing(sqlite3.connect(cls.path)) as conn, contextlib.redirect_stdout(io.StringIO()):
            cur = conn.cursor()
            db_loader.create_tables(cur)
            db_loader.load_departments(cur)
            db_loader.load_courses(cur)
            db_loader.load_plans(cur)
            db_loader.load_concentrations(cur)
            cur.execute("INSERT INTO dataset_meta VALUES ('fingerprint', 'archive')")
            conn.commit()

    def setUp(self):
        self.registry = self.dir / 'course_replacements.json'
        self.registry.unlink(missing_ok=True)
        patches = [mock.patch.object(advisor, 'DB_FILE', str(self.path)),
                   mock.patch.object(catalog_editions, 'data_root', return_value=ROOT),
                   mock.patch.object(cr, 'path', return_value=self.registry)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.cs = next(p for p in advisor.list_programs() if p['label'] == 'Computer Science, BSCS (Boston)')
        groups = advisor.lookup_concentration_catalog(self.cs['id'], '2024-2025')['groups']
        self.ai = next(o for o in groups[0]['options'] if o['name'] == 'Artificial Intelligence')

    def write(self, *records):
        self.registry.write_text(json.dumps(registry(*records)))

    def context(self):
        return advisor.planner_context(self.cs['id'], '2024-2025', [self.ai['id']])

    TERMS = {'summer1-2025': 'off', 'summer2-2025': 'off', 'summer1-2026': 'off', 'summer2-2026': 'off',
             'summer1-2027': 'off'}

    def student(self, ctx, extra=()):
        terms = timeline(start=(2024, 'fall'), count=16, current=(2026, 'fall'), **self.TERMS)
        history = [attempt(f'h{i}', term, code, credits) for i, (term, code, credits) in enumerate([
            ('fall-2024', 'CS 1200', 1), ('fall-2024', 'CS 1800', 4), ('fall-2024', 'CS 1802', 1),
            ('fall-2024', 'CS 2500', 4), ('fall-2024', 'CS 2501', 1), ('fall-2024', 'ENGW 1111', 4),
            ('spring-2025', 'CS 2510', 4), ('spring-2025', 'CS 2511', 1), ('spring-2025', 'MATH 1341', 4),
            ('fall-2025', 'CS 3000', 4), ('fall-2025', 'MATH 1365', 4), ('spring-2026', 'CS 3800', 4)])]
        return plan(ctx, history + list(extra), terms=terms, catalog_year='2024-2025', sample_variant=None)

    def ood(self, report):
        return next(r for r in report['requirements'] if r.get('options') == ['CS 3500 + CS 3501'])

    def test_current_prerequisites_with_older_degree_catalog(self):
        ctx = self.context()
        self.assertIn('CS 2100', json.dumps(ctx['catalog']['CS 3000']['prereq']))  # current published alternatives
        self.assertNotIn('CS 2100', json.dumps(ctx['archived']['CS 3000']['prereq']))
        self.assertTrue(ctx['catalog']['CS 2500']['historical_only'])
        self.assertEqual(ctx['catalog']['CS 2501']['max_credits'], 1)

    def test_real_candidates_explain_without_counting_and_registry_changes_fingerprint(self):
        missing = self.context()['fingerprint']
        self.write(record('ood', programs=[self.cs['id']], status='candidate'))
        ctx = self.context()
        self.assertNotEqual(ctx['fingerprint'], missing)
        p = self.student(ctx, [attempt('n1', 'spring-2027', 'CS 3100', status='planned'),
                               attempt('n2', 'spring-2027', 'CS 3101', 1, status='planned')])
        req = self.ood(planner.validate(p, ctx))
        self.assertEqual(req['status'], 'unsatisfied')
        self.assertEqual((req['retired'], req['replacements'][0]['review']), (['CS 3500', 'CS 3501'], 'candidate'))
        retired = [r['retired'] for r in ctx['rules'] if r.get('retired')]  # not choices with other current options
        self.assertEqual(retired, [['CS 2500', 'CS 2501'], ['CS 2510', 'CS 2511'], ['CS 3500', 'CS 3501']])
        self.write(record('ood', programs=[self.cs['id']], status='candidate', min_grade='C'))
        self.assertNotEqual(self.context()['fingerprint'], ctx['fingerprint'])
        self.registry.write_text('{')
        broken = self.context()
        self.assertTrue(any(i['id'] == 'replacements-invalid' for i in broken['issues']))
        self.assertFalse(broken['replacements'])

    def test_verified_rule_generates_current_ood_and_rechecks(self):
        self.write(record('ood', programs=[self.cs['id']]))
        ctx = self.context()
        p = self.student(ctx)
        result = planner.generate(p, ctx)
        generated = {a['code'] for a in result['proposal']['attempts'] if a['source'] == 'generated'}
        self.assertTrue({'CS 3100', 'CS 3101'} <= generated)
        self.assertFalse(generated & {'CS 2000', 'CS 2001', 'CS 2100', 'CS 2101', 'CS 2500', 'CS 3500', 'CS 3501'})
        self.assertEqual([a['id'] for a in result['proposal']['attempts'] if a['source'] == 'user'],
                         [f'h{i}' for i in range(12)])
        applied = plan(ctx, result['proposal']['attempts'], catalog_year='2024-2025',
                       terms=timeline(start=(2024, 'fall'), count=16, current=(2026, 'fall'), **self.TERMS))
        report = planner.validate(applied, ctx)
        self.assertEqual(report['errors'], [])
        req = self.ood(report)
        self.assertEqual(req['status'], 'planned')
        self.assertEqual({c['code'] for c in req['courses']}, {'CS 3100', 'CS 3101'})
        self.assertEqual({c['replacement']['id'] for c in req['courses']}, {'ood'})


if __name__ == '__main__':
    unittest.main()
