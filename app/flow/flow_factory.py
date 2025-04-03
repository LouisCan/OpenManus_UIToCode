from typing import Dict, List, Union

from app.agent.base import BaseAgent  # 导入基础代理类
from app.flow.base import BaseFlow, FlowType  # 导入基础流程类和流程类型枚举
from app.flow.planning import PlanningFlow  # 导入规划流程类

class FlowFactory:
    """工厂类，用于创建不同类型的流程，并支持多个代理"""

    @staticmethod
    def create_flow(
        flow_type: FlowType,  # 流程类型
        agents: Union[BaseAgent, List[BaseAgent], Dict[str, BaseAgent]],  # 代理，可以是单个代理、代理列表或代理字典
        **kwargs,  # 其他可选参数
    ) -> BaseFlow:  # 返回一个基础流程实例
        flows = {
            FlowType.PLANNING: PlanningFlow,  # 定义流程类型到流程类的映射
        }

        flow_class = flows.get(flow_type)  # 根据流程类型获取对应的流程类
        if not flow_class:
            raise ValueError(f"未知的流程类型: {flow_type}")  # 如果流程类型不存在，则抛出异常

        return flow_class(agents, **kwargs)  # 创建并返回流程实例
