"""Offline tests for requirement extraction, crawl boundaries, and safe publication."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from json_scrapers import plan_scraper, requirements_scraper as scraper

URL = scraper.BASE_URL + 'undergraduate/computer-information-science/computer-science/bscs/'
FINANCE = scraper.BASE_URL + 'undergraduate/business/concentrations/finance/'
SHARED = sorted(scraper.BASE_URL.rstrip('/') + path for path in scraper.SHARED_PATHS)


def page(body, title='Computer Science, BSCS (Boston)', year='2026-2027', container='programrequirementstextcontainer'):
    return (f'<h2 id="edition">{year} Edition</h2><h1>{title}</h1>'
            '<ul id="breadcrumb"><li>Home</li><li>Undergraduate</li><li>Khoury College</li></ul>'
            f'<div id="{container}">{body}</div>')


def course(code, title='Course', hours='4', alternative=False, indent=0):
    css = 'orclass' if alternative else ''
    prefix = 'or ' if alternative else ''
    return (f'<tr class="{css}"><td class="codecol">{prefix}'
            f'<div style="margin-left:{indent}px">{code}</div></td>'
            f'<td>{title}</td><td class="hourscol">{hours}</td></tr>')


def table(rows):
    return '<table class="sc_courselist"><tr><th>Code</th><th>Title</th><th>Hours</th></tr>' + rows + '</table>'


def sitemap(urls):
    return ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + ''.join(f'<url><loc>{url}</loc></url>' for url in urls) + '</urlset>')


class ParsingTest(unittest.TestCase):
    def test_program_id_matches_existing_plan_scraper(self):
        html = page('<p>Complete the core.</p>')
        plan = plan_scraper.parse_program(html, URL, '2026-2027')
        self.assertEqual(scraper.document_id(URL), plan['major'])

    def test_bundles_alternatives_and_choice_layout_keep_distinct_meanings(self):
        rows = ('<tr class="areaheader"><td colspan="2">Foundations</td><td class="hourscol"></td></tr>'
                + course('CS 2000 and CS 2001', hours='5')
                + course('CS 1800') + course('MATH 1365', alternative=True, hours='')
                + course('MATH 1465', alternative=True, hours='')
                + '<tr><td colspan="2">Complete two of the following:</td><td class="hourscol">8</td></tr>'
                + course('CS 4100', hours='', indent=20) + course('DS 4400', hours='', indent=20))
        record = scraper.parse_document(page('<h2>Core</h2>' + table(rows)), URL, '2026-2027')
        parsed = record['sections'][0]['entries'][0]['rows']
        self.assertEqual(parsed[1]['expression']['kind'], 'all_of')
        self.assertEqual(parsed[1]['credits'], {'min': 5, 'max': 5})
        self.assertNotIn('credits', parsed[1]['expression']['children'][0])
        self.assertEqual(parsed[2]['alternative_group'], parsed[4]['alternative_group'])
        self.assertEqual(parsed[5]['constraints']['selection_count'], 2)
        self.assertEqual(parsed[6]['indent'], 20)
        self.assertNotIn('required_courses', record)
        self.assertEqual(record['major'], scraper.document_id(URL))
        self.assertEqual(record['degree'], 'BSCS')
        self.assertEqual(record['campus'], 'Boston')
        self.assertFalse(record['semantics_validated'])

    def test_inline_concentrations_inside_wrappers_are_not_lost(self):
        body = ('<h2>Major</h2>' + table(course('CS 3000'))
                + '<div><h3>Artificial Intelligence Concentration</h3>'
                + table(course('DS 4400')) + '</div>')
        sections = scraper.parse_document(page(body), URL, '2026-2027')['sections']
        self.assertEqual([s['title'] for s in sections], ['Major', 'Artificial Intelligence Concentration'])
        self.assertEqual(sections[1]['heading_path'], ['Major', 'Artificial Intelligence Concentration'])

    def test_architecture_major_requirements_tab_is_supported(self):
        record = scraper.parse_document(page(table(course('ARCH 1110')), title='Architecture, BS (Boston)',
                                               container='majorrequirementstextcontainer'), URL, '2026-2027')
        self.assertEqual(record['sections'][0]['container_id'], 'majorrequirementstextcontainer')
        self.assertEqual(record['sections'][0]['entries'][0]['rows'][0]['courses'], ['ARCH 1110'])

    def test_custom_container_is_discovered_from_visible_requirements_tab(self):
        html = '<div id="tabs"><a href="#programtextcontainer">Program Requirements</a></div>'
        html += page(table(course('HSCI 1105')), title='Health Science, BS (Boston)', container='programtextcontainer')
        record = scraper.parse_document(html, URL, '2026-2027')
        self.assertEqual(record['sections'][0]['container_id'], 'programtextcontainer')

    def test_prose_refs_never_become_required_courses_and_all_notes_survive(self):
        body = ('<h2>Electives</h2><p>Placement out of CS 2000 requires approval.</p>'
                + table('<tr><td colspan="2">Complete 3 courses for a total of at least 10 semester hours. '
                        'One must be a lecture-based BIOL course.</td><td class="hourscol">10</td></tr>'
                        '<tr><td colspan="2">BIOL 2311 to BIOL 5999</td><td class="hourscol"></td></tr>'
                        '<tr><td colspan="2">CS 2300 or higher, except CS 5010</td><td class="hourscol"></td></tr>')
                + '<dl><dt>1</dt><dd>Minimum grade of C required.</dd></dl>')
        record = scraper.parse_document(page(body), URL, '2026-2027')
        rows = record['sections'][0]['entries'][1]['rows']
        self.assertEqual(rows[0]['constraints'], {'course_count': 3, 'minimum_credits': 10})
        self.assertTrue(rows[0]['requires_review'])
        self.assertEqual(rows[1]['course_filter'], {'subject': 'BIOL', 'minimum_number': '2311', 'maximum_number': '5999'})
        self.assertEqual(rows[2]['course_filter']['excluded_courses'], ['CS 5010'])
        self.assertNotIn('courses', rows[2])
        self.assertIn('Minimum grade of C', record['source_text'])
        self.assertIn('Minimum grade of C', record['sections'][0]['entries'][2]['text'])

    def test_zero_variable_credits_footnotes_and_mixed_operators(self):
        rows = (course('COOP 3945', hours='0-8')
                + course('CS 2000<sup>1</sup> and CS 2001', hours='5')
                + course('CS 4100 or CS 4120 and DS 4400', hours='4'))
        parsed = scraper.parse_document(page(table(rows)), URL, '2026-2027')['sections'][0]['entries'][0]['rows']
        self.assertEqual(parsed[0]['credits'], {'min': 0, 'max': 8})
        self.assertEqual(parsed[1]['footnote_refs'], ['1'])
        self.assertEqual(parsed[1]['expression']['kind'], 'all_of')
        self.assertTrue(parsed[1]['requires_review'])
        self.assertIsNone(parsed[2]['expression'])
        self.assertTrue(parsed[2]['requires_review'])

    def test_linked_concentration_and_shared_requirements_resolve_by_document(self):
        program = scraper.parse_document(page(f'<p><a href="{FINANCE}">Finance</a></p>'), URL, '2026-2027')
        finance = scraper.parse_document(page('<p>At most one course may overlap.</p>' + table(course('FINA 3301')),
                                               title='Finance', container='concentrationrequirementstextcontainer'), FINANCE, '2026-2027')
        scraper.resolve_links([program, finance])
        self.assertEqual(finance['kind'], 'concentration')
        self.assertEqual(program['linked_requirements'][0]['document_id'], finance['document_id'])

    def test_catalog_link_whitespace_and_index_aliases_resolve(self):
        body = f'<p><a href=" {FINANCE}index.html ">Finance</a></p><p><a href="{FINANCE}   ">Finance</a></p>'
        program = scraper.parse_document(page(body), URL, '2026-2027')
        finance = scraper.parse_document(page('<p>Core</p>', title='Finance', container='concentrationrequirementstextcontainer'), FINANCE, '2026-2027')
        scraper.resolve_links([program, finance])
        self.assertEqual(len(program['linked_requirements']), 2)
        self.assertFalse(program['unresolved_requirement_links'])

    def test_missing_concentration_link_is_reported_instead_of_dropped(self):
        program = scraper.parse_document(page('<p><a href="/undergraduate/business/concentrations/family-business/">Family Business</a></p>'), URL, '2026-2027')
        scraper.resolve_links([program])
        self.assertEqual(program['unresolved_requirement_links'][0]['text'], 'Family Business')

    def test_all_shared_tabs_and_overview_policies_are_preserved(self):
        html = page('', title='General Education Requirements', container='textcontainer')
        html += '<div id="nupathtextcontainer"><h2>NUpath</h2><p>Up to two attributes.</p></div>'
        html += '<div id="additionalrequirementsforbaprogramstextcontainer"><h2>BA Languages</h2><p>Language proficiency.</p></div>'
        record = scraper.parse_document(html, SHARED[0], '2026-2027')
        self.assertEqual(record['kind'], 'shared')
        self.assertEqual(len(record['sections']), 2)
        overview = '<div id="textcontainer"><h3>Progression</h3><p>Minimum grade C required.</p></div>'
        record = scraper.parse_document(page(table(course('NRSG 2000')), title='Nursing, BSN (Boston)') + overview, URL, '2026-2027')
        self.assertIn('Minimum grade C', record['overview_text'])

    def test_unknown_tables_are_kept_and_marked_for_review(self):
        record = scraper.parse_document(page('<table><tr><td>Advisor approval</td></tr></table>'), URL, '2026-2027')
        entry = record['sections'][0]['entries'][0]
        self.assertEqual(entry['kind'], 'unparsed_table')
        self.assertTrue(entry['requires_review'])
        self.assertIn('<table>', entry['html'])

    def test_conditions_in_course_titles_are_flagged_for_review(self):
        rows = course('FINA 3301', title='Corporate Finance (if not selected as a required course)')
        record = scraper.parse_document(page(table(rows)), URL, '2026-2027')
        self.assertTrue(record['sections'][0]['entries'][0]['rows'][0]['requires_review'])

    def test_option_counts_do_not_claim_bundles_are_single_courses(self):
        self.assertEqual(scraper.constraints('Complete one of the following lecture/lab pairs:'), {'selection_count': 1})
        self.assertEqual(scraper.constraints('Complete at least one of the following experiences:'), {'minimum_selections': 1})
        self.assertEqual(scraper.constraints('Complete three courses:'), {'course_count': 3})

    def test_missing_empty_wrong_edition_and_orphan_alternative_fail(self):
        cases = [page('', container='textcontainer'), page(''), page('<p>Core</p>', year='2025-2026'),
                 page(table(course('CS 4100', alternative=True))),
                 page(table('<tr><td rowspan="2">CS 4100</td></tr>'))]
        for html in cases:
            with self.subTest(html=html), self.assertRaises(scraper.RequirementsParseError):
                scraper.parse_document(html, URL, '2026-2027')

    def test_minors_and_department_pages_are_out_of_scope(self):
        for title in ['Computer Science, Minor', 'Computer Science']:
            self.assertIsNone(scraper.parse_document(page('<p>See majors</p>', title=title), URL, '2026-2027'))


class DiscoveryAndClientTest(unittest.TestCase):
    def test_sitemap_filters_external_archived_cps_and_duplicates(self):
        urls = [URL, URL, FINANCE, scraper.BASE_URL + 'archive/2025-2026/undergraduate/cs/',
                scraper.BASE_URL + 'professional-studies/undergraduate/cs/',
                'https://example.org/undergraduate/cs/', URL + '?print=true', URL + '#requirements']
        self.assertEqual(scraper.discover_urls(sitemap(urls)), sorted([URL, FINANCE]))

    def test_wrong_or_empty_sitemap_fails(self):
        for xml in ['<sitemapindex/>', sitemap([])]:
            with self.assertRaises(scraper.RequirementsParseError):
                scraper.discover_urls(xml)

    def test_robots_exclusions_are_checked_before_network_access(self):
        client = scraper.CatalogClient(0)
        client.robots = RobotFileParser()
        client.robots.parse(['User-agent: *', 'Disallow: /archive/', 'Disallow: /azindex/'])
        with patch.object(client.session, 'get') as get:
            for path in ['archive/2025-2026/', 'azindex/']:
                with self.assertRaises(scraper.RequirementsParseError):
                    client.fetch(scraper.BASE_URL + path)
            get.assert_not_called()
        client.session.close()

    def test_unexpected_redirect_is_not_followed(self):
        client = scraper.CatalogClient(0)
        client.robots.parse(['User-agent: *', 'Allow: /'])
        response = Mock(is_redirect=True, headers={'Location': '/archive/2025-2026/'})
        with patch.object(client.session, 'get', return_value=response) as get:
            with self.assertRaises(scraper.RequirementsParseError):
                client.fetch(URL)
            self.assertEqual(get.call_count, 1)
            self.assertFalse(get.call_args.kwargs['allow_redirects'])
        client.session.close()

    def test_same_url_redirect_fails_without_recursing(self):
        client = scraper.CatalogClient(0)
        client.robots.parse(['User-agent: *', 'Allow: /'])
        response = Mock(is_redirect=True, headers={'Location': URL})
        with patch.object(client.session, 'get', return_value=response) as get:
            with self.assertRaises(scraper.RequirementsParseError):
                client.fetch(URL)
            self.assertEqual(get.call_count, 1)
        client.session.close()


class RefreshTest(unittest.TestCase):
    def fetch(self, url):
        if url.endswith('undergraduate/'):
            return page('<p>Catalog</p>')
        if url.endswith('sitemap.xml'):
            return sitemap([URL, FINANCE, *SHARED])
        if url == URL:
            return page(table(course('CS 3000')) + f'<p><a href="{FINANCE}">Finance</a></p>')
        if url == FINANCE:
            return page(table(course('FINA 3301')), title='Finance', container='concentrationrequirementstextcontainer')
        return page('<p>Minimum 128 credits.</p>', title='University Requirements', container='textcontainer')

    def run_scrape(self, root, fetch=None, args=None):
        client = Mock()
        client.__enter__ = Mock(return_value=client)
        client.__exit__ = Mock(return_value=False)
        client.fetch.side_effect = fetch or self.fetch
        with patch.object(scraper, 'CatalogClient', return_value=client), contextlib.redirect_stdout(io.StringIO()):
            return scraper.main(['--output-dir', str(root), '--delay', '0', *(args or [])])

    def test_success_publishes_versioned_complete_manifest_and_resolved_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(self.run_scrape(root), 0)
            report = json.loads((root / 'requirements_catalog.json').read_text())
            self.assertTrue(report['complete'])
            self.assertEqual(report['program_count'], 1)
            self.assertEqual(report['concentration_count'], 1)
            self.assertEqual(report['shared_count'], 2)
            for metadata in report['documents']:
                self.assertTrue(metadata['file'].startswith('requirements/2026-2027/'))
                self.assertTrue((root / metadata['file']).exists())
            program = json.loads((root / report['programs'][0]['file']).read_text())
            self.assertEqual(program['linked_requirements'][0]['kind'], 'concentration')

    def test_failed_fetch_preserves_previous_manifest_and_same_year_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.run_scrape(root)
            manifest = (root / 'requirements_catalog.json').read_bytes()
            previous = {path: path.read_bytes() for path in root.glob('requirements/**/*.json')}
            def fail(url):
                if url == FINANCE:
                    raise requests.Timeout('Temporary failure')
                return self.fetch(url)
            self.assertEqual(self.run_scrape(root, fail), 1)
            self.assertEqual((root / 'requirements_catalog.json').read_bytes(), manifest)
            self.assertEqual(previous, {path: path.read_bytes() for path in root.glob('requirements/**/*.json')})
            self.assertFalse(json.loads((root / 'requirements_scrape_report.json').read_text())['complete'])

    def test_interrupted_publication_keeps_previous_snapshot_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.run_scrape(root)
            manifest = (root / 'requirements_catalog.json').read_bytes()
            old_files = {path: path.read_bytes() for path in root.glob('requirements/**/*.json')}
            original = scraper.write_json
            def write(path, data):
                if path.parent.parent.parent.name == 'requirements' and data.get('kind') == 'program':
                    raise OSError('Disk write failed')
                original(path, data)
            with patch.object(scraper, 'write_json', side_effect=write), self.assertRaises(OSError):
                self.run_scrape(root)
            self.assertEqual((root / 'requirements_catalog.json').read_bytes(), manifest)
            for path, content in old_files.items():
                self.assertEqual(path.read_bytes(), content)

    def test_archive_request_fails_before_sitemap_fetch(self):
        with tempfile.TemporaryDirectory() as directory:
            seen = []
            def fetch(url):
                seen.append(url)
                return self.fetch(url)
            self.assertEqual(self.run_scrape(Path(directory), fetch, ['--catalog-year', '2025-2026']), 1)
            self.assertEqual(len(seen), 1)

    def test_local_course_reference_check_preserves_missing_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'courses').mkdir()
            (root / 'courses' / 'cs.json').write_text(json.dumps({'courses': [{'number': '3000'}]}))
            record = scraper.parse_document(page(table(course('CS 3000') + course('CS 4990'))), URL, '2026-2027')
            check = scraper.check_course_references([record], root)
            self.assertEqual(check['unmatched_courses'], ['CS 4990'])
            self.assertEqual(record['unmatched_course_references'], ['CS 4990'])
            self.assertIn('CS 4990', record['sections'][0]['entries'][0]['rows'][1]['courses'])


if __name__ == '__main__':
    unittest.main()
