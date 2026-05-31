"""测试 BudgetTracker — token/time/cost 超限"""
import time
from ling_chat.core.budget_tracker import BudgetTracker, BudgetConfig


class TestTokenTracking:
    def test_record_and_check_tokens(self):
        bt = BudgetTracker(BudgetConfig(max_tokens=100), "deepseek-v4-flash")
        bt.record_llm_call(50, 60)
        status = bt.check_limits()
        assert status.total_tokens_used == 110
        assert status.tokens_exceeded is True

    def test_tokens_not_exceeded_under_limit(self):
        bt = BudgetTracker(BudgetConfig(max_tokens=1000), "deepseek-v4-flash")
        bt.record_llm_call(50, 60)
        status = bt.check_limits()
        assert status.tokens_exceeded is False

    def test_can_continue_when_under_limits(self):
        bt = BudgetTracker(BudgetConfig(max_tokens=1000), "deepseek-v4-flash")
        assert bt.check_limits().can_continue is True

    def test_multiple_calls_accumulate(self):
        bt = BudgetTracker(BudgetConfig(max_tokens=1000), "deepseek-v4-flash")
        bt.record_llm_call(100, 200)
        bt.record_llm_call(50, 50)
        status = bt.check_limits()
        assert status.prompt_tokens_used == 150
        assert status.completion_tokens_used == 250
        assert status.total_tokens_used == 400


class TestCostTracking:
    def test_cost_is_positive(self):
        bt = BudgetTracker(BudgetConfig(max_cost_yuan=10), "deepseek-v4-flash")
        bt.record_llm_call(1_000_000, 1_000_000)
        status = bt.check_limits()
        assert status.cost_yuan > 0

    def test_cost_exceeded(self):
        bt = BudgetTracker(BudgetConfig(max_cost_yuan=0.001), "deepseek-v4-flash")
        bt.record_llm_call(1_000_000, 1_000_000)
        status = bt.check_limits()
        assert status.cost_exceeded is True


class TestReset:
    def test_reset_timer(self):
        bt = BudgetTracker(BudgetConfig(max_time_seconds=1800), "deepseek-v4-flash")
        time.sleep(0.1)
        bt.reset_timer()
        status = bt.check_limits()
        assert status.elapsed_seconds < 1
        assert status.time_exceeded is False
