"""Model reports and provider-specific completion normalization."""

import re
from datetime import date

OPENROUTER_COMPLETION_POLICY = "openai-completed-v1"


def openrouter_finish_matches(requested: str, provider: object,
                             finish: object, native: object) -> bool:
    """Normalize one observed OpenAI status without trusting unknown providers.

    Call only for the OpenRouter route. Its normalized finish must still be stop;
    model, choice/error, content and usage checks remain the caller's responsibility.
    """
    if finish != "stop":
        return False
    if native in ("stop", "end_turn", "STOP"):
        return True
    return (native == "completed" and requested.startswith("openai/")
            and provider == "OpenAI")


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
