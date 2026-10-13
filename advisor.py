"""
Course Advisor — Flask API Backend

Serves REST endpoints for the React frontend to search, browse, and get
AI-powered analysis of Northeastern University courses. Course data is
read from a local SQLite database (courses.db) populated by db_loader.py.
AI analysis uses free OpenRouter models with per-request fallback by default, or the
user's own provider key and model for a single request (see ai_providers.py).

Setup: see README.md (pip install -r requirements.txt, OPENROUTER_API_KEY in .env).

Endpoints:
  GET  /api/search?q=<query>        Search courses by dept code, number, or title
  GET  /api/course/<dept>/<number>   Get full course details (prereqs, coreqs, attributes, schedule context)
  GET  /api/programs                 List majors/programs (stable id, display label, sample-plan status)
  GET  /api/programs/<id>/concentrations Current concentration choices and source requirements
  GET  /api/programs/<id>/courses?q=&offset=  Courses in that program's sample plans, optionally narrowed by q
  POST /api/analyze                  AI-generated course breakdown (summary, audience, skills, career relevance);
                                     optional "major" and "concentrations" tailor catalog context to selected choices
  POST /api/ai/models                List models for a provider (newest 10 + all); OpenRouter needs no key
  GET  /api/health                   Health check; returns configured primary model and whether AI is configured
"""

import functools
import json
import os
import re
import sqlite3
import time
from dotenv import load_dotenv
from flask import Flask, request, jsonify
import openai

import ai_providers
from ai_providers import AIError

load_dotenv()


# --- Configuration ---

def _bool_env(name: str, default: str) -> bool:
    raw = os.environ.get(name, default).strip().lower()
    if raw not in ("true", "false"):
        raise ValueError(f"{name} must be true or false")
    return raw == "true"


def _positive_env(name: str, default: str, cast):
    value = cast(os.environ.get(name, default))
    if not value > 0:
        raise ValueError(f"{name} must be positive")
    return value


API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()
DEFAULT_MODELS = [
    "google/gemma-4-31b-it:free",
    "openrouter/free",
]
PRIMARY_MODEL = os.environ.get("OPENROUTER_MODEL", "").strip() or DEFAULT_MODELS[0]
_fallbacks = os.environ.get("OPENROUTER_FALLBACK_MODELS", ",".join(DEFAULT_MODELS[1:])).split(",")
FALLBACK_MODELS = list(dict.fromkeys(m.strip() for m in _fallbacks if m.strip() not in ("", PRIMARY_MODEL)))
if bad := [m for m in (PRIMARY_MODEL, *FALLBACK_MODELS) if not re.fullmatch(r"[\w.-]+/[\w.:-]+", m)]:
    raise ValueError(f"Malformed OpenRouter model IDs: {bad}")
REASONING_ENABLED = _bool_env("OPENROUTER_REASONING_ENABLED", "false")
MAX_TOKENS = _positive_env("OPENROUTER_MAX_TOKENS", "2048", int)
TIMEOUT_SECONDS = _positive_env("OPENROUTER_TIMEOUT_SECONDS", "35", float)
DB_FILE = "courses.db"

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024  # request bodies are tiny; this caps key/config payloads
# No CORS: the React dev server proxies /api, so the browser only ever talks to one origin.


@app.after_request
def no_store(response):
    # POST routes may carry a user's API key or a response produced with it.
    if request.method == "POST":
        response.headers["Cache-Control"] = "no-store"
    return response


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


SEARCH_LIMIT = 20


def _search_clause(query: str) -> tuple[str, tuple]:
    """Interpret a query as dept + number prefix ("cs 2100"), a dept code ("cs"), or a title substring."""
    parts = query.strip().split()
    if not parts:
        return "1", ()
    if len(parts) == 2 and parts[0].isalpha() and parts[1].isdigit():
        return "department_code = ? AND number LIKE ?", (parts[0].lower(), f"{parts[1]}%")
    if len(parts) == 1 and parts[0].isalpha() and len(parts[0]) <= 4:
        return "department_code = ?", (parts[0].lower(),)
    return "title LIKE ?", (f"%{query.strip()}%",)


