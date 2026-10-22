"""Offline unit tests: every data-quality check must catch the defect it was written for,
and stay silent on clean data. No network needed."""
from datetime import date, timedelta

import pandas as pd

from mfvalidator import checks
from mfvalidator.checks import ERROR, INFO, WARNING, run_checks, to_frame

TODAY = date(2026, 10, 15)


def make(rows):
    """rows: list of (dd-mm-yyyy, nav-string)."""
    return to_frame([{"date": d, "nav": n} for d, n in rows])


def business_days(n, end=TODAY, start_nav=100.0, step=0.1):
    """n clean weekday records, newest first, with a gentle upward drift."""
    days, d = [], pd.Timestamp(end)
    while len(days) < n:
        if d.dayofweek < 5:
            days.append(d)
        d -= pd.Timedelta(days=1)
    navs = [start_nav + step * (n - i) for i in range(n)]
    return [(x.strftime("%d-%m-%Y"), f"{v:.4f}") for x, v in zip(days, navs)]


def names(issues):
    return {i.check for i in issues}


def test_clean_series_has_no_issues():
    assert run_checks(make(business_days(60)), today=TODAY) == []


def test_empty_dataset_is_error():
    issues = run_checks(make([]), today=TODAY)
    assert "empty_dataset" in names(issues)
    assert next(i for i in issues if i.check == "empty_dataset").severity == ERROR


def test_unparseable_date_detected():
    rows = business_days(10) + [("31-02-2026", "100.0"), ("2026/10/01", "101.0")]
    issue = checks.unparseable_dates(make(rows))
    assert issue and issue.count == 2 and issue.severity == ERROR


def test_non_numeric_nav_detected():
    rows = business_days(10)
    rows[3] = (rows[3][0], "N.A.")
    issue = checks.non_numeric_nav(make(rows))
    assert issue and issue.count == 1 and "N.A." in issue.examples


def test_non_positive_nav_detected():
    rows = business_days(10)
    rows[2] = (rows[2][0], "0.0000")
    rows[5] = (rows[5][0], "-12.5")
    issue = checks.non_positive_nav(make(rows))
    assert issue and issue.count == 2 and issue.severity == ERROR


def test_duplicate_dates_detected():
    rows = business_days(10)
    rows.append(rows[4])
    issue = checks.duplicate_dates(make(rows))
    assert issue and issue.count == 1 and issue.severity == ERROR


def test_future_date_detected():
    rows = business_days(10) + [((TODAY + timedelta(days=5)).strftime("%d-%m-%Y"), "150.0")]
    issue = checks.future_dates(make(rows), today=TODAY)
    assert issue and issue.count == 1 and issue.severity == ERROR


def test_sort_order_unsorted_is_warning_and_ascending_is_info():
    rows = business_days(10)
    shuffled = rows[:3] + rows[5:] + rows[3:5]
    assert checks.sort_order(make(shuffled)).severity == WARNING
    assert checks.sort_order(make(list(reversed(rows)))).severity == INFO
    assert checks.sort_order(make(rows)) is None


def test_stale_latest_detected():
    rows = business_days(30, end=TODAY - timedelta(days=20))
    issue = checks.stale_latest(make(rows), today=TODAY)
    assert issue and issue.severity == WARNING
    assert checks.stale_latest(make(business_days(30)), today=TODAY) is None


def test_date_gap_detected():
    rows = business_days(40)
    del rows[10:25]                      # remove about three weeks of records
    issue = checks.date_gaps(make(rows))
    assert issue and issue.count == 1 and issue.severity == WARNING


def test_daily_change_outlier_detected():
    rows = business_days(30)
    rows = [(d, f"{float(n) * 1.15:.4f}") if i < 10 else (d, n) for i, (d, n) in enumerate(rows)]  # one +15% step
    issue = checks.daily_change_outliers(make(rows), max_change_pct=10)
    assert issue and issue.count == 1 and issue.severity == WARNING


def test_market_style_drop_stays_a_warning_not_an_error():
    rows = business_days(30)
    rows = [(d, f"{float(n) * 0.87:.4f}") if i >= 10 else (d, n) for i, (d, n) in enumerate(rows)]  # persistent -13%
    assert checks.daily_change_outliers(make(rows)) is not None
    assert checks.spike_and_revert(make(rows)) is None
    assert checks.implausible_jumps(make(rows)) is None


def test_spike_and_revert_detected_with_real_observed_values():
    # MFapi.in, Quant Small Cap Fund (scheme 120828), observed 22 Oct 2026: one bad record on 27-05-2015
    rows = [("22-05-2015", "42.61150"), ("25-05-2015", "42.63780"), ("26-05-2015", "42.65000"),
            ("27-05-2015", "59.20900"), ("28-05-2015", "42.66570"), ("29-05-2015", "42.68370"),
            ("01-06-2015", "42.72390"), ("02-06-2015", "42.65700")]
    df = make(rows)
    issue = checks.spike_and_revert(df)
    assert issue and issue.severity == ERROR and issue.count == 1 and "27-05-2015" in issue.examples[0]
    assert checks.daily_change_outliers(df) is None          # not double-reported as a plain outlier
    assert checks.implausible_jumps(df) is None


def test_implausible_jump_detected_with_real_observed_values():
    # MFapi.in, HDFC Liquid Fund (scheme 119091), observed 22 Oct 2026: permanent 100x level shift on 30-08-2015
    rows = [("25-08-2015", "28.54240"), ("26-08-2015", "28.54830"), ("27-08-2015", "28.55430"),
            ("28-08-2015", "28.56030"), ("30-08-2015", "2857.24000"), ("31-08-2015", "2857.83190"),
            ("01-09-2015", "2858.42640"), ("02-09-2015", "2859.01370")]
    df = make(rows)
    issue = checks.implausible_jumps(df)
    assert issue and issue.severity == ERROR and issue.count == 1
    assert "30-08-2015" in issue.examples[0] and "100x" in issue.examples[0]
    assert checks.spike_and_revert(df) is None               # it does not revert, so it is a break, not a spike
    assert checks.daily_change_outliers(df) is None


def test_genuine_covid_style_crash_is_not_classified_as_an_error():
    # a -13% day followed by a partial rebound is a market event, not a bad record
    rows = business_days(20)
    rows[8] = (rows[8][0], f"{float(rows[8][1]) * 0.87:.4f}")
    rows[7] = (rows[7][0], f"{float(rows[7][1]) * 0.93:.4f}")
    df = make(rows)
    assert checks.spike_and_revert(df) is None
    assert checks.implausible_jumps(df) is None


def test_flat_run_detected():
    rows = business_days(30)
    for i in range(8, 16):
        rows[i] = (rows[i][0], "123.4500")
    issue = checks.flat_runs(make(rows), run_days=6)
    assert issue and issue.count == 1


def test_weekend_dates_info():
    rows = business_days(10) + [("04-10-2026", "99.0")]     # 4 Oct 2026 is a Sunday
    issue = checks.weekend_dates(make(rows))
    assert issue and issue.severity == INFO and issue.count == 1


def test_multiple_defects_are_all_reported():
    rows = business_days(40)
    rows.append(rows[2])                                     # duplicate
    rows[6] = (rows[6][0], "-1.0")                           # non-positive
    rows[12] = (rows[12][0], "oops")                         # non-numeric
    found = names(run_checks(make(rows), today=TODAY))
    assert {"duplicate_dates", "non_positive_nav", "non_numeric_nav"} <= found
