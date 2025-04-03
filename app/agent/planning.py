import time
from typing import Dict, List, Optional

from pydantic import Field, model_validator

from app.agent.toolcall import ToolCallAgent
from app.logger import logger
from app.prompt.planning import NEXT_STEP_PROMPT, PLANNING_SYSTEM_PROMPT
from app.schema import TOOL_CHOICE_TYPE, Message, ToolCall, ToolChoice
from app.tool import PlanningTool, Terminate, ToolCollection


class PlanningAgent(ToolCallAgent):
    """
    规划代理类，用于创建和管理任务解决方案的计划。

    此代理使用规划工具来创建和管理结构化的计划，并通过各个步骤跟踪进度直至任务完成。
    """

    name: str = "planning"  # 代理名称
    description: str = "创建和管理任务解决方案计划的代理"

    system_prompt: str = PLANNING_SYSTEM_PROMPT  # 系统提示语
    next_step_prompt: str = NEXT_STEP_PROMPT  # 下一步提示语

    available_tools: ToolCollection = Field(
        default_factory=lambda: ToolCollection(PlanningTool(), Terminate())
    )  # 可用工具集合，默认包含规划工具和终止工具
    tool_choices: TOOL_CHOICE_TYPE = ToolChoice.AUTO  # 工具选择类型
    special_tool_names: List[str] = Field(default_factory=lambda: [Terminate().name])  # 特殊工具名称列表

    tool_calls: List[ToolCall] = Field(default_factory=list)  # 工具调用列表
    active_plan_id: Optional[str] = Field(default=None)  # 当前活跃计划的 ID

    # 用于跟踪每个工具调用的步骤状态的字典
    step_execution_tracker: Dict[str, Dict] = Field(default_factory=dict)
    current_step_index: Optional[int] = None  # 当前步骤索引

    max_steps: int = 20  # 最大步骤数

    @model_validator(mode="after")
    def initialize_plan_and_verify_tools(self) -> "PlanningAgent":
        """初始化代理，设置默认计划 ID 并验证所需工具。"""
        self.active_plan_id = f"plan_{int(time.time())}"  # 设置默认计划 ID

        if "planning" not in self.available_tools.tool_map:
            self.available_tools.add_tool(PlanningTool())  # 如果规划工具不存在则添加

        return self

    async def think(self) -> bool:
        """基于计划状态决定下一个动作。"""
        # 根据是否有活跃计划生成提示语
        prompt = (
            f"CURRENT PLAN STATUS:\n{await self.get_plan()}\n\n{self.next_step_prompt}"
            if self.active_plan_id
            else self.next_step_prompt
        )
        self.messages.append(Message.user_message(prompt))  # 添加用户消息

        # 在思考前获取当前步骤索引
        self.current_step_index = await self._get_current_step_index()

        result = await super().think()  # 调用父类的思考方法

        # 思考后，如果决定执行工具且不是规划工具或特殊工具，将其与当前步骤关联以便跟踪
        if result and self.tool_calls:
            latest_tool_call = self.tool_calls[0]  # 获取最新的工具调用
            if (
                latest_tool_call.function.name!= "planning"
                and latest_tool_call.function.name not in self.special_tool_names
                and self.current_step_index is not None
            ):
                self.step_execution_tracker[latest_tool_call.id] = {
                    "step_index": self.current_step_index,
                    "tool_name": latest_tool_call.function.name,
                    "status": "pending",  # 执行后更新状态
                }

        return result

    async def act(self) -> str:
        """执行一个步骤并跟踪其完成状态。"""
        result = await super().act()  # 调用父类的执行方法

        # 执行工具后更新计划状态
        if self.tool_calls:
            latest_tool_call = self.tool_calls[0]

            # 更新执行状态为已完成
            if latest_tool_call.id in self.step_execution_tracker:
                self.step_execution_tracker[latest_tool_call.id]["status"] = "completed"
                self.step_execution_tracker[latest_tool_call.id]["result"] = result

                # 如果是非规划、非特殊工具，更新计划状态
                if (
                    latest_tool_call.function.name!= "planning"
                    and latest_tool_call.function.name not in self.special_tool_names
                ):
                    await self.update_plan_status(latest_tool_call.id)

        return result

    async def get_plan(self) -> str:
        """获取当前计划状态。"""
        if not self.active_plan_id:
            return "No active plan. Please create a plan first."  # 没有活跃计划时的提示

        result = await self.available_tools.execute(
            name="planning",
            tool_input={"command": "get", "plan_id": self.active_plan_id},
        )
        return result.output if hasattr(result, "output") else str(result)

    async def run(self, request: Optional[str] = None) -> str:
        """使用可选的初始请求运行代理。"""
        if request:
            await self.create_initial_plan(request)  # 根据请求创建初始计划
        return await super().run()

    async def update_plan_status(self, tool_call_id: str) -> None:
        """
        根据完成的工具执行更新当前计划进度。
        仅当关联的工具成功执行时将步骤标记为已完成。
        """
        if not self.active_plan_id:
            return

        if tool_call_id not in self.step_execution_tracker:
            logger.warning(f"No step tracking found for tool call {tool_call_id}")  # 没有步骤跟踪时的警告
            return

        tracker = self.step_execution_tracker[tool_call_id]
        if tracker["status"]!= "completed":
            logger.warning(f"Tool call {tool_call_id} has not completed successfully")  # 工具调用未完成时的警告
            return

        step_index = tracker["step_index"]

        try:
            # 将步骤标记为已完成
            await self.available_tools.execute(
                name="planning",
                tool_input={
                    "command": "mark_step",
                    "plan_id": self.active_plan_id,
                    "step_index": step_index,
                    "step_status": "completed",
                },
            )
            logger.info(
                f"Marked step {step_index} as completed in plan {self.active_plan_id}"  # 标记步骤完成的信息
            )
        except Exception as e:
            logger.warning(f"Failed to update plan status: {e}")  # 更新计划状态失败时的警告

    async def _get_current_step_index(self) -> Optional[int]:
        """
        解析当前计划以确定第一个未完成步骤的索引。
        如果没有找到活跃步骤，则返回 None。
        """
        if not self.active_plan_id:
            return None

        plan = await self.get_plan()

        try:
            plan_lines = plan.splitlines()
            steps_index = -1

            # 查找“Steps:”行的索引
            for i, line in enumerate(plan_lines):
                if line.strip() == "Steps:":
                    steps_index = i
                    break

            if steps_index == -1:
                return None

            # 查找第一个未完成的步骤
            for i, line in enumerate(plan_lines[steps_index + 1:], start=0):
                if "[ ]" in line or "[→]" in line:  # 未开始或在进行中
                    # 将当前步骤标记为进行中
                    await self.available_tools.execute(
                        name="planning",
                        tool_input={
                            "command": "mark_step",
                            "plan_id": self.active_plan_id,
                            "step_index": i,
                            "step_status": "in_progress",
                        },
                    )
                    return i

            return None  # 没有找到活跃步骤
        except Exception as e:
            logger.warning(f"Error finding current step index: {e}")  # 查找当前步骤索引出错时的警告
            return None

    async def create_initial_plan(self, request: str) -> None:
        """基于请求创建初始计划。"""
        logger.info(f"Creating initial plan with ID: {self.active_plan_id}")  # 创建初始计划的信息

        messages = [
            Message.user_message(
                f"Analyze the request and create a plan with ID {self.active_plan_id}: {request}"
            )
        ]
        self.memory.add_messages(messages)
        response = await self.llm.ask_tool(
            messages=messages,
            system_msgs=[Message.system_message(self.system_prompt)],
            tools=self.available_tools.to_params(),
            tool_choice=ToolChoice.AUTO,
        )
        assistant_msg = Message.from_tool_calls(
            content=response.content, tool_calls=response.tool_calls
        )

        self.memory.add_message(assistant_msg)

        plan_created = False
        for tool_call in response.tool_calls:
            if tool_call.function.name == "planning":
                result = await self.execute_tool(tool_call)
                logger.info(
                    f"Executed tool {tool_call.function.name} with result: {result}"  # 执行规划工具的信息
                )

                # 将工具响应添加到内存
                tool_msg = Message.tool_message(
                    content=result,
                    tool_call_id=tool_call.id,
                    name=tool_call.function.name,
                )
                self.memory.add_message(tool_msg)
                plan_created = True
                break

        if not plan_created:
            logger.warning("No plan created from initial request")  # 没有从初始请求创建计划时的警告
            tool_msg = Message.assistant_message(
                "Error: Parameter `plan_id` is required for command: create"  # 错误提示信息
            )
            self.memory.add_message(tool_msg)


async def main():
    # 配置并运行代理
    agent = PlanningAgent(available_tools=ToolCollection(PlanningTool(), Terminate()))
    result = await agent.run("Help me plan a trip to the moon")  # 运行代理并传入初始请求
    print(result)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())  # 运行主函数
