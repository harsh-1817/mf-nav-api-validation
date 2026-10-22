"""Offline tests of the unknown-scheme KNOWN ISSUE logic, using a fake client (no network)."""
from mfvalidator.client import ApiResponse
from mfvalidator.contract import unknown_scheme_known_issue_tests


def resp(status, body):
    return ApiResponse("http://fake", status, 5.0, "application/json", "", body)


class FakeClient:
    def __init__(self, response):
        self._r = response

    def scheme_history(self, code, *a, **k):
        return self._r

    def latest(self, code):
        return self._r


SUCCESS_EMPTY = {"meta": {"scheme_code": 0, "scheme_name": ""}, "data": [], "status": "SUCCESS"}


def test_known_issue_is_recorded_when_api_reports_success_for_unknown_scheme():
    results = unknown_scheme_known_issue_tests(FakeClient(resp(200, SUCCESS_EMPTY)))
    assert len(results) == 2
    assert all(not r.passed and r.known_issue for r in results)
    assert "status=SUCCESS" in results[0].detail and "scheme_code=0" in results[0].detail


def test_passes_when_api_rejects_unknown_scheme():
    results = unknown_scheme_known_issue_tests(FakeClient(resp(404, {"status": "ERROR"})))
    assert all(r.passed for r in results)
