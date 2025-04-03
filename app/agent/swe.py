from typing import List

from pydantic import Field

from app.agent.toolcall import ToolCallAgent
from app.prompt.swe import NEXT_STEP_TEMPLATE, SYSTEM_PROMPT
from app.tool import Bash, StrReplaceEditor, Terminate, ToolCollection


class SWEAgent(ToolCallAgent):
    """一个实现了SWEAgent范式的代理，用于执行代码和自然对话。"""

    name: str = "swe"  # 代理的名称
    description: str = "一个自主的AI程序员，直接与计算机交互以解决问题。"  # 代理的描述

    system_prompt: str = SYSTEM_PROMPT  # 系统提示信息
    next_step_prompt: str = NEXT_STEP_TEMPLATE  # 下一步提示模板

    available_tools: ToolCollection = ToolCollection(
        Bash(), StrReplaceEditor(), Terminate()  # 可用的工具集合，包括Bash命令执行、字符串替换编辑器和终止工具
    )
    special_tool_names: List[str] = Field(default_factory=lambda: [Terminate().name])  # 特殊工具名称列表，默认包含终止工具的名称

    max_steps: int = 30  # 最大执行步骤数

    bash: Bash = Field(default_factory=Bash)  # Bash工具实例
    working_dir: str = "."  # 当前工作目录，默认为当前目录

    async def think(self) -> bool:
        """处理当前状态并决定下一步行动"""
        # 更新工作目录
        result = await self.bash.execute("pwd")  # 执行pwd命令获取当前工作目录
        self.working_dir = result.output  # 更新当前工作目录
        self.next_step_prompt = self.next_step_prompt.format(
            current_dir=self.working_dir  # 更新下一步提示模板中的当前目录
        )

        return await super().think()  # 调用父类的think方法，继续处理下一步行动
