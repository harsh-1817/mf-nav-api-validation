import pytest

from mfvalidator import config
from mfvalidator.client import MFApiClient


@pytest.fixture(scope="session")
def client():
    return MFApiClient()


@pytest.fixture(scope="session")
def scheme_codes():
    return config.DEFAULT_SCHEME_CODES
