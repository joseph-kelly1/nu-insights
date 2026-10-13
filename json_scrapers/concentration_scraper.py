"""Build concentration choices from the selected requirements snapshot.

No new crawl is needed: the requirements scraper collects standalone pages and
inline tables. Run this after refreshing requirements, or let that scraper publish
it automatically. Source wording remains authoritative; this is not a degree audit.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote, urldefrag

if __package__:
    from .plan_scraper import DATA_DIR, clean, write_json
    from .requirements_scraper import canonical_reference
else:
    from plan_scraper import DATA_DIR, clean, write_json
    from requirements_scraper import canonical_reference


def identity(value):
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def name_key(value):
    value = clean(value).lower().strip('* :')
    value = re.sub(r'^.*?with a concentration in\s+', '', value)
    value = re.sub(r'^concentration in\s+', '', value)
    value = re.sub(r'\s+concentration(?:\s*\(optional\))?$', '', value)
    return re.sub(r'[^a-z0-9]', '', value)


def section_block(sections, index):
    """An option owns its heading and descendants, never its sibling options."""
    first = sections[index]
    result = [first]
    for section in sections[index + 1:]:
        if section['level'] <= first['level']:
            break
        result.append(section)
    return result


def source_text(sections):
    lines = []
    for section in sections:
        lines.append(section['title'])
        for entry in section['entries']:
            if entry['kind'] == 'course_table':
                lines.extend(row['text'] + (f" ({row['credits_text']} credits)" if row.get('credits_text') else '')
                             for row in entry['rows'])
            elif entry.get('text'):
                lines.append(entry['text'])
    return '\n'.join(lines)


def explicit_courses(sections):
    """Candidate course rows only; an elective range is not an explicit course."""
    return sorted({code for section in sections for entry in section['entries']
                   for row in entry.get('rows', []) if row['kind'] == 'course'
                   for code in row.get('courses', [])})


def policy(section, options):
    text = '\n'.join(entry.get('text', '') for entry in section['entries'] if entry['kind'] != 'list')
    wording = section['title'] + '\n' + text
    optional = bool(re.search(r'optional|not required', wording, re.I))
    # A second concentration being optional does not make the first optional.
    required = bool(re.search(r'one concentration is required|concentration required|'
                              r'required concentration|complete (?:the required |one |a )|'
                              r'(?:pick|select|choose) one', wording, re.I))
    required = False if re.search(r'not required', wording, re.I) or 'optional' in section['title'].lower() else required
    allows_second = bool(re.search(r'second concentration|(?:maximum of|up to) (?:two|2) concentrations', wording, re.I)
                         or any(o['secondary_only'] for o in options))
    alternatives = any(o['kind'] == 'alternative' for o in options)
    maximum = 2 if allows_second else 1 if alternatives or re.search(r'(?:complete|pick|select|choose) one', wording, re.I) else None
    return {'required': required if required or optional or alternatives else None,
            'max_selections': maximum, 'text': text}


def build_catalog(records, catalog_year, generation):
    by_url = {canonical_reference(r['source_url']): r for r in records}
    programs = []
    unresolved = []
    for program in records:
        if program['kind'] != 'program':
            continue
        sections = program['sections']
        groups = []
        seen_groups = set()
        for section in sections:
            if not ('concentr' in section['title'].lower() or section['title'] == 'Program Options'):
                continue
            option_links = [link for entry in section['entries'] if entry['kind'] == 'list'
                            for link in entry.get('links', []) if link.get('text')]
            # Catalog occasionally splits a single option into adjacent anchors.
            merged_links = {}
            for link in option_links:
                if link['url'] in merged_links and merged_links[link['url']]['text'] != link['text']:
                    merged_links[link['url']]['text'] += ' ' + link['text']
                else:
                    merged_links[link['url']] = dict(link)
            option_links = list(merged_links.values())
            if not option_links:
                continue
            options = []
            seen_options = set()
            for link in option_links:
                target_url, fragment = urldefrag(link['url'].strip())
                source = by_url.get(canonical_reference(target_url))
                label = clean(link['text'])
                alternative = bool(re.search(r'electives option|no concentration', label, re.I))
                if source and source['kind'] == 'concentration':
                    blocks = source['sections']
                    label = source['title']
                    matched_by = 'document'
                elif source and source['document_id'] == program['document_id'] and fragment:
                    candidates = [i for i, s in enumerate(sections)
                                  if unquote(fragment) in s.get('anchor_ids', [])]
                    matched_by = 'anchor'
                    if not candidates:
                        # Compatibility with snapshots predating anchor preservation.
                        candidates = [i for i, s in enumerate(sections) if name_key(s['title']) == name_key(label)]
                        matched_by = 'heading'
                    if len(candidates) != 1:
                        unresolved.append({'program_id': program['major'], 'label': label, 'source_url': link['url'],
                                           'reason': 'Missing or ambiguous inline requirement heading'})
                        continue
                    blocks = section_block(sections, candidates[0])
                else:
                    unresolved.append({'program_id': program['major'], 'label': label, 'source_url': link['url'],
                                       'reason': 'Requirement document was not collected'})
                    continue
                option_id = identity(program['major'] + '|' + canonical_reference(target_url) + '#' + fragment)
                if option_id in seen_options:
                    continue
                seen_options.add(option_id)
                annotations = [item for entry in section['entries'] for item in entry.get('items', [])
                               if name_key(label) in name_key(item)]
                options.append({'id': option_id, 'name': label, 'kind': 'alternative' if alternative else 'concentration',
                                'secondary_only': any('only as a second concentration' in item.lower() for item in annotations),
                                'notes': annotations, 'source_url': link['url'].strip(), 'catalog_year': catalog_year,
                                'match_method': matched_by, 'sections': blocks, 'source_text': source_text(blocks),
                                'courses': explicit_courses(blocks), 'semantics_validated': False})
            if not options:
                continue
            group_key = tuple(o['id'] for o in options)
            if group_key in seen_groups:
                continue
            seen_groups.add(group_key)
            groups.append({'id': identity(program['major'] + '|' + section['title']), 'title': section['title'],
                           'policy': policy(section, options), 'options': options, 'fixed': False})

        # Concentrations that are built into a named degree, not separately chosen.
        fixed_name = re.search(r'\bwith Concentration in (.+?)(?:,\s*B[A-Za-z]+)', program['title'], re.I)
        if fixed_name:
            label = fixed_name[1]
            option_id = identity(program['major'] + '|fixed')
            groups.insert(0, {'id': option_id, 'title': 'Included concentration', 'fixed': True,
                             'policy': {'required': True, 'max_selections': 1, 'text': 'Included in this degree program.'},
                             'options': [{'id': option_id, 'name': label, 'kind': 'concentration', 'secondary_only': False,
                                          'notes': [], 'source_url': program['source_url'], 'catalog_year': catalog_year,
                                          'match_method': 'program_title', 'sections': sections,
                                          'source_text': source_text(sections), 'courses': explicit_courses(sections),
                                          'semantics_validated': False}]})
        elif not groups:
            for i, section in enumerate(sections):
                if not re.search(r'^Concentration in |\bConcentration\s*(?:\(Optional\))?$', section['title'], re.I):
                    continue
                blocks = section_block(sections, i)
                if not explicit_courses(blocks):
                    continue
                option_id = identity(program['major'] + '|' + section['title'])
                optional = 'optional' in section['title'].lower()
                label = re.sub(r'^Concentration in |\s+Concentration\s*(?:\(Optional\))?$', '', section['title'], flags=re.I)
                groups.append({'id': option_id, 'title': 'Optional concentration' if optional else 'Included concentration',
                               'fixed': not optional,
                               'policy': {'required': not optional, 'max_selections': 1, 'text': ''},
                               'options': [{'id': option_id, 'name': label, 'kind': 'concentration', 'secondary_only': False,
                                            'notes': [], 'source_url': program['source_url'], 'catalog_year': catalog_year,
                                            'match_method': 'heading', 'sections': blocks, 'source_text': source_text(blocks),
                                            'courses': explicit_courses(blocks), 'semantics_validated': False}]})
        programs.append({'program_id': program['major'], 'title': program['title'], 'major_name': program['major_name'],
                         'degree': program['degree'], 'campus': program['campus'], 'college': program['college'],
                         'source_url': program['source_url'], 'groups': groups})
    return {'schema_version': 1, 'complete': True, 'catalog_year': catalog_year,
            'requirements_generation': generation, 'semantics_validated': False, 'programs': programs,
            'program_count': sum(bool(p['groups']) for p in programs),
            'option_count': sum(len(g['options']) for p in programs for g in p['groups']),
            'unresolved_options': unresolved,
            'unresolved_requirement_links': [{'program_id': r.get('major'), **link}
                                             for r in records for link in r.get('unresolved_requirement_links', [])]}


def export_catalog(catalog):
    """Store shared business requirements once, keeping program eligibility separate."""
    definitions = {}
    programs = []
    for program in catalog['programs']:
        groups = []
        for group in program['groups']:
            options = []
            for option in group['options']:
                requirement_id = identity(option['source_url'].strip().rstrip('/'))
                definitions[requirement_id] = {key: option[key] for key in ('sections', 'source_text', 'courses')}
                options.append({**{key: value for key, value in option.items() if key not in ('sections', 'source_text', 'courses')},
                                'requirements_id': requirement_id})
            groups.append({**group, 'options': options})
        programs.append({**program, 'groups': groups})
    return {**catalog, 'programs': programs, 'requirements': definitions}


def read_requirements(data_dir):
    root = Path(data_dir).resolve()
    manifest = json.loads((root / 'requirements_catalog.json').read_text())
    if not manifest.get('complete') or manifest.get('errors'):
        raise ValueError('Requirements snapshot is incomplete')
    records = []
    expected = root / 'requirements' / manifest['catalog_year'] / manifest['generation']
    for document in manifest['documents']:
        path = (root / document['file']).resolve()
        if path.parent != expected:
            raise ValueError('Requirement file is outside the selected snapshot')
        record = json.loads(path.read_text())
        if record['catalog_year'] != manifest['catalog_year'] or record['document_id'] != document['document_id']:
            raise ValueError('Requirement snapshot metadata does not match its document')
        records.append(record)
    return manifest, records


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=DATA_DIR)
    args = parser.parse_args(argv)
    manifest, records = read_requirements(args.data_dir)
    catalog = build_catalog(records, manifest['catalog_year'], manifest['generation'])
    write_json(args.data_dir / 'concentration_catalog.json', export_catalog(catalog))
    print(f"Concentrations: {catalog['program_count']} programs, {catalog['option_count']} options, "
          f"{len(catalog['unresolved_options'])} unresolved links ({catalog['catalog_year']})")


if __name__ == '__main__':
    main()
