"""
Course Scraper — Northeastern Course Catalog

Iterates over every department page on the Northeastern catalog and scrapes
individual course data including title, credits, description, prerequisites
(parsed into an AND/OR tree), corequisites, and NUpath attributes.

Usage:
  pip install requests beautifulsoup4 tqdm
  python json_scrapers/course_scraper.py

Output:
  data/courses/<dept>.json for each department, e.g.:
    {"department": "cs", "courses": [{"number": "2500", "title": "...", ...}, ...]}
"""

import requests
from bs4 import BeautifulSoup
import re
import os
import json
from tqdm import tqdm

def clean_text(text):
    """Replace non-breaking spaces with regular spaces and strip whitespace."""
    return text.replace('\xa0', ' ').strip()

def get_code(department):
    """Extract the department code (e.g. 'CS') from a string like 'Computer Science (CS)'."""
    match = re.search(r'\(([^()]+)\)\s*$', department)
    if match:
        return match.group(1).strip()
    else:
        raise ValueError(f"Could not find department code in {department}")


def scrape_department(url, failed_courses):
    """Scrape all courses from a single department page. Returns a dict with
    'department' code and 'courses' list, or None for CPS departments.
    Courses that fail to parse are appended to failed_courses."""
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')

    department = clean_text(soup.find('h1').text)

    if department:
        if 'CPS' not in department:
            department_code = get_code(department)
        else:
            # Skip CPS departments by throwing an exception
            # print(f"Skipping {department} department due to CPS")
            return None


    course_data = {
        "department": department_code,
        "courses": []
    }

    course_blocks = soup.find_all('div', class_='courseblock')

    for block in course_blocks:
        title_block = block.find('p', class_='courseblocktitle')
        if not title_block:
            continue

        strong_text = clean_text(title_block.find('strong').get_text())

        course_info = re.search(r'(\w+)\s+(\d+)\.?\s+(.*?)\.?\s+\((\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?)\s+Hours?\)', strong_text)

        if not course_info:
            failed_courses.append(strong_text)
            continue

        number = course_info.group(2).strip()
        title = course_info.group(3).strip()

        if title == "Elective":
            continue

        credits_text = course_info.group(4).strip()
        if '-' in credits_text:
            min_credits, max_credits = map(float, credits_text.split('-'))
            credits = {
                "min": min_credits,
                "max": max_credits
            }
        else:
            credits = float(credits_text)

        desc_block = block.find('p', class_='cb_desc')
        description = clean_text(desc_block.get_text()) if desc_block else ""

        prerequisites = []
        corequisites = []
        attributes = []

        block_extra = block.find_all('p', class_='courseblockextra')
        for block in block_extra:
            block_text = clean_text(block.get_text())

            if 'Prerequisite(s):' in block_text:
                parsed = format_prerequisites(block_text)
                if parsed:
                    prerequisites = parsed

            elif 'Corequisite(s):' in block_text:
                formatted_corequisites = format_corequisites(block_text)
                corequisites.extend(formatted_corequisites)

            elif 'Attribute(s):' in block_text:
                attr_content = block_text.split('Attribute(s):', 1)[1].strip()
                attributes = [attr.strip() for attr in attr_content.split(',') if attr.strip()]

        course_data["courses"].append({
            "number": number,
            "title": title,
            "credits": credits,
            "description": description,
            "prerequisites": prerequisites,
            "corequisites": corequisites,
            "attributes": attributes
        })

    return course_data

import re


def format_prerequisites(prerequisite):
    """Parse a raw prerequisite string into a nested AND/OR tree structure.
    Semicolons are treated as AND; 'or'/'and' keywords are normalized.
    Returns a dict tree, e.g. {"type": "AND", "courses": [{"course": "CS 2500"}, ...]}."""
    raw = prerequisite.split('Prerequisite(s):', 1)[1].strip()

    # Standardize spacing and logical operators
    raw = re.sub(r'\s*;\s*', ' AND ', raw)
    raw = re.sub(r'\s*\bor\b\s*', ' OR ', raw, flags=re.IGNORECASE)
    raw = re.sub(r'\s*\band\b\s*', ' AND ', raw, flags=re.IGNORECASE)
    raw = re.sub(r'\s+', ' ', raw).strip()

    # Start recursive parsing
    return parse_logic(raw)

