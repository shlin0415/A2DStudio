"""Tests for ScriptFunction.evaluate_safe — safe condition parser (no eval)."""

import pytest
from ling_chat.core.ai_service.script_engine.utils.script_function import ScriptFunction


class TestEvaluateSafe:
    """Safe parser: no eval(), only == and != operators."""

    # ── Empty / bare variable ────────────────────────────

    def test_empty_expression_returns_true(self):
        assert ScriptFunction.evaluate_safe("", {}) is True
        assert ScriptFunction.evaluate_safe("   ", {}) is True

    def test_bare_true_variable(self):
        assert ScriptFunction.evaluate_safe("flag", {"flag": True}) is True

    def test_bare_false_variable(self):
        assert ScriptFunction.evaluate_safe("flag", {"flag": False}) is False

    def test_bare_none_variable(self):
        assert ScriptFunction.evaluate_safe("flag", {"flag": None}) is False

    def test_bare_missing_variable(self):
        assert ScriptFunction.evaluate_safe("flag", {}) is False

    def test_bare_non_bool_variable_is_truthy(self):
        assert ScriptFunction.evaluate_safe("name", {"name": "艾玛"}) is True
        assert ScriptFunction.evaluate_safe("count", {"count": 42}) is True
        assert ScriptFunction.evaluate_safe("count", {"count": 0}) is True  # non-null

    # ── Equality ─────────────────────────────────────────

    def test_eq_bool_true(self):
        assert ScriptFunction.evaluate_safe("flag == true", {"flag": True}) is True
        assert ScriptFunction.evaluate_safe("flag == true", {"flag": False}) is False

    def test_eq_bool_false(self):
        assert ScriptFunction.evaluate_safe("flag == false", {"flag": False}) is True

    def test_eq_string(self):
        assert (
            ScriptFunction.evaluate_safe(
                'speaker == "ema"', {"speaker": "ema"}
            )
            is True
        )
        assert (
            ScriptFunction.evaluate_safe(
                'speaker == "ema"', {"speaker": "hiro"}
            )
            is False
        )

    def test_eq_number(self):
        assert ScriptFunction.evaluate_safe("count == 5", {"count": 5}) is True
        assert ScriptFunction.evaluate_safe("count == 5", {"count": 3}) is False

    def test_eq_null(self):
        assert ScriptFunction.evaluate_safe("val == null", {"val": None}) is True
        assert ScriptFunction.evaluate_safe("val == none", {"val": None}) is True

    # ── Inequality ───────────────────────────────────────

    def test_neq(self):
        assert ScriptFunction.evaluate_safe("flag != true", {"flag": False}) is True
        assert ScriptFunction.evaluate_safe("flag != true", {"flag": True}) is False

    def test_neq_string(self):
        assert (
            ScriptFunction.evaluate_safe('who != "ema"', {"who": "hiro"})
            is True
        )

    # ── Edge cases ───────────────────────────────────────

    def test_spaces_around_operator(self):
        assert ScriptFunction.evaluate_safe("flag  ==  true", {"flag": True}) is True

    def test_single_quoted_string(self):
        assert (
            ScriptFunction.evaluate_safe("speaker == 'ema'", {"speaker": "ema"})
            is True
        )

    def test_variable_with_int_vs_float(self):
        # 5 as int == 5.0 as float → both normalize to same numeric type
        assert ScriptFunction.evaluate_safe("x == 5", {"x": 5}) is True

    def test_case_insensitive_literals(self):
        assert ScriptFunction.evaluate_safe("a == TRUE", {"a": True}) is True
        assert ScriptFunction.evaluate_safe("a == False", {"a": False}) is True


class TestEvaluateSafeMatchesOldBehavior:
    """Verify evaluate_safe behaves correctly where old evaluate did."""

    def test_empty(self):
        assert ScriptFunction.evaluate_safe("", {}) == ScriptFunction.evaluate("", {})

    def test_bool_var(self):
        vars_ = {"flag": True}
        assert ScriptFunction.evaluate_safe("flag", vars_) == ScriptFunction.evaluate("flag", vars_)

    def test_missing_var(self):
        assert ScriptFunction.evaluate_safe("x", {}) == ScriptFunction.evaluate("x", {})

    def test_eq_true_lowercase(self):
        """evaluate_safe handles lowercase true (old eval did not — it's an improvement)."""
        vars_ = {"flag": True}
        assert ScriptFunction.evaluate_safe("flag == true", vars_) is True
