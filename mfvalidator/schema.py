"""JSON Schemas describing the MFapi.in response contract (shape only; business rules live in checks.py)."""
from jsonschema import Draft7Validator

_NAV_RECORD = {
    "type": "object",
    "required": ["date", "nav"],
    "properties": {
        "date": {"type": "string", "pattern": r"^\d{2}-\d{2}-\d{4}$"},
        "nav": {"type": "string", "pattern": r"^-?\d+(\.\d+)?$"},
    },
}

SCHEME_RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["meta", "data", "status"],
    "properties": {
        "meta": {
            "type": "object",
            "required": ["fund_house", "scheme_code", "scheme_name"],
            "properties": {
                "fund_house": {"type": "string", "minLength": 1},
                "scheme_type": {"type": ["string", "null"]},
                "scheme_category": {"type": ["string", "null"]},
                "scheme_code": {"type": ["integer", "string"]},
                "scheme_name": {"type": "string", "minLength": 1},
                "isin_growth": {"type": ["string", "null"]},
                "isin_div_reinvestment": {"type": ["string", "null"]},
            },
        },
        "data": {"type": "array", "items": _NAV_RECORD},
        "status": {"type": "string", "enum": ["SUCCESS"]},
    },
}

SEARCH_RESPONSE_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["schemeCode", "schemeName"],
        "properties": {
            "schemeCode": {"type": "integer"},
            "schemeName": {"type": "string", "minLength": 1},
        },
    },
}


def schema_errors(instance, schema) -> list:
    """Return human-readable schema violations (empty list = valid)."""
    out = []
    for err in Draft7Validator(schema).iter_errors(instance):
        path = "/".join(str(p) for p in err.absolute_path) or "<root>"
        out.append(f"{path}: {err.message}")
    return out[:10]
