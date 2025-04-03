# tool/planning.py
from typing import Dict, List, Literal, Optional

from app.exceptions import ToolError
from app.tool.base import BaseTool, ToolResult
from app.logger import logger  # 导入日志记录器

# 规划工具的描述信息
_PLANNING_TOOL_DESCRIPTION = """
A planning tool that allows the agent to create and manage plans for solving complex tasks.
The tool provides functionality for creating plans, updating plan steps, and tracking progress.
"""


class PlanningTool(BaseTool):
    """
    一个规划工具类，允许代理创建和管理解决复杂任务的计划。
    提供了创建计划、更新计划步骤和跟踪进度的功能。
    """

    name: str = "planning"
    description: str = _PLANNING_TOOL_DESCRIPTION
    parameters: dict = {
        "type": "object",
        "properties": {
            "command": {
                "description": "The command to execute. Available commands: create, update, list, get, set_active, mark_step, delete.",
                "enum": [
                    "create",
                    "update",
                    "list",
                    "get",
                    "set_active",
                    "mark_step",
                    "delete",
                ],
                "type": "string",
            },
            "plan_id": {
                "description": "Unique identifier for the plan. Required for create, update, set_active, and delete commands. Optional for get and mark_step (uses active plan if not specified).",
                "type": "string",
            },
            "title": {
                "description": "Title for the plan. Required for create command, optional for update command.",
                "type": "string",
            },
            "steps": {
                "description": "List of plan steps. Required for create command, optional for update command.",
                "type": "array",
                "items": {"type": "string"},
            },
            "step_index": {
                "description": "Index of the step to update (0-based). Required for mark_step command.",
                "type": "integer",
            },
            "step_status": {
                "description": "Status to set for a step. Used with mark_step command.",
                "enum": ["not_started", "in_progress", "completed", "blocked"],
                "type": "string",
            },
            "step_notes": {
                "description": "Additional notes for a step. Optional for mark_step command.",
                "type": "string",
            },
        },
        "required": ["command"],
        "additionalProperties": False,
    }

    # 存储计划的字典，键为 plan_id
    plans: dict = {}
    # 当前活跃计划的 ID，初始为 None
    _current_plan_id: Optional[str] = None

    async def execute(
        self,
        *,
        command: Literal[
            "create", "update", "list", "get", "set_active", "mark_step", "delete"
        ],
        plan_id: Optional[str] = None,
        title: Optional[str] = None,
        steps: Optional[List[str]] = None,
        step_index: Optional[int] = None,
        step_status: Optional[
            Literal["not_started", "in_progress", "completed", "blocked"]
        ] = None,
        step_notes: Optional[str] = None,
        **kwargs,
    ):
        """
        使用给定的命令和参数执行规划工具。

        Parameters:
        - command: The operation to perform
        - plan_id: Unique identifier for the plan
        - title: Title for the plan (used with create command)
        - steps: List of steps for the plan (used with create command)
        - step_index: Index of the step to update (used with mark_step command)
        - step_status: Status to set for a step (used with mark_step command)
        - step_notes: Additional notes for a step (used with mark_step command)
        """

        if command == "create":
            return self._create_plan(plan_id, title, steps)
        elif command == "update":
            return self._update_plan(plan_id, title, steps)
        elif command == "list":
            return self._list_plans()
        elif command == "get":
            return self._get_plan(plan_id)
        elif command == "set_active":
            return self._set_active_plan(plan_id)
        elif command == "mark_step":
            return self._mark_step(plan_id, step_index, step_status, step_notes)
        elif command == "delete":
            return self._delete_plan(plan_id)
        else:
            raise ToolError(
                f"Unrecognized command: {command}. Allowed commands are: create, update, list, get, set_active, mark_step, delete"
            )

    def _create_plan(
        self, plan_id: Optional[str], title: Optional[str], steps: Optional[List[str]]
    ) -> ToolResult:
        """使用给定的 ID、标题和步骤创建一个新计划。"""
        if not plan_id:
            raise ToolError("Parameter `plan_id` is required for command: create")

        if plan_id in self.plans:
            raise ToolError(
                f"A plan with ID '{plan_id}' already exists. Use 'update' to modify existing plans."
            )

        if not title:
            raise ToolError("Parameter `title` is required for command: create")

        if (
            not steps
            or not isinstance(steps, list)
            or not all(isinstance(step, str) for step in steps)
        ):
            raise ToolError(
                "Parameter `steps` must be a non-empty list of strings for command: create"
            )

        # Create a new plan with initialized step statuses
        plan = {
            "plan_id": plan_id,
            "title": title,
            "steps": steps,
            "step_statuses": ["not_started"] * len(steps),
            "step_notes": [""] * len(steps),
        }

        self.plans[plan_id] = plan
        self._current_plan_id = plan_id  # Set as active plan

        return ToolResult(
            output=f"Plan created successfully with ID: {plan_id}\n\n{self._format_plan(plan)}"
        )

    def _update_plan(
        self, plan_id: Optional[str], title: Optional[str], steps: Optional[List[str]]
    ) -> ToolResult:
        """使用新的标题或步骤更新现有计划。."""
        if not plan_id:
            raise ToolError("Parameter `plan_id` is required for command: update")

        if plan_id not in self.plans:
            raise ToolError(f"No plan found with ID: {plan_id}")

        plan = self.plans[plan_id]

        if title:
            plan["title"] = title

        if steps:
            if not isinstance(steps, list) or not all(
                isinstance(step, str) for step in steps
            ):
                raise ToolError(
                    "Parameter `steps` must be a list of strings for command: update"
                )

            # Preserve existing step statuses for unchanged steps
            old_steps = plan["steps"]
            old_statuses = plan["step_statuses"]
            old_notes = plan["step_notes"]

            # Create new step statuses and notes
            new_statuses = []
            new_notes = []

            for i, step in enumerate(steps):
                # If the step exists at the same position in old steps, preserve status and notes
                if i < len(old_steps) and step == old_steps[i]:
                    new_statuses.append(old_statuses[i])
                    new_notes.append(old_notes[i])
                else:
                    new_statuses.append("not_started")
                    new_notes.append("")

            plan["steps"] = steps
            plan["step_statuses"] = new_statuses
            plan["step_notes"] = new_notes

        return ToolResult(
            output=f"Plan updated successfully: {plan_id}\n\n{self._format_plan(plan)}"
        )

    def _list_plans(self) -> ToolResult:
        """列出所有可用的计划."""
        if not self.plans:
            return ToolResult(
                output="No plans available. Create a plan with the 'create' command."
            )

        output = "Available plans:\n"
        for plan_id, plan in self.plans.items():
            current_marker = " (active)" if plan_id == self._current_plan_id else ""
            completed = sum(
                1 for status in plan["step_statuses"] if status == "completed"
            )
            total = len(plan["steps"])
            progress = f"{completed}/{total} steps completed"
            output += f"• {plan_id}{current_marker}: {plan['title']} - {progress}\n"

        return ToolResult(output=output)

    def _get_plan(self, plan_id: Optional[str]) -> ToolResult:
        """获取特定计划的详细信息."""
        if not plan_id:
            # If no plan_id is provided, use the current active plan
            if not self._current_plan_id:
                raise ToolError(
                    "No active plan. Please specify a plan_id or set an active plan."
                )
            plan_id = self._current_plan_id

        if plan_id not in self.plans:
            raise ToolError(f"No plan found with ID: {plan_id}")

        plan = self.plans[plan_id]
        return ToolResult(output=self._format_plan(plan))

    def _set_active_plan(self, plan_id: Optional[str]) -> ToolResult:
        """将一个计划设置为活跃计划."""
        if not plan_id:
            raise ToolError("Parameter `plan_id` is required for command: set_active")

        if plan_id not in self.plans:
            raise ToolError(f"No plan found with ID: {plan_id}")

        self._current_plan_id = plan_id
        return ToolResult(
            output=f"Plan '{plan_id}' is now the active plan.\n\n{self._format_plan(self.plans[plan_id])}"
        )

    def _mark_step(
        self,
        plan_id: Optional[str],
        step_index: Optional[int],
        step_status: Optional[str],
        step_notes: Optional[str],
    ) -> ToolResult:
        """使用特定的状态和可选的注释标记一个步骤."""
        if not plan_id:
            # If no plan_id is provided, use the current active plan
            if not self._current_plan_id:
                raise ToolError(
                    "No active plan. Please specify a plan_id or set an active plan."
                )
            plan_id = self._current_plan_id

        if plan_id not in self.plans:
            raise ToolError(f"No plan found with ID: {plan_id}")

        if step_index is None:
            raise ToolError("Parameter `step_index` is required for command: mark_step")

        plan = self.plans[plan_id]

        if step_index < 0 or step_index >= len(plan["steps"]):
            raise ToolError(
                f"Invalid step_index: {step_index}. Valid indices range from 0 to {len(plan['steps'])-1}."
            )

        if step_status and step_status not in [
            "not_started",
            "in_progress",
            "completed",
            "blocked",
        ]:
            raise ToolError(
                f"Invalid step_status: {step_status}. Valid statuses are: not_started, in_progress, completed, blocked"
            )

        if step_status:
            plan["step_statuses"][step_index] = step_status

        if step_notes:
            plan["step_notes"][step_index] = step_notes

        return ToolResult(
            output=f"Step {step_index} updated in plan '{plan_id}'.\n\n{self._format_plan(plan)}"
        )

    def _delete_plan(self, plan_id: Optional[str]) -> ToolResult:
        """Delete a plan."""
        if not plan_id:
            raise ToolError("Parameter `plan_id` is required for command: delete")

        if plan_id not in self.plans:
            raise ToolError(f"No plan found with ID: {plan_id}")

        del self.plans[plan_id]

        # If the deleted plan was the active plan, clear the active plan
        if self._current_plan_id == plan_id:
            self._current_plan_id = None

        return ToolResult(output=f"Plan '{plan_id}' has been deleted.")

    def _format_plan(self, plan: Dict) -> str:
        """格式化计划以供显示."""
        output = f"Plan: {plan['title']} (ID: {plan['plan_id']})\n"
        output += "=" * len(output) + "\n\n"

        # Calculate progress statistics
        total_steps = len(plan["steps"])
        completed = sum(1 for status in plan["step_statuses"] if status == "completed")
        in_progress = sum(
            1 for status in plan["step_statuses"] if status == "in_progress"
        )
        blocked = sum(1 for status in plan["step_statuses"] if status == "blocked")
        not_started = sum(
            1 for status in plan["step_statuses"] if status == "not_started"
        )

        output += f"Progress: {completed}/{total_steps} steps completed "
        if total_steps > 0:
            percentage = (completed / total_steps) * 100
            output += f"({percentage:.1f}%)\n"
        else:
            output += "(0%)\n"

        output += f"Status: {completed} completed, {in_progress} in progress, {blocked} blocked, {not_started} not started\n\n"
        output += "Steps:\n"

        # Add each step with its status and notes
        for i, (step, status, notes) in enumerate(
            zip(plan["steps"], plan["step_statuses"], plan["step_notes"])
        ):
            status_symbol = {
                "not_started": "[ ]",
                "in_progress": "[→]",
                "completed": "[✓]",
                "blocked": "[!]",
            }.get(status, "[ ]")

            output += f"{i}. {status_symbol} {step}\n"
            if notes:
                output += f"   Notes: {notes}\n"

        return output
