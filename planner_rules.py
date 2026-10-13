"""Executable degree rules compiled from catalog requirement rows.

Only unambiguous structure becomes a rule: required rows, "or" alternatives,
"complete N of the following" lists, credit pools with subject/level filters,
total-credit thresholds, and NUpath competencies. Everything else (prose,
notes, approvals, GPA rules) becomes an explicit review item carrying its
original text. Unknown is a third result next to satisfied/unsatisfied.

A reviewed profile records that a person checked one source document's
interpretation. Profiles are keyed by the document's content fingerprint, so
any catalog change silently invalidates the review instead of the rules.
"""

import hashlib
import json
import re

GRADES = ['F', 'D-', 'D', 'D+', 'C-', 'C', 'C+', 'B-', 'B', 'B+', 'A-', 'A']
PASSING = set(GRADES[1:]) | {'S', 'P'}

# NUpath user codes -> course attribute. The first eight share the overlap and transfer limits.
NUPATH = {
    'ND': ('NUpath Natural/Designed World', 'Engaging with the Natural and Designed World'),
    'EI': ('NUpath Creative Express/Innov', 'Exploring Creative Expression and Innovation'),
    'IC': ('NUpath Interpreting Culture', 'Interpreting Culture'),
    'FQ': ('NUpath Formal/Quant Reasoning', 'Conducting Formal and Quantitative Reasoning'),
    'SI': ('NUpath Societies/Institutions', 'Understanding Societies and Institutions'),
    'AD': ('NUpath Analyzing/Using Data', 'Analyzing and Using Data'),
    'DD': ('NUpath Difference/Diversity', 'Engaging Differences and Diversity'),
    'ER': ('NUpath Ethical Reasoning', 'Employing Ethical Reasoning'),
    'WI': ('NUpath Writing Intensive', 'Writing-intensive courses in the major'),
    'CE': ('NUpath Capstone Experience', 'Demonstrating Thought and Action in a Capstone'),
    'EX': ('NUpath Integration Experience', 'Integrating Knowledge and Skills Through Experience'),
}
LIMITED = ('ND', 'EI', 'IC', 'FQ', 'SI', 'AD', 'DD', 'ER')
GEN_ED = 'general-education-requirements-106142af'
UNIVERSITYWIDE = 'university-wide-requirements-8435f4fd'

# Text that is structure, a pointer to a linked shared document, or a claim
# about coverage rather than a constraint.
GENERIC_TEXT = re.compile(
    r'^(Complete all courses listed below unless otherwise indicated|All undergraduate students are required to '
    r'complete the (Universitywide|NUpath) Requirements|The following NUPath Requirements are met by the major)', re.I)
INFORMATIONAL_SECTIONS = {'NUpath Requirements Satisfied'}

# Reviewed interpretations. Keys are document keys (program id, concentration id,
# or shared document id); "fingerprint" pins the exact source content reviewed.
# "texts" maps each source note/instruction to why it adds no unmodeled constraint.
REVIEWS = {
    'bscs-2bc732ab': {
        'fingerprint': '85dc13819998550a',
        'reviewed_on': '2026-10-13',
        'texts': {
            'All students can take a self-assessment to attempt to place out of CS 2000 and CS 2001 . Students who '
            'place out of CS 2000 and CS 2001 will instead substitute 4-5 semester hours of CS, CY, or DS coursework '
            'at the 3000 level or higher not otherwise required in the degree.':
                'CS 2000/2001 stay required; a placement out must be recorded as an approved substitution.',
            'Students should plan to take a NUpath capstone using designated courses in either a concentration, '
            'computer science electives, or as a general elective.':
                'Checked by the NUpath capstone (CE) rule.',
            'With advisor approval, directed study, research, project study, and appropriate graduate-level courses '
            'may also be taken as upper-division electives.':
                'Approval-only extension; never used automatically.',
        },
    },
    # BSCS Artificial Intelligence concentration: two required courses plus two of ten.
    'b9ea29663ab2c6cc': {'fingerprint': 'efe23749f6e441db', 'reviewed_on': '2026-10-13', 'texts': {}},
    GEN_ED: {'fingerprint': '86a65bb1ac93f4b4', 'reviewed_on': '2026-10-13'},
    UNIVERSITYWIDE: {'fingerprint': 'ec1dc124f24bfede', 'reviewed_on': '2026-10-13'},
}
# Concentration group policies reviewed alongside their program (keyed by policy text fingerprint).
REVIEWED_POLICIES = {
    '18f7d878eb23e904': 'One concentration is required (enforced at setup); the CS 4991 substitution needs college '
                        'approval and is never used automatically; missing prerequisites and NUpath courses are '
                        'planned as electives.',
}


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:16]


def grade_meets(grade, minimum) -> bool | None:
    """True/False when both grades are on the letter scale; None when it can't be decided."""
    if minimum is None:
        return True
    if grade in GRADES and minimum in GRADES:
        return GRADES.index(grade) >= GRADES.index(minimum)
    return None


