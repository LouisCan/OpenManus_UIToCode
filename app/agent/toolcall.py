import json
from typing import Any, List, Optional, Union

from pydantic import Field

from app.agent.react import ReActAgent  # 导入基础反应代理类
from app.exceptions import TokenLimitExceeded  # 导入令牌限制异常类
from app.logger import logger  # 导入日志记录器
from app.prompt.toolcall import NEXT_STEP_PROMPT, SYSTEM_PROMPT  # 导入提示语
from app.schema import (
    TOOL_CHOICE_TYPE,  # 工具选择类型
    AgentState,  # 代理状态
    Message,  # 消息类
    ToolCall,  # 工具调用类
    ToolChoice,  # 工具选择类
)
from app.tool import CreateChatCompletion, Terminate, ToolCollection  # 导入工具类


TOOL_CALL_REQUIRED = "Tool calls required but none provided"  # 工具调用必需但未提供的错误信息


class ToolCallAgent(ReActAgent):
    """处理工具/函数调用的基础代理类，具有增强的抽象"""

    name: str = "toolcall"  # 代理名称
    description: str = "an agent that can execute tool calls."  # 代理描述

    system_prompt: str = SYSTEM_PROMPT  # 系统提示语
    next_step_prompt: str = NEXT_STEP_PROMPT  # 下一步提示语

    available_tools: ToolCollection = ToolCollection(
        CreateChatCompletion(), Terminate()
    )  # 可用工具集合
    tool_choices: TOOL_CHOICE_TYPE = ToolChoice.AUTO  # 工具选择模式，默认自动
    special_tool_names: List[str] = Field(default_factory=lambda: [Terminate().name])  # 特殊工具名称列表

    tool_calls: List[ToolCall] = Field(default_factory=list)  # 工具调用列表
    _current_base64_image: Optional[str] = None  # 当前 base64 图像，用于特殊工具

    max_steps: int = 30  # 最大步骤数
    max_observe: Optional[Union[int, bool]] = None  # 最大观察次数或是否观察

    async def think(self) -> bool:
        """处理当前状态并使用工具决定下一步行动"""
        if self.next_step_prompt:
            user_msg = Message.user_message(self.next_step_prompt)  # 创建用户消息
            self.messages += [user_msg]  # 添加到消息列表

        try:
            # 使用工具获取响应
            response = await self.llm.ask_tool(
                messages=self.messages,
                system_msgs=(
                    [Message.system_message(self.system_prompt)]
                    if self.system_prompt
                    else None
                ),
                tools=self.available_tools.to_params(),
                tool_choice=self.tool_choices,
            )
        except ValueError:
            raise
        except Exception as e:
            # 检查是否是包含 TokenLimitExceeded 的 RetryError
            if hasattr(e, "__cause__") and isinstance(e.__cause__, TokenLimitExceeded):
                token_limit_error = e.__cause__
                logger.error(
                    f"🚨 Token limit error (from RetryError): {token_limit_error}"
                )
                self.memory.add_message(
                    Message.assistant_message(
                        f"Maximum token limit reached, cannot continue execution: {str(token_limit_error)}"
                    )
                )
                self.state = AgentState.FINISHED  # 设置代理状态为完成
                return False
            raise

        self.tool_calls = tool_calls = (
            response.tool_calls if response and response.tool_calls else []
        )
        content = response.content if response and response.content else ""

        # 记录响应信息
        logger.info(f"✨ {self.name}'s thoughts: {content}")
        logger.info(
            f"🛠️ {self.name} selected {len(tool_calls) if tool_calls else 0} tools to use"
        )
        if tool_calls:
            logger.info(
                f"🧰 Tools being prepared: {[call.function.name for call in tool_calls]}"
            )
            logger.info(f"🔧 Tool arguments: {tool_calls[0].function.arguments}")

        try:
            if response is None:
                raise RuntimeError("No response received from the LLM")

            # 根据工具选择模式处理
            if self.tool_choices == ToolChoice.NONE:
                if tool_calls:
                    logger.warning(
                        f"🤔 Hmm, {self.name} tried to use tools when they weren't available!"
                    )
                if content:
                    self.memory.add_message(Message.assistant_message(content))
                    return True
                return False

            # 创建并添加助手消息
            assistant_msg = (
                Message.from_tool_calls(content=content, tool_calls=self.tool_calls)
                if self.tool_calls
                else Message.assistant_message(content)
            )
            self.memory.add_message(assistant_msg)

            if self.tool_choices == ToolChoice.REQUIRED and not self.tool_calls:
                return True  # 将在 act() 中处理

            # 对于 'auto' 模式，如果没有命令但存在内容，则继续
            if self.tool_choices == ToolChoice.AUTO and not self.tool_calls:
                return bool(content)

            return bool(self.tool_calls)
        except Exception as e:
            logger.error(f"🚨 Oops! The {self.name}'s thinking process hit a snag: {e}")
            self.memory.add_message(
                Message.assistant_message(
                    f"Error encountered while processing: {str(e)}"
                )
            )
            return False

    async def act(self) -> str:
        """执行工具调用并处理结果"""
        if not self.tool_calls:
            if self.tool_choices == ToolChoice.REQUIRED:
                raise ValueError(TOOL_CALL_REQUIRED)

            # 如果没有工具调用，返回最后一条消息内容
            return self.messages[-1].content or "No content or commands to execute"

        results = []
        for command in self.tool_calls:
            # 为每个工具调用重置 base64_image
            self._current_base64_image = None

            result = await self.execute_tool(command)  # 执行工具

            if self.max_observe:
                result = result[: self.max_observe]  # 限制观察结果长度

            logger.info(
                f"🎯 Tool '{command.function.name}' completed its mission! Result: {result}"
            )

            # 将工具响应添加到内存
            tool_msg = Message.tool_message(
                content=result,
                tool_call_id=command.id,
                name=command.function.name,
                base64_image=self._current_base64_image,
            )
            self.memory.add_message(tool_msg)
            results.append(result)

        return "\n\n".join(results)

    async def execute_tool(self, command: ToolCall) -> str:
        """执行单个工具调用并处理错误"""
        if not command or not command.function or not command.function.name:
            return "Error: Invalid command format"

        name = command.function.name
        if name not in self.available_tools.tool_map:
            return f"Error: Unknown tool '{name}'"

        try:
            # 解析参数
            args = json.loads(command.function.arguments or "{}")

            # 执行工具
            logger.info(f"🔧 Activating tool: '{name}'...")
            result = await self.available_tools.execute(name=name, tool_input=args)

            # 处理特殊工具
            await self._handle_special_tool(name=name, result=result)

            # 处理包含 base64_image 的结果
            if hasattr(result, "base64_image") and result.base64_image:
                # Store the base64_image for later use in tool_message
                self._current_base64_image = result.base64_image

                # Format result for display
                observation = (
                    f"Observed output of cmd `{name}` executed:\n{str(result)}"
                    if result
                    else f"Cmd `{name}` completed with no output"
                )
                return observation

            # 格式化标准结果
            observation = (
                f"Observed output of cmd `{name}` executed:\n{str(result)}"
                if result
                else f"Cmd `{name}` completed with no output"
            )

            return observation
        except json.JSONDecodeError:
            error_msg = f"Error parsing arguments for {name}: Invalid JSON format"
            logger.error(
                f"📝 Oops! The arguments for '{name}' don't make sense - invalid JSON, arguments:{command.function.arguments}"
            )
            return f"Error: {error_msg}"
        except Exception as e:
            error_msg = f"⚠️ Tool '{name}' encountered a problem: {str(e)}"
            logger.exception(error_msg)
            return f"Error: {error_msg}"

    async def _handle_special_tool(self, name: str, result: Any, **kwargs):
        """处理特殊工具执行和状态更改"""
        if not self._is_special_tool(name):
            return

        if self._should_finish_execution(name=name, result=result, **kwargs):
            # Set agent state to finished
            logger.info(f"🏁 Special tool '{name}' has completed the task!")
            self.state = AgentState.FINISHED  # 设置代理状态为完成

    @staticmethod
    def _should_finish_execution(**kwargs) -> bool:
        """确定工具执行是否应结束代理"""
        return True

    def _is_special_tool(self, name: str) -> bool:
        """检查工具名称是否在特殊工具列表中"""
        return name.lower() in [n.lower() for n in self.special_tool_names]
