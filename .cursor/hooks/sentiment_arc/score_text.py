"""
Text-type-aware sentiment scoring.

Classifies text as code, error trace, mixed, or natural language,
and routes to the appropriate scoring method.
"""

import re

# Patterns that indicate code-heavy text
_CODE_INDICATORS = re.compile(r"(?:```|def |class |import |from |const |let |var |function |for |while |if |else |elif |return |try:|except:|except |finally:|with |async |await |public |private |protected |static |void|int |float |bool |char |String |struct |enum |interface |package |module |export |require |\{.*\}|\[.*\])", re.IGNORECASE)

# High indentation ratio check
_INDENTATION_PATTERN = re.compile(r"^\s{4,}", re.MULTILINE)

# Error/traceback patterns
_ERROR_INDICATORS = re.compile(
    r"(?:Traceback \(most recent call\)|Error:|Exception:|at line |stack trace|"
    r"File \"|ModuleNotFoundError|TypeError|ValueError|KeyError|AttributeError|"
    r"SyntaxError|IndexError|OSError|RuntimeError|NotImplementedError|"
    r"ENOENT|EACCES|EPERM|fatal:|error:|Error \d{3,}|HTTP \d{3}|failed|crashed|"
    r"panic:|segfault|core dumped)",
    re.IGNORECASE,
)

# Default negative score for error traces
_DEFAULT_ERROR_SCORE = -0.5

# Default negative score for mixed text
_DEFAULT_MIXED_SCORE = -0.2


def classify_text_type(text: str) -> str:
    """
    Classify text as 'natural_language', 'code', 'error_trace', or 'mixed'.

    Heuristics:
    - If >60% of lines start with 4+ spaces of indentation -> code
    - If contains code keywords/patterns AND error patterns -> mixed
    - If contains error patterns without code patterns -> error_trace
    - If contains code patterns without error patterns -> code
    - Otherwise -> natural_language
    """
    if not text or not text.strip():
        return "natural_language"

    lines = text.split("\n")
    non_empty_lines = [l for l in lines if l.strip()]
    if not non_empty_lines:
        return "natural_language"

    # Check indentation ratio
    indented_lines = sum(1 for l in non_empty_lines if l.startswith("    ") or l.startswith("\t"))
    indentation_ratio = indented_lines / len(non_empty_lines)

    has_code = bool(_CODE_INDICATORS.search(text)) or indentation_ratio > 0.6
    has_error = bool(_ERROR_INDICATORS.search(text))

    if has_code and has_error:
        return "mixed"
    if has_code:
        return "code"
    if has_error:
        return "error_trace"
    return "natural_language"


def score_text_by_type(
    text: str,
    sentiment_model=None,
    compute_fn=None,
    error_score: float = _DEFAULT_ERROR_SCORE,
    mixed_score: float = _DEFAULT_MIXED_SCORE,
) -> float:
    """
    Score text using the appropriate method based on text type.

    Returns sentiment score in [-1, +1].
    """
    text_type = classify_text_type(text)

    if text_type == "code":
        return 0.0  # Code has no sentiment
    elif text_type == "error_trace":
        return error_score
    elif text_type == "mixed":
        return mixed_score
    else:
        # Natural language — use the model
        if compute_fn is not None:
            result = compute_fn([text], sentiment_model)
            return result[0] if result else 0.0
        return 0.0


def score_text_by_type_with_confidence(
    text: str,
    sentiment_model=None,
    compute_fn=None,
    error_score: float = _DEFAULT_ERROR_SCORE,
    mixed_score: float = _DEFAULT_MIXED_SCORE,
) -> tuple[float, float]:
    """
    Score text and return (score, confidence).

    For code/error_trace/mixed texts scored heuristically, confidence = 1.0
    (these are deterministic rules, not uncertain predictions).
    For natural_language texts, confidence comes from the RoBERTa model.

    Returns (score in [-1, +1], confidence in [0.33, 1.0]).
    """
    text_type = classify_text_type(text)

    if text_type == "code":
        return 0.0, 1.0
    elif text_type == "error_trace":
        return error_score, 1.0
    elif text_type == "mixed":
        return mixed_score, 1.0
    else:
        # Natural language — use the model
        if compute_fn is not None:
            scores, confidences = compute_fn([text], sentiment_model)
            return (scores[0], confidences[0]) if scores else (0.0, 0.33)
        return 0.0, 0.33
