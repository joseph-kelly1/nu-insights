"""
SQLite Database Loader for NEU Course Data

Reads the scraped JSON files produced by the json_scrapers/ scripts
(departments, per-department course files, and sample plans of study)
and loads them into a normalized SQLite database (courses.db).

Usage:
  python db_loader.py

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
"""

import json
import os
import sqlite3

# --- Configuration: adjust these paths to match your repo ---
DEPARTMENTS_FILE = "data/departments.json"
COURSES_DIR = "data/courses"
DB_FILE = "courses.db"


def create_tables(cur: sqlite3.Cursor):
    """Drop and recreate all tables and indexes. This is a destructive reset."""

    cur.executescript("""
        DROP TABLE IF EXISTS courses;
        DROP TABLE IF EXISTS departments;
        DROP TABLE IF EXISTS course_corequisites;
        DROP TABLE IF EXISTS course_attributes;

        CREATE TABLE departments (
            code        TEXT PRIMARY KEY,
            name        TEXT NOT NULL
        );

        CREATE TABLE courses (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            department_code TEXT NOT NULL,
            number          TEXT NOT NULL,
            title           TEXT NOT NULL,
            credits         REAL,
            description     TEXT,
            prerequisites   TEXT,  -- stored as JSON (preserves AND/OR tree)
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
            year            INTEGER NOT NULL,
            term            TEXT NOT NULL,
            course_code     TEXT,
            is_coop         INTEGER DEFAULT 0,
            note            TEXT
        );

        CREATE INDEX idx_courses_dept ON courses(department_code);
        CREATE INDEX idx_courses_credits ON courses(credits);
        CREATE INDEX idx_attributes_attr ON course_attributes(attribute);
        CREATE INDEX idx_plan_course ON plan_entries(course_code);
        CREATE INDEX idx_plan_major ON plan_entries(major);
    """)


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
            if isinstance(credits, dict):
                credits = credits.get("max", credits.get("min"))

            cur.execute(
                """INSERT INTO courses
                   (department_code, number, title, credits, description, prerequisites)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    dept_code,
                    course["number"],
                    course["title"],
                    credits,
                    course.get("description"),
                    prereqs_json,
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


def load_plans(cur: sqlite3.Cursor):
    """Load sample plans of study from data/plans/*.json into plan_entries.
    Each plan file contains semesters with course lists, co-op markers, and notes."""

    plans_dir = os.path.join(os.path.dirname(DEPARTMENTS_FILE), "plans")

    if not os.path.exists(plans_dir):
        print("  No plans/ directory found, skipping.")
        return

    total = 0

    for filename in sorted(os.listdir(plans_dir)):
        if not filename.endswith(".json"):
            continue

        filepath = os.path.join(plans_dir, filename)

        with open(filepath, "r") as f:
            data = json.load(f)

        major = data["major"]
        major_name = data["major_name"]

        for plan in data["plans"]:
            plan_name = plan["plan_name"]

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
                    continue

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

        print(f"  {filename}: {major_name} ({len(data['plans'])} plan(s))")

    print(f"  Total: {total} plan entries loaded")


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
    conn.commit()

    verify(cur)

    conn.close()
    print(f"\nDone! Database saved to {DB_FILE}")