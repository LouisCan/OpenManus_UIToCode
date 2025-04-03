import argparse  # 命令行参数解析库
import asyncio  # 异步编程库
import atexit  # 注册退出时执行的函数
import json  # JSON 处理库
import logging  # 日志记录库
import os  # 操作系统相关功能库
import sys  # 系统相关功能库
from inspect import Parameter, Signature  # 用于获取函数签名信息
from typing import Any, Dict, Optional  # 类型提示

from mcp.server.fastmcp import FastMCP  # 导入 FastMCP 类

# 将相关目录添加到 Python 路径，以便正确导入模块
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
root_dir = os.path.dirname(parent_dir)
sys.path.insert(0, parent_dir)
sys.path.insert(0, current_dir)
sys.path.insert(0, root_dir)

# 配置日志记录（使用与原始代码相同的格式）
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("mcp-server")

from app.tool.base import BaseTool  # 导入基础工具类
from app.tool.bash import Bash  # 导入 Bash 工具类
from app.tool.browser_use_tool import BrowserUseTool  # 导入浏览器使用工具类
from app.tool.str_replace_editor import StrReplaceEditor  # 导入字符串替换编辑器工具类
from app.tool.terminate import Terminate  # 导入终止工具类


class MCPServer:
    """MCP 服务器实现，包含工具注册和管理。"""

    def __init__(self, name: str = "openmanus"):
        self.server = FastMCP(name)  # 创建 FastMCP 服务器实例
        self.tools: Dict[str, BaseTool] = {}  # 初始化工具字典

        # 初始化标准工具
        self.tools["bash"] = Bash()
        self.tools["browser"] = BrowserUseTool()
        self.tools["editor"] = StrReplaceEditor()
        self.tools["terminate"] = Terminate()

        from app.logger import logger as app_logger  # 导入应用日志记录器

        global logger
        logger = app_logger  # 使用应用日志记录器

    def register_tool(self, tool: BaseTool, method_name: Optional[str] = None) -> None:
        """注册工具，并进行参数验证和文档生成。"""
        tool_name = method_name or tool.name  # 确定工具名称
        tool_param = tool.to_param()  # 获取工具参数
        tool_function = tool_param["function"]  # 获取工具函数信息

        # 定义要注册的异步函数
        async def tool_method(**kwargs):
            logger.info(f"执行 {tool_name}: {kwargs}")  # 记录执行信息
            result = await tool.execute(**kwargs)  # 执行工具

            logger.info(f"{tool_name} 的结果: {result}")  # 记录结果

            # 处理不同类型的结果（匹配原始逻辑）
            if hasattr(result, "model_dump"):
                return json.dumps(result.model_dump())
            elif isinstance(result, dict):
                return json.dumps(result)
            return result

        # 设置方法的元数据
        tool_method.__name__ = tool_name
        tool_method.__doc__ = self._build_docstring(tool_function)  # 构建文档字符串
        tool_method.__signature__ = self._build_signature(tool_function)  # 构建函数签名

        # 存储参数模式（对于程序化访问参数很重要）
        param_props = tool_function.get("parameters", {}).get("properties", {})
        required_params = tool_function.get("parameters", {}).get("required", [])
        tool_method._parameter_schema = {
            param_name: {
                "description": param_details.get("description", ""),
                "type": param_details.get("type", "any"),
                "required": param_name in required_params,
            }
            for param_name, param_details in param_props.items()
        }

        # 将工具方法注册到服务器
        self.server.tool()(tool_method)
        logger.info(f"注册工具: {tool_name}")  # 记录注册信息

    def _build_docstring(self, tool_function: dict) -> str:
        """从工具函数元数据构建格式化的文档字符串。"""
        description = tool_function.get("description", "")  # 获取描述
        param_props = tool_function.get("parameters", {}).get("properties", {})
        required_params = tool_function.get("parameters", {}).get("required", [])

        # 构建文档字符串（匹配原始格式）
        docstring = description
        if param_props:
            docstring += "\n\nParameters:\n"
            for param_name, param_details in param_props.items():
                required_str = (
                    "(required)" if param_name in required_params else "(optional)"
                )
                param_type = param_details.get("type", "any")
                param_desc = param_details.get("description", "")
                docstring += (
                    f"    {param_name} ({param_type}) {required_str}: {param_desc}\n"
                )

        return docstring

    def _build_signature(self, tool_function: dict) -> Signature:
        """从工具函数元数据构建函数签名。"""
        param_props = tool_function.get("parameters", {}).get("properties", {})
        required_params = tool_function.get("parameters", {}).get("required", [])

        parameters = []

        # 遵循原始类型映射
        for param_name, param_details in param_props.items():
            param_type = param_details.get("type", "")
            default = Parameter.empty if param_name in required_params else None

            # 将 JSON Schema 类型映射到 Python 类型（与原始代码相同）
            annotation = Any
            if param_type == "string":
                annotation = str
            elif param_type == "integer":
                annotation = int
            elif param_type == "number":
                annotation = float
            elif param_type == "boolean":
                annotation = bool
            elif param_type == "object":
                annotation = dict
            elif param_type == "array":
                annotation = list

            # 创建具有与原始代码相同结构的参数
            param = Parameter(
                name=param_name,
                kind=Parameter.KEYWORD_ONLY,
                default=default,
                annotation=annotation,
            )
            parameters.append(param)

        return Signature(parameters=parameters)

    async def cleanup(self) -> None:
        """清理服务器资源。"""
        logger.info("清理资源")  # 记录清理信息
        # 遵循原始清理逻辑 - 仅清理浏览器工具
        if "browser" in self.tools and hasattr(self.tools["browser"], "cleanup"):
            await self.tools["browser"].cleanup()

    def register_all_tools(self) -> None:
        """将所有工具注册到服务器。"""
        for tool in self.tools.values():
            self.register_tool(tool)

    def run(self, transport: str = "stdio") -> None:
        """运行 MCP 服务器。"""
        # 注册所有工具
        self.register_all_tools()

        # 注册清理函数（匹配原始行为）
        atexit.register(lambda: asyncio.run(self.cleanup()))

        # 启动服务器（使用与原始代码相同的日志记录）
        logger.info(f"启动 OpenManus 服务器 ({transport} 模式)")
        self.server.run(transport=transport)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="OpenManus MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio"],
        default="stdio",
        help="Communication method: stdio or http (default: stdio)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()  # 解析命令行参数

    # 创建并运行服务器（保持原始流程）
    server = MCPServer()
    server.run(transport=args.transport)
