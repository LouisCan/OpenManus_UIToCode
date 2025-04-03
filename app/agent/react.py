from abc import ABC, abstractmethod  # 导入抽象基类和抽象方法装饰器
from typing import Optional  # 导入Optional类型提示

from pydantic import Field  # 导入pydantic的Field用于字段验证和默认值设置

from app.agent.base import BaseAgent  # 导入基础代理类
from app.llm import LLM  # 导入大型语言模型类
from app.schema import AgentState, Memory  # 导入代理状态和记忆类

class ReActAgent(BaseAgent, ABC):  # 定义ReActAgent类，继承自BaseAgent和ABC
    name: str  # 代理名称
    description: Optional[str] = None  # 代理描述，可选

    system_prompt: Optional[str] = None  # 系统提示，可选
    next_step_prompt: Optional[str] = None  # 下一步提示，可选

    llm: Optional[LLM] = Field(default_factory=LLM)  # 大型语言模型实例，使用Field设置默认工厂
    memory: Memory = Field(default_factory=Memory)  # 记忆实例，使用Field设置默认工厂
    state: AgentState = AgentState.IDLE  # 代理状态，初始为IDLE

    max_steps: int = 10  # 最大步骤数
    current_step: int = 0  # 当前步骤数

    @abstractmethod  # 定义抽象方法think，子类必须实现
    async def think(self) -> bool:
        """处理当前状态并决定下一步行动"""
        pass

    @abstractmethod  # 定义抽象方法act，子类必须实现
    async def act(self) -> str:
        """执行决定的行动"""
        pass

    async def step(self) -> str:  # 定义step方法，执行单步操作：思考和行动
        """执行单步：思考和行动"""
        should_act = await self.think()  # 调用think方法决定是否行动
        if not should_act:  # 如果不需要行动
            return "Thinking complete - no action needed"  # 返回思考完成信息
        return await self.act()  # 否则执行行动并返回结果
