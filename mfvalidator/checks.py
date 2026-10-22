"""Data-quality checks for a mutual fund NAV time series.

Each check is a small pure function: DataFrame in, Issue (or None) out. That keeps them easy to unit-test
with synthetic bad data and easy to extend.

Severity guide
  ERROR   - the data is wrong or unusable (bad format, non-positive NAV, duplicates, future dates)
  WARNING - suspicious, needs a human look (big jumps, gaps, stale feed, frozen NAV, unsorted)
  INFO    - worth knowing, not necessarily a defect
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from . import config

ERROR, WARNING, INFO = "ERROR", "WARNING", "INFO"


@dataclass
class Issue:
    check: str
    severity: str
    count: int
    detail: str
    examples: list = field(default_factory=list)


def to_frame(records: list | None) -> pd.DataFrame:
    """Turn the API's `data` list into a typed DataFrame, keeping the raw strings for diagnostics."""
    df = pd.DataFrame(records or []).reindex(columns=["date", "nav"])
    df = df.rename(columns={"date": "date_raw", "nav": "nav_raw"})
    df["date"] = pd.to_datetime(df["date_raw"], format="%d-%m-%Y", errors="coerce")
    df["nav"] = pd.to_numeric(df["nav_raw"], errors="coerce")
    return df


def _examples(series, n: int = 5) -> list:
    return [str(x) for x in list(series)[:n]]


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    """Rows with a valid date and a valid positive NAV, one row per date, oldest first."""
    out = df.dropna(subset=["date", "nav"])
    out = out[out["nav"] > 0].drop_duplicates("date").sort_values("date")
    return out.reset_index(drop=True)


# ----------------------------------------------------------------------------------------- checks
def empty_dataset(df, **_):
    if len(df) == 0:
        return Issue("empty_dataset", ERROR, 0, "No NAV records were returned.")


def unparseable_dates(df, **_):
    bad = df[df["date"].isna()]
    if len(bad):
        return Issue("unparseable_dates", ERROR, len(bad), "Date is not a valid dd-mm-yyyy value.",
                     _examples(bad["date_raw"]))


def non_numeric_nav(df, **_):
    bad = df[df["nav"].isna()]
    if len(bad):
        return Issue("non_numeric_nav", ERROR, len(bad), "NAV is missing or not a number.",
                     _examples(bad["nav_raw"]))


def non_positive_nav(df, **_):
    bad = df[df["nav"] <= 0]
    if len(bad):
        return Issue("non_positive_nav", ERROR, len(bad), "NAV must be greater than zero.",
                     [f"{r.date_raw}: {r.nav_raw}" for r in bad.head(5).itertuples()])


def duplicate_dates(df, **_):
    valid = df[df["date"].notna()]
    dup = valid[valid.duplicated("date", keep=False)]
    if len(dup):
        days = dup["date"].nunique()
        return Issue("duplicate_dates", ERROR, days, "The same date appears more than once.",
                     _examples(dup["date_raw"].drop_duplicates()))


def future_dates(df, today: date | None = None, **_):
    today = pd.Timestamp(today or date.today())
    bad = df[df["date"] > today]
    if len(bad):
        return Issue("future_dates", ERROR, len(bad), "NAV is dated in the future.", _examples(bad["date_raw"]))


def sort_order(df, **_):
    d = df["date"].dropna().reset_index(drop=True)
    if len(d) < 2 or d.is_monotonic_decreasing:
        return None
    if d.is_monotonic_increasing:
        return Issue("sort_order", INFO, 0, "Records are oldest-first; the API normally returns newest-first.")
    out_of_order = int((d.diff() > pd.Timedelta(0)).sum())
    return Issue("sort_order", WARNING, out_of_order, "Records are not in a consistent date order.")


def stale_latest(df, today: date | None = None, stale_after_days: int = config.STALE_AFTER_DAYS, **_):
    latest = df["date"].max()
    if pd.isna(latest):
        return None
    age = (pd.Timestamp(today or date.today()) - latest).days
    if age > stale_after_days:
        return Issue("stale_latest_nav", WARNING, 1,
                     f"Latest NAV is {age} days old (threshold {stale_after_days}).", [latest.strftime("%d-%m-%Y")])


def date_gaps(df, max_gap_days: int = config.MAX_GAP_DAYS, **_):
    s = _clean(df)
    if len(s) < 2:
        return None
    gaps = s["date"].diff().dt.days
    big = s[gaps > max_gap_days]
    if len(big):
        ex = [f"{gaps[i]:.0f} days before {s.at[i, 'date']:%d-%m-%Y}" for i in big.index[:5]]
        return Issue("date_gaps", WARNING, len(big), f"Gap between NAV dates above {max_gap_days} days.", ex)


