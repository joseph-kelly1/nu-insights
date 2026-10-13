"""Scrape published undergraduate sample plans from Northeastern's catalog.

Defaults to the edition currently published by the catalog. Missing plans are
reported explicitly; requirements are never converted into invented schedules.
Run: python json_scrapers/plan_scraper.py
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from urllib.parse import urldefrag, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = 'https://catalog.northeastern.edu/'
DATA_DIR = Path(__file__).resolve().parents[1] / 'data'
DEGREE = re.compile(r',\s*(B[A-Za-z]+)(?=\s*(?:\(|$|—))')
YEAR = re.compile(r'^\d{4}-\d{4}$')


class PlanParseError(ValueError):
    """Published plan markup could not be parsed safely."""


def clean(value):
    return re.sub(r'\s+', ' ', value.replace('\xa0', ' ')).strip()


def edition(soup):
    label = soup.select_one('#edition')
    match = re.search(r'\b(\d{4}-\d{4})\b', label.get_text() if label else '')
    if not match:
        raise PlanParseError('Catalog edition is missing')
    return match.group(1)


def discover_programs(soup, root):
    index = soup.select_one('#atozindex')
    if index is None:
        raise PlanParseError('Catalog A-Z index is missing')
    prefix = urlparse(urljoin(root, 'undergraduate/')).path
    programs = {}
    for link in index.select('a[href]'):
        title = clean(link.get_text(' ', strip=True))
        url = urldefrag(urljoin(root, link['href']))[0]
        parsed = urlparse(url)
        if parsed.netloc != urlparse(root).netloc or not parsed.path.startswith(prefix):
            continue
        if not DEGREE.search(title) or parsed.query:
            continue
        programs[url] = {'title': title, 'source_url': url}
    if not programs:
        raise PlanParseError('No undergraduate bachelor programs discovered')
    return [programs[url] for url in sorted(programs)]


def course_codes(text):
    """Recognize full codes and abbreviated alternatives such as ECON 1115 or 1116."""
    result = []
    subject = None
    previous_end = 0
    for match in re.finditer(r'\b(?:([A-Z]{2,5})\s+)?(\d{4})\b', text):
        prefix, number = match.groups()
        if prefix:
            subject = prefix
        elif subject is None or not re.fullmatch(r'[\s,]*(?:(?:and|or)[\s,]*)?', text[previous_end:match.start()]):
            subject = None
        if subject:
            code = f'{subject} {number}'
            if code not in result:
                result.append(code)
        previous_end = match.end()
    return result


def expanded_cells(row):
    cells = []
    for cell in row.find_all(['td', 'th'], recursive=False):
        if int(cell.get('rowspan', 1)) != 1:
            raise PlanParseError('Unsupported rowspan in plan grid')
        span = int(cell.get('colspan', 1))
        cells.extend([cell] + [None] * (span - 1))
    return cells


def cell_text(cell):
    return clean(cell.get_text(' ', strip=True)) if cell else ''


def parse_grid(table):
    semesters = []
    current = []
    groups = {}
    year = None
    width = None
    for row in table.find_all('tr'):
        classes = row.get('class', [])
        if 'plangridyear' in classes:
            match = re.fullmatch(r'Year\s+(\d+)', clean(row.get_text(' ', strip=True)), re.I)
            if not match:
                raise PlanParseError('Unrecognized year row')
            year = int(match.group(1))
            current = []
            groups = {}
            continue
        if 'plangridsum' in classes or 'plangridtotal' in classes:
            continue
        cells = expanded_cells(row)
        if 'plangridterm' in classes:
            if year is None or len(cells) % 2:
                raise PlanParseError('Invalid semester header')
            width = len(cells)
            current = []
            groups = {}
            for offset in range(0, width, 2):
                term = cell_text(cells[offset])
                semester = None
                if term:
                    if cell_text(cells[offset + 1]).lower() not in ('hours', 'credits'):
                        raise PlanParseError('Missing semester credits column')
                    semester = {'year': year, 'term': term, 'courses': [], 'notes': [], 'entries': []}
                    semesters.append(semester)
                current.append(semester)
            continue
        if not cells:
            continue
        if not current or len(cells) != width:
            raise PlanParseError('Plan row does not match semester columns')
        for position, semester in enumerate(current):
            cell = cells[position * 2]
            text = cell_text(cell)
            if not text:
                continue
            if semester is None:
                raise PlanParseError('Plan entry has no semester header')
            credits = cell_text(cells[position * 2 + 1])
            codes = course_codes(text)
            indented = bool(cell.select('[style*="margin-left"], .indent'))
            if indented and position in groups:
                groups[position]['options'].append({'text': text, 'courses': codes, 'credits': credits})
                continue
            groups.pop(position, None)
            is_choice = bool(re.search(r'\b(or|select|choose|take (?:one|two|three|\d+))\b', text, re.I))
            kind = 'choice' if is_choice or indented else 'course' if codes else 'note'
            if re.fullmatch(r'Co[-– ]?op(?:\s+.*)?', text, re.I):
                kind = 'coop'
                semester['is_coop'] = True
            entry = {'text': text, 'credits': credits, 'kind': kind, 'courses': codes}
            if kind == 'choice':
                entry['options'] = []
                groups[position] = entry
            semester['entries'].append(entry)
            if kind == 'course':
                semester['courses'].extend(code for code in codes if code not in semester['courses'])
    semesters = [semester for semester in semesters if semester['entries']]
    if not semesters:
        raise PlanParseError('Published plan grid has no entries')
    for semester in semesters:
        for entry in semester['entries']:
            if entry['kind'] not in ('course', 'coop'):
                note = entry['text']
                if entry.get('options'):
                    note += ' ' + '; '.join(option['text'] for option in entry['options'])
                semester['notes'].append(note)
    return semesters


def parse_program(html, url, catalog_year):
    soup = BeautifulSoup(html, 'html.parser')
    if edition(soup) != catalog_year:
        raise PlanParseError('Program page belongs to a different catalog edition')
    heading = soup.select_one('h1')
    title = clean(heading.get_text(' ', strip=True)) if heading else ''
    degree = DEGREE.search(title)
    if not degree:
        raise PlanParseError('Page is not an undergraduate bachelor program')
    campus_match = re.search(r'\(([^()]+)\)$', title)
    crumbs = soup.select('#breadcrumb li')
    college = clean(crumbs[2].get_text(' ', strip=True)).rstrip('›').strip() if len(crumbs) > 2 else ''
    program_id = urlparse(url).path.rstrip('/').split('/')[-1][:100] + '-' + hashlib.sha256(urlparse(url).path.encode()).hexdigest()[:8]
    record = {
        'major': program_id, 'major_name': title[:degree.start()].strip(),
        'degree': degree.group(1), 'campus': campus_match.group(1) if campus_match else '',
        'college': college, 'catalog_year': catalog_year, 'source_url': url, 'plans': [],
    }
    container = soup.select_one('#planofstudytextcontainer')
    record['notes'] = [clean(p.get_text(' ', strip=True)) for p in container.select('p')
                       if p.find_parent('table') is None] if container else []
    tables = container.select('table.sc_plangrid') if container else soup.select('table.sc_plangrid')
    if not tables:
        if container is not None or soup.select_one('#planofstudytexttab') is not None:
            raise PlanParseError('Plan section exists but contains no supported plan grids')
        record['status'] = 'no_published_plan'
        return record
    for number, table in enumerate(tables, 1):
        heading = table.find_previous(['h2', 'h3', 'h4'])
        name = clean(heading.get_text(' ', strip=True)) if heading else f'Sample plan {number}'
        notes = []
        for sibling in table.previous_siblings:
            if getattr(sibling, 'name', None) in ('table', 'h2', 'h3', 'h4'):
                break
            if getattr(sibling, 'name', None) == 'p':
                notes.append(clean(sibling.get_text(' ', strip=True)))
        record['plans'].append({'plan_name': name, 'notes': list(reversed(notes)), 'semesters': parse_grid(table)})
    record['status'] = 'available'
    return record


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def fetch(session, url):
    response = session.get(url, timeout=(10, 45))
    response.raise_for_status()
    if urlparse(response.url).path.rstrip('/') != urlparse(url).path.rstrip('/'):
        raise PlanParseError(f'Unexpected redirect to {response.url}')
    return response.text


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog-year', help='Catalog edition, e.g. 2026-2027; defaults to current live edition')
    parser.add_argument('--output-dir', type=Path, default=DATA_DIR, help='Data directory for JSON and coverage manifest')
    parser.add_argument('--delay', type=float, default=0.1, help='Seconds between program requests')
    args = parser.parse_args(argv)
    if args.delay < 0 or (args.catalog_year and (not YEAR.fullmatch(args.catalog_year) or int(args.catalog_year[5:]) != int(args.catalog_year[:4]) + 1)):
        parser.error('Use a nonnegative delay and a consecutive catalog year such as 2026-2027')
    session = requests.Session()
    session.headers['User-Agent'] = 'NEUInsightsPlanScraper/1.0'
    session.mount('https://', HTTPAdapter(max_retries=Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504], respect_retry_after_header=True)))
    current_year = edition(BeautifulSoup(fetch(session, BASE_URL + 'undergraduate/'), 'html.parser'))
    catalog_year = args.catalog_year or current_year
    root = BASE_URL if catalog_year == current_year else urljoin(BASE_URL, f'archive/{catalog_year}/')
    index = BeautifulSoup(fetch(session, urljoin(root, 'azindex/')), 'html.parser')
    if edition(index) != catalog_year:
        raise PlanParseError('A-Z index belongs to a different catalog edition')
    programs = discover_programs(index, root)
    print(f'{catalog_year}: discovered {len(programs)} undergraduate bachelor program variants', flush=True)
    records = []
    errors = []
    for position, program in enumerate(programs, 1):
        if position > 1:
            time.sleep(args.delay)
        try:
            record = parse_program(fetch(session, program['source_url']), program['source_url'], catalog_year)
            records.append(record)
        except (requests.RequestException, ValueError) as error:
            errors.append({**program, 'status': 'error', 'error': str(error)})
            print(f'ERROR {program["source_url"]}: {error}', flush=True)
        if position % 25 == 0 or position == len(programs):
            print(f'Checked {position}/{len(programs)}; {sum(bool(r["plans"]) for r in records)} with plans; {len(errors)} errors', flush=True)
    report = {
        'catalog_year': catalog_year, 'scraped_at': datetime.now(timezone.utc).isoformat(),
        'scope': 'undergraduate bachelor programs; includes combined majors and campus variants; excludes CPS',
        'complete': not errors, 'program_count': len(programs),
        'programs_with_plans': sum(bool(r['plans']) for r in records),
        'plan_count': sum(len(r['plans']) for r in records),
        'programs_without_plans': sum(not r['plans'] for r in records), 'errors': errors,
        'programs': [],
    }
    for record in records:
        metadata = {k: v for k, v in record.items() if k != 'plans'}
        if record['plans']:
            metadata['file'] = f'plans/{catalog_year}/{record["major"]}.json'
        report['programs'].append(metadata)
    write_json(args.output_dir / 'plan_scrape_report.json', report)
    if errors:
        print('Refresh incomplete; active plans unchanged. See plan_scrape_report.json.', flush=True)
        return 1
    for record in records:
        if record['plans']:
            write_json(args.output_dir / 'plans' / catalog_year / f'{record["major"]}.json', record)
    # Publish the manifest last. The loader reads only files declared in it.
    write_json(args.output_dir / 'plan_catalog.json', report)
    print(f'Published {report["plan_count"]} plans; {report["programs_without_plans"]} programs have no published plan.', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
