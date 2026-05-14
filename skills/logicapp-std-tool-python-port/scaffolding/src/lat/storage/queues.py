"""Queue helpers — used by ClearJobQueue and CancelRuns (job-queue path)."""
from __future__ import annotations

from azure.storage.queue import QueueServiceClient

from ..settings import settings


def service_client() -> QueueServiceClient:
    conn = settings.connection_string
    if not conn:
        raise RuntimeError("AzureWebJobsStorage is not set")
    return QueueServiceClient.from_connection_string(conn)
