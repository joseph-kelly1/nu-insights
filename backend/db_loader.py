"""
SQLite Database Loader for NEU Course Data

Reads the scraped JSON files produced by the json_scrapers/ scripts
(departments, per-department course files, and sample plans of study)
and loads them into a normalized SQLite database (var/courses.db).

Usage:
  python -m backend.db_loader

Expects this file structure:
  data/
    departments.json            [{"code": "cs", "name": "Computer Science"}, ...]
    courses/
      cs.json                   {"department": "cs", "courses": [{...}, ...]}
      math.json
      ...
    plans/                      (optional)
      cs.json                   {"major": "CS", "major_name": "...", "plans": [...]}
      ...

Tables created:
  departments          — department code and name
  courses              — course metadata; prerequisites stored as JSON tree
  course_corequisites  — flat list of corequisite course codes per course
  course_attributes    — NUpath attribute tags per course
  plan_entries         — rows from sample plans of study (major, year, term, course)
  programs             — one row per catalog program (stable id, display label, plan status)
  concentration_programs — current program-specific choice groups and selection policies
  concentrations       — selected source requirement blocks, including alternatives
  concentration_courses — explicit candidate course rows (not a mandatory-course list)
  plan_variants        — each sample plan exactly as published (entries, choices, co-op, credits)
  requirement_documents — shared requirement sources (NUpath, universitywide) with fingerprints
  dataset_meta         — fingerprint of the loaded inputs, so planner reports can detect a reload
"""

from collections import Counter
import hashlib
import json
import os
import re
from pathlib import Path
import sqlite3

from .paths import DATA_DIR, DB_FILE as DEFAULT_DB_FILE

DEPARTMENTS_FILE = str(DATA_DIR / 'departments.json')
COURSES_DIR = str(DATA_DIR / 'courses')
DB_FILE = str(DEFAULT_DB_FILE)


