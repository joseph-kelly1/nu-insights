"""Collect current undergraduate major requirements from Northeastern's catalog.

Uses the public sitemap, respects robots.txt, and preserves original requirement
text alongside structured rows. This is an extraction dataset, not a degree-audit
engine. Run: python json_scrapers/requirements_scraper.py
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import time
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.robotparser import RobotFileParser
import uuid
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup, Comment, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

if __package__:
    from .plan_scraper import BASE_URL, DATA_DIR, DEGREE, YEAR, clean, edition, write_json
else:
    from plan_scraper import BASE_URL, DATA_DIR, DEGREE, YEAR, clean, edition, write_json

USER_AGENT = 'NUInsightsRequirementsScraper/1.0'
SHARED_PATHS = {
    '/undergraduate/university-academics/university-wide-requirements/',
    '/undergraduate/university-academics/general-education-requirements/',
}
NUMBER_WORDS = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
                'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10}
COUNT = r'(\d+|one|two|three|four|five|six|seven|eight|nine|ten)'
CODE = re.compile(r'\b([A-Z]{2,5})\s*(\d{4})\b')


class RequirementsParseError(ValueError):
    """A source page cannot be extracted safely."""


def document_id(url):
    """Match the existing plan scraper's program identifiers."""
    path = urlparse(url).path
    return path.rstrip('/').split('/')[-1][:100] + '-' + hashlib.sha256(path.encode()).hexdigest()[:8]


def codes(text):
    return list(dict.fromkeys(f'{m[1]} {m[2]}' for m in CODE.finditer(text)))


def links(element, url):
    return [{'text': clean(a.get_text(' ', strip=True)), 'url': urljoin(url, a['href'].strip())}
            for a in element.select('a[href]') if 'code' not in a.get('class', [])]


def canonical_reference(url):
    parsed = urlparse(url.strip())
    path = parsed.path
    if path.endswith('/index.html'):
        path = path[:-len('index.html')]
    return parsed._replace(path=path.rstrip('/'), fragment='').geturl()


def numeric_credits(text):
    """Retain zero credits and ranges; never assign bundle credits per course."""
    match = re.fullmatch(r'(\d+(?:\.\d+)?)(?:\s*[-–—]\s*(\d+(?:\.\d+)?))?', text)
    if not match:
        return None
    lower, upper = float(match[1]), float(match[2] or match[1])
    if lower > upper:
        raise RequirementsParseError(f'Reversed credit range: {text}')
    return {'min': lower, 'max': upper}


def constraints(text):
    """Extract explicit counts only. Additional prose remains authoritative."""
    result = {}
    count = re.search(r'\b(?:complete|choose|select|take)\s+(at least\s+)?' + COUNT
                      + r'\s+(of the following|courses?\b|lecture)', text, re.I)
    if count:
        value = NUMBER_WORDS.get(count[2].lower())
        unit = 'courses' if count[3].lower().startswith('course') else 'selections'
        key = f'minimum_{unit}' if count[1] else 'course_count' if unit == 'courses' else 'selection_count'
        result[key] = value if value else int(count[2])
    credits = re.search(r'\b(?:complete|at least|minimum of|total of(?: at least)?)\s+'
                        r'(\d+(?:\.\d+)?)\s+(?:semester hours|credits)\b', text, re.I)
    if credits:
        result['minimum_credits'] = float(credits[1])
    return result


def course_filter(text):
    """Recognize subject/level pools without expanding them into required courses."""
    match = re.search(r'\b([A-Z]{2,5})\s+(\d{4})\s+(?:to\s+(?:\1\s+)?(\d{4})|or higher)', text)
    if not match:
        return None
    result = {'subject': match[1], 'minimum_number': match[2]}
    if match[3]:
        result['maximum_number'] = match[3]
    if re.search(r'\bexcept\b', text, re.I):
        result['excluded_courses'] = codes(re.split(r'\bexcept\b', text, flags=re.I)[1])
    return result


def course_expression(text):
    """Parse unambiguous AND/OR chains. Mixed or annotated expressions need review."""
    normalized = CODE.sub(lambda m: f'{m[1]} {m[2]}', text)
    parts = re.split(r'\s+(and|or)\s+', normalized)
    if not parts or any(not re.fullmatch(r'[A-Z]{2,5} \d{4}', part)
                        for part in parts[::2]):
        return None
    operators = set(parts[1::2])
    if len(operators) > 1:
        return None
    leaves = [{'kind': 'course', 'course': part} for part in parts[::2]]
    if len(leaves) == 1:
        return leaves[0]
    return {'kind': 'all_of' if operators == {'and'} else 'any_of', 'children': leaves}


