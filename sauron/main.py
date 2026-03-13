"""Sauron — Personal Voice Intelligence System.

FastAPI service on port 8003. Processes audio from Pi and Plaud recorders,
producing structured intelligence for the Networking App and CFTC Command Center.

v0.3.0:
  - Serves React frontend from frontend/dist/
  - CORS enabled for development
  - SPA fallback for client-side routing
"""

from dotenv import load_dotenv
load_dotenv()

import logging
import os
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from sauron.config import SAURON_PORT, LOGS_DIR
from sauron import __version__
from sauron.db.schema import init_db
from sauron.pipeline.watcher import InboxWatcher
from sauron.pipeline.processor import process_conversation, process_through_speaker_id

# Configure logging
LOGS_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOGS_DIR / "sauron.log"),
    ],
)
logger = logging.getLogger("sauron")

# Frontend dist path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_FRONTEND_DIR = _PROJECT_ROOT / "frontend" / "dist"

# File watcher instance
_watcher: InboxWatcher | None = None

# Scheduler instance (may be None if APScheduler not installed)
_scheduler = None


def _on_new_file(conversation_id: str, path):
    """Callback when a new audio file is detected — kick off processing in background."""
    logger.info(f"New file detected, queuing: {path.name} -> {conversation_id[:8]}")
    thread = threading.Thread(
        target=process_through_speaker_id,
        args=(conversation_id,),
        daemon=True,
    )
    thread.start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    global _watcher, _scheduler

    # Initialize database
    init_db()
    logger.info("Database initialized")

    # Start file watcher
    _watcher = InboxWatcher(on_new_file=_on_new_file)
    _watcher.start()
    logger.info("Inbox watcher started")

    # Startup scan: process any conversations stuck in pending
    from sauron.db.connection import get_connection as _get_conn
    _conn = _get_conn()
    try:
        _pending = _conn.execute(
            "SELECT id FROM conversations WHERE processing_status = 'pending' ORDER BY captured_at"
        ).fetchall()
    finally:
        _conn.close()
    if _pending:
        import time as _time
        logger.info(f"Startup scan: {len(_pending)} pending conversations — processing in background")
        def _process_pending_batch(conv_ids):
            for cid in conv_ids:
                try:
                    process_through_speaker_id(cid)
                except Exception as exc:
                    logger.error(f"Startup processing failed for {cid[:8]}: {exc}")
                _time.sleep(2)  # avoid overwhelming system
        _t = threading.Thread(
            target=_process_pending_batch,
            args=([r["id"] for r in _pending],),
            daemon=True,
        )
        _t.start()

    # Start APScheduler for morning brief (graceful if not installed)
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
        from sauron.jobs.morning_email import run_morning_brief_job

        _scheduler = AsyncIOScheduler()
        _scheduler.add_job(
            run_morning_brief_job,
            CronTrigger(hour=6, minute=30),
            id="morning_brief",
            replace_existing=True,
        )
        # Weekly learning analysis (Sundays at midnight)
        from sauron.learning.amendments import analyze_corrections_and_amend
        _scheduler.add_job(
            analyze_corrections_and_amend,
            CronTrigger(day_of_week="sun", hour=0, minute=0),
            id="weekly_learning",
            replace_existing=True,
        )

        # Retry failed routing every 30 minutes (Phase D)
        from apscheduler.triggers.interval import IntervalTrigger
        from sauron.routing.retry import retry_failed_routes_job
        _scheduler.add_job(
            retry_failed_routes_job,
            IntervalTrigger(minutes=30),
            id="retry_failed_routes",
            replace_existing=True,
        )

        _scheduler.start()
        logger.info("Scheduler started (morning brief 6:30am daily, learning analysis weekly, routing retry every 30m)")
    except ImportError:
        logger.warning(
            "APScheduler not installed — morning brief will not run automatically. "
            "Install with: pip install apscheduler"
        )
    except Exception as exc:
        logger.error("Failed to start scheduler: %s", exc)

    yield

    # Shutdown scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown()
            logger.info("Scheduler stopped")
        except Exception as exc:
            logger.error("Scheduler shutdown error: %s", exc)

    # Shutdown file watcher
    if _watcher:
        _watcher.stop()
        logger.info("Inbox watcher stopped")