def search_courses(query: str, major: str | None = None, offset: int = 0, concentrations: list[str] | None = None) -> dict:
    """Search courses, optionally only those in one program's sample plans. The program filter
    runs in SQL before LIMIT, so a page never mixes in or drops courses. Returns up to 20 rows
    with basic info (dept, number, title, credits) and the total number of matches."""
    where, params = _search_clause(query)
    if concentrations is not None:
        placeholders = ','.join('?' for _ in concentrations)
        where += (" AND upper(department_code) || ' ' || number IN"
                  f" (SELECT course_code FROM concentration_courses WHERE concentration_id IN ({placeholders}))")
        params += tuple(concentrations)
    elif major:
        # Exact program id; IN also collapses a course that appears in several terms or plans.
        where += (" AND upper(department_code) || ' ' || number IN"
                  " (SELECT course_code FROM plan_entries WHERE major = ?)")
        params += (major,)
    conn = get_connection()
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM courses WHERE {where}", params).fetchone()[0]
        rows = conn.execute(
            f"""SELECT department_code, number, title, credits FROM courses WHERE {where}
                ORDER BY department_code, number LIMIT ? OFFSET ?""",
            (*params, SEARCH_LIMIT, offset),
        ).fetchall()
    finally:
        conn.close()
    return {"results": [dict(r) for r in rows], "total": total}


def list_programs() -> list[dict]:
    """All catalog programs, A-Z by label. Empty if the database predates the programs table."""
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT id, label, major_name, degree, campus, college, status FROM programs ORDER BY label")]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def lookup_program(program_id: str) -> dict | None:
    """Resolve a program id to its canonical row, or None if unknown."""
    return next((p for p in list_programs() if p["id"] == program_id), None)


def lookup_concentration_catalog(program_id: str) -> dict:
    conn = get_connection()
    try:
        row = conn.execute('SELECT catalog_year, source_url, groups_json FROM concentration_programs WHERE program_id = ?',
                           (program_id,)).fetchone()
        if row:
            return {'available': True, 'catalog_year': row['catalog_year'], 'source_url': row['source_url'],
                    'groups': json.loads(row['groups_json']), 'semantics_validated': False}
    except sqlite3.OperationalError:
        pass  # an older database can still browse courses and plans
    finally:
        conn.close()
    return {'available': False, 'catalog_year': None, 'groups': []}


def resolve_concentrations(program: dict | None, selected) -> list[dict]:
    """Validate ownership and explicit selection restrictions before using context."""
    if not program or not isinstance(selected, list) or len(selected) > 20 or any(not isinstance(s, str) for s in selected):
        raise ValueError('Choose concentrations for your selected major.')
    if len(set(selected)) != len(selected):
        raise ValueError('Choose each concentration only once.')
    catalog = lookup_concentration_catalog(program['id'])
    groups = catalog['groups']
    allowed = {option['id']: option for group in groups for option in group['options']}
    if any(option_id not in allowed for option_id in selected):
        raise ValueError('A concentration is not available for this major and catalog year. Choose it again.')
    for group in groups:
        choices = [o for o in group['options'] if o['id'] in selected]
        maximum = group['policy']['max_selections']
        if maximum and len(choices) > maximum:
            raise ValueError(f"Choose at most {maximum} options for {group['title']}.")
        if any(o['secondary_only'] for o in choices) and not any(not o['secondary_only'] for o in choices):
            raise ValueError('This concentration is available only as a second concentration.')
        if any(o['kind'] == 'alternative' for o in choices) and len(choices) > 1:
            raise ValueError('Choose either a concentration or its electives/no-concentration alternative.')
    return [allowed[option_id] for option_id in selected]


