"""Schema tests: prompt rendering + verdict parsing round-trip and robustness."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from fake_forge import generate_tasks  # noqa: E402

from reconforge_model import schema  # noqa: E402


def test_system_prompt_mentions_all_exception_types():
    for et in schema.EXCEPTION_TYPES:
        assert et in schema.SYSTEM_PROMPT
    assert "MATCH" in schema.SYSTEM_PROMPT
    assert "ESCALATE" in schema.SYSTEM_PROMPT


def test_render_user_message_contains_both_sides():
    task = generate_tasks(n=1, seed=1)[0]
    text = schema.render_user_message(task)
    assert "LEDGER ENTRY" in text
    assert "BANK STATEMENT" in text
    assert task["ledger"]["ref"] in text
    assert task["statement"]["ref"] in text


def test_roundtrip_canonical_json_parses_back():
    for task in generate_tasks(n=50, seed=7):
        expected = task["expected"]
        canonical = schema.canonical_verdict_json(expected)
        parsed = schema.parse_verdict(canonical)
        assert parsed is not None
        assert parsed["verdict"] == expected["verdict"]
        assert parsed["exception_type"] == expected.get("exception_type")
        assert parsed["severity"] == expected["severity"]
        assert parsed["confidence"] == 1.0
        assert parsed["resolution"] == expected["resolution"]


def test_parse_verdict_robustness():
    good = '{"verdict":"EXCEPTION","exception_type":"AMOUNT_MISMATCH","severity":"HIGH","confidence":0.9,"reason":"amounts differ","resolution":"auto-adjust"}'
    cases = [
        (f"```json\n{good}\n```", True),
        (f"Here is the verdict:\n{good}\n\nHope this helps", True),
        (good[:-1], True),  # truncated closing brace -> synthetic close
        ("I think the answer is no", False),
        ('{"foo": 1}', False),
        ('{"verdict":"BANANA","confidence":0.5}', False),
        ('{"verdict":"EXCEPTION","confidence":0.5}', False),  # missing exception_type
    ]
    for text, expect_ok in cases:
        parsed = schema.parse_verdict(text)
        assert (parsed is not None) == expect_ok, f"case failed: {text!r}"


def test_parse_verdict_defaults_and_normalization():
    text = '{"verdict":"MATCH","confidence":1.0,"reason":"ok"}'
    parsed = schema.parse_verdict(text)
    assert parsed["severity"] == "LOW"
    assert parsed["exception_type"] is None
    assert parsed["resolution"] == "flag-review"
    # MATCH with an exception_type is normalized to None
    text2 = '{"verdict":"MATCH","exception_type":"DUPLICATE","confidence":1.0}'
    parsed2 = schema.parse_verdict(text2)
    assert parsed2["exception_type"] is None


def test_confidence_clamped_and_typed():
    for raw in (1.7, -0.2, "abc", None):
        parsed = schema.parse_verdict(
            json.dumps({"verdict": "MATCH", "confidence": raw})
        )
        assert 0.0 <= parsed["confidence"] <= 1.0


def test_severity_defaults_match_taxonomy():
    assert schema.default_severity("AMOUNT_MISMATCH", "EXCEPTION") == "HIGH"
    assert schema.default_severity("VALUE_DATE_MISMATCH", "EXCEPTION") == "MEDIUM"
    assert schema.default_severity("DUPLICATE", "EXCEPTION") == "LOW"
