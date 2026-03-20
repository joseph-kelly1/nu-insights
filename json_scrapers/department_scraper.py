"""
Department Scraper — Northeastern Course Catalog

Scrapes the A-Z department index from the Northeastern catalog and saves
a list of department names and codes to data/departments.json.

Usage:
  pip install requests beautifulsoup4
  python json_scrapers/department_scraper.py

Output:
  data/departments.json — [{"name": "Computer Science", "code": "CS"}, ...]
"""

import requests
from bs4 import BeautifulSoup
import json
import re
import os

def scrape(url):
    """Fetch the catalog A-Z index page and extract raw department name strings from the list."""
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')

    index = soup.find(id='atozindex')
    department_links = index.find_all('li')

    departments = []
    for department in department_links:
        text = re.search(r'>([^<>]+)</a>', str(department))
        if text:
            departments.append(text.group(1).strip())

    return departments

def add_departments(departments):
    """Parse raw department strings into structured dicts with 'name' and 'code' fields.
    CPS (College of Professional Studies) departments are skipped."""

    department_list = []

    for department in departments:
        # Skip CPS departments
        if 'CPS' in department:
            print(department)
            continue

        match = re.search(r'\(([^()]+)\)\s*$', department)
        if match:
            department_code = match.group(1).strip()
            department_name = department[:match.start()].strip()
        else:
            raise ValueError(f"Could not find department name and code in {department}")

        department_data = {
            "name": department_name,
            "code": department_code,
        }
        # print(department_data)
        department_list.append(department_data)

    return department_list

def save_to_json(departments):
    """Write the department list to data/departments.json."""
    filename = os.path.join(os.path.dirname(__file__), '..', 'data', 'departments.json')
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(departments, f, ensure_ascii=False, indent=2)

def main():
    """Scrape departments from the catalog index and save to JSON."""
    departments = scrape("https://catalog.northeastern.edu/course-descriptions/")
    department_data = add_departments(departments)
    save_to_json(department_data)

if __name__ == '__main__':
    main()