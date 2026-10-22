"""Central configuration. Every threshold can be overridden here or via environment variables."""
import os

BASE_URL = os.getenv("MFAPI_BASE_URL", "https://api.mfapi.in").rstrip("/")
TIMEOUT_S = float(os.getenv("MFAPI_TIMEOUT_S", "20"))
RETRIES = 3
REQUEST_DELAY_S = 0.25          # be polite to a free public API

# Performance threshold for a single request (milliseconds)
SLA_MS = int(os.getenv("MFAPI_SLA_MS", "3000"))

# Scheme(s) always tested. 125497 is the example code used in the official MFapi.in docs.
DEFAULT_SCHEME_CODES = [125497]
# Extra schemes are discovered through the search endpoint, so a wrong hard-coded code cannot break the run.
DEFAULT_SEARCH_QUERIES = [
    "Parag Parikh Flexi Cap Direct Growth",
    "SBI Liquid Fund Direct Growth",
    "Nippon India Small Cap Direct Growth",
]

# Data-quality thresholds
MAX_DAILY_NAV_CHANGE_PCT = 10.0   # a one-day NAV move above this is flagged for review
STALE_AFTER_DAYS = 7              # latest NAV older than this (calendar days) is stale
MAX_GAP_DAYS = 10                 # gap between consecutive NAV dates above this is flagged
FLAT_RUN_DAYS = 6                 # identical NAV for this many consecutive records is flagged

# Classification of large one-day moves
SPIKE_MIN_PCT = 10.0              # both legs of a spike-and-revert must move at least this much
SPIKE_REVERT_TOLERANCE = 0.2      # ...and the net move over both days must be within 20% of the first leg
IMPLAUSIBLE_CHANGE_PCT = 50.0     # a one-day move this large that does NOT revert is treated as a data break
