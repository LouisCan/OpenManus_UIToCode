from abc import ABC, abstractmethod  # 导入抽象基类和抽象方法装饰器
from typing import Any, Dict, Optional  # 导入类型提示相关模块

from pydantic import BaseModel, Field  # 导入Pydantic的模型和字段类


class BaseTool(ABC, BaseModel):
    name: str  # 工具名称
    description: str  # 工具描述
    parameters: Optional[dict] = None  # 工具参数，可选，默认为None

    class Config:
        arbitrary_types_allowed = True  # 允许任意类型

    async def __call__(self, **kwargs) -> Any:
        """使用给定参数执行工具。"""
        return await self.execute(**kwargs)

    @abstractmethod
    async def execute(self, **kwargs) -> Any:
        """使用给定参数执行工具的抽象方法，子类必须实现。"""

    def to_param(self) -> Dict:
        """将工具转换为函数调用格式。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolResult(BaseModel):
    """表示工具执行结果的类。"""

    output: Any = Field(default=None)  # 工具执行的输出结果，默认为None
    error: Optional[str] = Field(default=None)  # 执行错误信息，默认为None
    base64_image: Optional[str] = Field(default=None)  # 可选的Base64编码图像，默认为None
    system: Optional[str] = Field(default=None)  # 系统信息，默认为None

    class Config:
        arbitrary_types_allowed = True  # 允许任意类型

    def __bool__(self):
        """判断工具执行结果是否有有效输出或错误。"""
        return any(getattr(self, field) for field in self.__fields__)

    def __add__(self, other: "ToolResult"):
        """合并两个工具执行结果。"""
        def combine_fields(
            field: Optional[str], other_field: Optional[str], concatenate: bool = True
        ):
            if field and other_field:
                if concatenate:
                    return field + other_field
                raise ValueError("Cannot combine tool results")
            return field or other_field

        return ToolResult(
            output=combine_fields(self.output, other.output),
            error=combine_fields(self.error, other.error),
            base64_image=combine_fields(self.base64_image, other.base64_image, False),
            system=combine_fields(self.system, other.system),
        )

    def __str__(self):
        """返回工具执行结果的字符串表示。"""
        return f"Error: {self.error}" if self.error else self.output

    def replace(self, **kwargs):
        """返回一个新的ToolResult，替换给定的字段。"""
        return type(self)(**{**self.dict(), **kwargs})


class CLIResult(ToolResult):
    """可以渲染为CLI输出的ToolResult子类。"""


class ToolFailure(ToolResult):
    """表示工具执行失败的ToolResult子类。"""
