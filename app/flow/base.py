from abc import ABC, abstractmethod  # 导入抽象基类和抽象方法装饰器
from enum import Enum  # 导入枚举类
from typing import Dict, List, Optional, Union  # 导入类型提示相关模块

from pydantic import BaseModel  # 导入 Pydantic 的基模型，用于数据验证

from app.agent.base import BaseAgent  # 导入自定义的基代理类


class FlowType(str, Enum):
    """流程类型枚举"""
    PLANNING = "planning"  # 规划类型的流程


class BaseFlow(BaseModel, ABC):
    """支持多代理的执行流程基类"""

    agents: Dict[str, BaseAgent]  # 存储代理的字典，键为代理名称，值为代理实例
    tools: Optional[List] = None  # 可选的工具列表
    primary_agent_key: Optional[str] = None  # 主代理的键名，默认为 None

    class Config:
        arbitrary_types_allowed = True  # 允许任意类型，以支持存储代理实例

    def __init__(
        self, agents: Union[BaseAgent, List[BaseAgent], Dict[str, BaseAgent]], **data
    ):
        """
        初始化 BaseFlow 实例，支持多种方式传入代理
        :param agents: 单个代理实例、代理实例列表或代理字典
        :param data: 其他初始化数据
        """
        # 处理不同方式提供的代理
        if isinstance(agents, BaseAgent):
            agents_dict = {"default": agents}  # 单个代理，键名为 "default"
        elif isinstance(agents, list):
            # 列表中的代理，键名为 "agent_0", "agent_1", ...
            agents_dict = {f"agent_{i}": agent for i, agent in enumerate(agents)}
        else:
            agents_dict = agents  # 已经是代理字典

        # 如果未指定主代理键名，使用第一个代理的键名
        primary_key = data.get("primary_agent_key")
        if not primary_key and agents_dict:
            primary_key = next(iter(agents_dict))
            data["primary_agent_key"] = primary_key  # 更新数据字典中的主代理键名

        # 设置代理字典到数据中
        data["agents"] = agents_dict

        # 使用 BaseModel 的初始化方法进行初始化
        super().__init__(**data)

    @property
    def primary_agent(self) -> Optional[BaseAgent]:
        """获取流程的主代理"""
        return self.agents.get(self.primary_agent_key)

    def get_agent(self, key: str) -> Optional[BaseAgent]:
        """根据键名获取特定的代理"""
        return self.agents.get(key)

    def add_agent(self, key: str, agent: BaseAgent) -> None:
        """向流程中添加一个新的代理"""
        self.agents[key] = agent

    @abstractmethod
    async def execute(self, input_text: str) -> str:
        """使用给定的输入文本执行流程，需要在子类中实现"""
        pass


class PlanStepStatus(str, Enum):
    """计划步骤状态的枚举类"""

    NOT_STARTED = "not_started"  # 未开始
    IN_PROGRESS = "in_progress"  # 进行中
    COMPLETED = "completed"  # 已完成
    BLOCKED = "blocked"  # 阻塞

    @classmethod
    def get_all_statuses(cls) -> list[str]:
        """获取所有可能的步骤状态值"""
        return [status.value for status in cls]

    @classmethod
    def get_active_statuses(cls) -> list[str]:
        """获取表示活动状态的值（未开始或进行中）"""
        return [cls.NOT_STARTED.value, cls.IN_PROGRESS.value]

    @classmethod
    def get_status_marks(cls) -> Dict[str, str]:
        """获取状态到其标记符号的映射"""
        return {
            cls.COMPLETED.value: "[✓]",  # 已完成标记
            cls.IN_PROGRESS.value: "[→]",  # 进行中标记
            cls.BLOCKED.value: "[!]",  # 阻塞标记
            cls.NOT_STARTED.value: "[ ]",  # 未开始标记
        }
