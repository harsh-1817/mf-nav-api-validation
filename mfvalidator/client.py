"""Thin HTTP client: retries, timeouts and response-time measurement for every call."""
from __future__ import annotations

import time
from dataclasses import dataclass

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import config


@dataclass
class ApiResponse:
    url: str
    status_code: int | None
    elapsed_ms: float | None
    content_type: str
    text: str
    json: object | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.status_code == 200


class MFApiClient:
    def __init__(self, base_url: str = config.BASE_URL, timeout: float = config.TIMEOUT_S,
                 retries: int = config.RETRIES, delay: float = config.REQUEST_DELAY_S):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.delay = delay
        self.session = requests.Session()
        retry = Retry(total=retries, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=frozenset(["GET"]), raise_on_status=False)
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.mount("http://", HTTPAdapter(max_retries=retry))
        self.session.headers.update({"Accept": "application/json", "User-Agent": "mf-nav-api-validation/1.0"})

    def get(self, path: str, params: dict | None = None) -> ApiResponse:
        url = f"{self.base_url}{path}"
        time.sleep(self.delay)
        start = time.perf_counter()
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            return ApiResponse(url, None, (time.perf_counter() - start) * 1000, "", "", None, error=str(exc))
        elapsed = (time.perf_counter() - start) * 1000
        try:
            body = resp.json()
        except ValueError:
            body = None
        return ApiResponse(resp.url, resp.status_code, elapsed, resp.headers.get("Content-Type", ""),
                           resp.text[:500], body)

    # ---- endpoint helpers -------------------------------------------------
    def search(self, query: str) -> ApiResponse:
        return self.get("/mf/search", {"q": query})

    def list_schemes(self, limit: int = 10, offset: int = 0) -> ApiResponse:
        return self.get("/mf", {"limit": limit, "offset": offset})

    def scheme_history(self, code, start: str | None = None, end: str | None = None) -> ApiResponse:
        params = {}
        if start:
            params["startDate"] = start
        if end:
            params["endDate"] = end
        return self.get(f"/mf/{code}", params or None)

    def latest(self, code) -> ApiResponse:
        return self.get(f"/mf/{code}/latest")