def create_tables(cur: sqlite3.Cursor):
    """Drop and recreate all tables and indexes. This is a destructive reset."""

    cur.executescript("""
        DROP TABLE IF EXISTS courses;
        DROP TABLE IF EXISTS departments;
        DROP TABLE IF EXISTS course_corequisites;
        DROP TABLE IF EXISTS course_attributes;
        DROP TABLE IF EXISTS plan_entries;
        DROP TABLE IF EXISTS plan_catalog;
        DROP TABLE IF EXISTS programs;
        DROP TABLE IF EXISTS concentration_programs;
        DROP TABLE IF EXISTS concentration_courses;
        DROP TABLE IF EXISTS concentrations;
        DROP TABLE IF EXISTS program_requirements;
        DROP TABLE IF EXISTS program_courses;
        DROP TABLE IF EXISTS plan_variants;
        DROP TABLE IF EXISTS requirement_documents;
        DROP TABLE IF EXISTS dataset_meta;

        CREATE TABLE departments (
            code        TEXT PRIMARY KEY,
            name        TEXT NOT NULL
        );

        CREATE TABLE courses (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            department_code TEXT NOT NULL,
            number          TEXT NOT NULL,
            title           TEXT NOT NULL,
            credits         REAL,  -- browsing display only; planning uses credit_options
            credit_options  TEXT,  -- JSON {"values": [...]} or {"min", "max"}; NULL when unknown
            description     TEXT,
            prerequisites   TEXT,  -- stored as JSON (preserves AND/OR tree)
            prerequisites_text TEXT,  -- catalog wording, NULL in datasets scraped before it was kept
            corequisites_text  TEXT,
            catalog_year    TEXT,
            FOREIGN KEY (department_code) REFERENCES departments(code),
            UNIQUE(department_code, number)
        );

        CREATE TABLE course_corequisites (
            course_id       INTEGER NOT NULL,
            corequisite     TEXT NOT NULL,
            FOREIGN KEY (course_id) REFERENCES courses(id)
        );

        CREATE TABLE course_attributes (
            course_id       INTEGER NOT NULL,
            attribute       TEXT NOT NULL,
            FOREIGN KEY (course_id) REFERENCES courses(id)
        );

        -- Indexes for common searches
        CREATE TABLE plan_entries (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            major           TEXT NOT NULL,
            major_name      TEXT NOT NULL,
            plan_name       TEXT NOT NULL,
            year            INTEGER,
            term            TEXT NOT NULL,
            course_code     TEXT,
            is_coop         INTEGER DEFAULT 0,
            note            TEXT,
            catalog_year    TEXT,
            source_url      TEXT,
            degree          TEXT,
            campus          TEXT,
            program_title   TEXT
        );

        CREATE TABLE plan_catalog (
            catalog_year         TEXT,
            current_catalog_year TEXT,
            plan_count           INTEGER NOT NULL
        );

        -- id is plan_entries.major; label is unique so the major picker can show it alone
        CREATE TABLE programs (
            id          TEXT PRIMARY KEY,
            label       TEXT NOT NULL UNIQUE,
            major_name  TEXT NOT NULL,
            degree      TEXT,
            campus      TEXT,
            college     TEXT,
            status      TEXT NOT NULL  -- 'available' or 'no_published_plan'
        );

        CREATE INDEX idx_courses_dept ON courses(department_code);
        CREATE INDEX idx_courses_credits ON courses(credits);
        CREATE INDEX idx_attributes_attr ON course_attributes(attribute);
        CREATE INDEX idx_plan_course ON plan_entries(course_code);
        CREATE INDEX idx_plan_major ON plan_entries(major);

        CREATE TABLE concentration_programs (
            program_id TEXT PRIMARY KEY,
            catalog_year TEXT NOT NULL,
            source_url TEXT NOT NULL,
            groups_json TEXT NOT NULL
        );
        CREATE TABLE concentrations (
            id TEXT PRIMARY KEY,
            program_id TEXT NOT NULL,
            group_id TEXT NOT NULL,
            catalog_year TEXT NOT NULL,
            data_json TEXT NOT NULL
        );
        CREATE TABLE concentration_courses (
            concentration_id TEXT NOT NULL,
            course_code TEXT NOT NULL,
            PRIMARY KEY (concentration_id, course_code)
        );
        CREATE TABLE program_requirements (
            program_id TEXT PRIMARY KEY,
            catalog_year TEXT NOT NULL,
            source_url TEXT NOT NULL,
            sections_json TEXT NOT NULL,
            linked_json TEXT NOT NULL DEFAULT '[]'  -- shared requirement document ids
        );
        CREATE TABLE program_courses (
            program_id TEXT NOT NULL,
            course_code TEXT NOT NULL,
            contexts_json TEXT NOT NULL,
            PRIMARY KEY (program_id, course_code)
        );
        CREATE TABLE plan_variants (
            id TEXT PRIMARY KEY,
            program_id TEXT NOT NULL,
            name TEXT NOT NULL,
            catalog_year TEXT,
            source_url TEXT,
            plan_json TEXT NOT NULL
        );
        CREATE TABLE requirement_documents (
            document_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            catalog_year TEXT NOT NULL,
            source_url TEXT NOT NULL,
            sections_json TEXT NOT NULL
        );
        CREATE TABLE dataset_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)


def dataset_fingerprint(data_dir: Path) -> str:
    """Hash every input file the loader reads, so a reload is detectable."""
    digest = hashlib.sha256()
    for path in sorted(p for p in data_dir.rglob('*.json') if 'report' not in p.name):
        digest.update(str(path.relative_to(data_dir)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def load_departments(cur: sqlite3.Cursor):
    """Insert all departments from data/departments.json into the departments table."""

    with open(DEPARTMENTS_FILE, "r") as f:
        departments = json.load(f)

    # Adjust keys to match your actual structure
    for dept in departments:
        cur.execute(
            "INSERT INTO departments (code, name) VALUES (?, ?)",
            (dept.get("code"), dept.get("name")),
        )

    print(f"  Loaded {len(departments)} departments")


def load_courses(cur: sqlite3.Cursor):
    """Iterate over data/courses/*.json and insert each course, its corequisites,
    and NUpath attributes. Prerequisites are stored as a JSON string to preserve
    the AND/OR tree structure. Variable-credit courses store the max value."""

    total = 0

    for filename in sorted(os.listdir(COURSES_DIR)):
        if not filename.endswith(".json"):
            continue

        dept_code = filename.replace(".json", "")
        filepath = os.path.join(COURSES_DIR, filename)

        with open(filepath, "r") as f:
            data = json.load(f)

        # Handle wrapper object: {"department": "CS", "courses": [...]}
        if isinstance(data, dict):
            courses = data.get("courses", [])
        else:
            courses = data

        for course in courses:
            # Store prerequisites as JSON string to preserve the AND/OR tree
            prereqs = course.get("prerequisites")
            # Skip empty lists/dicts, keep actual prerequisite data
            prereqs_json = json.dumps(prereqs) if prereqs else None

            # Handle credits that are a range like {"min": 1.0, "max": 4.0}
            credits = course.get("credits")
            options = course.get("credit_options")
            if options is None and isinstance(credits, (int, float)):
                options = {"values": [float(credits)]}  # a single value is unambiguous
            if isinstance(credits, dict):
                credits = credits.get("max", credits.get("min"))

            cur.execute(
                """INSERT INTO courses
                   (department_code, number, title, credits, credit_options, description, prerequisites,
                    prerequisites_text, corequisites_text, catalog_year)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    dept_code,
                    course["number"],
                    course["title"],
                    credits,
                    json.dumps(options) if options else None,
                    course.get("description"),
                    prereqs_json,
                    course.get("prerequisites_text"),
                    course.get("corequisites_text"),
                    data.get("catalog_year") if isinstance(data, dict) else None,
                ),
            )

            course_id = cur.lastrowid

            # Corequisites go in their own table (simple flat list)
            for coreq in course.get("corequisites", []):
                cur.execute(
                    "INSERT INTO course_corequisites (course_id, corequisite) VALUES (?, ?)",
                    (course_id, coreq),
                )

            # Attributes (NUpath tags) go in their own table for filtering
            for attr in course.get("attributes", []):
                cur.execute(
                    "INSERT INTO course_attributes (course_id, attribute) VALUES (?, ?)",
                    (course_id, attr),
                )

            total += 1

        print(f"  {dept_code}: {len(courses)} courses")

    print(f"  Total: {total} courses loaded")


def program_labels(programs: list[dict]) -> dict:
    """Catalog titles, plus the college when a title repeats (e.g. four
    "Interdisciplinary Studies, BS (Oakland)" programs from different colleges)."""
    def title(p):
        t = p.get("program_title") or p.get("major_name") or p["major"]
        return t + ")" if t.count("(") > t.count(")") else t  # a few scraped titles lose their ")"
    counts = Counter(title(p) for p in programs)
    labels = {p["major"]: f"{title(p)} — {p['college']}" if counts[title(p)] > 1 and p.get("college") else title(p)
              for p in programs}
    duplicates = Counter(labels.values())
    # Occasionally the catalog publishes the same degree in two departments
    # within one college. Preserve both identities rather than dropping one.
    return {p['major']: f"{labels[p['major']]} ({p['major']})" if duplicates[labels[p['major']]] > 1 else labels[p['major']]
            for p in programs}


def load_programs(cur: sqlite3.Cursor, programs: list[dict]):
    programs = [p for p in programs if p.get("major")]  # an entry without an id can't be selected
    labels = program_labels(programs)
    for p in programs:
        cur.execute(
            "INSERT INTO programs (id, label, major_name, degree, campus, college, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (p["major"], labels[p["major"]], p.get("major_name") or labels[p["major"]], p.get("degree"), p.get("campus"), p.get("college"),
             p.get("status", "available")),
        )
    print(f"  Loaded {len(programs)} programs")


def load_plans(cur: sqlite3.Cursor):
    """Load sample plans of study from data/plans/*.json into plan_entries.
    Each plan file contains semesters with course lists, co-op markers, and notes."""

    plans_dir = os.path.join(os.path.dirname(DEPARTMENTS_FILE), "plans")

    catalog_file = Path(DEPARTMENTS_FILE).parent / "plan_catalog.json"
    catalog_year = None
    if catalog_file.exists():
        with catalog_file.open() as f:
            catalog = json.load(f)
        if not catalog.get("complete") or catalog.get("errors"):
            raise ValueError("Plan catalog refresh is incomplete")
        catalog_year = catalog["catalog_year"]
        programs = catalog["programs"]  # includes programs with no published plan
        files = [catalog_file.parent / program["file"]
                 for program in programs if program["status"] == "available"]
        expected_dir = (Path(plans_dir) / catalog_year).resolve()
        if any(path.resolve().parent != expected_dir for path in files):
            raise ValueError("Plan file is outside the selected catalog directory")
        cur.execute(
            "INSERT INTO plan_catalog (catalog_year, current_catalog_year, plan_count) VALUES (?, ?, ?)",
            (catalog_year, catalog.get("current_catalog_year"), catalog.get("plan_count", 0)),
        )
        print(f"  Using {catalog_year} plan catalog; {catalog['programs_without_plans']} programs have no published plan")
    else:
        if not os.path.exists(plans_dir):
            print("  No plans/ directory found, skipping.")
            return
        files = sorted(Path(plans_dir).glob("*.json"))
        programs = None

    total = 0
    file_programs = []

    for filepath in files:
        with open(filepath, "r") as f:
            data = json.load(f)
        if catalog_year and data.get("catalog_year") != catalog_year:
            raise ValueError(f"Plan catalog year mismatch in {filepath}")

        major = data["major"]
        major_name = data["major_name"]
        file_programs.append(data)

        for index, plan in enumerate(data["plans"]):
            plan_name = plan["plan_name"]
            # Some programs publish several plans under one name (e.g. per concentration); the
            # source position keeps each one distinct instead of mixing them.
            variant_id = hashlib.sha256(f"{major}|{data.get('catalog_year')}|{index}|{plan_name}".encode()).hexdigest()[:16]
            cur.execute("INSERT INTO plan_variants VALUES (?, ?, ?, ?, ?, ?)",
                        (variant_id, major, plan_name, data.get("catalog_year"), data.get("source_url"), json.dumps(plan)))

            for semester in plan["semesters"]:
                year = semester["year"]
                term = semester["term"]
                is_coop = 1 if semester.get("is_coop") else 0

                if is_coop:
                    cur.execute(
                        """INSERT INTO plan_entries
                           (major, major_name, plan_name, year, term, is_coop)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (major, major_name, plan_name, year, term, 1),
                    )
                    total += 1

                for course in semester.get("courses", []):
                    cur.execute(
                        """INSERT INTO plan_entries
                           (major, major_name, plan_name, year, term, course_code)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (major, major_name, plan_name, year, term, course),
                    )
                    total += 1

                for note in semester.get("notes", []):
                    cur.execute(
                        """INSERT INTO plan_entries
                           (major, major_name, plan_name, year, term, note)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (major, major_name, plan_name, year, term, note),
                    )
                    total += 1

        cur.execute(
            "UPDATE plan_entries SET catalog_year = ?, source_url = ?, degree = ?, campus = ?, program_title = ? WHERE major = ?",
            (data.get("catalog_year"), data.get("source_url"), data.get("degree"), data.get("campus"), data.get("program_title"), major),
        )
        print(f"  {filepath.name}: {major_name} ({len(data['plans'])} plan(s))")

    load_programs(cur, programs if programs is not None else file_programs)
    print(f"  Total: {total} plan entries loaded")


def load_concentrations(cur: sqlite3.Cursor):
    """Load current concentration choices, independent of historical plan coverage.

    Always derive from the selected requirements snapshot so refreshing requirements
    cannot leave a stale concentration file active. The JSON catalog is an export.
    """
    from json_scrapers.concentration_scraper import build_catalog, read_requirements
    from json_scrapers.requirement_courses import course_contexts, major_sections
    data_dir = Path(DEPARTMENTS_FILE).resolve().parent
    if not (data_dir / 'requirements_catalog.json').exists():
        return
    manifest, records = read_requirements(data_dir)
    catalog = build_catalog(records, manifest['catalog_year'], manifest['generation'])
    records_by_id = {r['document_id']: r for r in records}
    # Archived plans hash their archived URL. Match the exact catalog path, not
    # the degree title, so saved majors and historical placements keep their ID.
    def current_source(url):
        return re.sub(r'/archive/\d{4}-\d{4}/', '/', url.strip()).rstrip('/')
    plan_file = data_dir / 'plan_catalog.json'
    plan_sources = {}
    if plan_file.exists():
        plan_manifest = json.loads(plan_file.read_text())
        plan_sources = {current_source(p['source_url']): p['major'] for p in plan_manifest['programs'] if p.get('source_url')}
    existing = {r[0]: dict(zip(('major', 'program_title', 'major_name', 'degree', 'campus', 'college', 'status'), r))
                for r in cur.execute('SELECT id, label, major_name, degree, campus, college, status FROM programs')}
    for program in catalog['programs']:
        program_id = plan_sources.get(current_source(program['source_url']), program['program_id'])
        previous = existing.get(program_id, {})
        existing[program_id] = {
            'major': program_id, 'program_title': program['title'], 'major_name': program['major_name'],
            'degree': program['degree'], 'campus': program['campus'], 'college': program['college'],
            'status': previous.get('status', 'no_published_plan'),
        }
        cur.execute('INSERT INTO concentration_programs VALUES (?, ?, ?, ?)',
                    (program_id, catalog['catalog_year'], program['source_url'], json.dumps(program['groups'])))
        record = records_by_id[program['program_id']]
        sections = major_sections(record, program)
        linked = [link['document_id'] for link in record.get('linked_requirements', []) if link.get('kind') == 'shared']
        cur.execute('INSERT INTO program_requirements VALUES (?, ?, ?, ?, ?)',
                    (program_id, catalog['catalog_year'], program['source_url'], json.dumps(sections),
                     json.dumps(linked)))
        contexts = course_contexts(sections)
        cur.executemany('INSERT INTO program_courses VALUES (?, ?, ?)',
                        [(program_id, code, json.dumps(context)) for code, context in contexts.items()])
        for group in program['groups']:
            for option in group['options']:
                cur.execute('INSERT INTO concentrations VALUES (?, ?, ?, ?, ?)',
                            (option['id'], program_id, group['id'], catalog['catalog_year'], json.dumps(option)))
                cur.executemany('INSERT INTO concentration_courses VALUES (?, ?)',
                                [(option['id'], code) for code in option['courses']])
    for record in records:
        if record['kind'] == 'shared':
            cur.execute('INSERT INTO requirement_documents VALUES (?, ?, ?, ?, ?, ?)',
                        (record['document_id'], record['kind'], record['title'], record['catalog_year'],
                         record['source_url'], json.dumps(record['sections'])))
    cur.execute('DELETE FROM programs')
    load_programs(cur, list(existing.values()))
    print(f"  Loaded {catalog['option_count']} concentration/program options in {catalog['program_count']} programs "
          f"({catalog['catalog_year']}); {len(catalog['unresolved_options'])} unresolved options")


def verify(cur: sqlite3.Cursor):
    """Print row counts and sample queries to sanity-check the loaded data."""

    print("\n--- Verification ---")

    cur.execute("SELECT COUNT(*) FROM departments")
    print(f"Departments: {cur.fetchone()[0]}")

    cur.execute("SELECT COUNT(*) FROM courses")
    print(f"Courses: {cur.fetchone()[0]}")

    # Sample: show CS courses with 4 credits
    print("\nSample — 4-credit CS courses:")
    cur.execute("""
        SELECT department_code || ' ' || number AS code, title
        FROM courses
        WHERE department_code = 'CS' AND credits = 4.0
        ORDER BY number
        LIMIT 5
    """)
    for row in cur.fetchall():
        print(f"  {row[0]}: {row[1]}")

    # Sample: courses with NUpath Formal/Quant Reasoning
    print("\nSample — NUpath Formal/Quant Reasoning:")
    cur.execute("""
        SELECT c.department_code || ' ' || c.number AS code, c.title
        FROM courses c
        JOIN course_attributes a ON c.id = a.course_id
        WHERE a.attribute LIKE '%Formal/Quant%'
        LIMIT 5
    """)
    for row in cur.fetchall():
        print(f"  {row[0]}: {row[1]}")


if __name__ == "__main__":
    Path(DB_FILE).parent.mkdir(parents=True, exist_ok=True)
    # Remove old DB if it exists
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
        print(f"Removed old {DB_FILE}")

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    print(f"Creating {DB_FILE}...\n")

    create_tables(cur)
    load_departments(cur)
    load_courses(cur)
    load_plans(cur)
    load_concentrations(cur)
    cur.execute("INSERT INTO dataset_meta VALUES ('fingerprint', ?)",
                (dataset_fingerprint(Path(DEPARTMENTS_FILE).parent),))
    conn.commit()

    verify(cur)

    conn.close()
    print(f"\nDone! Database saved to {DB_FILE}")
