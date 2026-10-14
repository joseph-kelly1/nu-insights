"""Collect versioned AP/IB equivalencies from Northeastern's published charts.

Run: python json_scrapers/exam_scraper.py
Downloads public PDFs into memory. Publishes only after every row is parsed;
keeps old snapshots so saved plans retain their original policy evidence.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import tempfile
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import pdfplumber
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LANDING = 'https://admissions.northeastern.edu/application-information/transferring-credit/'
ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = 'NUInsightsExamScraper/1.0'
ATTRS = {'ND', 'EI', 'IC', 'FQ', 'SI', 'AD', 'DD', 'ER', 'WF'}


class ExamParseError(ValueError):
    pass


def clean(text):
    return re.sub(r'\s+', ' ', text or '').strip()


def exam_id(kind, name):
    return kind + ':' + re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')


def course_codes(text):
    """Expand explicit shorthand like BIOL1111/1112 and ENVR 1101 & 1990."""
    found, subject = [], None
    for match in re.finditer(r'\b(?:([A-Z]{2,5})\s*)?(\d{4})\b', text):
        subject = match[1] or subject
        if not subject:
            raise ExamParseError(f'Course number has no subject: {text}')
        code = f'{subject} {match[2]}'
        if code not in found:
            found.append(code)
    return found


def subjects(kind, name):
    name = {'United States Government and': 'United States Government and Politics',
            'English A: Language andLiterature': 'English A: Language and Literature',
            'Art Drawing': 'Drawing', 'Capstone: Research': 'Research', 'Capstone: Seminar': 'Seminar'}.get(name, name)
    if kind == 'ap' and name == 'Calculus AB (or AB Subscore)':
        return [['Calculus AB'], ['Calculus BC: AB Subscore']]
    if kind == 'ap' and name.startswith('English Literature') and ' AND ' in name:
        return [['English Literature and Composition', 'English Language and Composition']]
    if kind == 'ap' and name.startswith('Spanish Language') and 'Spanish Literature' in name:
        return [['Spanish Language and Culture', 'Spanish Literature and Culture']]
    # Language A alternatives are distinct exams with the same award.
    if kind == 'ib' and re.search(r'-?\s*OR\s*-?', name):
        return [[clean(n)] for n in re.split(r'-?\s*OR\s*-?', name) if clean(n)]
    return [[name]]


def parse_row(kind, row, page, catalog):
    name, codes, title, attrs, hours = map(clean, row)
    if not name:
        raise ExamParseError(f'Empty exam on page {page}')
    warnings = []
    attributes = set(re.findall(r'\(([A-Z]{2})\)', attrs)) & ATTRS
    if 'Difference/Diversity' in attrs:
        attributes.add('DD')
    if 'Analyzing/Using Data' in attrs:
        attributes.add('AD')
    if 'Natural/Designed World' in attrs:
        attributes.add('ND')
    if '(FD)' in attrs and 'Formal/Quant' in attrs:
        attributes.add('FQ')
        warnings.append('Chart labels Formal/Quant Reasoning as FD; normalized to catalog code FQ.')
    denied = 'non-transferable' in codes.lower()
    total = 0 if denied else float(re.fullmatch(r'(\d+(?:\.\d+)?)\s*SH', hours)[1]) if re.fullmatch(r'(\d+(?:\.\d+)?)\s*SH', hours) else None
    if total is None:
        raise ExamParseError(f'Unrecognized credit total: {row}')
    awards = []
    for code in course_codes(codes) if not denied else []:
        explicit = re.search(re.escape(code).replace(r'\ ', r'\s*') + r'\s*\((\d+(?:\.\d+)?)SH\)', codes)
        known = catalog.get(code)
        credits = float(explicit[1]) if explicit else known['credits'] if known else None
        awards.append({'code': code, 'title': known['title'] if known else title or f'{code.split()[0]} elective',
                       'credits': credits, 'nupath': sorted(attributes)})
    unknown = [a for a in awards if a['credits'] is None]
    if len(unknown) == 1:
        unknown[0]['credits'] = total - sum(a['credits'] for a in awards if a['credits'] is not None)
    if not denied and (not awards or any(a['credits'] is None or a['credits'] < 0 for a in awards)
                       or abs(sum(a['credits'] for a in awards) - total) > .001):
        raise ExamParseError(f'Cannot safely split course credits: {row}')
    return [{'requirements': [{'exam_id': exam_id(kind, n), 'name': n,
                              'min_score': 4 if kind == 'ap' else 5, 'level': None if kind == 'ap' else 'HL'} for n in names],
             'awards': awards, 'total_credits': total, 'eligible': not denied,
             'page': page, 'raw_row': row, 'notes': warnings}
            for names in subjects(kind, name)]


def parse_pdf(kind, content, catalog):
    rules = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        text = '\n'.join(p.extract_text() or '' for p in pdf.pages)
        year = re.search(r'(?:Advanced Placement|International Baccalaureate)\s+(\d{4}-\d{4})', text)
        if not year:
            raise ExamParseError('Missing policy year')
        expected = '4 or 5' if kind == 'ap' else '5, 6, or 7'
        if expected not in text or '32 semester hours' not in text or (kind == 'ib' and 'Higher Level' not in text):
            raise ExamParseError('Score policy changed; review before publishing')
        for i, page in enumerate(pdf.pages):
            for table in page.extract_tables():
                for raw in table:
                    if len(raw) != 5 or raw[0] in ('AP Exam', 'IB Exam', 'Language') or all(v is None for v in raw[1:]):
                        continue
                    if kind == 'ib' and i >= 2:
                        # Language table uses merged language cells and has no NUpath column.
                        raw = [raw[1], raw[2], raw[3], 'N/A', raw[4]]
                    if not clean(raw[0]) or clean(raw[0]) == 'IB Exam':
                        continue
                    rules.extend(parse_row(kind, raw, i + 1, catalog))
    if len(rules) < (35 if kind == 'ap' else 50):
        raise ExamParseError(f'Unexpectedly few {kind.upper()} rules: {len(rules)}')
    return year[1], rules


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', dir=path.parent, delete=False) as stream:
        json.dump(data, stream, indent=2, ensure_ascii=False)
        stream.write('\n')
        name = stream.name
    Path(name).replace(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'data' / 'exams')
    parser.add_argument('--courses-dir', type=Path, default=ROOT / 'data' / 'courses')
    args = parser.parse_args(argv)
    catalog = {}
    for path in sorted(args.courses_dir.glob('*.json')):
        data = json.loads(path.read_text())
        for course in data['courses']:
            catalog[f'{path.stem.upper()} {course["number"]}'] = course
    with requests.Session() as session:
        session.headers['User-Agent'] = USER_AGENT
        session.mount('https://', HTTPAdapter(max_retries=Retry(total=3, backoff_factor=1,
                      status_forcelist=[429, 500, 502, 503, 504], respect_retry_after_header=True)))
        robots = RobotFileParser()
        robots_url = urljoin(LANDING, '/robots.txt')
        response = session.get(robots_url, timeout=(10, 45))
        response.raise_for_status()
        robots.parse(response.text.splitlines())

        def fetch(url):
            if urlparse(url).netloc != urlparse(LANDING).netloc or not robots.can_fetch(USER_AGENT, url):
                raise ExamParseError(f'Source not allowed: {url}')
            response = session.get(url, timeout=(10, 45), allow_redirects=False)
            response.raise_for_status()
            if response.is_redirect:
                raise ExamParseError(f'Source moved; rediscover URL: {url}')
            return response

        soup = BeautifulSoup(fetch(LANDING).text, 'html.parser')
        sources, rules, years = [], [], set()
        for kind, label in [('ap', 'Advanced Placement'), ('ib', 'International Baccalaureate')]:
            link = next((a for a in soup.select('a[href]') if label in a.get_text() and '.pdf' in a['href']), None)
            if link is None:
                raise ExamParseError(f'Missing {kind.upper()} chart link')
            url = urljoin(LANDING, link['href'])
            url = urlparse(url)._replace(scheme='https').geturl()
            content = fetch(url).content
            year, parsed = parse_pdf(kind, content, catalog)
            years.add(year)
            digest = hashlib.sha256(content).hexdigest()
            sources.append({'kind': kind, 'url': url, 'sha256': digest})
            for i, rule in enumerate(parsed):
                rules.append({**rule, 'id': f'{kind}:{i}', 'kind': kind, 'source_url': url})
        if len(years) != 1:
            raise ExamParseError(f'Charts cover different years: {years}')
        year = years.pop()
        version = hashlib.sha256(json.dumps({'rules': rules, 'sources': sources}, sort_keys=True).encode()).hexdigest()[:16]
        exams = {}
        for rule in rules:
            for req in rule['requirements']:
                exams[req['exam_id']] = {'id': req['exam_id'], 'name': req['name'], 'kind': rule['kind']}
        snapshot = {'schema_version': 1, 'policy_year': year, 'version': version, 'test_credit_cap': 32,
                    'retrieved_at': datetime.now(timezone.utc).isoformat(), 'sources': sources,
                    'exams': sorted(exams.values(), key=lambda e: (e['kind'], e['name'])), 'rules': rules}
        relative = f'{year}/{version}.json'
        if not (args.output_dir / relative).exists():
            write_json(args.output_dir / relative, snapshot)
        manifest_path = args.output_dir / 'catalog.json'
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {'schema_version': 1, 'policies': []}
        policies = [p for p in manifest['policies'] if not (p['policy_year'] == year and p['version'] == version)]
        for p in policies:
            if p['policy_year'] == year:
                p['current'] = False
        policies.append({'policy_year': year, 'version': version, 'file': relative, 'current': True})
        write_json(manifest_path, {'schema_version': 1, 'policies': policies})
        print(f'Published {year}: {len(exams)} exams, {len(rules)} rules, version {version}')


if __name__ == '__main__':
    main()
