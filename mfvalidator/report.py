"""Builds the HTML, CSV and Excel validation reports."""
from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

import pandas as pd

CSS = """
body{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#f5f6f8;color:#1f2933}
header{background:#1f3a5f;color:#fff;padding:24px 32px}
header h1{margin:0 0 4px;font-size:22px} header p{margin:0;opacity:.8;font-size:13px}
main{padding:24px 32px;max-width:1200px;margin:auto}
.cards{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:24px}
.card{background:#fff;border-radius:8px;padding:16px 20px;min-width:150px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
.card .n{font-size:28px;font-weight:600} .card .l{font-size:12px;color:#617d98;text-transform:uppercase}
.pass{color:#1b873f} .fail{color:#c62828} .warn{color:#b26a00}
h2{margin:28px 0 8px;font-size:17px}
table{border-collapse:collapse;width:100%;background:#fff;border-radius:8px;overflow:hidden;
box-shadow:0 1px 3px rgba(0,0,0,.08);font-size:13px}
th{background:#e4e9f0;text-align:left;padding:8px 10px} td{padding:7px 10px;border-top:1px solid #edf0f4;vertical-align:top}
.tag{padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;color:#fff}
.KNOWN{background:#7b5ea7}.ERROR,.FAIL{background:#c62828}.WARNING{background:#e08a00}.INFO{background:#5b7a99}.PASS{background:#1b873f}
"""


def _table(df: pd.DataFrame, tag_cols=()) -> str:
    if df.empty:
        return "<p><em>Nothing to show.</em></p>"
    rows = []
    for _, r in df.iterrows():
        cells = []
        for col in df.columns:
            v = html.escape("" if pd.isna(r[col]) else str(r[col]))
            cells.append(f'<td><span class="tag {v}">{v}</span></td>' if col in tag_cols else f"<td>{v}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in df.columns)
    return f"<table><tr>{head}</tr>{''.join(rows)}</table>"


def _known(contract_df: pd.DataFrame) -> pd.Series:
    return contract_df["known_issue"].fillna(False).astype(bool) if "known_issue" in contract_df else \
        pd.Series(False, index=contract_df.index)


def summarise(contract_df: pd.DataFrame, issues_df: pd.DataFrame, schemes_df: pd.DataFrame) -> dict:
    known = _known(contract_df)
    lat = contract_df["latency_ms"].dropna() if "latency_ms" in contract_df else pd.Series(dtype=float)
    sev = issues_df["severity"].value_counts().to_dict() if not issues_df.empty else {}
    return {
        "schemes_tested": len(schemes_df),
        "tests_run": len(contract_df),
        "tests_passed": int(contract_df["passed"].sum()) if len(contract_df) else 0,
        "tests_failed": int((~contract_df["passed"] & ~known).sum()) if len(contract_df) else 0,
        "known_issues": int((~contract_df["passed"] & known).sum()) if len(contract_df) else 0,
        "errors": int(sev.get("ERROR", 0)),
        "warnings": int(sev.get("WARNING", 0)),
        "info": int(sev.get("INFO", 0)),
        "median_latency_ms": round(float(lat.median())) if len(lat) else None,
        "p95_latency_ms": round(float(lat.quantile(0.95))) if len(lat) else None,
    }


def write_reports(out_dir: Path, base_url: str, contract_df, issues_df, schemes_df) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    s = summarise(contract_df, issues_df, schemes_df)
    stamp = datetime.now().strftime("%d %b %Y, %H:%M")

    shown = contract_df.copy()
    if not shown.empty:
        kn = _known(contract_df)
        shown["result"] = ["PASS" if p else ("KNOWN" if k else "FAIL") for p, k in zip(contract_df["passed"], kn)]
        shown["latency_ms"] = shown["latency_ms"].round(0)
        shown = shown[["test_id", "result", "name", "target", "detail", "latency_ms"]]
    failed_only = shown[shown["result"] != "PASS"] if not shown.empty else shown

    cards = [
        (s["schemes_tested"], "Schemes tested", ""),
        (s["tests_run"], "API tests run", ""),
        (s["tests_passed"], "Passed", "pass"),
        (s["tests_failed"], "Failed", "fail" if s["tests_failed"] else "pass"),
        (s["known_issues"], "Known API issues", "warn" if s["known_issues"] else "pass"),
        (s["errors"], "Data errors", "fail" if s["errors"] else "pass"),
        (s["warnings"], "Data warnings", "warn" if s["warnings"] else "pass"),
        (f"{s['median_latency_ms']} ms" if s["median_latency_ms"] is not None else "n/a", "Median latency", ""),
        (f"{s['p95_latency_ms']} ms" if s["p95_latency_ms"] is not None else "n/a", "p95 latency", ""),
    ]
    card_html = "".join(f'<div class="card"><div class="n {c}">{n}</div><div class="l">{l}</div></div>' for n, l, c in cards)

    doc = f"""<!doctype html><html><head><meta charset="utf-8"><title>MFapi validation report</title>
<style>{CSS}</style></head><body>
<header><h1>MFapi.in API Test &amp; Data Validation Report</h1><p>Target: {html.escape(base_url)} | Generated {stamp}</p></header>
<main><div class="cards">{card_html}</div>
<h2>Schemes tested</h2>{_table(schemes_df)}
<h2>Failed tests and known API issues</h2>{_table(failed_only, tag_cols=("result",))}
<h2>Data-quality findings</h2>{_table(issues_df, tag_cols=("severity",))}
<h2>All API tests</h2>{_table(shown, tag_cols=("result",))}
</main></body></html>"""
    (out_dir / "validation_report.html").write_text(doc, encoding="utf-8")
    contract_df.to_csv(out_dir / "contract_results.csv", index=False)
    issues_df.to_csv(out_dir / "data_quality_issues.csv", index=False)
    with pd.ExcelWriter(out_dir / "validation_report.xlsx", engine="openpyxl") as xw:
        pd.DataFrame([s]).T.reset_index().rename(columns={"index": "metric", 0: "value"}).to_excel(
            xw, sheet_name="Summary", index=False)
        schemes_df.to_excel(xw, sheet_name="Schemes", index=False)
        contract_df.to_excel(xw, sheet_name="API tests", index=False)
        issues_df.to_excel(xw, sheet_name="Data quality", index=False)
    return s
