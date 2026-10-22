"""API contract and behaviour tests against MFapi.in.

The same functions power the command-line runner and the pytest live suite, so there is one source of truth.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from . import config
from .client import MFApiClient
from .schema import SCHEME_RESPONSE_SCHEMA, SEARCH_RESPONSE_SCHEMA, schema_errors


@dataclass
class TestResult:
    __test__ = False  # stop pytest from collecting this dataclass as a test class
    test_id: str
    name: str
    target: str
    passed: bool
    detail: str = ""
    latency_ms: float | None = None
    known_issue: bool = False   # a documented API defect: reported, but does not fail the run


def _res(out: list, test_id: str, name: str, target: str, passed: bool, detail: str = "", latency=None,
         known_issue: bool = False):
    out.append(TestResult(test_id, name, target, bool(passed), detail if not passed else "", latency, known_issue))


def _is_success_payload(resp) -> bool:
    """True if the response looks like a genuine successful NAV payload."""
    j = resp.json
    return bool(resp.status_code == 200 and isinstance(j, dict) and j.get("status") == "SUCCESS" and j.get("data"))


# ------------------------------------------------------------------------------ per-scheme tests
def scheme_tests(client: MFApiClient, code) -> tuple[list, object]:
    """Run the contract tests for one scheme. Returns (results, history_response)."""
    out: list = []
    t = str(code)
    hist = client.scheme_history(code)

    _res(out, "H01", "History: HTTP 200", t, hist.status_code == 200,
         f"status={hist.status_code} error={hist.error}", hist.elapsed_ms)
    _res(out, "H02", f"History: response time under {config.SLA_MS} ms", t,
         hist.elapsed_ms is not None and hist.elapsed_ms <= config.SLA_MS, f"{hist.elapsed_ms:.0f} ms" if hist.elapsed_ms else "no response", hist.elapsed_ms)
    _res(out, "H03", "History: Content-Type is JSON", t, "application/json" in hist.content_type.lower(), hist.content_type)

    body = hist.json if isinstance(hist.json, dict) else None
    errs = schema_errors(hist.json, SCHEME_RESPONSE_SCHEMA) if hist.json is not None else ["response is not JSON"]
    _res(out, "H04", "History: response matches JSON schema", t, not errs, "; ".join(errs))
    if body is None:
        return out, hist

    meta = body.get("meta") or {}
    _res(out, "H05", "History: meta.scheme_code equals requested code", t,
         str(meta.get("scheme_code")) == t, f"got {meta.get('scheme_code')}")
    _res(out, "H06", 'History: status field is "SUCCESS"', t, body.get("status") == "SUCCESS", f"got {body.get('status')}")
    data = body.get("data") or []
    _res(out, "H07", "History: data array is not empty", t, len(data) > 0, "empty")

    # Latest endpoint
    latest = client.latest(code)
    _res(out, "L01", "Latest: HTTP 200", t, latest.status_code == 200, f"status={latest.status_code}", latest.elapsed_ms)
    _res(out, "L02", f"Latest: response time under {config.SLA_MS} ms", t,
         latest.elapsed_ms is not None and latest.elapsed_ms <= config.SLA_MS,
         f"{latest.elapsed_ms:.0f} ms" if latest.elapsed_ms else "no response", latest.elapsed_ms)
    lerrs = schema_errors(latest.json, SCHEME_RESPONSE_SCHEMA) if latest.json is not None else ["response is not JSON"]
    _res(out, "L03", "Latest: response matches JSON schema", t, not lerrs, "; ".join(lerrs))
    ldata = (latest.json or {}).get("data", []) if isinstance(latest.json, dict) else []
    _res(out, "L04", "Latest: returns exactly one record", t, len(ldata) == 1, f"records={len(ldata)}")

    # Cross-endpoint consistency: /latest must agree with the newest record of /mf/{code}
    if ldata and data:
        newest = max(data, key=lambda r: datetime.strptime(r["date"], "%d-%m-%Y")
                     if r.get("date") and len(r["date"]) == 10 else datetime.min)
        l = ldata[0]
        same_date = l.get("date") == newest.get("date")
        try:
            newer_or_same = datetime.strptime(l["date"], "%d-%m-%Y") >= datetime.strptime(newest["date"], "%d-%m-%Y")
        except (KeyError, ValueError):
            newer_or_same = False
        nav_ok = (not same_date) or (float(l.get("nav", "nan")) == float(newest.get("nav", "nan")))
        _res(out, "X01", "Consistency: /latest is not older than newest history record", t, newer_or_same,
             f"latest={l.get('date')} history_newest={newest.get('date')}")
        _res(out, "X02", "Consistency: same-date NAV matches between /latest and history", t, nav_ok,
             f"latest={l.get('nav')} history={newest.get('nav')} on {newest.get('date')}")

    # Date-range filter
    if data:
        dates = [datetime.strptime(r["date"], "%d-%m-%Y") for r in data if r.get("date") and len(r["date"]) == 10]
        if dates:
            end = max(dates)
            start = end - timedelta(days=60)
            rng = client.scheme_history(code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
            rdata = (rng.json or {}).get("data", []) if isinstance(rng.json, dict) else []
            rdates = [datetime.strptime(r["date"], "%d-%m-%Y") for r in rdata if r.get("date") and len(r["date"]) == 10]
            inside = all(start <= d <= end for d in rdates)
            _res(out, "R01", "Date range: HTTP 200 and non-empty", t, rng.status_code == 200 and len(rdata) > 0,
                 f"status={rng.status_code} records={len(rdata)}", rng.elapsed_ms)
            _res(out, "R02", "Date range: every returned date lies inside startDate..endDate", t, inside,
                 f"{sum(1 for d in rdates if not start <= d <= end)} records outside {start:%Y-%m-%d}..{end:%Y-%m-%d}")
            if len(dates) > 90:
                _res(out, "R03", "Date range: filtered result is smaller than full history", t,
                     len(rdata) < len(data), f"filtered={len(rdata)} full={len(data)}")
    return out, hist


# ------------------------------------------------------------------------------ global tests
def global_tests(client: MFApiClient) -> list:
    out: list = []
    s = client.search("HDFC")
    _res(out, "S01", "Search: HTTP 200", "/mf/search", s.status_code == 200, f"status={s.status_code}", s.elapsed_ms)
    _res(out, "S02", f"Search: response time under {config.SLA_MS} ms", "/mf/search",
         s.elapsed_ms is not None and s.elapsed_ms <= config.SLA_MS, f"{s.elapsed_ms}", s.elapsed_ms)
    errs = schema_errors(s.json, SEARCH_RESPONSE_SCHEMA) if s.json is not None else ["response is not JSON"]
    _res(out, "S03", "Search: response matches JSON schema", "/mf/search", not errs, "; ".join(errs))
    rows = s.json if isinstance(s.json, list) else []
    _res(out, "S04", "Search: returns at least one result for 'HDFC'", "/mf/search", len(rows) > 0, "no results")
    codes = [r.get("schemeCode") for r in rows if isinstance(r, dict)]
    _res(out, "S05", "Search: no duplicate scheme codes in results", "/mf/search", len(codes) == len(set(codes)),
         f"{len(codes) - len(set(codes))} duplicates")
    _res(out, "S06", "Search: results actually relate to the query", "/mf/search",
         (not rows) or all("hdfc" in str(r.get("schemeName", "")).lower() for r in rows[:50]),
         "some results do not contain the query text")

    lst = client.list_schemes(limit=5, offset=0)
    lrows = lst.json if isinstance(lst.json, list) else []
    _res(out, "P01", "List: HTTP 200", "/mf", lst.status_code == 200, f"status={lst.status_code}", lst.elapsed_ms)
    _res(out, "P02", "List: limit=5 returns at most 5 rows", "/mf", 0 < len(lrows) <= 5, f"rows={len(lrows)}")
    nxt = client.list_schemes(limit=5, offset=5)
    nrows = nxt.json if isinstance(nxt.json, list) else []
    _res(out, "P03", "List: offset moves to different rows (pagination works)", "/mf",
         bool(lrows and nrows and lrows[0] != nrows[0]), "first row identical for offset 0 and 5")

    # Negative / robustness tests. We do not assume a specific error format; we assert "not a success, no crash".
    bad = client.scheme_history("999999999")
    _res(out, "N01", "Negative: unknown scheme code is not returned as a success", "/mf/999999999",
         not _is_success_payload(bad), f"status={bad.status_code} body={bad.text[:80]}", bad.elapsed_ms)
    _res(out, "N02", "Negative: unknown scheme code does not cause a 5xx", "/mf/999999999",
         bad.status_code is not None and bad.status_code < 500, f"status={bad.status_code}")
    alpha = client.scheme_history("abc")
    _res(out, "N03", "Negative: non-numeric scheme code is not returned as a success", "/mf/abc",
         not _is_success_payload(alpha), f"status={alpha.status_code}")
    _res(out, "N04", "Negative: non-numeric scheme code does not cause a 5xx", "/mf/abc",
         alpha.status_code is not None and alpha.status_code < 500, f"status={alpha.status_code}")
    inj = client.search("' OR 1=1 --")
    _res(out, "N05", "Security: SQL-injection style search input does not cause a 5xx", "/mf/search",
         inj.status_code is not None and inj.status_code < 500, f"status={inj.status_code}")
    empty = client.get("/mf/search")
    _res(out, "N06", "Negative: search without q does not cause a 5xx", "/mf/search",
         empty.status_code is not None and empty.status_code < 500, f"status={empty.status_code}")
    out += unknown_scheme_known_issue_tests(client)
    return out


def unknown_scheme_known_issue_tests(client) -> list:
    """An unknown scheme code should be rejected (4xx) or at least not reported as status SUCCESS.

    Observed live behaviour (22 Oct 2026): GET /mf/999999999 returns HTTP 200 with status "SUCCESS", empty data
    and scheme_code 0. These tests record that defect as a KNOWN ISSUE so it is visible in every report
    without failing CI. If the API is fixed, they simply start passing.
    """
    out: list = []
    for test_id, label, call in (("N07", "/mf/999999999", client.scheme_history),
                                 ("N08", "/mf/999999999/latest", client.latest)):
        resp = call("999999999")
        body = resp.json if isinstance(resp.json, dict) else {}
        reports_success = resp.status_code == 200 and body.get("status") == "SUCCESS"
        detail = (f"HTTP {resp.status_code}, status={body.get('status')}, "
                  f"scheme_code={(body.get('meta') or {}).get('scheme_code')}, records={len(body.get('data') or [])}")
        _res(out, test_id, "KNOWN ISSUE: unknown scheme code should not be reported as status SUCCESS",
             label, not reports_success, detail, resp.elapsed_ms, known_issue=True)
    return out