def parse_table(table, url):
    """Keep ordered layout and indentation so choice scope is never flattened away."""
    rows = []
    for tr in table.find_all('tr'):
        if tr.find_parent('table') is not table:
            raise RequirementsParseError('Nested course table is unsupported')
        if tr.find('th'):
            continue
        cells = tr.find_all('td', recursive=False)
        if not cells:
            continue
        if any(int(c.get('rowspan', 1)) != 1 for c in cells):
            raise RequirementsParseError('Unsupported rowspan in course table')
        text = clean(tr.get_text(' ', strip=True))
        if not text:
            continue
        hours = tr.select_one('td.hourscol')
        credits_text = clean(hours.get_text(' ', strip=True)) if hours else ''
        body = clean(' '.join(c.get_text(' ', strip=True) for c in cells if c is not hours))
        row = {'index': len(rows), 'kind': 'note', 'text': body, 'credits_text': credits_text,
               'credits': numeric_credits(credits_text), 'links': links(tr, url),
               'footnote_refs': [clean(s.get_text()) for s in tr.select('sup')],
               'indent': 0, 'requires_review': True}
        for element in tr.select('[style*="margin-left"], .blockindent, .commentindent'):
            match = re.search(r'margin-left:\s*([\d.]+)px', element.get('style', ''))
            row['indent'] = max(row['indent'], float(match[1]) if match else 20)
        classes = tr.get('class', [])
        code_cell = tr.select_one('td.codecol')
        if 'areaheader' in classes or tr.select_one('.areaheader'):
            row.update(kind='header', requires_review=False)
        elif 'sumrow' in classes or re.match(r'^Total (?:Hours|Credits)\b', body, re.I):
            row['kind'] = 'total'
        elif code_cell is not None:
            # Superscripts identify footnotes, not part of a course expression.
            copy = BeautifulSoup(str(code_cell), 'html.parser')
            for sup in copy.select('sup'):
                sup.decompose()
            code_text = clean(copy.get_text(' ', strip=True))
            alternative = 'orclass' in classes or 'orclass' in code_cell.get('class', [])
            row.update(kind='course', courses=codes(code_text), code_text=code_text,
                       alternative_to_previous=alternative)
            expression = course_expression(re.sub(r'^or\s+', '', code_text))
            row['expression'] = expression
            conditional = re.search(r'\b(?:if|except|approval|not already|not selected|minimum grade|up to)\b', body, re.I)
            row['requires_review'] = (expression is None or bool(conditional) or bool(row['footnote_refs'])
                                      or (credits_text != '' and row['credits'] is None))
            if not row['courses']:
                row.update(kind='unparsed', requires_review=True)
        elif re.search(r'\b(?:complete|choose|select|take)\b', body, re.I):
            row.update(kind='instruction', constraints=constraints(body))
        pool = course_filter(body)
        if pool:
            row.update(kind='elective_filter', course_filter=pool, requires_review=True)
        if row['kind'] == 'course' and row['alternative_to_previous']:
            previous = rows[-1] if rows else None
            if not previous or previous['kind'] != 'course':
                raise RequirementsParseError('Alternative course has no preceding course option')
            row['alternative_group'] = previous.get('alternative_group', previous['index'])
            previous['alternative_group'] = row['alternative_group']
        rows.append(row)
    if not rows:
        raise RequirementsParseError('Course table has no requirement rows')
    return {'kind': 'course_table', 'caption': clean(table.caption.get_text()) if table.caption else '',
            'rows': rows, 'requires_review': any(r['requires_review'] for r in rows),
            'scope_note': 'Course rows may be options. Use instructions, headers, indentation, and alternatives together.'}


