import json
import time
from typing import Dict, List, Optional, Union

from pydantic import Field

from app.agent.base import BaseAgent
from app.flow.base import BaseFlow, PlanStepStatus
from app.llm import LLM
from app.logger import logger
from app.schema import AgentState, Message, ToolChoice
from app.tool import PlanningTool


class PlanningFlow(BaseFlow):
    """规划流程类，用于使用代理管理任务的规划和执行。"""

    llm: LLM = Field(default_factory=lambda: LLM())  # 默认创建一个 LLM 实例
    planning_tool: PlanningTool = Field(default_factory=PlanningTool)  # 默认创建一个规划工具实例
    executor_keys: List[str] = Field(default_factory=list)  # 执行器键的列表
    active_plan_id: str = Field(default_factory=lambda: f"plan_{int(time.time())}")  # 当前活动计划的 ID
    current_step_index: Optional[int] = None  # 当前步骤的索引

    def __init__(
        self, agents: Union[BaseAgent, List[BaseAgent], Dict[str, BaseAgent]], **data
    ):
        # 在调用父类初始化之前设置执行器键
        if "executors" in data:
            data["executor_keys"] = data.pop("executors")

        # 如果提供了计划 ID，则设置它
        if "plan_id" in data:
            data["active_plan_id"] = data.pop("plan_id")

        # 如果没有提供规划工具，则初始化一个
        if "planning_tool" not in data:
            planning_tool = PlanningTool()
            data["planning_tool"] = planning_tool

        # 使用处理后的数据调用父类的初始化方法
        super().__init__(agents, **data)

        # 如果没有指定执行器键，则将所有代理的键设置为执行器键
        if not self.executor_keys:
            self.executor_keys = list(self.agents.keys())

    def get_executor(self, step_type: Optional[str] = None) -> BaseAgent:
        """
        获取当前步骤的合适执行代理。
        可以扩展为基于步骤类型/要求选择代理。
        """
        # 如果提供了步骤类型并且与代理键匹配，则使用该代理
        if step_type and step_type in self.agents:
            return self.agents[step_type]

        # 否则使用第一个可用的执行器或回退到主代理
        for key in self.executor_keys:
            if key in self.agents:
                return self.agents[key]

        # 回退到主代理
        return self.primary_agent

    async def execute(self, input_text: str) -> str:
        """使用代理执行规划流程。"""
        try:
            if not self.primary_agent:
                raise ValueError("没有可用的主代理")

            # 如果提供了输入，则创建初始计划
            if input_text:
                await self._create_initial_plan(input_text)

                # 验证计划是否成功创建
                if self.active_plan_id not in self.planning_tool.plans:
                    logger.error(
                        f"计划创建失败。计划 ID {self.active_plan_id} 在规划工具中未找到。"
                    )
                    return f"为: {input_text} 创建计划失败"

            result = ""
            while True:
                # 获取要执行的当前步骤
                self.current_step_index, step_info = await self._get_current_step_info()

                # 如果没有更多步骤或计划完成，则退出
                if self.current_step_index is None:
                    result += await self._finalize_plan()
                    break

                # 使用合适的代理执行当前步骤
                step_type = step_info.get("type") if step_info else None
                executor = self.get_executor(step_type)
                step_result = await self._execute_step(executor, step_info)
                result += step_result + "