def in_pool(code: str, rule: dict) -> bool:
    """Shared eligibility for credit pools: explicit codes, or subject/level filters minus exclusions."""
    if rule.get('any') or code in rule['courses']:
        return True
    subject, _, number = code.partition(' ')
    return any(subject == f['subject'] and f['minimum_number'] <= number <= f.get('maximum_number', '9999')
               and code not in f.get('excluded_courses', []) for f in rule['filters'])


def _bundles(row):
    """A course row as alternative bundles: each bundle is courses taken together (lecture + lab)."""
    node = row.get('expression')
    if not node:
        return None
    if node['kind'] == 'course':
        return [[node['course']]]
    if node['kind'] == 'all_of':
        return [[c['course'] for c in node['children']]]
    return [[c['course']] if c['kind'] == 'course' else [g['course'] for g in c['children']] for c in node['children']]


def compile_document(key, url, sections, review=None, skip_sections=()):
    """Compile one source document's sections. Returns (rules, issues, flags)."""
    reviewed = review is not None
    state = 'reviewed' if reviewed else 'extracted'
    texts = (review or {}).get('texts', {})
    rules, issues, flags = [], [], set()

    def issue(rid, text, section):
        if text in texts:
            return  # reviewed as informational
        issues.append({'id': rid, 'text': text, 'section': section, 'source_url': url})

    for si, section in enumerate(sections):
        title = section['title']
        if title in skip_sections:
            continue
        for ei, entry in enumerate(section['entries']):
            rid = f'{key}#{si}.{ei}'
            if entry['kind'] != 'course_table':
                text = entry.get('text', '').strip()
                if not text or GENERIC_TEXT.match(text):
                    continue
                if m := re.fullmatch(r'(\d+) total semester hours required', text):
                    rules.append({'id': rid, 'kind': 'total_credits', 'title': 'Total semester hours',
                                  'min_credits': float(m[1]), 'text': text, 'section': title,
                                  'source_url': url, 'review': state})
                elif re.search(r'Integrating Knowledge and Skills Through Experience is satisfied through co-op', text):
                    flags.add('ex_by_coop')
                elif title not in INFORMATIONAL_SECTIONS:
                    issue(rid, text, title)
                continue
            area, current = title, None  # current: open choose/credits rule, or 'uncertain'

            def add(rule):
                rule.update(section=title, area=area, source_url=url, review=state)
                rules.append(rule)
                return rule

            rows = entry['rows']
            index = 0
            while index < len(rows):
                row = rows[index]
                rrid = f'{rid}.{row["index"]}'
                kind = row['kind']
                if kind == 'header':
                    area, current = row['text'], None
                elif kind == 'instruction':
                    c = row.get('constraints') or {}
                    need = next((c[k] for k in ('selection_count', 'course_count', 'minimum_selections', 'minimum_courses')
                                 if k in c), None)
                    if 'minimum_credits' in c:
                        current = add({'id': rrid, 'kind': 'credits', 'title': area, 'text': row['text'],
                                       'min_credits': c['minimum_credits'], 'min_count': need or 0,
                                       'courses': [], 'filters': [],
                                       'any': bool(re.search(r'general electives?', row['text'], re.I))})
                    elif need:
                        current = add({'id': rrid, 'kind': 'choose', 'title': area, 'text': row['text'],
                                       'need': need, 'options': []})
                    else:
                        issue(rrid, row['text'], title)
                        if row['text'] not in texts:
                            current = 'uncertain'  # following rows' role is unknown until reviewed
                elif kind == 'note':
                    issue(rrid, row['text'], title)
                elif kind == 'elective_filter':
                    if isinstance(current, dict) and current['kind'] == 'credits' and row.get('course_filter'):
                        current['filters'].append(row['course_filter'])
                        current['any'] = False
                    else:
                        issue(rrid, row['text'], title)
                elif kind == 'course':
                    option = _bundles(row)
                    group = row.get('alternative_group')
                    text = row['text']
                    while option is not None and group is not None and index + 1 < len(rows) \
                            and rows[index + 1].get('alternative_group') == group:
                        index += 1
                        more = _bundles(rows[index])
                        option = None if more is None else option + more
                        text += ' ' + rows[index]['text']
                    if option is None or current == 'uncertain':
                        issue(rrid, text, title)
                    elif current is None:
                        add({'id': rrid, 'kind': 'choose', 'title': area, 'text': text, 'need': 1, 'options': [option]})
                    elif current['kind'] == 'choose':
                        current['options'].append(option)
                        current['text'] += '\n' + text
                    else:
                        current['courses'].extend(code for bundle in option for code in bundle)
                        current['any'] = False
                index += 1
    for rule in rules:
        if rule['kind'] == 'credits' and not rule['any'] and not rule['courses'] and not rule['filters']:
            rule['kind'] = 'review'  # a pool with nothing eligible can't be evaluated
            issues.append({'id': rule['id'], 'text': rule['text'], 'section': rule['section'], 'source_url': url})
    return [r for r in rules if r['kind'] != 'review'], issues, flags


