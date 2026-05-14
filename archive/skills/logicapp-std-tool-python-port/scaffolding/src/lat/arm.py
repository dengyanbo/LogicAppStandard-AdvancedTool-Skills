"""ARM HTTP helpers — mirrors Shared/HttpOperations.cs and the inline ARM
calls scattered through Operations/*.cs.

See references/07-arm-endpoints.md for the full URL templates per
operation.
"""
from __future__ import annotations

import json
import time

import httpx

from .msi import MIToken, retrieve_token, verify_token
from .settings import settings


def _headers(token: MIToken | None = None, content_type: bool = False) -> dict[str, str]:
    tok = verify_token(token or retrieve_token())
    h = {"Authorization": f"Bearer {tok.access_token}"}
    if content_type:
        h["Content-Type"] = "application/json"
    return h


def _request(method: str, url: str, *, body: dict | None = None,
             expected_message: str | None = None) -> httpx.Response:
    """Issue an ARM request with bearer-token auth, retry on 429/5xx."""
    backoff = [1, 2, 4]
    for attempt in range(4):
        resp = httpx.request(
            method,
            url,
            headers=_headers(content_type=body is not None),
            content=json.dumps(body) if body is not None else None,
            timeout=60.0,
        )
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "120"))
            time.sleep(retry_after)
            continue
        if 500 <= resp.status_code < 600 and attempt < 3:
            time.sleep(backoff[attempt])
            continue
        if not resp.is_success:
            msg = expected_message or f"{method} {url}"
            raise RuntimeError(
                f"{msg} failed ({resp.status_code}): {resp.text}"
            )
        return resp
    raise RuntimeError(f"{method} {url} exhausted retries (HTTP 429/5xx)")


def _site_base() -> str:
    return settings.management_base_url


def get_appsettings() -> dict:
    """Read site app settings (POST .../config/appsettings/list)."""
    url = f"{_site_base()}/config/appsettings/list?api-version=2022-03-01"
    return _request("POST", url, expected_message="get appsettings").json()["properties"]


def put_appsettings(properties: dict) -> None:
    """Replace site app settings — POSTs to list to fetch the envelope, then PUTs."""
    list_url = f"{_site_base()}/config/appsettings/list?api-version=2022-03-01"
    envelope = _request("POST", list_url, expected_message="get appsettings").json()
    envelope["properties"] = properties
    put_url = f"{_site_base()}/config/appsettings?api-version=2022-03-01"
    _request("PUT", put_url, body=envelope, expected_message="update appsettings")


def restart_site() -> None:
    url = f"{_site_base()}/restart?api-version=2022-03-01"
    _request("POST", url, expected_message="restart site")


# --- Workflow runs (hostruntime) -----------------------------------------------

def _runtime_base() -> str:
    return f"{_site_base()}/hostruntime/runtime/webhooks/workflow/api/management"


def list_runs(workflow: str, *, status: str, start_time: str, end_time: str
              ) -> list[dict]:
    """List workflow runs with paginated nextLink chasing."""
    flt = (f"status eq '{status}' and startTime ge '{start_time}' "
           f"and startTime le '{end_time}'")
    url = f"{_runtime_base()}/workflows/{workflow}/runs?api-version=2018-11-01&$filter={flt}"
    out: list[dict] = []
    while url:
        r = _request("GET", url, expected_message=f"list runs for {workflow}")
        body = r.json()
        out.extend(body.get("value", []))
        url = body.get("nextLink")
    return out


def cancel_run(workflow: str, run_id: str) -> None:
    url = f"{_runtime_base()}/workflows/{workflow}/runs/{run_id}/cancel?api-version=2018-11-01"
    _request("POST", url, expected_message=f"cancel {workflow}/{run_id}")


def resubmit_run(workflow: str, run_id: str) -> None:
    url = f"{_runtime_base()}/workflows/{workflow}/runs/{run_id}/resubmit?api-version=2018-11-01"
    _request("POST", url, expected_message=f"resubmit {workflow}/{run_id}")