"

                # 检查代理是否想要终止
                if hasattr(executor, "state") and executor.state == AgentState.FINISHED:
                    break

            return result
        except Exception as e:
            logger.error(f"Error in PlanningFlow: {str(e)}")
            return f"Execution failed: {str(e)}"

       async def _create_initial_plan(self, request: str) -> None:
           """根据请求使用流程的LLM和PlanningTool创建初始计划。"""
           logger.info(f"Creating initial plan with ID: {self.active_plan_id}")  # 记录创建计划的日志信息

           # 创建用于计划创建的系统消息
           system_message = Message.system_message(
               "You are a planning assistant. Create a concise, actionable plan with clear steps. "
               "Focus on key milestones rather than detailed sub-steps. "
               "Optimize for clarity and efficiency."
           )

           # 创建包含请求的用户消息
           user_message = Message.user_message(
               f"Create a reasonable plan with clear steps to accomplish the task: {request}"
           )

           # 使用PlanningTool调用LLM
           response = await self.llm.ask_tool(
               messages=[user_message],
               system_msgs=[system_message],
               tools=[self.planning_tool.to_param()],
               tool_choice=ToolChoice.AUTO,
           )

           # 如果存在工具调用，则进行处理
           if response.tool_calls:
               for tool_call in response.tool_calls:
                   if tool_call.function.name == "planning":
                       # 解析参数
                       args = tool_call.function.arguments
                       if isinstance(args, str):
                           try:
                               args = json.loads(args)
                           except json.JSONDecodeError:
                               logger.error(f"Failed to parse tool arguments: {args}")
                               continue

                       # 确保plan_id设置正确并执行工具
                       args["plan_id"] = self.active_plan_id

                       # 通过ToolCollection而不是直接执行工具
                       result = await self.planning_tool.execute(**args)

                       logger.info(f"Plan creation result: {str(result)}")
                       return

           # 如果执行到这里，创建默认计划
           logger.warning("Creating default plan")

           # 使用ToolCollection创建默认计划
           await self.planning_tool.execute(
               **{
                   "command": "create",
                   "plan_id": self.active_plan_id,
                   "title": f"Plan for: {request[:50]}{'...' if len(request) > 50 else ''}",
                   "steps": ["Analyze request", "Execute task", "Verify results"],
               }
           )

       async def _get_current_step_info(self) -> tuple[Optional[int], Optional[dict]]:
           """
           解析当前计划以确定第一个未完成步骤的索引和信息。
           如果没有找到活动步骤，则返回(None, None)。
           """
           if (
               not self.active_plan_id
               or self.active_plan_id not in self.planning_tool.plans
           ):
               logger.error(f"Plan with ID {self.active_plan_id} not found")
               return None, None

           try:
               # 直接从规划工具存储中访问计划数据
               plan_data = self.planning_tool.plans[self.active_plan_id]
               steps = plan_data.get("steps", [])
               step_statuses = plan_data.get("step_statuses", [])

               # 查找第一个未完成的步骤
               for i, step in enumerate(steps):
                   if i >= len(step_statuses):
                       status = PlanStepStatus.NOT_STARTED.value
                   else:
                       status = step_statuses[i]

                   if status in PlanStepStatus.get_active_statuses():
                       # 如果可用，提取步骤类型/类别
                       step_info = {"text": step}

                       # 尝试从文本中提取步骤类型（例如[SEARCH]或[CODE]）
                       import re

                       type_match = re.search(r"\[([A-Z_]+)\]", step)
                       if type_match:
                           step_info["type"] = type_match.group(1).lower()

                       # 将当前步骤标记为进行中
                       try:
                           await self.planning_tool.execute(
                               command="mark_step",
                               plan_id=self.active_plan_id,
                               step_index=i,
                               step_status=PlanStepStatus.IN_PROGRESS.value,
                           )
                       except Exception as e:
                           logger.warning(f"Error marking step as in_progress: {e}")
                           # 如果需要，直接更新步骤状态
                           if i < len(step_statuses):
                               step_statuses[i] = PlanStepStatus.IN_PROGRESS.value
                           else:
                               while len(step_statuses) < i:
                                   step_statuses.append(PlanStepStatus.NOT_STARTED.value)
                               step_statuses.append(PlanStepStatus.IN_PROGRESS.value)

                           plan_data["step_statuses"] = step_statuses

                       return i, step_info

               return None, None  # 没有找到活动步骤

           except Exception as e:
               logger.warning(f"Error finding current step index: {e}")
               return None, None

       async def _execute_step(self, executor: BaseAgent, step_info: dict) -> str:
           """使用指定的代理执行当前步骤。"""
           # 为代理准备带有当前计划状态的上下文
           plan_status = await self._get_plan_text()
           step_text = step_info.get("text", f"Step {self.current_step_index}")

           # 创建一个提示，供代理执行当前步骤
           step_prompt = f"""
           CURRENT PLAN STATUS:
           {plan_status}

           YOUR CURRENT TASK:
           You are now working on step {self.current_step_index}: "{step_text}"

           Please execute this step using the appropriate tools. When you're done, provide a summary of what you accomplished.
           """

           # 使用agent.run()执行步骤
           try:
               step_result = await executor.run(step_prompt)

               # 成功执行后，将步骤标记为已完成
               await self._mark_step_completed()

               return step_result
           except Exception as e:
               logger.error(f"Error executing step {self.current_step_index}: {e}")
               return f"Error executing step {self.current_step_index}: {str(e)}"

       async def _mark_step_completed(self) -> None:
           """将当前步骤标记为已完成。"""
           if self.current_step_index is None:
               return

           try:
               # 将步骤标记为已完成
               await self.planning_tool.execute(
                   command="mark_step",
                   plan_id=self.active_plan_id,
                   step_index=self.current_step_index,
                   step_status=PlanStepStatus.COMPLETED.value,
               )
               logger.info(
                   f"Marked step {self.current_step_index} as completed in plan {self.active_plan_id}"
               )
           except Exception as e:
               logger.warning(f"Failed to update plan status: {e}")
               # 如果需要，直接在规划工具存储中更新步骤状态
               if self.active_plan_id in self.planning_tool.plans:
                   plan_data = self.planning_tool.plans[self.active_plan_id]
                   step_statuses = plan_data.get("step_statuses", [])

                   # 确保step_statuses列表足够长
                   while len(step_statuses) <= self.current_step_index:
                       step_statuses.append(PlanStepStatus.NOT_STARTED.value)

                   # 更新状态
                   step_statuses[self.current_step_index] = PlanStepStatus.COMPLETED.value
                   plan_data["step_statuses"] = step_statuses

       async def _get_plan_text(self) -> str:
           """获取当前计划的格式化文本。"""
           try:
               result = await self.planning_tool.execute(
                   command="get", plan_id=self.active_plan_id
               )
               return result.output if hasattr(result, "output") else str(result)
           except Exception as e:
               logger.error(f"Error getting plan: {e}")
               return self._generate_plan_text_from_storage()

       def _generate_plan_text_from_storage(self) -> str:
           """如果规划工具失败，则直接从存储中生成计划文本。"""
           try:
               if self.active_plan_id not in self.planning_tool.plans:
                   return f"Error: Plan with ID {self.active_plan_id} not found"

               plan_data = self.planning_tool.plans[self.active_plan_id]
               title = plan_data.get("title", "Untitled Plan")
               steps = plan_data.get("steps", [])
               step_statuses = plan_data.get("step_statuses", [])
               step_notes = plan_data.get("step_notes", [])

               # 确保step_statuses和step_notes与步骤数量匹配
               while len(step_statuses) < len(steps):
                   step_statuses.append(PlanStepStatus.NOT_STARTED.value)
               while len(step_notes) < len(steps):
                   step_notes.append("")

               # 按状态计算步骤数量
               status_counts = {status: 0 for status in PlanStepStatus.get_all_statuses()}

               for status in step_statuses:
                   if status in status_counts:
                       status_counts[status] += 1

               completed = status_counts[PlanStepStatus.COMPLETED.value]
               total = len(steps)
               progress = (completed / total) * 100 if total > 0 else 0

               plan_text = f"Plan: {title} (ID: {self.active_plan_id})\n"
               plan_text += "=" * len(plan_text) + "\n\n"

               plan_text += (
                   f"Progress: {completed}/{total} steps completed ({progress:.1f}%)\n"
               )
               plan_text += f"Status: {status_counts[PlanStepStatus.COMPLETED.value]} completed, {status_counts[PlanStepStatus.IN_PROGRESS.value]} in progress, "
               plan_text += f"{status_counts[PlanStepStatus.BLOCKED.value]} blocked, {status_counts[PlanStepStatus.NOT_STARTED.value]} not started\n\n"
               plan_text += "Steps:\n"

               status_marks = PlanStepStatus.get_status_marks()

               for i, (step, status, notes) in enumerate(
                   zip(steps, step_statuses, step_notes)
               ):
                   # 使用状态标记来表示步骤状态
                   status_mark = status_marks.get(
                       status, status_marks[PlanStepStatus.NOT_STARTED.value]
                   )

                   plan_text += f"{i}. {status_mark} {step}\n"
                   if notes:
                       plan_text += f"   Notes: {notes}\n"

               return plan_text
           except Exception as e:
               logger.error(f"Error generating plan text from storage: {e}")
               return f"Error: Unable to retrieve plan with ID {self.active_plan_id}"

       async def _finalize_plan(self) -> str:
           """最终确定计划并提供使用流程的LLM直接生成的摘要。"""
           plan_text = await self._get_plan_text()

           # 使用流程的LLM直接创建摘要
           try:
               system_message = Message.system_message(
                   "You are a planning assistant. Your task is to summarize the completed plan."
               )

               user_message = Message.user_message(
                   f"The plan has been completed. Here is the final plan status:\n\n{plan_text}\n\nPlease provide a summary of what was accomplished and any final thoughts."
               )

               response = await self.llm.ask(
                   messages=[user_message], system_msgs=[system_message]
               )

               return f"Plan completed:\n\n{response}"
           except Exception as e:
               logger.error(f"Error finalizing plan with LLM: {e}")

               # 如果LLM失败，使用代理生成摘要
               try:
                   agent = self.primary_agent
                   summary_prompt = f"""
                   The plan has been completed. Here is the final plan status:

                   {plan_text}

                   Please provide a summary of what was accomplished and any final thoughts.
                   """
                   summary = await agent.run(summary_prompt)
                   return f"Plan completed:\n\n{summary}"
               except Exception as e2:
                   logger.error(f"Error finalizing plan with agent: {e2}")
                   return "Plan completed. Error generating summary."