def parse_sections(container, url):
    """Walk wrappers as well as direct children (inline concentrations can be nested)."""
    sections = []
    heading_path = []
    current = None

    def add(entry):
        nonlocal current
        if current is None:
            current = {'title': 'Preamble', 'heading_path': [], 'level': 0, 'entries': []}
            sections.append(current)
        current['entries'].append(entry)

    def walk(parent):
        nonlocal current, heading_path
        for element in parent.children:
            if isinstance(element, Comment):
                continue
            if not isinstance(element, Tag):
                text = clean(str(element))
                if text:
                    add({'kind': 'text', 'text': text, 'requires_review': True})
                continue
            if element.name in ('script', 'style'):
                continue
            text = clean(element.get_text(' ', strip=True))
            if element.name in ('h2', 'h3', 'h4', 'h5', 'h6'):
                level = int(element.name[1:])
                heading_path = [(n, label) for n, label in heading_path if n < level]
                heading_path.append((level, text))
                current = {'title': text, 'heading_path': [label for _, label in heading_path],
                           'level': level, 'entries': []}
                sections.append(current)
            elif element.name == 'table':
                if 'sc_courselist' in element.get('class', []):
                    add(parse_table(element, url))
                elif text:
                    add({'kind': 'unparsed_table', 'text': text, 'html': str(element),
                         'links': links(element, url), 'requires_review': True})
            elif element.name in ('p', 'ul', 'ol', 'dl', 'blockquote'):
                if text:
                    entry = {'kind': 'list' if element.name in ('ul', 'ol') else 'text',
                             'text': text, 'links': links(element, url),
                             'constraints': constraints(text), 'requires_review': True}
                    if element.name in ('ul', 'ol'):
                        entry['items'] = [clean(li.get_text(' ', strip=True))
                                          for li in element.find_all('li', recursive=False)]
                    add(entry)
            else:
                walk(element)

    walk(container)
    return sections


def parse_document(html, url, catalog_year):
    soup = BeautifulSoup(html, 'html.parser')
    if edition(soup) != catalog_year:
        raise RequirementsParseError('Page belongs to a different catalog edition')
    heading = soup.select_one('h1')
    title = clean(heading.get_text(' ', strip=True)) if heading else ''
    if not title:
        raise RequirementsParseError('Page title is missing')
    degree = DEGREE.search(title)
    if degree:
        kind = 'program'
        containers = soup.select('#programrequirementstextcontainer, #majorrequirementstextcontainer')
        # Some departments use custom IDs (e.g. programtextcontainer) while
        # exposing the same visible requirements tab. Follow that explicit tab.
        for tab in soup.select('#tabs a[href^="#"]'):
            if re.fullmatch(r'(?:Program|Major|Degree) Requirements?', clean(tab.get_text()), re.I):
                candidate = soup.find(id=tab['href'][1:])
                if candidate is not None and candidate not in containers:
                    containers.append(candidate)
        if not containers:
            raise RequirementsParseError('Bachelor program has no requirements container')
    elif soup.select_one('#concentrationrequirementstextcontainer'):
        kind = 'concentration'
        containers = soup.select('#concentrationrequirementstextcontainer')
    elif urlparse(url).path in SHARED_PATHS:
        kind = 'shared'
        containers = [c for c in soup.select('[id$="textcontainer"]') if clean(c.get_text())]
    else:
        return None
    if not containers or not any(clean(c.get_text()) for c in containers):
        raise RequirementsParseError('Requirements content is empty')
    record = {'document_id': document_id(url), 'kind': kind, 'title': title,
              'catalog_year': catalog_year, 'source_url': url,
              'semantics_validated': False, 'sections': []}
    if degree:
        campus = re.search(r'\(([^()]+)\)$', title)
        crumbs = soup.select('#breadcrumb li')
        record.update(major=record['document_id'], major_name=title[:degree.start()].strip(),
                      degree=degree[1], campus=campus[1] if campus else '',
                      college=clean(crumbs[2].get_text(' ', strip=True)).rstrip('›').strip()
                      if len(crumbs) > 2 else '')
    overview = soup.select_one('#textcontainer')
    record['overview_text'] = clean(overview.get_text(' ', strip=True)) if overview and overview not in containers else ''
    record['source_text'] = '\n\n'.join(c.get_text('\n', strip=True).replace('\xa0', ' ') for c in containers)
    record['referenced_courses'] = sorted({code for c in containers for a in c.select('a.code')
                                           for code in codes(a.get('title', a.get_text(' ', strip=True)))})
    record['links'] = [link for c in containers for link in links(c, url)]
    for container in containers:
        for section in parse_sections(container, url):
            section['container_id'] = container.get('id')
            record['sections'].append(section)
    if not any(s['entries'] for s in record['sections']):
        raise RequirementsParseError('Requirements contain no extractable entries')
    record['referenced_courses'] = sorted(set(record['referenced_courses']) | {
        code for section in record['sections'] for entry in section['entries']
        for row in entry.get('rows', []) if row['kind'] == 'course' for code in row['courses']})
    return record