def parse_logic(expression):
    """Recursively parse a logical expression into a tree of AND/OR nodes
    and leaf nodes (course codes or admission requirements)."""
    expression = expression.strip()
    if expression.startswith('(') and expression.endswith(')'):
        # Remove outermost parentheses only if they wrap the entire expression
        inner = expression[1:-1].strip()
        if balanced_parentheses(inner):
            return parse_logic(inner)

    # Try to split by top-level OR or AND
    for operator in [' OR ', ' AND ']:
        parts = split_top_level(expression, operator)
        if len(parts) > 1:
            return {
                "type": operator.strip(),
                "courses": [parse_logic(part) for part in parts]
            }

    # Leaf node: course or requirement
    course_match = re.search(r'([A-Z]{2,4})\s+(\d{4})', expression)
    if course_match:
        return {"course": f"{course_match.group(1)} {course_match.group(2)}"}

    return {"admission_requirement": expression.strip()}

def split_top_level(text, delimiter):
    """Split text by a delimiter, but only at the top level (outside parentheses)."""
    parts = []
    bracket_level = 0
    current = ''
    i = 0
    while i < len(text):
        char = text[i]
        if char == '(':
            bracket_level += 1
        elif char == ')':
            bracket_level -= 1

        if bracket_level == 0 and text[i:i+len(delimiter)] == delimiter:
            parts.append(current.strip())
            current = ''
            i += len(delimiter)
            continue

        current += char
        i += 1

    if current:
        parts.append(current.strip())
    return parts

def balanced_parentheses(text):
    """Return True if parentheses in text are balanced."""
    count = 0
    for char in text:
        if char == '(':
            count += 1
        elif char == ')':
            count -= 1
            if count < 0:
                return False
    return count == 0


def format_corequisites(corequisite):
    """Extract corequisite course codes (e.g. 'CS 2501') from a raw corequisite string."""
    coreq_content = corequisite.split('Corequisite(s):', 1)[1].strip()

    formatted_coreqs = re.findall(r'([A-Z]+\s+\d+)', coreq_content)
    return formatted_coreqs

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def save_to_json(data, department_code):
    """Write a department's course data to data/courses/<dept>.json."""
    out_dir = os.path.join(SCRIPT_DIR, '..', 'data', 'courses')
    os.makedirs(out_dir, exist_ok=True)

    filename = os.path.join(out_dir, f'{department_code.lower()}.json')
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # print(f"Scraped {len(data['courses'])} courses from {data['department']} department")

def get_department_urls():
    """Fetch the catalog index page and return a list of full URLs for each department page."""
    url = "https://catalog.northeastern.edu/course-descriptions/"
    response = requests.get(url)

    soup = BeautifulSoup(response.text, 'html.parser')
    index = soup.find(id='atozindex')

    departments = []

    if index:
        department_links = index.find_all('li')

        for link in department_links:
            a_tag = link.find('a')
            if a_tag and 'href' in a_tag.attrs:
                relative_url = a_tag['href']
                full_url = f"https://catalog.northeastern.edu{relative_url}"
                departments.append(full_url)

    return departments


def main():
    """Scrape all departments and save per-department course JSON files."""
    departments = get_department_urls()
    failed_courses = []

    for url in tqdm(departments, desc="Scraping departments"):
        try:
            course_data = scrape_department(url, failed_courses)
            if course_data:
                save_to_json(course_data, course_data["department"])
        except Exception as e:
            tqdm.write(f"Error scraping {url}: {e}")

    if failed_courses:
        print(f"\nCould not parse {len(failed_courses)} course(s):")
        for title in failed_courses:
            print(f"  - {title}")


if __name__ == '__main__':
    main()