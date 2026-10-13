"""Index explicit requirement rows without turning alternatives into obligations."""

import re


def browse_sections(sections, courses, matches=None):
    """Build ordered, clickable requirement trees. Keep matching OR bundles whole.

    Only source-parsed operators become AND/OR groups; ambiguous expressions
    retain their original wording alongside individually browsable courses.
    """
    def expression(row):
        def hydrate(node):
            if node['kind'] == 'course':
                code = node['course']
                return {'kind': 'course', 'code': code, 'course': courses.get(code)}
            return {'kind': node['kind'], 'children': [hydrate(c) for c in node['children']]}
        if row.get('expression'):
            return hydrate(row['expression'])
        return {'kind': 'unparsed', 'text': row['text'], 'children': [
            {'kind': 'course', 'code': code, 'course': courses.get(code)} for code in row['courses']]}

    def codes(node):
        if node['kind'] == 'course':
            return {node['code']}
        return set().union(*(codes(c) for c in node.get('children', [])))

    result = []
    for section in sections:
        entries = []
        for entry in section['entries']:
            if entry['kind'] != 'course_table':
                entries.append({'kind': 'text', 'text': entry['text']})
                continue
            rows = entry['rows']
            nodes = []
            index = 0
            while index < len(rows):
                row = rows[index]
                if row['kind'] != 'course':
                    nodes.append({'kind': row['kind'], 'text': row['text']})
                    index += 1
                    continue
                node = expression(row)
                group = row.get('alternative_group')
                if group is not None:
                    children = [node]
                    while index + 1 < len(rows) and rows[index + 1].get('alternative_group') == group:
                        index += 1
                        children.append(expression(rows[index]))
                    node = {'kind': 'any_of', 'children': children}
                nodes.append(node)
                index += 1
            if matches is not None:
                # Keep the header/instructions preceding each retained course
                # unit, rather than unrelated subsection headings.
                pending = []
                kept = []
                for node in nodes:
                    if node['kind'] not in ('course', 'any_of', 'all_of', 'unparsed'):
                        if node['kind'] == 'header':
                            pending = []
                        pending.append(node)
                    elif codes(node) & matches:
                        kept.extend(pending)
                        pending = []
                        kept.append(node)
                nodes = kept
            entries.extend(nodes)
        if entries and (matches is None or any(codes(e) & matches for e in entries)):
            result.append({'title': section['title'], 'entries': entries})
    return result


def course_contexts(sections):
    """Retain each course's section, instruction, and complete OR expressions.

    Bundles stay intact (A and B OR C and D). Subject/level pools are not
    expanded, and instructions do not imply every candidate is required.
    """
    result = {}
    for section in sections:
        for entry in section['entries']:
            if entry['kind'] != 'course_table':
                continue
            alternatives = {}
            for row in entry['rows']:
                if row['kind'] == 'course' and 'alternative_group' in row:
                    alternatives.setdefault(row['alternative_group'], []).append(re.sub(r'^or\s+', '', row['code_text']))
            instruction = ''
            area = ''
            for row in entry['rows']:
                if row['kind'] == 'header':
                    area, instruction = row['text'], ''
                elif row['kind'] in ('instruction', 'elective_filter'):
                    instruction = row['text']
                elif row['kind'] == 'course':
                    choices = alternatives.get(row.get('alternative_group'), [])
                    if choices:
                        choice_text = 'Choose one: ' + ' or '.join(choices)
                    elif (row.get('expression') or {}).get('kind') == 'any_of':
                        choice_text = 'Choose one: ' + row['code_text']
                    else:
                        choice_text = ''
                    context = {'section': section['title'], 'area': area, 'instruction': instruction,
                               'choice_text': choice_text, 'row_text': row['text']}
                    for code in row['courses']:
                        result.setdefault(code, [])
                        if context not in result[code]:
                            result[code].append(context)
    return result


def major_sections(record, program):
    """Core major rows exclude selectable inline curricula/concentrations.

    Fixed concentrations remain part of their named degree. Selectable blocks
    are available through the concentration view, including no-concentration
    and electives alternatives.
    """
    excluded = {id(section) for group in program['groups'] if not group['fixed']
                for option in group['options'] for section in option['sections']}
    return [section for section in record['sections'] if id(section) not in excluded]
