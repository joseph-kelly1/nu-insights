"""Documented course replacements for retired degree requirements.

A record says one current bundle (lecture + lab) fulfills one retired bundle in
named programs and catalog years. Only `verified` records change fulfillment;
`candidate` records are shown to the student as a lead to confirm with advising.
Nothing is inferred: no reverse, transitive, partial-bundle, or prerequisite
equivalence. A missing registry means no replacements.
"""

import functools
import hashlib
import json
import re

import catalog_editions
from planner_rules import GRADES

CODE = re.compile(r'[A-Z]{2,5} \d{2}[0-9A-Z]{2}')
YEAR = re.compile(r'\d{4}-\d{4}')
DATE = re.compile(r'\d{4}-\d{2}-\d{2}')
SESSIONS = ('spring', 'summer1', 'summer2', 'fall')  # same order as planner.SESSIONS
ORIGINS = {'nu', 'ap', 'ib', 'transfer', 'substitution'}
STATUSES = {'candidate', 'verified'}
FIELDS = {'id', 'original', 'replacement', 'direction', 'purpose', 'scope', 'effective_term', 'restrictions',
          'evidence', 'rationale', 'review'}
MAX_BUNDLE = 4


class RegistryError(ValueError):
    pass


def path(db_file):
    return catalog_editions.data_root(db_file) / 'course_replacements.json'


def load(db_file):
    """{'version', 'records'}; version is None without a registry. Raises RegistryError when invalid."""
    try:
        raw = path(db_file).read_bytes()
    except FileNotFoundError:
        return {'version': None, 'records': []}
    return _parse(raw)


@functools.lru_cache(maxsize=4)
def _parse(raw):  # keyed by file content, so an edited registry is never served stale
    digest = hashlib.sha256(raw).hexdigest()[:12]
    try:
        data = json.loads(raw)
    except ValueError:
        raise RegistryError('Course replacement registry is not valid JSON.')
    records = validate(data)
    return {'version': f"{data['registry_version']}:{digest}", 'records': records}


