"""Live tests against the real MFapi.in API.  Run with:  pytest -m live -v"""
import pytest

from mfvalidator.checks import ERROR, run_checks, to_frame
from mfvalidator.contract import global_tests, scheme_tests

pytestmark = pytest.mark.live


def _fail_msg(results):
    return "\n".join(f"[{r.test_id}] {r.name} -> {r.detail}" for r in results if not r.passed)


def test_global_endpoints_and_negative_cases(client):
    results = global_tests(client)
    assert not [r for r in results if not r.passed], _fail_msg(results)


def test_scheme_contract_and_consistency(client, scheme_codes):
    for code in scheme_codes:
        results, _ = scheme_tests(client, code)
        assert not [r for r in results if not r.passed], f"scheme {code}\n" + _fail_msg(results)


def test_scheme_data_has_no_error_level_issues(client, scheme_codes):
    for code in scheme_codes:
        body = client.scheme_history(code).json
        issues = run_checks(to_frame(body["data"]))
        errors = [i for i in issues if i.severity == ERROR]
        assert not errors, f"scheme {code}: " + "; ".join(f"{i.check} x{i.count} {i.examples}" for i in errors)