def lookup_schedule_context(dept: str, number: str) -> list[dict]:
    """Look up which majors/plans include this course and in which year/term,
    based on official sample plans of study stored in the plan_entries table."""
    conn = get_connection()
    cur = conn.cursor()
    course_code = f"{dept.upper()} {number}"
    cur.execute(
        """SELECT major, major_name, plan_name, year, term, catalog_year, source_url, degree, campus, program_title
           FROM plan_entries WHERE course_code = ?
           ORDER BY major, plan_name, year, term""",
        (course_code,),
    )
    results = [dict(r) for r in cur.fetchall()]
    conn.close()
    return results


def lookup_plan_dataset() -> dict:
    """Read provenance from the loaded database, not a potentially newer JSON crawl."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT catalog_year, current_catalog_year, plan_count FROM plan_catalog LIMIT 1").fetchone()
        if row:
            dataset = dict(row)
        else:
            count = conn.execute("SELECT COUNT(DISTINCT major || ':' || plan_name) FROM plan_entries").fetchone()[0]
            dataset = {"catalog_year": None, "current_catalog_year": None, "plan_count": count}
        dataset["historical"] = bool(dataset["catalog_year"] and dataset["current_catalog_year"]
                                     and dataset["catalog_year"] != dataset["current_catalog_year"])
        return dataset
    finally:
        conn.close()


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
        placement = f"Year {e['year']}, {e['term']}" if e['year'] is not None else e['term']
        program = ', '.join(value for value in (e.get('degree'), e.get('campus')) if value) or e['major']
        title = e.get('program_title') or f"{e['major_name']} ({program})"
        lines.append(
            f"- {title}, "
            f"\"{e['plan_name']}\": {placement}"
            + (f" (sample plan catalog: {e['catalog_year']})" if e.get("catalog_year") else "")
        )
    return "\n".join(list(dict.fromkeys(lines)))


def build_prompt(course: dict, program: dict | None = None, concentrations: list[dict] | None = None) -> str:
    """Assemble the user prompt sent to the AI model, including course metadata,
    prerequisite info, NUpath attributes, and sample plan schedule context.
    With a program, only that program's placements are included, all of them."""
    code = f"{course['department_code'].upper()} {course['number']}"
    schedule = lookup_schedule_context(course["department_code"], course["number"])
    dataset = lookup_plan_dataset()
    if program:
        schedule = [e for e in schedule if e["major"] == program["id"]]

    prompt = f"Course: {code} — {course['title']}\n\n"
    if program:
        prompt += f"Student's major: {program['label']}\n\n"
    if concentrations:
        catalog = lookup_concentration_catalog(program['id'])
        prompt += f"=== CONCENTRATION REQUIREMENTS ({catalog['catalog_year']}) ===\n"
        prompt += ('These are source requirement options, not a validated degree audit. '
                   'Course rows may be alternatives or electives, not universally required. '
                   'Preserve counts, exclusions, overlap rules, and approvals. '
                   'Concentration data does not establish semester placement.\n')
        for group in catalog['groups']:
            if any(o['id'] in {c['id'] for c in concentrations} for o in group['options']):
                prompt += f"Selection policy: {group['policy']['text']}\n"
        for concentration in concentrations:
            listed = code in concentration['courses']
            prompt += (f"\nSelected option: {concentration['name']}\nSource: {concentration['source_url']}\n"
                       f"Course appears in an explicit course row: {listed}. Absence does not establish ineligibility.\n"
                       f"{concentration['source_text']}\n")
        prompt += '=== END CONCENTRATION REQUIREMENTS ===\n\n'
    prompt += "=== NORTHEASTERN-SPECIFIC CONTEXT ===\n"
    prompt += f"Credits: {course['credits']}\n"
    prompt += f"Prerequisites: {format_prereqs(course['prerequisites'])}\n"
    prompt += f"Corequisites: {', '.join(course['corequisites']) or 'None'}\n"
    prompt += f"NUpath attributes: {', '.join(course['attributes']) or 'None'}\n"
    prompt += f"\nTypical semester (from sample plans of study):\n"
    if dataset["catalog_year"]:
        prompt += f"Sample plan catalog: {dataset['catalog_year']}.\n"
    if dataset["historical"]:
        prompt += (f"These are historical plans; the current catalog is {dataset['current_catalog_year']}. "
                   "Describe placement as historical, not current degree requirements or eligibility.\n")
    if program and program["status"] != "available":
        prompt += f"{program['label']} has no published sample plan in this dataset, so no placement is known for this major.\n"
    elif program and not schedule:
        prompt += f"This course does not appear in the collected sample plans for {program['label']}.\n"
    else:
        if program:
            prompt += f"Only placements in {program['label']} sample plans are listed.\n"
        prompt += format_schedule_context(schedule) + "\n"
    prompt += "=====================================\n\n"
    prompt += f"Catalog description: {course['description']}"
    return prompt


