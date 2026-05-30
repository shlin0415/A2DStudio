"""Cost tracking — token / time / cost limits for A2D Studio ASMR mode."""
import time
from dataclasses import dataclass

from ling_chat.core.logger import logger

# Rough pricing (CNY per 1M tokens)
MODEL_PRICES = {
    "deepseek-v4-flash": {"prompt": 0.55, "completion": 1.10},
    "deepseek-v4":      {"prompt": 1.10, "completion": 2.20},
    "deepseek-chat":    {"prompt": 1.00, "completion": 2.00},
    "gpt-4o-mini":      {"prompt": 1.10, "completion": 4.40},
    "claude-sonnet-4-6": {"prompt": 21.00, "completion": 84.00},
}


@dataclass
class BudgetConfig:
    max_time_seconds: int = 1800   # 30 minutes
    max_tokens: int = 100_000      # 100k tokens
    max_cost_yuan: float = 1.0     # 1 CNY


@dataclass
class BudgetStatus:
    elapsed_seconds: float = 0
    prompt_tokens_used: int = 0
    completion_tokens_used: int = 0
    total_tokens_used: int = 0
    cost_yuan: float = 0.0
    time_exceeded: bool = False
    tokens_exceeded: bool = False
    cost_exceeded: bool = False

    @property
    def can_continue(self) -> bool:
        return not (self.time_exceeded or self.tokens_exceeded or self.cost_exceeded)


class BudgetTracker:
    def __init__(self, config: BudgetConfig | None = None, model: str = "deepseek-v4-flash"):
        self.config = config or BudgetConfig()
        self.model = model
        self.start_time = time.time()

        self.prompt_tokens_used = 0
        self.completion_tokens_used = 0

    def record_llm_call(self, prompt_tokens: int, completion_tokens: int):
        self.prompt_tokens_used += prompt_tokens
        self.completion_tokens_used += completion_tokens

    def check_limits(self) -> BudgetStatus:
        elapsed = time.time() - self.start_time
        total_tokens = self.prompt_tokens_used + self.completion_tokens_used

        price = MODEL_PRICES.get(
            self.model, {"prompt": 1.0, "completion": 2.0}
        )
        cost = (
            self.prompt_tokens_used / 1_000_000 * price["prompt"]
            + self.completion_tokens_used / 1_000_000 * price["completion"]
        )

        status = BudgetStatus(
            elapsed_seconds=elapsed,
            prompt_tokens_used=self.prompt_tokens_used,
            completion_tokens_used=self.completion_tokens_used,
            total_tokens_used=total_tokens,
            cost_yuan=round(cost, 4),
            time_exceeded=elapsed >= self.config.max_time_seconds,
            tokens_exceeded=total_tokens >= self.config.max_tokens,
            cost_exceeded=cost >= self.config.max_cost_yuan,
        )

        if not status.can_continue:
            logger.warning(
                f"Budget exceeded: time={status.time_exceeded}, "
                f"tokens={status.tokens_exceeded}, cost={status.cost_exceeded}"
            )

        return status

    def reset_timer(self):
        self.start_time = time.time()
