from pydantic import Field

from app.agent.browser import BrowserAgent  # 导入浏览器代理类
from app.config import config  # 导入配置模块
from app.prompt.browser import NEXT_STEP_PROMPT as BROWSER_NEXT_STEP_PROMPT  # 导入浏览器下一步提示语，并重命名为 BROWSER_NEXT_STEP_PROMPT
from app.prompt.manus import NEXT_STEP_PROMPT, SYSTEM_PROMPT  # 导入手稿的下一步提示语和系统提示语
from app.tool import Terminate, ToolCollection  # 导入终止工具和工具集合
from app.tool.browser_use_tool import BrowserUseTool  # 导入浏览器使用工具
from app.tool.python_execute import PythonExecute  # 导入 Python 执行工具
from app.tool.str_replace_editor import StrReplaceEditor  # 导入字符串替换编辑工具
from app.tool.wireframe_generator import WireframeGenerator  # 导入线框图生成工具
from app.tool.wireframe_to_html import WireframeToHTML  # 导入线框图转HTML工具
from app.tool.html_to_springboot import HTMLToSpringboot  # 导入将HTML原型界面转换为Springboot+MyBatis后端项目的工具
from app.tool.html_to_api_doc import HTMLToAPIDoc  # 导入将HTML原型界面转换为API接口文档的工具
from app.tool.html_to_vue import HTMLToVue  # 导入将HTML原型界面转换为Vue前端项目的工具

class Manus(BrowserAgent):
    """
    Manus 是一个多功能通用代理，使用规划来解决各种任务。

    This agent extends BrowserAgent with a comprehensive set of tools and capabilities,
    including Python execution, web browsing, file operations, and information retrieval
    to handle a wide range of user requests.
    """

    name: str = "Manus"  # 代理名称
    description: str = (
        "A versatile agent that can solve various tasks using multiple tools"
    )

    system_prompt: str = SYSTEM_PROMPT.format(directory=config.workspace_root)  # 格式化系统提示语，使用配置中的工作区根目录
    next_step_prompt: str = NEXT_STEP_PROMPT  # 设置下一步提示语

    max_observe: int = 10000  # 最大观察次数
    max_steps: int = 20  # 最大步骤数

    # 向工具集合添加通用工具
    available_tools: ToolCollection = Field(
        default_factory=lambda: ToolCollection(
            PythonExecute(), BrowserUseTool(), StrReplaceEditor(), WireframeGenerator(), WireframeToHTML(), HTMLToSpringboot(), HTMLToAPIDoc(), HTMLToVue(), Terminate()  # 包含 Python 执行、浏览器使用、字符串替换编辑、线框图生成、线框图转HTML、HTML转Springboot、HTML转API文档、HTML转Vue和终止工具
        )
    )

    async def think(self) -> bool:
        """处理当前状态并根据适当的上下文决定下一步行动。"""
        # 存储原始提示语
        original_prompt = self.next_step_prompt

        # 仅检查最近的消息（最后 3 条）以确定是否有浏览器活动
        recent_messages = self.memory.messages[-3:] if self.memory.messages else []
        browser_in_use = any(
            "browser_use" in msg.content.lower()
            for msg in recent_messages
            if hasattr(msg, "content") and isinstance(msg.content, str)  # 检查消息内容是否包含 "browser_use"
        )

        if browser_in_use:
            # 如果浏览器在使用中，暂时覆盖为浏览器特定的提示语以获取浏览器上下文
            self.next_step_prompt = BROWSER_NEXT_STEP_PROMPT

        # 调用父类的 think 方法
        result = await super().think()

        # 恢复原始提示语
        self.next_step_prompt = original_prompt

        return result  # 返回思考结果