app = FastAPI(
    title="Sauron",
    description="Personal Voice Intelligence System",
    version=__version__,
    lifespan=lifespan,
)

# CORS (allow dev and production origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routers — all under /api prefix
from sauron.api.conversations import router as conversations_router
from sauron.api.voice_profiles_api import router as profiles_router
from sauron.api.corrections import router as corrections_router
from sauron.api.graph import router as graph_router
from sauron.api.brief import router as brief_router
from sauron.api.performance import router as performance_router
from sauron.api.baselines_api import router as baselines_router
from sauron.api.search_api import router as search_router
from sauron.api.pipeline_api import router as pipeline_router
from sauron.api.audio_api import router as audio_router
from sauron.api.beliefs_api import router as beliefs_router
from sauron.api.learning_api import router as learning_router
from sauron.api.routing_api import router as routing_router
from sauron.api.routing_api import conv_routing_router
from sauron.api.provisional_orgs_api import router as provisional_orgs_router
from sauron.api.graph_edges_api import router as graph_edges_router
from sauron.api.rename import router as rename_router
from sauron.api.text_replace import router as text_replace_router

app.include_router(conversations_router, prefix="/api")
app.include_router(profiles_router, prefix="/api")
app.include_router(corrections_router, prefix="/api")
app.include_router(graph_router, prefix="/api")
app.include_router(brief_router, prefix="/api")
app.include_router(performance_router, prefix="/api")
app.include_router(baselines_router, prefix="/api")
app.include_router(search_router, prefix="/api")
app.include_router(pipeline_router, prefix="/api")
app.include_router(audio_router, prefix="/api")
app.include_router(beliefs_router, prefix="/api")
app.include_router(learning_router, prefix="/api")
app.include_router(routing_router, prefix="/api")
app.include_router(conv_routing_router, prefix="/api")
app.include_router(provisional_orgs_router, prefix="/api")
app.include_router(graph_edges_router, prefix="/api")
app.include_router(rename_router, prefix="/api")
app.include_router(text_replace_router, prefix="/api")


@app.get("/api/health")
def health_check():
    """API health check."""
    from sauron.db.connection import get_connection
    conn = get_connection()
    try:
        pending = conn.execute(
            "SELECT COUNT(*) as n FROM conversations WHERE processing_status = 'pending'"
        ).fetchone()["n"]
        total = conn.execute(
            "SELECT COUNT(*) as n FROM conversations"
        ).fetchone()["n"]
        profiles = conn.execute(
            "SELECT COUNT(*) as n FROM voice_profiles"
        ).fetchone()["n"]
    finally:
        conn.close()

    return {
        "service": "sauron",
        "version": __version__,
        "status": "operational",
        "conversations": {"total": total, "pending": pending},
        "voice_profiles": profiles,
        "scheduler_active": _scheduler is not None,
    }


# Serve static frontend assets
if _FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(_FRONTEND_DIR / "assets")), name="static-assets")

    @app.get("/vite.svg")
    async def vite_svg():
        return FileResponse(str(_FRONTEND_DIR / "vite.svg"))

    # Serve SPA for all non-API 404s (exception handler avoids
    # intercepting include_router routes like a catch-all would)
    from starlette.exceptions import HTTPException as StarletteHTTPException
    from fastapi.responses import JSONResponse

    @app.exception_handler(404)
    async def spa_404_handler(request: Request, exc):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        # Check if the path maps to an actual file in dist
        rel = request.url.path.lstrip("/")
        file_path = _FRONTEND_DIR / rel
        if file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(_FRONTEND_DIR / "index.html"))
else:
    @app.get("/")
    def root():
        """Fallback when no frontend is built."""
        return health_check()


def cli():
    """CLI entry point."""
    if len(sys.argv) > 1 and sys.argv[1] == "init-db":
        init_db()
        return

    uvicorn.run(
        "sauron.main:app",
        host="0.0.0.0",
        port=SAURON_PORT,
        reload=False,
    )


if __name__ == "__main__":
    cli()
