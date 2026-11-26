"""Per-request values that the request log needs but the generation code does not pass around.

Each request runs in its own task, so a value set at the start of the task is only seen by that task.
"""

from contextvars import ContextVar
from typing import Optional

# The client API key that made the request; 0 means the master key or no key.
client_key_id_var: ContextVar[int] = ContextVar("flow2api_client_key_id", default=0)

# The job that this task is running, when the request came through /v1/jobs.
job_id_var: ContextVar[Optional[str]] = ContextVar("flow2api_job_id", default=None)
