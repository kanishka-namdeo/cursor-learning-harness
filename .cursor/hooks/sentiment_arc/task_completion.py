"""
Task Completion Detection — LLM-as-judge for sentiment arc sessions.

Evaluates whether the user's task was completed successfully by analyzing
the first prompt and the final exchanges of a session. Uses the same LLM
infrastructure as summarizer_agent.py (llm.env config).

Industry research (LangSmith, UpTrain, Galileo) shows task completion is
the #1 predictor of user satisfaction, not raw sentiment.

Returns {score: 0.0-1.0, label, explanation} where label is one of:
  "completed" | "partial" | "failed" | "abandoned" | "unknown"
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# LLM config loaded from llm.env (same pattern as summarizer_agent.py)
_HOOKS_DIR = Path(__file__).parent.parent
_LLM_ENV_PATH = _HOOKS_DIR.parent / "llm.env"

# Cache for the LLM instance to avoid re-creating it per session
_llm_cache: Any = None


def _get_llm():
    """Lazy-init the LLM using the project's llm.env config."""
    global _llm_cache
    if _llm_cache is not None:
        return _llm_cache

    # Load env vars from llm.env
    env_path = _LLM_ENV_PATH
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip()
                    if key and key not in os.environ:
                        os.environ[key] = value

    api_key = os.getenv("API_KEY")
    if not api_key:
        raise RuntimeError("API_KEY not set in llm.env for task completion judge")

    base_url = os.getenv("BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("FAST_MODEL") or os.getenv("REASONING_MODEL", "qwen3.6-plus")

    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        raise RuntimeError("langchain_openai is required for task completion judge")

    _llm_cache = ChatOpenAI(
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=0.0,
        max_tokens=256,
        timeout=30,
    )
    return _llm_cache


# ---------------------------------------------------------------------------
# Turn extraction
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are evaluating whether a user's task was completed in a conversation with an AI coding assistant.

The user's original request was:
{first_user_prompt}

The final exchanges were:
{formatted_final_turns}

Evaluate on two dimensions:
1. COMPLETENESS: Did the assistant address the user's stated goal?
2. USER ACCEPTANCE: Does the user's final response indicate satisfaction, acceptance, or continued frustration?

Return ONLY a JSON object (no markdown, no explanation outside JSON) with:
- "score": a float from 0.0 to 1.0 (1.0 = fully completed and accepted, 0.0 = failed or abandoned)
- "label": one of "completed", "partial", "failed", "abandoned"
- "explanation": 1-2 sentences explaining your assessment

Classification rules:
- "completed": goal addressed + user accepted (explicit thanks, confirmation, or silence after solution)
- "partial": partial progress made but user still has unresolved needs
- "failed": assistant did not solve the problem and user expressed dissatisfaction
- "abandoned": user stopped responding or session ended without resolution (no final user message)
"""


def _extract_final_turns(turns: list[dict], n: int = 3) -> tuple[str, str]:
    """Extract the first user prompt and the last N user/assistant turns.

    Returns (first_user_prompt, formatted_final_turns_string).
    """
    # First user prompt
    first_user_prompt = ""
    for t in turns:
        if t["role"] == "user":
            first_user_prompt = t["text"][:500]
            break

    # Last N user + last N assistant turns, in chronological order
    user_turns = [t for t in turns if t["role"] == "user"][-n:]
    assistant_turns = [t for t in turns if t["role"] == "assistant"][-n:]

    # Reconstruct chronological order from the last turns
    all_final = []
    seen_indices = set()
    # Walk backwards from the end, collecting up to N of each role
    user_collected = 0
    assistant_collected = 0
    for i in range(len(turns) - 1, -1, -1):
        t = turns[i]
        if t["role"] == "user" and user_collected < n:
            all_final.append((i, t))
            user_collected += 1
        elif t["role"] == "assistant" and assistant_collected < n:
            all_final.append((i, t))
            assistant_collected += 1
        if user_collected >= n and assistant_collected >= n:
            break

    # Sort back to chronological order
    all_final.sort(key=lambda x: x[0])

    lines = []
    for _, t in all_final:
        role_label = "User" if t["role"] == "user" else "Assistant"
        text = t["text"][:400]
        lines.append(f"{role_label}: {text}")

    formatted = "\n\n".join(lines) if lines else "(no final exchanges found)"

    return first_user_prompt or "(no user prompt found)", formatted


def _has_final_user_message(turns: list[dict]) -> bool:
    """Check if the last text-bearing turn is from the user."""
    for i in range(len(turns) - 1, -1, -1):
        if turns[i]["role"] == "user" and turns[i]["text"].strip():
            return True
        elif turns[i]["role"] == "assistant" and turns[i]["text"].strip():
            return False
    return False


def evaluate_task_completion(turns: list[dict]) -> dict:
    """Evaluate whether the user's task was completed.

    Args:
        turns: list of turn dicts from parser (with 'role' and 'text' keys)

    Returns:
        dict with keys: score (float or None), label (str), explanation (str)
    """
    # Edge case: too few turns
    if len(turns) < 2:
        return {
            "score": 0.0,
            "label": "abandoned",
            "explanation": "Session too short to evaluate task completion.",
        }

    # Quick heuristic check: if session ended without a final user message
    # and the last assistant turn didn't contain an explicit resolution signal,
    # it's likely abandoned. We use this to avoid unnecessary LLM calls for
    # clearly abandoned sessions.
    has_final_user = _has_final_user_message(turns)

    try:
        llm = _get_llm()
    except (RuntimeError, ImportError) as e:
        logger.warning("LLM judge unavailable for task completion: %s", e)
        # Fail-open with heuristic-only result
        if not has_final_user:
            return {
                "score": 0.1,
                "label": "abandoned",
                "explanation": "Session ended without final user response; LLM judge unavailable.",
            }
        return {
            "score": None,
            "label": "unknown",
            "explanation": f"LLM judge unavailable: {e}",
        }

    first_prompt, final_turns = _extract_final_turns(turns)
    prompt = SYSTEM_PROMPT.format(
        first_user_prompt=first_prompt,
        formatted_final_turns=final_turns,
    )

    # Try up to 2 times to get valid JSON
    for attempt in range(2):
        try:
            from langchain_core.messages import HumanMessage

            response = llm.invoke([HumanMessage(content=prompt)])
            text = response.content.strip() if hasattr(response, "content") else str(response).strip()

            # Strip markdown code fences if present
            if text.startswith("```"):
                lines = text.split("\n")
                # Remove first and last line if they are ``` markers
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip().startswith("```"):
                    lines = lines[:-1]
                text = "\n".join(lines)

            result = json.loads(text)

            # Validate required fields
            if not isinstance(result, dict):
                raise ValueError("Response is not a JSON object")
            if "score" not in result or "label" not in result:
                raise ValueError("Missing required fields: score and label")

            score = float(result["score"])
            score = max(0.0, min(1.0, score))  # Clamp

            label = result.get("label", "unknown")
            if label not in ("completed", "partial", "failed", "abandoned"):
                # Fallback: infer label from score
                if score >= 0.8:
                    label = "completed"
                elif score >= 0.4:
                    label = "partial"
                elif score >= 0.1:
                    label = "abandoned"
                else:
                    label = "failed"

            explanation = result.get("explanation", "")

            return {"score": score, "label": label, "explanation": explanation}

        except (json.JSONDecodeError, ValueError, KeyError, TypeError, RuntimeError) as e:
            logger.warning("Task completion LLM parse error (attempt %d): %s", attempt + 1, e)
            if attempt == 1:
                # Final fallback
                if not has_final_user:
                    return {
                        "score": 0.1,
                        "label": "abandoned",
                        "explanation": "Session ended without final user response.",
                    }
                return {
                    "score": None,
                    "label": "unknown",
                    "explanation": f"Could not parse LLM response after 2 attempts: {e}",
                }
