"""Background jobs.

Each job is a plain async function taking the arq context as its first argument. The
pipeline tasks land here in phase 4; registration happens in `app.worker`.
"""

from app.jobs.system import ping

__all__ = ["ping"]
