from __future__ import annotations

from coding_agent.config import StepAllocConfig
from coding_agent.context.budget import TokenBudget, ZoneUsage


class TestZoneUsage:
    def test_defaults(self):
        zu = ZoneUsage()
        assert zu.allocated == 0
        assert zu.used == 0
        assert zu.remaining == 0

    def test_remaining(self):
        zu = ZoneUsage(allocated=1000, used=300)
        assert zu.remaining == 700

    def test_over_allocated(self):
        zu = ZoneUsage(allocated=100, used=200)
        assert zu.remaining == 0


class TestTokenBudget:
    def test_default_init(self):
        budget = TokenBudget(total=128000, step_allocations=StepAllocConfig())
        assert budget.total == 128000
        assert budget.available == 128000 - 4000 - 4096  # total - reserved
        assert budget.used_total == 0
        assert budget.used_this_step == 0

    def test_remaining(self):
        budget = TokenBudget(total=10000, step_allocations=StepAllocConfig(), reserved_for_system=0, reserved_for_response=0)
        assert budget.remaining() == 10000
        budget.record_usage(1000)
        assert budget.remaining() == 9000

    def test_remaining_fraction(self):
        budget = TokenBudget(total=10000, step_allocations=StepAllocConfig(), reserved_for_system=0, reserved_for_response=0)
        assert budget.remaining_fraction() == 1.0
        budget.record_usage(5000)
        assert budget.remaining_fraction() == 0.5

    def test_remaining_fraction_no_available(self):
        budget = TokenBudget(total=1000, step_allocations=StepAllocConfig(), reserved_for_system=1000, reserved_for_response=0)
        assert budget.remaining_fraction() == 0.0

    def test_can_execute_within_budget(self):
        budget = TokenBudget(total=100000, step_allocations=StepAllocConfig(), max_fraction_per_step=0.1, reserved_for_system=0, reserved_for_response=0)
        assert budget.can_execute(100) is True
        assert budget.can_execute(5000) is True

    def test_can_execute_too_large(self):
        budget = TokenBudget(total=10000, step_allocations=StepAllocConfig(), max_fraction_per_step=0.1, reserved_for_system=0, reserved_for_response=0)
        remaining = budget.remaining()
        max_for_step = int(remaining * 0.1)
        assert budget.can_execute(max_for_step + 1) is False

    def test_can_execute_insufficient_headroom(self):
        budget = TokenBudget(total=1000, step_allocations=StepAllocConfig(), max_fraction_per_step=0.5, reserved_for_system=0, reserved_for_response=0)
        # Use most of the budget first
        budget.record_usage(900)
        # 100 remaining, headroom is 5% of 1000 = 50
        # estimated 60 would leave 40 < 50
        assert budget.can_execute(60) is False
        assert budget.can_execute(40) is True

    def test_record_usage(self):
        budget = TokenBudget(total=10000, step_allocations=StepAllocConfig(), reserved_for_system=0, reserved_for_response=0)
        budget.record_usage(500)
        assert budget.used_total == 500
        assert budget.used_this_step == 500

    def test_record_usage_with_zone(self):
        budget = TokenBudget(total=10000, step_allocations=StepAllocConfig(), reserved_for_system=0, reserved_for_response=0)
        budget.record_usage(300, zone="working")
        assert budget.zones["working"].used == 300

    def test_record_usage_negative(self):
        budget = TokenBudget(total=10000, step_allocations=StepAllocConfig(), reserved_for_system=0, reserved_for_response=0)
        budget.record_usage(500)
        budget.record_usage(-200)
        assert budget.used_total == 300

    def test_start_new_step(self):
        budget = TokenBudget(total=10000, step_allocations=StepAllocConfig(), reserved_for_system=0, reserved_for_response=0)
        budget.record_usage(500)
        assert budget.used_this_step == 500
        budget.start_new_step()
        assert budget.used_this_step == 0
        assert budget.step_number == 1

    def test_set_zone_allocation_new(self):
        budget = TokenBudget(total=10000, step_allocations=StepAllocConfig(), reserved_for_system=0, reserved_for_response=0)
        budget.set_zone_allocation("working", 5000)
        assert budget.zones["working"].allocated == 5000

    def test_set_zone_allocation_existing(self):
        budget = TokenBudget(total=10000, step_allocations=StepAllocConfig(), reserved_for_system=0, reserved_for_response=0)
        budget.record_usage(100, zone="working")
        budget.set_zone_allocation("working", 200)
        assert budget.zones["working"].allocated == 200
        assert budget.zones["working"].used == 100

    def test_zone_remaining_nonexistent(self):
        budget = TokenBudget(total=10000, step_allocations=StepAllocConfig(), reserved_for_system=0, reserved_for_response=0)
        assert budget.zone_remaining("nonexistent") == 0

    def test_zone_remaining(self):
        budget = TokenBudget(total=10000, step_allocations=StepAllocConfig(), reserved_for_system=0, reserved_for_response=0)
        budget.set_zone_allocation("working", 1000)
        budget.record_usage(300, zone="working")
        assert budget.zone_remaining("working") == 700

    def test_zone_is_over_nonexistent(self):
        budget = TokenBudget(total=10000, step_allocations=StepAllocConfig(), reserved_for_system=0, reserved_for_response=0)
        assert budget.zone_is_over("nonexistent") is False

    def test_zone_is_over(self):
        budget = TokenBudget(total=10000, step_allocations=StepAllocConfig(), reserved_for_system=0, reserved_for_response=0)
        budget.set_zone_allocation("working", 100)
        budget.record_usage(150, zone="working")
        assert budget.zone_is_over("working") is True

    def test_zone_not_over(self):
        budget = TokenBudget(total=10000, step_allocations=StepAllocConfig(), reserved_for_system=0, reserved_for_response=0)
        budget.set_zone_allocation("working", 100)
        budget.record_usage(50, zone="working")
        assert budget.zone_is_over("working") is False

    def test_estimate_tool_output_read_file(self):
        budget = TokenBudget(total=10000, step_allocations=StepAllocConfig(), reserved_for_system=0, reserved_for_response=0)
        est = budget.estimate_tool_output("read_file", {"start_line": 1, "end_line": 50})
        assert est == max(50, 49 * 3)

    def test_estimate_tool_output_search_code(self):
        budget = TokenBudget(total=10000, step_allocations=StepAllocConfig(), reserved_for_system=0, reserved_for_response=0)
        est = budget.estimate_tool_output("search_code", {})
        assert est == StepAllocConfig().tool_result

    def test_estimate_tool_output_find_symbols(self):
        budget = TokenBudget(total=10000, step_allocations=StepAllocConfig(), reserved_for_system=0, reserved_for_response=0)
        est = budget.estimate_tool_output("find_symbols", {})
        assert est == 200

    def test_estimate_tool_output_run_command(self):
        budget = TokenBudget(total=10000, step_allocations=StepAllocConfig(), reserved_for_system=0, reserved_for_response=0)
        est = budget.estimate_tool_output("run_command", {})
        assert est == 500

    def test_estimate_tool_output_default(self):
        budget = TokenBudget(total=10000, step_allocations=StepAllocConfig(), reserved_for_system=0, reserved_for_response=0)
        est = budget.estimate_tool_output("unknown_tool", {})
        assert est == 800

    def test_summary(self):
        budget = TokenBudget(total=10000, step_allocations=StepAllocConfig(), reserved_for_system=0, reserved_for_response=0)
        summary = budget.summary()
        assert "Budget:" in summary
        assert "step #0" in summary

    def test_summary_after_usage(self):
        budget = TokenBudget(total=10000, step_allocations=StepAllocConfig(), reserved_for_system=0, reserved_for_response=0)
        budget.record_usage(1000)
        budget.start_new_step()
        summary = budget.summary()
        assert "step #1" in summary