def validate(data):
    """Checked records sorted by ID; any malformed, unsupported, or conflicting record rejects the registry."""
    def fail(why, rid=None):
        raise RegistryError(f"Course replacement {rid + ': ' if rid else ''}{why}")

    if not (isinstance(data, dict) and data.get('schema_version') == 1 and isinstance(data.get('registry_version'), str)
            and isinstance(data.get('records'), list)):
        fail('registry needs schema_version 1, registry_version, and records.')
    seen = {}
    for r in data['records']:
        rid = r.get('id') if isinstance(r, dict) else None
        if not (isinstance(rid, str) and re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', rid)) or rid in seen:
            fail('each record needs a unique lowercase ID.')
        if set(r) - FIELDS or not {'original', 'replacement', 'direction', 'purpose', 'scope', 'effective_term',
                                   'evidence', 'review'} <= set(r):
            fail('unknown or missing fields.', rid)
        for side in ('original', 'replacement'):
            bundle = r[side]
            if not (isinstance(bundle, list) and 0 < len(bundle) <= MAX_BUNDLE and len(set(bundle)) == len(bundle)
                    and all(isinstance(c, str) and CODE.fullmatch(c) for c in bundle)):
                fail(f'{side} must list 1 to {MAX_BUNDLE} distinct course codes like "CS 3500".', rid)
        if set(r['original']) & set(r['replacement']):
            fail('original and replacement bundles overlap.', rid)
        if r['direction'] != 'replacement_fulfills_original' or r['purpose'] != 'degree_requirement':
            fail('only replacement_fulfills_original degree_requirement records are supported.', rid)
        scope = r['scope']
        if not (isinstance(scope, dict) and set(scope) == {'program_ids', 'campus', 'catalog_years'}
                and isinstance(scope['program_ids'], list) and scope['program_ids']
                and all(isinstance(p, str) and p for p in scope['program_ids'])
                and isinstance(scope['campus'], str) and scope['campus']
                and isinstance(scope['catalog_years'], list) and scope['catalog_years']
                and all(isinstance(y, str) and YEAR.fullmatch(y) for y in scope['catalog_years'])):
            fail('scope needs program_ids, campus, and catalog_years.', rid)
        term = r['effective_term']
        if not (isinstance(term, dict) and set(term) == {'year', 'session'} and isinstance(term['year'], int)
                and 1990 <= term['year'] <= 2100 and term['session'] in SESSIONS):
            fail('effective_term needs a year and session.', rid)
        limits = r.get('restrictions', {})
        if not (isinstance(limits, dict) and set(limits) <= {'origins', 'min_grade'}
                and ('origins' not in limits or (isinstance(limits['origins'], list) and limits['origins']
                                                 and set(limits['origins']) <= ORIGINS))
                and limits.get('min_grade') in [None, *GRADES]):
            fail('restrictions support only origins and min_grade.', rid)
        evidence = r['evidence']
        if not (isinstance(evidence, list) and evidence and all(
                isinstance(e, dict) and set(e) == {'url', 'retrieved_on', 'sha256'}
                and isinstance(e['url'], str) and e['url'].startswith('https://')
                and isinstance(e['retrieved_on'], str) and DATE.fullmatch(e['retrieved_on'])
                and isinstance(e['sha256'], str) and re.fullmatch(r'[0-9a-f]{64}', e['sha256']) for e in evidence)):
            fail('evidence needs https URLs with retrieval dates and content hashes.', rid)
        review = r['review']
        if not (isinstance(review, dict) and review.get('status') in STATUSES
                and isinstance(review.get('reviewed_on'), str) and DATE.fullmatch(review['reviewed_on'])
                and set(review) <= {'status', 'reviewed_on', 'gap'}
                and (review['status'] == 'verified' or isinstance(review.get('gap'), str) and review['gap'])):
            fail('review needs a status and date; a candidate also names its evidence gap.', rid)
        seen[rid] = r
    verified = [r for r in seen.values() if r['review']['status'] == 'verified']
    for i, a in enumerate(verified):
        for b in verified[i + 1:]:
            if set(a['original']) & set(b['original']) and set(a['scope']['program_ids']) & set(b['scope']['program_ids']) \
                    and set(a['scope']['catalog_years']) & set(b['scope']['catalog_years']) \
                    and a['scope']['campus'] == b['scope']['campus']:
                fail(f"conflicts with {b['id']} for the same courses and scope.", a['id'])
    return [seen[k] for k in sorted(seen)]


def resolve(registry, program, catalog_year):
    """(verified, candidate) records whose explicit scope names this program, campus, and catalog year."""
    mine = [r for r in registry['records'] if program['id'] in r['scope']['program_ids']
            and (program.get('campus') or 'Boston') == r['scope']['campus'] and catalog_year in r['scope']['catalog_years']]
    return ([r for r in mine if r['review']['status'] == 'verified'],
            [r for r in mine if r['review']['status'] == 'candidate'])


def public(record):
    """Browser summary of one record."""
    return {'id': record['id'], 'original': record['original'], 'replacement': record['replacement'],
            'review': record['review']['status'], 'source_url': record['evidence'][0]['url'],
            'effective_term': record['effective_term'], 'rationale': record.get('rationale', ''),
            **({'gap': record['review']['gap']} if record['review'].get('gap') else {})}


def expand(rules, verified, candidates):
    """Execution rules plus modeling gaps.

    A verified replacement bundle joins the SAME choice slot as its exact original
    bundle, so the requirement still counts once with its own count and grade rules.
    Source options stay on the rule for display. A slot that lists the courses
    differently, or already lists a replacement course, is reported, not guessed.
    """
    out, gaps = [], []
    for rule in rules:
        if rule['kind'] != 'choose':
            out.append(rule)
            continue
        options = [[list(b) for b in o] for o in rule['options']]
        listed = {c for o in options for b in o for c in b}
        notes, replaced_by = [], {}
        for record in [*verified, *candidates]:
            original = set(record['original'])
            exact = [o for o in options if any(set(b) == original for b in o)]
            partial = not exact and any(set(b) & original for o in options for b in o)
            if not exact and not partial:
                continue
            active = record['review']['status'] == 'verified'
            if partial or len(exact) > 1 or (active and listed & set(record['replacement'])):
                if active:
                    gaps.append({'id': f"replacement:{record['id']}:{rule['id']}", 'section': rule.get('section', ''),
                                 'source_url': record['evidence'][0]['url'],
                                 'text': f"{rule['title']}: {' + '.join(record['replacement'])} replaces "
                                         f"{' + '.join(record['original'])}, but this requirement lists the courses "
                                         'differently, so the replacement is not applied automatically.'})
                continue
            if active:
                exact[0].append(list(record['replacement']))
                listed |= set(record['replacement'])
                replaced_by.update({code: record for code in record['replacement']})
            notes.append(public(record))
        if notes:
            rule = {**rule, 'options': options, 'source_options': rule['options'], 'replacements': notes,
                    'replaced_by': replaced_by}
        out.append(rule)
    return out, gaps
