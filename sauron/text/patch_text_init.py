"""Add dotenv loading to sauron/text/__init__.py so all text modules have API key."""

INIT_PATH = "/Users/stephen/Documents/Website/Sauron/sauron/text/__init__.py"

with open(INIT_PATH, "r") as f:
    content = f.read()

if "load_dotenv" in content:
    print("Already patched.")
else:
    content = '''"""Sauron text pipeline — iMessage ingestion, clustering, extraction."""
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root so ANTHROPIC_API_KEY is available
# when running text modules directly (outside FastAPI/uvicorn)
_project_root = Path(__file__).parent.parent.parent
_env_file = _project_root / ".env"
if _env_file.exists():
    load_dotenv(_env_file)
'''
    with open(INIT_PATH, "w") as f:
        f.write(content)
    print("Patched sauron/text/__init__.py: loads .env from project root.")
