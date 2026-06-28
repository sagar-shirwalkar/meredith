from __future__ import annotations

import pytest

from coding_agent.agent.planner import Planner
from coding_agent.config import AppConfig
from coding_agent.types import Plan, SubTask, TaskStatus


@pytest.fixture
def config() -> AppConfig:
    return AppConfig()


class BaseParserTests:
    """Tests shared by both planners (they inherit the same parse methods)."""

    def test_parse_json_plan(self, config: AppConfig):
        planner = Planner(llm=None, config=config)  # type: ignore[arg-type]
        text = """```json
{
  "goal": "Fix auth bug",
  "subtasks": [
    {"id": 1, "description": "Read auth.py", "files": ["auth.py"]},
    {"id": 2, "description": "Fix login function"}
  ],
  "dependencies": {"2": [1]}
}
```"""
        plan = planner._parse_plan_response(text)
        assert isinstance(plan, Plan)
        assert plan.goal == "Fix auth bug"
        assert len(plan.subtasks) == 2
        assert plan.subtasks[0].description == "Read auth.py"
        assert plan.subtasks[0].files == ["auth.py"]
        assert plan.subtasks[0].status == TaskStatus.IN_PROGRESS
        assert plan.current_subtask_idx == 0

    def test_parse_json_with_best_plan(self, config: AppConfig):
        planner = Planner(llm=None, config=config)  # type: ignore[arg-type]
        text = """```json
{
  "best_plan": {
    "goal": "Fix auth",
    "subtasks": [
      {"id": 1, "description": "Read the code"}
    ]
  }
}
```"""
        plan = planner._parse_plan_response(text)
        assert plan.goal == "Fix auth"
        assert len(plan.subtasks) == 1

    def test_parse_json_without_fences(self, config: AppConfig):
        planner = Planner(llm=None, config=config)  # type: ignore[arg-type]
        text = '{"goal": "Test", "subtasks": [{"id": 1, "description": "Run tests"}]}'
        plan = planner._parse_plan_response(text)
        assert plan.goal == "Test"
        assert len(plan.subtasks) == 1

    def test_parse_fallback_lines_numbered(self, config: AppConfig):
        planner = Planner(llm=None, config=config)  # type: ignore[arg-type]
        text = "1. First step\n2. Second step\n3. Third step"
        plan = planner._parse_plan_response(text)
        assert len(plan.subtasks) == 3

    def test_parse_fallback_lines_bullet(self, config: AppConfig):
        planner = Planner(llm=None, config=config)  # type: ignore[arg-type]
        text = "- Do this\n- Do that\n- Do other"
        plan = planner._parse_plan_response(text)
        assert len(plan.subtasks) == 3
        assert plan.subtasks[0].description == "Do this"

    def test_parse_fallback_unparseable(self, config: AppConfig):
        planner = Planner(llm=None, config=config)  # type: ignore[arg-type]
        text = "Just a plain description with no numbered steps"
        plan = planner._parse_plan_response(text)
        assert len(plan.subtasks) == 1
        assert plan.subtasks[0].description == "Just a plain description with no numbered steps"

    def test_format_subtasks(self, config: AppConfig):
        result = Planner._format_subtasks([
            SubTask(id=1, description="Read files", files=["test.py"]),
            SubTask(id=2, description="Write code"),
        ])
        assert "1. [pending] Read files (files: test.py)" in result
        assert "2. [pending] Write code" in result

    def test_empty_subtasks_list(self, config: AppConfig):
        plan = Planner(llm=None, config=config)._parse_plan_response(  # type: ignore[arg-type]
            '{"goal": "Empty", "subtasks": []}',
        )
        assert plan.current_subtask_idx == -1


class TestPlanner:
    def test_plan(self, config: AppConfig):
        planner = Planner(llm=None, config=config)  # type: ignore[arg-type]
        plan = planner._parse_plan_response("1. Read auth.py\n2. Fix login\n3. Test")
        assert isinstance(plan, Plan)


class TestTreeOfThoughtPlanner:
    def test_plan(self, config: AppConfig):
        planner = Planner(llm=None, config=config, strategy="tree_of_thought")  # type: ignore[arg-type]
        plan = planner._parse_plan_response("1. Research\n2. Implement\n3. Verify")
        assert isinstance(plan, Plan)
