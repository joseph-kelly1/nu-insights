"""
Course Advisor — Flask API Backend

Serves REST endpoints for the React frontend to search, browse, and get
AI-powered analysis of Northeastern University courses. Course data is
read from a local SQLite database (courses.db) populated by db_loader.py.
AI analysis is powered by the Gemini API with automatic model fallback
on rate-limit errors.

Setup:
  pip install flask flask-cors google-genai
  export GEMINI_API_KEY="your-key-here"
  python3 advisor.py

Endpoints:
  GET  /api/search?q=<query>        Search courses by dept code, number, or title
  GET  /api/course/<dept>/<number>   Get full course details (prereqs, coreqs, attributes, schedule context)
  POST /api/analyze                  AI-generated course breakdown (summary, audience, skills, career relevance)
  GET  /api/health                   Health check; returns current Gemini model in use
"""

import json
import os
import sqlite3
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_cors import CORS
from google import genai

load_dotenv()

# --- Configuration ---
API_KEY = os.environ.get("GEMINI_API_KEY")
DB_FILE = "courses.db"


MODEL_FALLBACK_CHAIN = [
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]

_current_model_index = 0

ai_client = genai.Client(api_key=API_KEY)

app = Flask(__name__)
CORS(app)  # allows React dev server to call the API


# --- Database helpers ---

