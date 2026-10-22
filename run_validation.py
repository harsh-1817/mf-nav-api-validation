"""Command-line runner: API contract tests + data-quality validation, with HTML/CSV/Excel reports.

Examples
    python run_validation.py
    python run_validation.py --codes 125497 119551 --queries "HDFC Flexi Cap Direct Growth"
    python run_validation.py --out reports --max-change 8

Exit code is 1 when any API test fails or any ERROR-level data issue is found (CI friendly).
"""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from mfvalidator import config
from mfvalidator.checks import ERROR, run_checks, to_frame
from mfvalidator.client import MFApiClient
from mfvalidator.contract import global_tests, scheme_tests
from mfvalidator.report import write_reports

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("mfvalidator")


def resolve_schemes(client: MFApiClient, codes: list, queries: list) -> list:
    """Combine explicit scheme codes with the best (Direct/Growth) match for each search query."""
    found = [int(c) for c in codes]
    for q in queries:
        resp = client.search(q)
        rows = resp.json if resp.ok and isinstance(resp.json, list) else []
        if not rows:
            log.warning("Search '%s' returned nothing (status %s)", q, resp.status_code)
            continue
        pick = next((r for r in rows if "direct" in r.get("schemeName", "").lower()
                     and "growth" in r.get("schemeName", "").lower()), rows[0])
        log.info("Search '%s' -> %s (%s)", q, pick["schemeCode"], pick["schemeName"])
        if pick["schemeCode"] not in found:
            found.append(pick["schemeCode"])
    return found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Validate the MFapi.in API and its NAV data.")
    ap.add_argument("--codes", nargs="*", default=config.DEFAULT_SCHEME_CODES, help="scheme codes to test")
    ap.add_argument("--queries", nargs="*", default=config.DEFAULT_SEARCH_QUERIES,
                    help="search phrases; the best match for each is added to the run")
    ap.add_argument("--out", default="reports", help="output folder")
    ap.add_argument("--max-change", type=float, default=config.MAX_DAILY_NAV_CHANGE_PCT,
                    help="flag one-day NAV moves above this percentage")
    args = ap.parse_args(argv)

    client = MFApiClient()
    log.info("Target: %s", client.base_url)

    contract_rows = [asdict(r) for r in global_tests(client)]
    schemes = resolve_schemes(client, args.codes, args.queries)

    issue_rows, scheme_rows = [], []
    for code in schemes:
        log.info("Testing scheme %s", code)
        results, hist = scheme_tests(client, code)
        contract_rows += [asdict(r) for r in results]
        body = hist.json if isinstance(hist.json, dict) else {}
        meta = body.get("meta") or {}
        df = to_frame(body.get("data"))
        scheme_rows.append({
            "scheme_code": code, "scheme_name": meta.get("scheme_name"), "fund_house": meta.get("fund_house"),
            "category": meta.get("scheme_category"), "nav_records": len(df),
            "first_date": df["date"].min().strftime("%d-%m-%Y") if df["date"].notna().any() else None,
            "last_date": df["date"].max().strftime("%d-%m-%Y") if df["date"].notna().any() else None,
        })
        for issue in run_checks(df, max_change_pct=args.max_change):
            issue_rows.append({"scheme_code": code, "scheme_name": meta.get("scheme_name"),
                               "check": issue.check, "severity": issue.severity, "count": issue.count,
                               "detail": issue.detail, "examples": " | ".join(issue.examples)})

    contract_df = pd.DataFrame(contract_rows)
    issues_df = pd.DataFrame(issue_rows, columns=["scheme_code", "scheme_name", "check", "severity",
                                                   "count", "detail", "examples"])
    schemes_df = pd.DataFrame(scheme_rows)
    summary = write_reports(Path(args.out), client.base_url, contract_df, issues_df, schemes_df)

    log.info("Tests: %d run, %d passed, %d failed, %d known API issues | Data issues: %d errors, %d warnings, %d info",
             summary["tests_run"], summary["tests_passed"], summary["tests_failed"], summary["known_issues"],
             summary["errors"], summary["warnings"], summary["info"])
    log.info("Report written to %s", Path(args.out) / "validation_report.html")
    return 1 if (summary["tests_failed"] or (issues_df["severity"] == ERROR).any()) else 0


if __name__ == "__main__":
    sys.exit(main())