def _spike_positions(s: pd.DataFrame, min_pct: float = config.SPIKE_MIN_PCT,
                     tol: float = config.SPIKE_REVERT_TOLERANCE) -> list:
    """Positions i where NAV jumps away from its neighbours and returns the next record (one bad record)."""
    nav = s["nav"].to_numpy()
    hits = []
    for i in range(1, len(nav) - 1):
        a = nav[i] / nav[i - 1] - 1
        b = nav[i + 1] / nav[i] - 1
        net = nav[i + 1] / nav[i - 1] - 1
        if abs(a) * 100 >= min_pct and abs(b) * 100 >= min_pct and a * b < 0 and abs(net) <= tol * abs(a):
            hits.append(i)
    return hits


def _implausible_positions(s: pd.DataFrame, max_pct: float, spikes: list) -> list:
    chg = s["nav"].pct_change() * 100
    covered = set(spikes) | {i + 1 for i in spikes}
    return [i for i in range(1, len(s)) if abs(chg.iloc[i]) >= max_pct and i not in covered]


def spike_and_revert(df, spike_min_pct: float = config.SPIKE_MIN_PCT, **_):
    s = _clean(df)
    if len(s) < 3:
        return None
    hits = _spike_positions(s, spike_min_pct)
    if hits:
        ex = [f"{s.at[i, 'date']:%d-%m-%Y}: NAV {s.at[i, 'nav']:g} between {s.at[i - 1, 'nav']:g} and "
              f"{s.at[i + 1, 'nav']:g}" for i in hits[:5]]
        return Issue("spike_and_revert", ERROR, len(hits),
                     "NAV jumps and returns to its previous level on the next record: a single bad record, "
                     "not a market move.", ex)


def implausible_jumps(df, max_pct: float = config.IMPLAUSIBLE_CHANGE_PCT, **_):
    s = _clean(df)
    if len(s) < 2:
        return None
    pos = _implausible_positions(s, max_pct, _spike_positions(s))
    if not pos:
        return None
    ex = []
    for i in pos[:5]:
        prev, cur = s.at[i - 1, "nav"], s.at[i, "nav"]
        ratio = cur / prev
        hint = ""
        for k in (10, 100, 1000):
            if abs(ratio / k - 1) < 0.1 or abs(ratio * k - 1) < 0.1:
                hint = f" (about {k}x: possible scale or face-value change)"
        ex.append(f"{s.at[i, 'date']:%d-%m-%Y}: {prev:g} -> {cur:g} (x{ratio:.2f}){hint}")
    return Issue("implausible_jumps", ERROR, len(pos),
                 f"One-day NAV move of {max_pct:g}% or more that does not revert: a break in the series, "
                 "so returns computed across it would be wrong.", ex)


def daily_change_outliers(df, max_change_pct: float = config.MAX_DAILY_NAV_CHANGE_PCT, **_):
    """Large moves that are NOT already classified as a spike or a series break (likely real market events)."""
    s = _clean(df)
    if len(s) < 2:
        return None
    spikes = _spike_positions(s)
    implausible = _implausible_positions(s, config.IMPLAUSIBLE_CHANGE_PCT, spikes)
    covered = set(spikes) | {i + 1 for i in spikes} | set(implausible)
    chg = s["nav"].pct_change() * 100
    big = [i for i in range(1, len(s)) if abs(chg.iloc[i]) > max_change_pct and i not in covered]
    if big:
        ex = [f"{s.at[i, 'date']:%d-%m-%Y}: {chg.iloc[i]:+.1f}%" for i in big[:5]]
        return Issue("daily_change_outliers", WARNING, len(big),
                     f"One-day NAV move above {max_change_pct:g}% (review: market event, payout, merger or data error).", ex)


def flat_runs(df, run_days: int = config.FLAT_RUN_DAYS, **_):
    s = _clean(df)
    if len(s) < run_days:
        return None
    groups = (s["nav"] != s["nav"].shift()).cumsum()
    sizes = s.groupby(groups).size()
    long_runs = sizes[sizes >= run_days]
    if len(long_runs):
        ex = []
        for g in long_runs.index[:5]:
            block = s[groups == g]
            ex.append(f"{len(block)} identical NAVs ({block['nav'].iloc[0]}) from "
                      f"{block['date'].iloc[0]:%d-%m-%Y} to {block['date'].iloc[-1]:%d-%m-%Y}")
        return Issue("flat_nav_runs", WARNING, len(long_runs),
                     f"NAV unchanged for {run_days}+ consecutive records (possible frozen feed).", ex)


def weekend_dates(df, **_):
    bad = df[df["date"].dt.dayofweek >= 5]
    if len(bad):
        return Issue("weekend_dates", INFO, len(bad), "NAV published on a Saturday or Sunday.",
                     _examples(bad["date_raw"]))


CHECKS = [empty_dataset, unparseable_dates, non_numeric_nav, non_positive_nav, duplicate_dates, future_dates,
          sort_order, stale_latest, date_gaps, spike_and_revert, implausible_jumps, daily_change_outliers,
          flat_runs, weekend_dates]


def run_checks(df: pd.DataFrame, today: date | None = None, **thresholds) -> list:
    """Run every check and return the issues found (an empty list means the series is clean)."""
    issues = []
    for check in CHECKS:
        issue = check(df, today=today, **thresholds)
        if issue is not None:
            issues.append(issue)
    return issues
