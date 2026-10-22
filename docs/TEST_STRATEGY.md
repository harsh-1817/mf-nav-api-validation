# Test strategy: MFapi.in NAV API

## Scope
| In scope | Out of scope |
|---|---|
| Public MFapi.in REST endpoints: search, scheme list, NAV history (with date range), latest NAV | Load / stress testing (the API is a free shared service) |
| Response contract (status, headers, JSON shape) | Authentication / authorisation (the API is open) |
| Accuracy and integrity of the returned NAV time series | Verifying NAVs against the AMC / AMFI source of record |
| Cross-endpoint consistency, robustness to bad input, response time | Any private or company endpoint |

## Risks the tests target
| Risk | Why it matters in finance | How it is tested |
|---|---|---|
| Wrong or corrupt NAV (zero, negative, text) | Portfolio valuation and P&L would be wrong | `non_numeric_nav`, `non_positive_nav`, schema pattern, PM-H11 |
| Duplicate or missing dates | Returns and XIRR are miscalculated | `duplicate_dates`, `date_gaps`, PM-H12 |
| Isolated bad records | One wrong NAV distorts returns and risk figures | `spike_and_revert`, PM-H15 |
| Breaks in the series (scale / face-value change) | Returns across the break are wrong by orders of magnitude | `implausible_jumps`, PM-H16 |
| Sudden NAV jumps | Could be a genuine market event, payout or merger | `daily_change_outliers` (WARNING, human review), PM-H14 |
| Stale or frozen data | Users see yesterday's price as today's | `stale_latest_nav`, `flat_nav_runs` |
| Endpoints disagreeing with each other | `/latest` shows a different NAV than the history | X01, X02, PM-L08, PM-L09 |
| Contract drift (field renamed, type changed) | Downstream integrations break silently | JSON-schema tests H04, L03, S03, PM-*-schema |
| Bad input crashes the service or leaks internals | Reliability and security | N01-N06, PM-N01 to PM-N10 |
| Slow responses | Poor user experience, timeouts | H02, L02, S02, PM-*-response time |

## Test layers
1. **Postman / Newman collection** (`postman/`): 56 assertions across 5 folders. Black-box API testing, readable by non-programmers, runnable in CI with Newman.
2. **Python contract tests** (`mfvalidator/contract.py`): the same API behaviours, plus cross-endpoint checks, producing a structured result per test.
3. **Python data-quality checks** (`mfvalidator/checks.py`): 14 reusable checks that analyse the full NAV history of each scheme.
4. **Unit tests** (`tests/test_checks.py`): synthetic bad data proves every check catches the defect it was written for and stays quiet on clean data. They run offline.

## Severity model for data issues
| Severity | Meaning | Affects exit code |
|---|---|---|
| ERROR | Data is wrong or unusable (bad format, non-positive NAV, duplicates, future dates, empty) | Yes |
| WARNING | Suspicious, needs a human review (jumps, gaps, stale, frozen, unsorted) | No |
| INFO | Worth knowing (weekend dates, oldest-first ordering) | No |

## Design decisions
- **Negative tests do not assume an error format.** The API docs do not specify how unknown scheme codes are reported, so the tests assert the behaviours that must always hold: *the request is not returned as a success payload* and *the service does not return a 5xx*.
- **Schemes are discovered through the search endpoint** so a wrong hard-coded scheme code cannot break the run.
- **Schema checks only describe shape; business rules live in the data checks.** A schema failure means the contract changed, a data check failure means the numbers are suspicious. Keeping them apart makes failures easy to triage.
- **Warnings are not failures.** A 15% one-day move in a small-cap fund may be real. The report surfaces it with examples for a human decision.

## Test case catalogue (Python)
| ID | Endpoint | Check |
|---|---|---|
| S01-S06 | `/mf/search` | status 200, response time, schema, non-empty results, no duplicate codes, results relevant to the query |
| P01-P03 | `/mf` | status 200, `limit` respected, `offset` pagination moves |
| H01-H07 | `/mf/{code}` | status 200, response time, JSON content type, schema, code matches request, status `SUCCESS`, data not empty |
| L01-L04 | `/mf/{code}/latest` | status 200, response time, schema, exactly one record |
| X01-X02 | cross-endpoint | `/latest` not older than newest history record; same-date NAV matches |
| R01-R03 | `/mf/{code}?startDate&endDate` | filter returns data, all dates inside the range, result smaller than full history |
| N01-N06 | negative / security | unknown and non-numeric codes, SQL-injection style input, missing parameter |
| N07-N08 | negative (known issue) | an unknown scheme code must not be reported as `status: SUCCESS` (currently is: HTTP 200 + SUCCESS + empty data + `scheme_code: 0`) |

The Postman collection mirrors these with `PM-` prefixed IDs and adds checks for calendar-valid dates, future dates, XSS reflection and information leakage.