def discover_urls(xml):
    root = ET.fromstring(xml)
    if root.tag.rsplit('}', 1)[-1] != 'urlset':
        raise RequirementsParseError('Expected a URL sitemap, not a sitemap index')
    urls = set()
    for entry in root:
        if entry.tag.rsplit('}', 1)[-1] != 'url':
            continue
        for node in entry:
            if node.tag.rsplit('}', 1)[-1] != 'loc':
                continue
            url = (node.text or '').strip()
            parsed = urlparse(url)
            if (parsed.scheme == 'https' and parsed.netloc == urlparse(BASE_URL).netloc
                    and parsed.path.startswith('/undergraduate/') and not parsed.query and not parsed.fragment):
                urls.add(url)
    if not urls:
        raise RequirementsParseError('No current undergraduate pages in sitemap')
    return sorted(urls)


class CatalogClient:
    """A paced, retrying client that checks robots before every catalog request."""

    def __init__(self, delay):
        self.delay = delay
        self.last_request = None
        self.session = requests.Session()
        self.session.headers['User-Agent'] = USER_AGENT
        self.session.mount('https://', HTTPAdapter(max_retries=Retry(
            total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504],
            respect_retry_after_header=True)))
        self.robots = RobotFileParser()
        self.robots.set_url(urljoin(BASE_URL, 'robots.txt'))

    def __enter__(self):
        try:
            self.robots.parse(self.fetch(urljoin(BASE_URL, 'robots.txt'), check_robots=False).splitlines())
            crawl_delay = self.robots.crawl_delay(USER_AGENT) or self.robots.crawl_delay('*')
            if crawl_delay:
                self.delay = max(self.delay, crawl_delay)
            return self
        except Exception:
            self.session.close()
            raise

    def __exit__(self, *_):
        self.session.close()

    def fetch(self, url, check_robots=True, _redirected=False):
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.netloc != urlparse(BASE_URL).netloc:
            raise RequirementsParseError(f'Not a catalog URL: {url}')
        if check_robots and not self.robots.can_fetch(USER_AGENT, url):
            raise RequirementsParseError(f'Blocked by robots.txt: {url}')
        if self.last_request is not None:
            time.sleep(max(0, self.delay - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        # Inspect redirects rather than following one into a robots-excluded path.
        response = self.session.get(url, timeout=(10, 45), allow_redirects=False)
        response.raise_for_status()
        if response.is_redirect:
            target = urljoin(url, response.headers.get('Location', ''))
            if _redirected or target == url or target.rstrip('/') != url.rstrip('/'):
                raise RequirementsParseError(f'Unexpected redirect to {target}')
            return self.fetch(target, check_robots=check_robots, _redirected=True)
        if urlparse(response.url).path.rstrip('/') != parsed.path.rstrip('/'):
            raise RequirementsParseError(f'Unexpected response URL: {response.url}')
        return response.text


def resolve_links(records):
    by_url = {canonical_reference(r['source_url']): r for r in records}
    for record in records:
        related = []
        unresolved = []
        seen = set()
        for link in record['links']:
            target, fragment = urldefrag(link['url'].strip())
            if link['url'] in seen:
                continue
            seen.add(link['url'])
            match = by_url.get(canonical_reference(target))
            if match:
                related.append({**link, 'document_id': match['document_id'],
                                'kind': match['kind'], 'fragment': fragment})
            elif (urlparse(target).netloc == urlparse(BASE_URL).netloc
                  and '/undergraduate/' in urlparse(target).path and '/concentrations/' in urlparse(target).path):
                unresolved.append(link)
        record['linked_requirements'] = related
        record['unresolved_requirement_links'] = unresolved


def check_course_references(records, output_dir):
    """Compare references with local course data when present; never invent matches."""
    files = sorted((output_dir / 'courses').glob('*.json'))
    if not files:
        return {'status': 'not_available'}
    known = set()
    for path in files:
        data = json.loads(path.read_text())
        courses = data.get('courses', []) if isinstance(data, dict) else data
        known.update(f'{path.stem.upper()} {course["number"]}' for course in courses)
    missing = set()
    for record in records:
        record['unmatched_course_references'] = sorted(set(record['referenced_courses']) - known)
        missing.update(record['unmatched_course_references'])
    return {'status': 'checked', 'known_course_count': len(known), 'unmatched_courses': sorted(missing)}


def publish(records, report, output_dir):
    """Write a fresh snapshot, then atomically select it with the manifest."""
    resolve_links(records)
    report['unresolved_requirement_links'] = [{'source_url': record['source_url'], **link}
                                              for record in records for link in record['unresolved_requirement_links']]
    report['course_reference_check'] = check_course_references(records, output_dir)
    generation = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    report.update(generation=generation, documents=[], programs=[])
    for record in records:
        relative = Path('requirements') / report['catalog_year'] / generation / (record['document_id'] + '.json')
        write_json(output_dir / relative, record)
        metadata = {key: record[key] for key in ('document_id', 'kind', 'title', 'source_url')}
        metadata['file'] = relative.as_posix()
        report['documents'].append(metadata)
        if record['kind'] == 'program':
            report['programs'].append({**metadata, **{key: record[key] for key in ('major', 'major_name', 'degree', 'campus', 'college')}})
    report['complete'] = True
    write_json(output_dir / 'requirements_scrape_report.json', report)
    write_json(output_dir / 'requirements_catalog.json', report)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog-year', help='Expected live edition; archived crawling is not supported')
    parser.add_argument('--output-dir', type=Path, default=DATA_DIR)
    parser.add_argument('--delay', type=float, default=0.25, help='Minimum seconds between requests')
    args = parser.parse_args(argv)
    if not math.isfinite(args.delay) or args.delay < 0:
        parser.error('Use a finite, nonnegative delay')
    if args.catalog_year and (not YEAR.fullmatch(args.catalog_year)
                             or int(args.catalog_year[5:]) != int(args.catalog_year[:4]) + 1):
        parser.error('Use a consecutive catalog year such as 2026-2027')
    report = {'schema_version': 1, 'catalog_year': args.catalog_year,
              'scraped_at': datetime.now(timezone.utc).isoformat(),
              'scope': 'current undergraduate bachelor programs, concentrations, universitywide and general education requirements; excludes CPS, minors, graduate programs',
              'discovery_url': urljoin(BASE_URL, 'sitemap.xml'),
              'complete': False, 'semantics_validated': False, 'candidate_count': 0,
              'program_count': 0, 'concentration_count': 0, 'shared_count': 0,
              'document_count': 0, 'errors': [], 'programs': [], 'documents': [], 'skipped_pages': []}
    records = []
    try:
        with CatalogClient(args.delay) as client:
            current_year = edition(BeautifulSoup(client.fetch(urljoin(BASE_URL, 'undergraduate/')), 'html.parser'))
            if args.catalog_year and args.catalog_year != current_year:
                raise RequirementsParseError(f'Only live edition {current_year} is supported; /archive/ is excluded by robots.txt')
            report['catalog_year'] = current_year
            urls = discover_urls(client.fetch(report['discovery_url']))
            report['candidate_count'] = len(urls)
            print(f'{current_year}: inspecting {len(urls)} undergraduate sitemap pages', flush=True)
            for position, url in enumerate(urls, 1):
                try:
                    record = parse_document(client.fetch(url), url, current_year)
                    if record:
                        records.append(record)
                    else:
                        report['skipped_pages'].append({'source_url': url, 'reason': 'outside requirements scope'})
                except (requests.RequestException, ValueError) as error:
                    report['errors'].append({'source_url': url, 'error': str(error)})
                    print(f'ERROR {url}: {error}', flush=True)
                if position % 25 == 0 or position == len(urls):
                    print(f'Checked {position}/{len(urls)}; {len(records)} requirement documents; {len(report["errors"])} errors', flush=True)
        if not any(r['kind'] == 'program' for r in records):
            raise RequirementsParseError('No bachelor requirements found')
        required = {urljoin(BASE_URL, path) for path in SHARED_PATHS}
        if required - {r['source_url'] for r in records}:
            raise RequirementsParseError('Universitywide or general education requirements are missing')
    except (requests.RequestException, ValueError, ET.ParseError) as error:
        report['errors'].append({'error': str(error)})
        print(f'ERROR: {error}', flush=True)
    for kind in ('program', 'concentration', 'shared'):
        report[f'{kind}_count'] = sum(r['kind'] == kind for r in records)
    report['document_count'] = len(records)
    if report['errors']:
        write_json(args.output_dir / 'requirements_scrape_report.json', report)
        print('Refresh incomplete; active requirements unchanged. See requirements_scrape_report.json.', flush=True)
        return 1
    # Each refresh gets immutable paths. Publishing the manifest last also protects
    # an existing same-edition dataset from interrupted writes or failed refreshes.
    publish(records, report, args.output_dir)
    print(f'Published {report["program_count"]} programs, {report["concentration_count"]} concentrations, '
          f'{report["shared_count"]} shared documents.', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