# --- AI helper (OpenRouter) ---

SYSTEM_INSTRUCTION = (
    "You are a helpful Northeastern University academic advisor. "
    "You will be given a course name, its catalog description, AND structured "
    "metadata including prerequisites, corequisites, NUpath attributes, and "
    "data from official sample plans of study showing which year and semester "
    "students typically take this course.\n\n"
    "Use ALL of the provided metadata to give accurate advice. Do NOT guess "
    "about prerequisites or when students take the course — use the sample plan "
    "data provided. If the course appears in multiple plans or majors, mention that. "
    "Sample plans illustrate typical timing; they do not prove the course is offered "
    "in a given term. If sample plans are historical, identify their catalog year and "
    "do not present them as current degree requirements. If no sample plan data is provided, say so instead of inventing "
    "a year or semester.\n\n"
    "If a student's major is given, tailor the skills, connections to other courses, and "
    "co-op/career insights to that major where it is genuinely useful. The sample plan data "
    "then covers only that major. Do not claim the course is required for, counts toward, or "
    "is restricted to the major unless the provided data says so; appearing in a sample plan "
    "is historical evidence of typical timing, not a current requirement. If no placement is "
    "provided for the major, say the collected plans for that major do not include it.\n\n"
    "If selected concentration requirements are supplied, use their catalog year and source wording. "
    "Distinguish required courses from elective options, alternative curricula, and approved substitutions. "
    "Do not treat all listed courses as required, certify graduation eligibility, or infer a schedule from requirements.\n\n"
    "Provide a concise breakdown (roughly 250-400 words) with:\n"
    "1. A plain-English summary of what the course actually covers (2-3 sentences)\n"
    "2. Who should take it — use the sample plan data to state the typical year/semester\n"
    "3. Key skills you'll walk away with\n"
    "4. How it connects to co-op or career opportunities\n\n"
    "Be honest and practical — speak like an upperclassman giving advice, not a catalog."
)


def _upstream_error(status, retry_after: int | None = None) -> AIError:
    """Map an OpenRouter HTTP status or embedded error code to a safe AIError."""
    if status == 429:
        return AIError(429, "rate_limited", "The free AI models are rate-limited right now. Try again in a minute.", retry_after)
    if status in (401, 402):
        return AIError(503, "ai_misconfigured", "AI analysis is unavailable due to a server configuration problem.")
    if status == 408:
        return AIError(504, "ai_timeout", "The AI model took too long to respond. Try again later.")
    if status in (404, 502, 503):  # 404: no endpoint passes the free-only price caps
        return AIError(503, "ai_unavailable", "No free AI model is available right now. Try again later.")
    return AIError(502, "upstream_error", "The AI service returned an error. Try again later.")


@functools.cache
def _client() -> openai.OpenAI:
    # timeout is the SDK's per-request network timeout, not a total wall-clock deadline.
    # max_retries=0: OpenRouter handles model fallback; client retries would burn free quota.
    return openai.OpenAI(base_url="https://openrouter.ai/api/v1", api_key=API_KEY,
                         timeout=TIMEOUT_SECONDS, max_retries=0)