def get_connection() -> sqlite3.Connection:
    """Open a connection to the SQLite courses database with Row factory enabled."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def lookup_course(dept: str, number: str) -> dict | None:
    """Fetch a single course by department code and number, including its corequisites,
    NUpath attributes, and parsed prerequisite tree. Returns None if not found."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """SELECT id, department_code, number, title, credits, description, prerequisites
           FROM courses WHERE department_code = ? AND number = ?""",
        (dept.lower(), number),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return None

    course = dict(row)

    cur.execute(
        "SELECT corequisite FROM course_corequisites WHERE course_id = ?",
        (course["id"],),
    )
    course["corequisites"] = [r["corequisite"] for r in cur.fetchall()]

    cur.execute(
        "SELECT attribute FROM course_attributes WHERE course_id = ?",
        (course["id"],),
    )
    course["attributes"] = [r["attribute"] for r in cur.fetchall()]

    if course["prerequisites"]:
        course["prerequisites"] = json.loads(course["prerequisites"])
    else:
        course["prerequisites"] = []

    conn.close()
    return course


def search_courses(query: str) -> list[dict]:
    """Search courses by department code, department + number prefix, or title substring.
    Returns up to 20 matching courses with basic info (dept, number, title, credits)."""
    conn = get_connection()
    cur = conn.cursor()

    # Check if query looks like a course code, e.g. "cs 2100", "CS2100", "cs"
    parts = query.strip().split()
    if len(parts) == 2 and parts[0].isalpha() and parts[1].isdigit():
        # Dept + number: exact or prefix match on number
        cur.execute(
            """SELECT department_code, number, title, credits
               FROM courses
               WHERE department_code = ? AND number LIKE ?
               ORDER BY number LIMIT 20""",
            (parts[0].lower(), f"{parts[1]}%"),
        )
    elif len(parts) == 1 and parts[0].isalpha() and len(parts[0]) <= 4:
        # Just a department code like "cs"
        cur.execute(
            """SELECT department_code, number, title, credits
               FROM courses
               WHERE department_code = ?
               ORDER BY number LIMIT 20""",
            (parts[0].lower(),),
        )
    else:
        # General title search
        cur.execute(
            """SELECT department_code, number, title, credits
               FROM courses WHERE title LIKE ?
               ORDER BY department_code, number LIMIT 20""",
            (f"%{query}%",),
        )

    results = [dict(r) for r in cur.fetchall()]
    conn.close()
    return results


def lookup_schedule_context(dept: str, number: str) -> list[dict]:
    """Look up which majors/plans include this course and in which year/term,
    based on official sample plans of study stored in the plan_entries table."""
    conn = get_connection()
    cur = conn.cursor()
    course_code = f"{dept.upper()} {number}"
    cur.execute(
        """SELECT major, major_name, plan_name, year, term
           FROM plan_entries WHERE course_code = ?
           ORDER BY major, plan_name, year, term""",
        (course_code,),
    )
    results = [dict(r) for r in cur.fetchall()]
    conn.close()
    return results


# --- Formatting helpers ---

def format_prereqs(prereqs) -> str:
    """Recursively flatten the prerequisite AND/OR tree into a human-readable string."""
    if not prereqs:
        return "None"
    if isinstance(prereqs, list) and len(prereqs) == 0:
        return "None"
    if isinstance(prereqs, dict):
        if "course" in prereqs:
            return prereqs["course"]
        if "type" in prereqs and "courses" in prereqs:
            joiner = f" {prereqs['type']} "
            parts = [format_prereqs(c) for c in prereqs["courses"]]
            if len(parts) > 1:
                return f"({joiner.join(parts)})"
            return parts[0]
        if "admission_requirement" in prereqs:
            return prereqs["admission_requirement"]
    return str(prereqs)


def format_schedule_context(entries: list[dict]) -> str:
    """Format plan_entries rows into a deduplicated, human-readable list for the AI prompt."""
    if not entries:
        return "No sample plan data available for this course."
    lines = []
    for e in entries:
        lines.append(
            f"- {e['major_name']} ({e['major']}), "
            f"\"{e['plan_name']}\": Year {e['year']}, {e['term']}"
        )
    return "\n".join(list(dict.fromkeys(lines)))


def build_prompt(course: dict) -> str:
    """Assemble the full text prompt sent to Gemini, including course metadata,
    prerequisite info, NUpath attributes, and sample plan schedule context."""
    code = f"{course['department_code'].upper()} {course['number']}"
    schedule = lookup_schedule_context(course["department_code"], course["number"])

    prompt = f"Course: {code} — {course['title']}\n\n"
    prompt += "=== NORTHEASTERN-SPECIFIC CONTEXT ===\n"
    prompt += f"Credits: {course['credits']}\n"
    prompt += f"Prerequisites: {format_prereqs(course['prerequisites'])}\n"
    prompt += f"Corequisites: {', '.join(course['corequisites']) or 'None'}\n"
    prompt += f"NUpath attributes: {', '.join(course['attributes']) or 'None'}\n"
    prompt += f"\nTypical semester (from sample plans of study):\n"
    prompt += format_schedule_context(schedule) + "\n"
    prompt += "=====================================\n\n"
    prompt += f"Catalog description: {course['description']}"
    return prompt


# --- AI helper with model fallback ---

def _is_rate_limit_error(exc: Exception) -> bool:
    """Check if an exception indicates a rate limit or quota exhaustion."""
    msg = str(exc).lower()
    return any(term in msg for term in ["429", "rate limit", "quota", "resource exhausted", "resource_exhausted"])


def generate_with_fallback(contents: str, system_instruction: str):
    """Try generating with the current model; on rate-limit errors, fall back to the next model."""
    global _current_model_index

    while _current_model_index < len(MODEL_FALLBACK_CHAIN):
        model = MODEL_FALLBACK_CHAIN[_current_model_index]
        try:
            return ai_client.models.generate_content(
                model=model,
                contents=contents,
                config={
                    "system_instruction": system_instruction,
                    "max_output_tokens": 2048,
                    "temperature": 0.7,
                },
            )
        except Exception as e:
            if _is_rate_limit_error(e) and _current_model_index < len(MODEL_FALLBACK_CHAIN) - 1:
                _current_model_index += 1
                print(f"Rate limited on {model}, falling back to {MODEL_FALLBACK_CHAIN[_current_model_index]}")
            else:
                raise
    return None


def get_current_model() -> str:
    """Return the name of the Gemini model currently being used."""
    return MODEL_FALLBACK_CHAIN[_current_model_index]


# --- API Routes ---

@app.route("/api/search")
def api_search():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify([])
    results = search_courses(query)
    return jsonify(results)


@app.route("/api/course/<dept>/<number>")
def api_course(dept, number):
    course = lookup_course(dept, number)
    if not course:
        return jsonify({"error": "Course not found"}), 404

    schedule = lookup_schedule_context(dept, number)
    course["schedule_context"] = schedule
    course["prerequisites_text"] = format_prereqs(course["prerequisites"])

    return jsonify(course)


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    data = request.json
    dept = data.get("dept", "")
    number = data.get("number", "")

    course = lookup_course(dept, number)
    if not course:
        return jsonify({"error": "Course not found"}), 404

    prompt = build_prompt(course)

    response = generate_with_fallback(
        contents=prompt,
        system_instruction=(
            "You are a helpful Northeastern University academic advisor. "
            "You will be given a course name, its catalog description, AND structured "
            "metadata including prerequisites, corequisites, NUpath attributes, and "
            "data from official sample plans of study showing which year and semester "
            "students typically take this course.\n\n"
            "Use ALL of the provided metadata to give accurate advice. Do NOT guess "
            "about prerequisites or when students take the course — use the sample plan "
            "data provided. If the course appears in multiple plans or majors, mention that.\n\n"
            "Provide a concise breakdown with:\n"
            "1. A plain-English summary of what the course actually covers (2-3 sentences)\n"
            "2. Who should take it — use the sample plan data to state the typical year/semester\n"
            "3. Key skills you'll walk away with\n"
            "4. How it connects to co-op or career opportunities\n\n"
            "Be honest and practical — speak like an upperclassman giving advice, not a catalog."
        ),
    )

    if response is None:
        return jsonify({"error": "All AI models exhausted. Try again later."}), 502

    return jsonify({"analysis": response.text})


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "model": get_current_model()})


if __name__ == "__main__":
    print(f"Starting Course Advisor API...")
    print(f"Model: {get_current_model()} (fallback chain: {' → '.join(MODEL_FALLBACK_CHAIN)})")
    print(f"Database: {DB_FILE}")
    print(f"http://localhost:8000")
    app.run(debug=True, port=8000)