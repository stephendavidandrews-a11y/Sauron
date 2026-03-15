"""Sauron text pipeline — iMessage ingestion, clustering, extraction."""
from pathlib import Path
from dotenv import load_dotenv

_project_root = Path(__file__).parent.parent.parent
_env_file = _project_root / ".env"
if _env_file.exists():
    load_dotenv(_env_file)