def generate_analysis(course_prompt: str) -> dict:
    """Run one OpenRouter completion, free-only, and return the validated Markdown analysis."""
    if not API_KEY:
        raise AIError(503, "ai_not_configured", "AI analysis is not configured on the server.")

    extra_body = {
        "provider": {
            "require_parameters": True,
            "sort": "latency",
            "max_price": {"prompt": 0, "completion": 0, "request": 0},  # never pay, even if pricing changes
        },
        "reasoning": {"enabled": REASONING_ENABLED, "exclude": True},
    }
    if FALLBACK_MODELS:
        extra_body["models"] = FALLBACK_MODELS

    started = time.monotonic()
    try:
        completion = _client().chat.completions.create(
            model=PRIMARY_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_INSTRUCTION},
                {"role": "user", "content": course_prompt},
            ],
            temperature=0.3,
            max_tokens=MAX_TOKENS,
            extra_body=extra_body,
        )
    except openai.APITimeoutError:
        raise _upstream_error(408)
    except openai.APIStatusError as e:
        retry_after = e.response.headers.get("retry-after", "")
        raise _upstream_error(e.status_code, int(retry_after) if retry_after.isdigit() else None)
    except openai.APIConnectionError:
        raise _upstream_error(503)
    except openai.APIError:
        raise _upstream_error(None)

    # OpenRouter can report errors inside an HTTP 200 body, at top level or per choice.
    choice = (completion.choices or [None])[0]
    error = getattr(completion, "error", None) or getattr(choice, "error", None)
    if error:
        raise _upstream_error(error.get("code") if isinstance(error, dict) else None)
    if choice is None:
        raise AIError(502, "bad_response", "The AI service returned an unusable response. Try again.")
    if choice.finish_reason == "length":
        raise AIError(502, "incomplete_response", "The AI response was cut off. Try again.")
    content = ((choice.message and choice.message.content) or "").strip()
    if choice.finish_reason != "stop" or not content:
        raise AIError(502, "bad_response", "The AI service returned an unusable response. Try again.")

    return {
        "analysis": content,
        "model": completion.model,
        "id": completion.id,
        "usage": completion.usage.model_dump(exclude_none=True) if completion.usage else None,
        "elapsed_ms": round((time.monotonic() - started) * 1000),
    }


# --- API Routes ---

@app.route("/api/search")
def api_search():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify([])
    return jsonify(search_courses(query)["results"])


@app.route("/api/programs")
def api_programs():
    return jsonify(list_programs())


@app.route("/api/programs/<program_id>/courses")
def api_program_courses(program_id):
    program = lookup_program(program_id)
    if not program:
        return jsonify({"error": "Unknown major.", "code": "unknown_major"}), 404
    offset = request.args.get("offset", "0")
    if not offset.isdigit():
        return jsonify({"error": "offset must be a non-negative integer.", "code": "invalid_request"}), 400
    selected = None
    if 'concentrations' in request.args:
        try:
            options = resolve_concentrations(program, request.args['concentrations'].split(',') if request.args['concentrations'] else [])
            selected = [o['id'] for o in options]
        except ValueError as error:
            return jsonify({'error': str(error), 'code': 'invalid_concentration'}), 400
    found = search_courses(request.args.get("q", ""), program_id, int(offset), concentrations=selected)
    if selected is not None:
        catalog = lookup_concentration_catalog(program_id)
        return jsonify({'program': program, 'concentration_dataset': {'catalog_year': catalog['catalog_year'],
                        'semantics_validated': False}, **found})
    return jsonify({"program": program, "plan_dataset": lookup_plan_dataset(), **found})


@app.route('/api/programs/<program_id>/concentrations')
def api_concentrations(program_id):
    program = lookup_program(program_id)
    if not program:
        return jsonify({'error': 'Unknown major.', 'code': 'unknown_major'}), 404
    return jsonify({'program': program, **lookup_concentration_catalog(program_id)})


