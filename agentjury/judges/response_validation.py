"""Model reports accepted by direct vendor adapters."""

import re
from datetime import date


def direct_model_matches(requested: str, observed: object, *, compact_date: bool = False) -> bool:
    if observed == requested:
        return True
    if not isinstance(observed, str):
        return False
    # Explicit snapshots must match exactly. A named alias may resolve only to
    # the same name plus a syntactically valid dated snapshot, never another model.
    date_pattern = r"\d{8}" if compact_date else r"\d{4}-\d{2}-\d{2}"
    if re.search(r"-" + date_pattern + r"$", requested):
        return False
    match = re.fullmatch(re.escape(requested) + r"-(" + date_pattern + r")", observed)
    if match is None:
        return False
    try:
        date.fromisoformat(match.group(1))
    except ValueError:
        return False
    return True