def shared_rules(document, flags, program_rules):
    """NUpath and universitywide rules from their shared source documents."""
    review = REVIEWS.get(document['document_id'])
    current = review and review['fingerprint'] == fingerprint(document['sections'])
    state = 'reviewed' if current else 'extracted'
    url = document['source_url']
    base = {'source_url': url, 'section': document['title'], 'review': state}
    rules, issues = [], []
    if not current:
        issues.append({'id': document['document_id'], 'source_url': url, 'section': document['title'],
                       'text': f"{document['title']} changed since its rules were reviewed; check them against the source."})
    if document['document_id'] == GEN_ED:
        for code, (attribute, title) in NUPATH.items():
            rule = {**base, 'id': f'nupath:{code}', 'kind': 'nupath', 'code': code, 'attribute': attribute,
                    'title': f'NUpath {code}: {title}', 'need': 2 if code == 'WI' else 1,
                    'limited': code in LIMITED, 'transfer_ok': code in LIMITED, 'text': title}
            if code == 'EX' and 'ex_by_coop' in flags:
                rule['coop_ok'] = True
            rules.append(rule)
        # Writing rules live in program rows; the shared document adds grade and timing conditions.
        for label, pattern in (('First-year writing', r'First-Year Writing|College Writing'),
                               ('Advanced Writing in the Disciplines', r'Advanced Writing')):
            matched = [r for r in program_rules if r['kind'] == 'choose' and re.search(pattern, r.get('area', ''))]
            for rule in matched:
                rule['min_grade'] = 'C'
                if label.startswith('Advanced'):
                    rule.update(awd=True, transfer_ok=False)
            if not matched:
                issues.append({'id': f'nupath:{label}', 'source_url': url, 'section': document['title'],
                               'text': f'{label} is not listed in this program; confirm how it is met.'})
        issues.append({'id': 'nupath:in-major', 'source_url': url, 'section': document['title'],
                       'text': 'Writing-intensive and capstone courses must be in the major; this check counts any '
                               'course carrying the attribute.'})
    elif document['document_id'] == UNIVERSITYWIDE:
        rules.append({**base, 'id': 'uw:total', 'kind': 'total_credits', 'title': 'Universitywide minimum semester hours',
                      'min_credits': 128.0, 'text': 'Minimum 128 total semester hours required'})
        rules.append({**base, 'id': 'uw:residency', 'kind': 'residency', 'title': 'Northeastern semester hours',
                      'min_credits': 64.0, 'text': 'Students must earn a minimum of 64 Northeastern University semester hours'})
        rules.append({**base, 'id': 'uw:experiential', 'kind': 'experience', 'title': 'Experiential learning requirement',
                      'text': 'Complete the experiential learning graduation requirement (co-op, internship, '
                              'clinical placement, or an approved industry-partner course).'})
        issues.append({'id': 'uw:gpa', 'source_url': url, 'section': document['title'],
                       'text': 'Minimum 2.000 GPA required. GPA is not evaluated here.'})
    return rules, issues


def compile_program(program_id, requirement, groups, selected, documents):
    """Compose major rules, selected concentration blocks, and linked shared documents.

    requirement: program_requirements row (sections, source_url, linked ids)
    groups: concentration groups; selected: chosen option dicts; documents: shared docs by id.
    """
    sources, rules, issues, flags = [], [], [], set()

    def compile_source(key, title, url, sections, skip=()):
        review = REVIEWS.get(key)
        stamp = fingerprint(sections)
        review = review if review and review['fingerprint'] == stamp else None
        found, notes, more = compile_document(key, url, sections, review, skip)
        sources.append({'key': key, 'title': title, 'source_url': url, 'fingerprint': stamp,
                        'review': 'reviewed' if review else 'extracted',
                        'reviewed_on': review['reviewed_on'] if review else None})
        rules.extend(found)
        issues.extend(notes)
        flags.update(more)

    selectable = {g['title'] for g in groups if not g['fixed']}
    compile_source(program_id, 'Major requirements', requirement['source_url'], requirement['sections'], selectable)
    chosen = {o['id'] for o in selected}
    for group in groups:
        mine = [o for o in group['options'] if o['id'] in chosen]
        if group['fixed'] or not mine:
            continue
        if group['policy']['text'] and fingerprint(group['policy']['text']) not in REVIEWED_POLICIES:
            issues.append({'id': f"policy:{group['id']}", 'text': group['policy']['text'],
                           'section': group['title'], 'source_url': mine[0]['source_url']})
        for option in mine:
            compile_source(option['id'], option['name'], option['source_url'], option['sections'])
    for document_id in requirement.get('linked', []):
        document = documents.get(document_id)
        if document:
            found, notes = shared_rules(document, flags, rules)
            sources.append({'key': document_id, 'title': document['title'], 'source_url': document['source_url'],
                            'fingerprint': fingerprint(document['sections']),
                            'review': 'reviewed' if all(r['review'] == 'reviewed' for r in found) else 'extracted'})
            rules.extend(found)
            issues.extend(notes)
    reviewed = all(s['review'] == 'reviewed' for s in sources)
    return {'rules': rules, 'issues': issues, 'sources': sources,
            'capability': 'reviewed' if reviewed else 'extracted'}