@app.route("/api/course/<dept>/<number>")
def api_course(dept, number):
    course = lookup_course(dept, number)
    if not course:
        return jsonify({"error": "Course not found"}), 404

    schedule = lookup_schedule_context(dept, number)
    course["schedule_context"] = schedule
    course["plan_dataset"] = lookup_plan_dataset()
    course["prerequisites_text"] = format_prereqs(course["prerequisites"])

    return jsonify(course)


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    data = request.get_json(silent=True)
    data = data if isinstance(data, dict) else {}
    dept, number = data.get("dept"), data.get("number")
    if not (isinstance(dept, str) and isinstance(number, str)
            and re.fullmatch(r"[A-Za-z]{2,4} \d{4}", f"{dept} {number}")):
        return jsonify({"error": 'Send JSON like {"dept": "cs", "number": "3000"}.', "code": "invalid_request"}), 400

    try:  # only a missing "ai" field means app default; anything malformed is rejected
        config = ai_providers.parse_ai_config(data["ai"]) if "ai" in data else None
    except AIError as e:
        return jsonify(e.body), e.status

    program = None
    if "major" in data:  # absent means no major; anything else must name a known program
        major = data["major"]
        program = lookup_program(major) if isinstance(major, str) and len(major) <= 200 else None
        if not program:
            return jsonify({"error": "Unknown major. Choose it again from the major list.", "code": "unknown_major"}), 400

    concentrations = None
    if 'concentrations' in data:
        try:
            concentrations = resolve_concentrations(program, data['concentrations'])
        except ValueError as error:
            return jsonify({'error': str(error), 'code': 'invalid_concentration'}), 400

    course = lookup_course(dept, number)
    if not course:
        return jsonify({"error": "Course not found", "code": "course_not_found"}), 404

    source = config[0] if config else "default"
    try:
        prompt = build_prompt(course, program, concentrations) if concentrations else build_prompt(course, program)
        result = ai_providers.generate(*config, SYSTEM_INSTRUCTION, prompt) if config else generate_analysis(prompt)
    except AIError as e:
        app.logger.warning("analysis failed course=%s %s source=%s code=%s", dept, number, source, e.body["code"])
        return jsonify(e.body), e.status
    except Exception as e:
        app.logger.error("analysis crashed course=%s %s source=%s error=%s", dept, number, source, type(e).__name__)
        return jsonify({"error": "Something went wrong. Try again later.", "code": "internal_error"}), 500

    app.logger.info("analysis ok course=%s %s source=%s model=%s id=%s ms=%d usage=%s", dept, number, source,
                    result["model"], result["id"], result["elapsed_ms"], result["usage"])
    body = {"analysis": result["analysis"], "model": result["model"]}
    if config:
        body["provider"] = result["provider"]
    return jsonify(body)


@app.route("/api/ai/models", methods=["POST"])
def api_models():
    try:
        provider, key = ai_providers.parse_discovery(request.get_json(silent=True))
        catalog = ai_providers.list_models(provider, key)
    except AIError as e:
        app.logger.warning("model discovery failed code=%s", e.body["code"])
        return jsonify(e.body), e.status
    except Exception as e:
        app.logger.error("model discovery crashed error=%s", type(e).__name__)
        return jsonify({"error": "Something went wrong. Try again later.", "code": "internal_error"}), 500
    return jsonify({"provider": provider, **catalog})


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "model": PRIMARY_MODEL, "provider": "openrouter", "ai_configured": bool(API_KEY)})


if __name__ == "__main__":
    print(f"Starting Course Advisor API...")
    print(f"Model: {PRIMARY_MODEL} (fallbacks: {', '.join(FALLBACK_MODELS) or 'none'})")
    print(f"AI configured: {bool(API_KEY)}")
    print(f"Database: {DB_FILE}")
    print(f"http://localhost:8000")
    app.run(port=8000)  # debug off: its traceback page could expose request data. Opt in with FLASK_DEBUG=1.
