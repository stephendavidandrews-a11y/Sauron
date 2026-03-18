"""Centralised job submission for Sauron.

All background work — pipeline processing, learning analysis, text sync,
resynthesis — runs through one of two thread pools.  This replaces ad-hoc
``threading.Thread(daemon=True)`` launches scattered across API modules.

Pools
-----
pipeline : max_workers=2
    GPU-heavy work (transcription, diarization, extraction).
    Bounded at 2 so the Mac Mini M4 GPU is not over-committed.

background : max_workers=3
    CPU-bound work (correction analysis, text sync, belief resynthesis).
    Safe to overlap with pipeline work.
"""

import logging
from concurrent.futures import Future, ThreadPoolExecutor

logger = logging.getLogger(__name__)

_pipeline_pool: ThreadPoolExecutor | None = None
_background_pool: ThreadPoolExecutor | None = None


def _ensure_pools():
    """Lazily create pools on first use."""
    global _pipeline_pool, _background_pool
    if _pipeline_pool is None:
        _pipeline_pool = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="sauron-pipeline"
        )
    if _background_pool is None:
        _background_pool = ThreadPoolExecutor(
            max_workers=3, thread_name_prefix="sauron-background"
        )


def submit_pipeline_job(fn, *args, **kwargs) -> Future:
    """Submit GPU-heavy work (transcription, extraction) to the pipeline pool."""
    _ensure_pools()
    logger.debug("Pipeline job submitted: %s", fn.__name__)
    return _pipeline_pool.submit(fn, *args, **kwargs)


def submit_background_job(fn, *args, **kwargs) -> Future:
    """Submit CPU-bound work (learning, sync, resynthesis) to the background pool."""
    _ensure_pools()
    logger.debug("Background job submitted: %s", fn.__name__)
    return _background_pool.submit(fn, *args, **kwargs)


def shutdown(wait: bool = False):
    """Shut down both pools.  Called from main.py lifespan on app shutdown."""
    global _pipeline_pool, _background_pool
    if _pipeline_pool is not None:
        _pipeline_pool.shutdown(wait=wait)
        _pipeline_pool = None
    if _background_pool is not None:
        _background_pool.shutdown(wait=wait)
        _background_pool = None
    logger.info("Executor pools shut down (wait=%s)", wait)


def pool_stats() -> dict:
    """Return current pool utilisation for the diagnostics endpoint."""
    _ensure_pools()
    return {
        "pipeline": {
            "max_workers": _pipeline_pool._max_workers,
            "threads_alive": sum(
                1 for t in (_pipeline_pool._threads or set()) if t.is_alive()
            ),
        },
        "background": {
            "max_workers": _background_pool._max_workers,
            "threads_alive": sum(
                1 for t in (_background_pool._threads or set()) if t.is_alive()
            ),
        },
    }
