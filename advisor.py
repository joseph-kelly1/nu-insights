import json
import os
from google import genai

# --- Configuration ---
API_KEY = os.environ.get("GEMINI_API_KEY", "")

enum Models:
    GEMINI_2_5_FLASH = "gemini-2.5-flash" # 10 RPM, 250 req/day
    GEMINI_2_5_FLASH_LITE = "gemini-2.5-flash-lite" # 15 RPM, 1000 req/day
    GEMINI_2_5_PRO = "gemini-2.5-pro" # 5 RPM, 100 req/day
MODEL = Models.GEMINI_2_5_FLASH  # Free tier: 10 RPM, 250 requests/day

client = genai.Client(api_key=API_KEY)

SYSTEM_PROMPT = (
    "You are a helpful Northeastern University academic advisor. "
    "When given a course name and description, provide a concise breakdown with:\n"
    "1. A plain-English summary of what the course actually covers (2-3 sentences)\n"
    "2. Who should take it (major, year, goals)\n"
    "3. Key skills you'll walk away with\n"
    "4. How it connects to co-op or career opportunities\n\n"
    "Be honest and practical — speak like an upperclassman giving advice, not a catalog."
)


def analyze_course(course_name: str, course_description: str) -> str:
    """Send a course description to Gemini and get a student-friendly breakdown."""

    user_message = f"Course: {course_name}\n\nDescription: {course_description}"

    response = client.models.generate_content(
        model=MODEL,
        contents=user_message,
        config={
            "system_instruction": SYSTEM_PROMPT,
            "max_output_tokens": 1024,
            "temperature": 0.7,
        },
    )

    return response.text


def analyze_from_json(json_path: str, department: str = None):
    """
    Load courses from one of your scraped JSON files and analyze them.
    Adjust the keys below to match your actual JSON structure.
    """

    with open(json_path, "r") as f:
        courses = json.load(f)

    for course in courses:
        name = course.get("name", course.get("title", "Unknown"))
        desc = course.get("description", "No description available.")

        if department and department.upper() not in name.upper():
            continue

        print(f"\n{'='*60}")
        print(f"  {name}")
        print(f"{'='*60}")

        analysis = analyze_course(name, desc)
        print(analysis)
        print()

        input("Press Enter for the next course (Ctrl+C to stop)...")


# --- Try it out ---
if __name__ == "__main__":

    # Test with a single course first
    sample_course = "CS 3500 — Object-Oriented Design"
    sample_description = (
        "Presents a comparative study of several approaches to "
        "object-oriented design including design patterns, "
        "refactoring, and testing. Students apply these techniques "
        "in a semester-long project."
    )

    print("Asking Gemini to break down this course...\n")
    result = analyze_course(sample_course, sample_description)
    print(result)

    # --- EXPERIMENTS TO TRY ---
    # Once the above works, try these modifications:

    # 1. Change the system prompt to output JSON instead of prose:
    #    Add to SYSTEM_PROMPT: "Respond ONLY in JSON with keys:
    #    summary, who_should_take, skills (array), career_connection"
    #    Then parse with: json.loads(result)

    # 2. Compare two courses in one prompt:
    #    "Compare CS 3500 (OOD) vs CS 3000 (Algorithms).
    #    Which is more useful for a student targeting SWE co-ops?"

    # 3. Hook up your scraped data:
    #    analyze_from_json("courses/CS.json")

    # 4. Try swapping models to see how output quality changes:
    #    MODEL = "gemini-2.5-flash-lite"  # faster, lighter
    #    MODEL = "gemini-2.5-pro"         # smarter, 100 req/day limit