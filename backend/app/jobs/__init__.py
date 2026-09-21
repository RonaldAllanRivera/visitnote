"""Background jobs.

Each job is a plain async function taking the arq context as its first argument.
Registration happens in `app.worker`.
"""

from app.jobs.pipeline import process_visit
from app.jobs.system import ping

__all__ = ["ping", "process_visit"]
