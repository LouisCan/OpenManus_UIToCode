import json
from typing import Any, Optional

from pydantic import Field

from app.agent.toolcall import ToolCallAgent
from app.logger import logger
from app.prompt.browser import NEXT_STEP_PROMPT, SYSTEM_PROMPT
from app.schema import Message, ToolChoice
from app.tool import BrowserUseTool, Terminate, ToolCollection


class BrowserAgent(ToolCallAgent):
    """
    浏览器代理类，使用 browser_use 库来控制浏览器。

    此代理可以导航网页、与元素交互、填写表单、提取内容以及执行其他基于浏览器的操作来完成任务。
    """

    name: str = "browser"  # 代理名称
    description: str = "能够控制浏览器以完成任务的浏览器代理"

    system_prompt: str = SYSTEM_PROMPT  # 系统提示语
    next_step_prompt: str = NEXT_STEP_PROMPT  # 下一步提示语

    max_observe: int = 10000  # 最大观察次数
    max_steps: int = 20  # 最大步骤数

    # 配置可用工具
    available_tools: ToolCollection = Field(
        default_factory=lambda: ToolCollection(BrowserUseTool(), Terminate())
    )

    # 使用 Auto 作为工具选择，允许工具使用和自由形式响应
    tool_choices: ToolChoice = ToolChoice.AUTO
    special_tool_names: list[str] = Field(default_factory=lambda: [Terminate().name])

    _current_base64_image: Optional[str] = None  # 当前的 base64 编码图片

    async def _handle_special_tool(self, name: str, result: Any, **kwargs):
        """
        处理特殊工具的调用。
        如果不是特殊工具，则不做处理；否则，清理浏览器工具并调用父类的处理方法。
        """
        if not self._is_special_tool(name):
            return
        else:
            await self.available_tools.get_tool(BrowserUseTool().name).cleanup()
            await super()._handle_special_tool(name, result, **kwargs)

    async def get_browser_state(self) -> Optional[dict]:
        """
        获取当前浏览器的状态，用于下一步的上下文。
        从工具中直接获取浏览器状态，如果成功则存储截图并解析状态信息。
        如果发生错误或获取失败，则返回 None。
        """
        browser_tool = self.available_tools.get_tool(BrowserUseTool().name)
        if not browser_tool:
            return None

        try:
            # Get browser state directly from the tool
            result = await browser_tool.get_current_state()

            if result.error:
                logger.debug(f"浏览器状态错误: {result.error}")
                return None

            # Store screenshot if available
            if hasattr(result, "base64_image") and result.base64_image:
                self._current_base64_image = result.base64_image

            # Parse the state info
            return json.loads(result.output)

        except Exception as e:
            logger.debug(f"获取浏览器状态失败: {str(e)}")
            return None

    async def think(self) -> bool:
        """
        处理当前状态并决定下一步动作，使用工具并添加浏览器状态信息。
        获取浏览器状态，并根据状态更新提示语中的占位符。
        调用父类的 think 方法，并在之后重置提示语。
        """
        browser_state = await self.get_browser_state()

        # 初始化占位符的值
        url_info = ""
        tabs_info = ""
        content_above_info = ""
        content_below_info = ""
        results_info = ""

        if browser_state and not browser_state.get("error"):
            # URL 和标题信息
            url_info = f"\n   URL: {browser_state.get('url', 'N/A')}\n   Title: {browser_state.get('title', 'N/A')}"

            # 标签信息
            if "tabs" in browser_state:
                tabs = browser_state.get("tabs", [])
                if tabs:
                    tabs_info = f"\n   {len(tabs)} 个标签可用"

            # 视口上下内容的信息
            pixels_above = browser_state.get("pixels_above", 0)
            pixels_below = browser_state.get("pixels_below", 0)

            if pixels_above > 0:
                content_above_info = f" ({pixels_above} pixels)"

            if pixels_below > 0:
                content_below_info = f" ({pixels_below} pixels)"

            # 如果有截图，则添加到消息中
            if self._current_base64_image:
                # Create a message with image attachment
                image_message = Message.user_message(
                    content="当前浏览器截图:",
                    base64_image=self._current_base64_image,
                )
                self.memory.add_message(image_message)

        # 使用实际的浏览器状态信息替换提示语中的占位符
        self.next_step_prompt = NEXT_STEP_PROMPT.format(
            url_placeholder=url_info,
            tabs_placeholder=tabs_info,
            content_above_placeholder=content_above_info,
            content_below_placeholder=content_below_info,
            results_placeholder=results_info,
        )

        # 调用父类的 think 方法
        result = await super().think()

        # 重置下一步提示语到原始状态
        self.next_step_prompt = NEXT_STEP_PROMPT

        return result
