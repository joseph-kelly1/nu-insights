"""Deterministic AP/IB lookup. Saved exam inputs pin a published policy snapshot."""

import functools
import json
from pathlib import Path
import re

from .paths import DATA_DIR as CATALOG_DIR

DATA_DIR = CATALOG_DIR / 'exams'


class ExamCreditError(ValueError):
    pass


@functools.lru_cache(maxsize=16)
def _read(path, stamp):
    return json.loads(Path(path).read_text())


def read(path):
    try:
        return _read(str(path), path.stat().st_mtime_ns)
    except (OSError, ValueError) as error:
        raise ExamCreditError('AP/IB policies are unavailable. Try again after the dataset is refreshed.') from error


def catalog(year=None, version=None):
    manifest = read(DATA_DIR / 'catalog.json')
    policies = [{**{k: p[k] for k in ('policy_year', 'version')},
                 'exams': snapshot(p['policy_year'], p['version'])['exams']}
                for p in manifest['policies'] if p['current'] and (not year or p['policy_year'] != year)]
    if year or version:
        saved = snapshot(year, version)
        policies.append({k: saved[k] for k in ('policy_year', 'version', 'exams')})
    return {'policies': policies}


def snapshot(year, version):
    if not isinstance(year, str) or not re.fullmatch(r'\d{4}-\d{4}', year) or not isinstance(version, str) or not re.fullmatch(r'[a-f0-9]{16}', version):
        raise ExamCreditError('Choose a published AP/IB policy year.')
    manifest = read(DATA_DIR / 'catalog.json')
    policy = next((p for p in manifest['policies'] if p['policy_year'] == year and p['version'] == version), None)
    if not policy:
        raise ExamCreditError('This AP/IB policy version is unavailable. Choose a published policy year again.')
    return read(DATA_DIR / policy['file'])


def resolve(records):
    if not isinstance(records, list) or len(records) > 50:
        raise ExamCreditError('A plan can hold at most 50 AP/IB exams.')
    normalized, ids, selections = [], set(), {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get('id'), str) or not re.fullmatch(r'[A-Za-z0-9:_-]{1,80}', record['id']) or record['id'] in ids:
            raise ExamCreditError('Each AP/IB exam needs a unique ID.')
        ids.add(record['id'])
        data = snapshot(record.get('policy_year'), record.get('version'))
        exam = next((e for e in data['exams'] if e['id'] == record.get('exam_id')), None)
        if exam is None:
            raise ExamCreditError('Choose an exam from the selected policy.')
        score = record.get('score')
        if type(score) is not int or not 1 <= score <= (5 if exam['kind'] == 'ap' else 7):
            raise ExamCreditError('AP scores must be 1–5; IB scores must be 1–7.')
        level = record.get('level') if exam['kind'] == 'ib' else None
        state = record.get('state')
        if (exam['kind'] == 'ib' and level not in ('HL', 'SL')) or state not in ('estimated', 'awarded'):
            raise ExamCreditError('Choose an IB level and whether exam credit is estimated or awarded.')
        # One cohort per plan; don't combine credits from conflicting annual policies.
        selections.setdefault((data['policy_year'], data['version']), {})
        group = selections[(data['policy_year'], data['version'])]
        if exam['id'] in group:
            raise ExamCreditError('This exam is already recorded. Edit its score or credit state instead.')
        item = {k: record[k] for k in ('id', 'exam_id', 'score', 'policy_year', 'version', 'state')}
        item.update(kind=exam['kind'], name=exam['name'], level=level)
        normalized.append(item)
        group[exam['id']] = item
    if len(selections) > 1:
        raise ExamCreditError('Use one admission policy year and version for all AP/IB exams in this plan.')
    awards, preview = {}, {}
    for (year, version), group in selections.items():
        data = snapshot(year, version)
        for state, target in [('awarded', awards), ('preview', preview)]:
            for rule in data['rules']:
                selected = [group.get(r['exam_id']) for r in rule['requirements']]
                if not rule['eligible'] or any(s is None or s['score'] < r['min_score'] or s['level'] != r['level']
                                             or (state == 'awarded' and s['state'] != 'awarded')
                                             for s, r in zip(selected, rule['requirements'])):
                    continue
                for award in rule['awards']:
                    code = award['code']
                    existing = target.get(code)
                    if existing:
                        existing['credits'] = max(existing['credits'], award['credits'])
                        existing['nupath'] = sorted(set(existing['nupath']) | set(award['nupath']))
                        existing['exam_ids'] = sorted(set(existing['exam_ids']) | {s['id'] for s in selected})
                    else:
                        target[code] = {**award, 'exam_ids': [s['id'] for s in selected],
                                        'source_url': rule['source_url'], 'page': rule['page']}
    for item in normalized:
        item['equivalents'] = [a for a in preview.values() if item['id'] in a['exam_ids']]
        item['source_url'] = next(s['url'] for s in snapshot(item['policy_year'], item['version'])['sources'] if s['kind'] == item['kind'])
        item['message'] = '' if item['equivalents'] else ('IB Standard Level exams do not earn credit.' if item['level'] == 'SL'
                              else 'No credit under this policy for the selected exam and score, or another qualifying exam is required.')
        if item['state'] == 'awarded' and not any(item['id'] in a['exam_ids'] for a in awards.values()):
            raise ExamCreditError(f'{item["name"]}: no qualifying award. Save it as an estimate or check the score and level.')
    total = sum(a['credits'] for a in awards.values())
    if total > 32:
        raise ExamCreditError(f'AP/IB awards total {total:g} credits. Choose at most 32 credits to count toward your degree.')
    return {'exams': normalized, 'awards': list(awards.values()), 'awarded_credits': total,
            'estimated_credits': sum(a['credits'] for a in preview.values()), 'notes': [], 'test_credit_cap': 32}
