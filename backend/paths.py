"""Repository paths shared by the API and loaders, independent of shell location."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / 'data'
RUNTIME_DIR = PROJECT_ROOT / 'var'
DB_FILE = RUNTIME_DIR / 'courses.db'
