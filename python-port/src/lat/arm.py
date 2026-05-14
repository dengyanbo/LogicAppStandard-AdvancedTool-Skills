"""ARM operations via `azure-mgmt-web` for site management.

This replaces the previous hand-rolled httpx/IMDS code with the official
`WebSiteManagementClient`. Functions exposed here:

* `web_client()` — singleton `WebSiteManagementClient`; tests can override
  via `_set_web_client(...)`.
* `restart_site()` — POSTs `Microsoft.Web/sites/{name}/restart`.
* `get_appsettings()` / `put_appsettings(props)` — read/replace the site's
  app settings (production wraps these for snapshot/restore + connection
  cleanup).
* Hostruntime helpers (`list_runs`, `cancel_run`, `resubmit_run`) — still
  direct HTTPS POSTs through ARM, because no Python SDK wraps the LA
  Standard hostruntime endpoint. They authenticate via the MI token from
  `auth.credential()`.
"""
from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

import httpx
from azure.mgmt.web import WebSiteManagementClient
from azure.mgmt.web.models import StringDictionary

from .auth import DEFAULT_AUDIENCE, credential, retrieve_token
from .settings import settings

_web_client: WebSiteManagementClient | None = None


def web_client() -> WebSiteManagementClient:
    """Singleton WebSiteManagementClient. Built lazily so tests can override first."""
    global _web_client
    if _web_client is None:
        sub = settings.subscription_id
        if not sub:
            raise RuntimeError("WEBSITE_OWNER_NAME is not set; cannot resolve subscription ID")
        _web_client = WebSiteManagementClient(credential(), sub)
    return _web_client


def _set_web_client(client: WebSiteManagementClient | None) -> None:
    """Test seam — override or clear the singleton client."""
    global _web_client
    _web_client = client


def _site_params() -> tuple[str, str]:
    rg = settings.resource_group
    name = settings.logic_app_name
    if not rg or not name:
        raise RuntimeError("WEBSITE_RESOURCE_GROUP / WEBSITE_SITE_NAME must be set")
    return rg, name


# ---------------------------------------------------------------------------
# Site management — backed by azure-mgmt-web
# ---------------------------------------------------------------------------


def restart_site() -> None:
    """POST .../sites/{name}/restart via the management SDK."""
    rg, name = _site_params()
    web_client().web_apps.restart(rg, name)


def get_appsettings() -> dict[str, str]:
    """Read site app settings as a plain dict."""
    rg, name = _site_params()
    result = web_client().web_apps.list_application_settings(rg, name)
    return dict(result.properties or {})


def put_appsettings(properties: dict[str, str]) -> None:
    """Replace site app settings (also auto-restarts the site)."""
    rg, name = _site_params()
    web_client().web_apps.update_application_settings(
        rg, name, StringDictionary(properties=properties)
    )


# ---------------------------------------------------------------------------
# Hostruntime — direct HTTPS through the ARM proxy, MI-bearer auth.
# ---------------------------------------------------------------------------


def _hostruntime_base() -> str:
    rg, name = _site_params()
    sub = settings.subscription_id
    return (
        f"https://management.azure.com/subscriptions/{sub}/resourceGroups/{rg}"
        f"/providers/Microsoft.Web/sites/{name}/hostruntime/runtime/webhooks/workflow/api/management"
    )


def _bearer_headers(*, content_type: bool = False) -> dict[str, str]:
    token = retrieve_token(DEFAULT_AUDIENCE)
    headers = {"Authorization": f"Bearer {token.access_token}"}
    if content_type:
        headers["Content-Type"] = "application/json"
    return headers


def _hostruntime_request(
    method: str,
    url: str,
    *,
    body: dict | None = None,
    expected_message: str | None = None,
) -> httpx.Response:
    """ARM-proxied hostruntime request with 429/5xx retry."""
    backoff = [1, 2, 4]
    last_resp: httpx.Response | None = None
    for attempt in range(4):
        resp = httpx.request(
            method,
            url,
            headers=_bearer_headers(content_type=body is not None),
            content=json.dumps(body) if body is not None else None,
            timeout=60.0,
        )
        last_resp = resp
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "120"))
            time.sleep(retry_after)
            continue
        if 500 <= resp.status_code < 600 and attempt < 3:
            time.sleep(backoff[attempt])
            continue
        if not resp.is_success:
            msg = expected_message or f"{method} {url}"
            raise RuntimeError(f"{msg} failed ({resp.status_code}): {resp.text}")
        return resp
    assert last_resp is not None
    raise RuntimeError(f"{method} {url} exhausted retries (HTTP {last_resp.status_code})")


def list_runs(
    workflow: str, *, status: str, start_time: str, end_time: str
) -> Iterator[dict[str, Any]]:
    """List workflow runs matching the status/date window, yielding through nextLink."""
    flt = (
        f"status eq '{status}' and startTime ge '{start_time}' "
        f"and startTime le '{end_time}'"
    )
    url: str | None = (
        f"{_hostruntime_base()}/workflows/{workflow}/runs?api-version=2018-11-01"
        f"&$filter={flt}"
    )
    while url:
        r = _hostruntime_request("GET", url, expected_message=f"list runs for {workflow}")
        body = r.json()
        yield from body.get("value", [])
        url = body.get("nextLink")


def cancel_run(workflow: str, run_id: str) -> None:
    url = (
        f"{_hostruntime_base()}/workflows/{workflow}/runs/{run_id}/cancel"
        "?api-version=2018-11-01"
    )
    _hostruntime_request("POST", url, expected_message=f"cancel {workflow}/{run_id}")


def resubmit_run(workflow: str, run_id: str) -> None:
    url = (
        f"{_hostruntime_base()}/workflows/{workflow}/runs/{run_id}/resubmit"
        "?api-version=2018-11-01"
    )
    _hostruntime_request("POST", url, expected_message=f"resubmit {workflow}/{run_id}")
