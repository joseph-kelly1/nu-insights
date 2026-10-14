"""Import explicitly selected public undergraduate archive editions.

Run: python json_scrapers/archive_requirements_scraper.py --years 2022-2023 2023-2024 2024-2025 2025-2026
Keeps each edition's requirements, concentrations, and course descriptions together.
Does not replace the live requirements manifest or follow links outside the selected archive.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import urldefrag, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

if __package__:
    from . import requirements_scraper as requirements, course_scraper
    from .plan_scraper import BASE_URL, DATA_DIR, YEAR, edition, write_json
else:
    import requirements_scraper as requirements
    import course_scraper
    from plan_scraper import BASE_URL, DATA_DIR, YEAR, edition, write_json


def discover(index, root):
    prefix = urlparse(urljoin(root, 'undergraduate/')).path
    container = index.select_one('#atozindex')
    if container is None:
        raise ValueError('Archive index is missing')
    urls = set()
    for a in container.select('a[href]'):
        url = urldefrag(urljoin(root, a['href']))[0]
        parsed = urlparse(url)
        if parsed.netloc == urlparse(root).netloc and parsed.path.startswith(prefix) and not parsed.query:
            urls.add(url)
    # Shared requirements are linked by programs but may not be in the index.
    urls.update(urljoin(root, p) for p in ('undergraduate/university-academics/nupath/',
                                        'undergraduate/university-academics/university-wide-requirements/'))
    return sorted(urls)


def collect(year, output_dir, delay, refresh=False):
    root = urljoin(BASE_URL, f'archive/{year}/')
    destination = output_dir / 'catalogs' / year
    if (destination / 'requirements_catalog.json').exists() and not refresh:
        print(f'{year}: already collected', flush=True)
        return
    records, errors, course_pages, skipped = [], [], {}, []
    cache = Path('/private/tmp/nu-catalog-imports') / year
    cache.mkdir(parents=True, exist_ok=True)
    with requests.Session() as session:
        session.headers['User-Agent'] = 'NUInsightsArchiveImport/1.0'
        session.mount('https://', HTTPAdapter(max_retries=Retry(total=3, backoff_factor=1,
                      status_forcelist=[429, 500, 502, 503, 504], respect_retry_after_header=True)))
        previous = 0

        def fetch(url):
            nonlocal previous
            parsed = urlparse(url)
            if parsed.scheme != 'https' or parsed.netloc != urlparse(BASE_URL).netloc or not parsed.path.startswith(urlparse(root).path):
                raise ValueError(f'URL outside selected archive: {url}')
            cached = cache / (hashlib.sha256(url.encode()).hexdigest() + '.html')
            if cached.exists():
                return cached.read_text()
            time.sleep(max(0, delay - (time.monotonic() - previous)))
            previous = time.monotonic()
            response = session.get(url, timeout=(10, 45), allow_redirects=False)
            response.raise_for_status()
            if response.is_redirect:
                raise ValueError(f'Unexpected archive redirect: {url}')
            html = response.text
            if edition(BeautifulSoup(html, 'html.parser')) != year:
                raise ValueError(f'Wrong archive edition: {url}')
            cached.write_text(html)
            return html

        index = BeautifulSoup(fetch(urljoin(root, 'azindex/')), 'html.parser')
        urls = discover(index, root)
        print(f'{year}: inspecting {len(urls)} undergraduate pages', flush=True)
        for i, url in enumerate(urls, 1):
            try:
                record = requirements.parse_document(fetch(url), url, year)
                if record:
                    records.append(record)
                    for code in record['referenced_courses']:
                        subject = code.split()[0].lower()
                        course_pages[subject] = urljoin(root, f'course-descriptions/{subject}/')
            except (requests.RequestException, ValueError) as error:
                if str(error) == 'Bachelor program has no requirements container':
                    skipped.append({'source_url': url, 'reason': 'No published requirements in this edition'})
                else:
                    errors.append({'source_url': url, 'error': str(error)})
            if i % 50 == 0:
                print(f'{year}: {i}/{len(urls)} pages; {len(records)} documents; {len(errors)} errors', flush=True)
        required = {'General Education Requirements', 'NUpath', 'NUpath Requirements', 'Universitywide Requirements'}
        shared = [r for r in records if r['kind'] == 'shared']
        if len(shared) != 2 or not any(r['title'] in required and 'nupath' in r['source_url'] for r in shared):
            errors.append({'error': 'Both archived shared requirement documents are required'})
        if errors:
            write_json(destination / 'requirements_scrape_report.json', {'catalog_year': year, 'errors': errors, 'complete': False})
            raise ValueError(f'{year}: {len(errors)} archive errors; no active snapshot published')
        course_errors = []
        for subject, url in sorted(course_pages.items()):
            try:
                courses = course_scraper.parse_department(fetch(url), url, course_errors)
                if courses is not None:
                    write_json(destination / 'courses' / f'{subject}.json', courses)
            except requests.HTTPError as error:
                # Some requirements reference elective-only subjects without a taught course page.
                if error.response.status_code != 404:
                    raise
            if course_errors:
                raise ValueError(f'Could not parse archived courses: {course_errors[:3]}')
    report = {'schema_version': 1, 'catalog_year': year, 'scraped_at': datetime.now(timezone.utc).isoformat(),
              'discovery_url': urljoin(root, 'azindex/'), 'scope': 'explicitly selected undergraduate archive edition',
              'semantics_validated': False, 'errors': [], 'skipped_pages': skipped, 'course_departments': len(course_pages),
              'document_count': len(records), 'program_count': sum(r['kind'] == 'program' for r in records),
              'concentration_count': sum(r['kind'] == 'concentration' for r in records), 'shared_count': len(shared)}
    requirements.publish(records, report, destination)
    print(f'{year}: published {report["program_count"]} programs, {len(course_pages)} course departments', flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--years', nargs='+', required=True)
    parser.add_argument('--output-dir', type=Path, default=DATA_DIR)
    parser.add_argument('--delay', type=float, default=.15)
    parser.add_argument('--refresh', action='store_true', help='Publish a new snapshot from cached source HTML')
    args = parser.parse_args(argv)
    if args.delay < 0 or any(not YEAR.fullmatch(y) or int(y[5:]) != int(y[:4]) + 1 for y in args.years):
        parser.error('Choose consecutive catalog years and a nonnegative delay')
    for year in args.years:
        collect(year, args.output_dir, args.delay, args.refresh)


if __name__ == '__main__':
    main()
