"""Read complete archived requirement snapshots without replacing live browsing data."""

import functools
import json
from pathlib import Path
import re

from json_scrapers.concentration_scraper import build_catalog, read_requirements
from json_scrapers.requirement_courses import major_sections
from json_scrapers.requirements_scraper import canonical_reference


def data_root(db_file):
    return Path(db_file).resolve().parent / 'data'


def editions(db_file):
    root = data_root(db_file) / 'catalogs'
    return sorted((p.parent.name for p in root.glob('*/requirements_catalog.json')
                   if re.fullmatch(r'\d{4}-\d{4}', p.parent.name)), reverse=True)


@functools.lru_cache(maxsize=5)
def _load(root, year, stamp):
    directory = Path(root) / 'catalogs' / year
    manifest, records = read_requirements(directory)
    catalog = build_catalog(records, year, manifest['generation'])
    courses = {}
    for path in sorted((directory / 'courses').glob('*.json')):
        data = json.loads(path.read_text())
        if isinstance(data.get('courses'), dict):
            data = data['courses']  # tolerate an older import wrapper
        for course in data['courses']:
            courses[f'{path.stem.upper()} {course["number"]}'] = {**course,
                'credits': course['credits']['max'] if isinstance(course['credits'], dict) else course['credits']}
    return {'manifest': manifest, 'records': {r['document_id']: r for r in records},
            'programs': catalog['programs'], 'courses': courses}


def load(db_file, year):
    if not isinstance(year, str) or not re.fullmatch(r'\d{4}-\d{4}', year):
        return None
    root = data_root(db_file)
    manifest = root / 'catalogs' / year / 'requirements_catalog.json'
    if not manifest.exists():
        return None
    return _load(str(root), year, manifest.stat().st_mtime_ns)


def program_data(conn, db_file, program, year):
    data = load(db_file, year)
    if not data:
        return None
    row = conn.execute('SELECT source_url FROM program_requirements WHERE program_id = ?', (program['id'],)).fetchone()
    source = canonical_reference(row[0]) if row else None
    matches = [p for p in data['programs'] if source and canonical_reference(p['source_url']) == source]
    if not matches:
        # Exact name, degree, and campus only. Never infer changed or combined majors.
        matches = [p for p in data['programs'] if p['major_name'] == program['major_name']
                   and p['degree'] == program['degree'] and (p['campus'] or 'Boston') == (program['campus'] or 'Boston')]
    if len(matches) != 1:
        return None
    archived = matches[0]
    record = data['records'][archived['program_id']]
    return {'catalog_year': year, 'source_url': record['source_url'], 'groups': archived['groups'],
            'sections': major_sections(record, archived),
            'linked': [l['document_id'] for l in record.get('linked_requirements', []) if l['kind'] == 'shared'],
            'documents': {k: v for k, v in data['records'].items() if v['kind'] == 'shared'},
            'courses': data['courses'], 'generation': data['manifest']['generation']}


def available(conn, db_file, program):
    return [year for year in editions(db_file) if program_data(conn, db_file, program, year)]
