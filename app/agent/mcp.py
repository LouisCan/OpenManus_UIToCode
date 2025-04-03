from typing import Any, Dict, List, Optional, Tuple

from pydantic import Field

from app.agent.toolcall import ToolCallAgent
from app.logger import logger
from app.prompt.mcp import MULTIMEDIA_RESPONSE_PROMPT, NEXT_STEP_PROMPT, SYSTEM_PROMPT
from app.schema import AgentState, Message
from app.tool.base import ToolResult
from app.tool.mcp import MCPClients


class MCPAgent(ToolCallAgent):
    """与MCP（模型上下文协议）服务器交互的代理。

    此代理使用SSE或stdio传输连接到MCP服务器，并通过代理的工具接口使服务器的工具可用。
    """

    name: str = "mcp_agent"  # 代理名称
    description: str = "连接到MCP服务器并使用其工具的代理。"  # 代理描述

    system_prompt: str = SYSTEM_PROMPT  # 系统提示信息
    next_step_prompt: str = NEXT_STEP_PROMPT  # 下一步提示信息

    # 初始化MCP工具集合
    mcp_clients: MCPClients = Field(default_factory=MCPClients)  # MCP客户端实例
    available_tools: MCPClients = None  # 可用工具，将在initialize()中设置

    max_steps: int = 20  # 最大步骤数
    connection_type: str = "stdio"  # 连接类型，"stdio" 或 "sse"

    # 跟踪工具模式以检测更改
    tool_schemas: Dict[str, Dict[str, Any]] = Field(default_factory=dict)  # 工具模式字典
    _refresh_tools_interval: int = 5  # 每N步刷新一次工具

    # 应触发终止的特殊工具名称
    special_tool_names: List[str] = Field(default_factory=lambda: ["terminate"])

    async def initialize(
        self,
        connection_type: Optional[str] = None,
        server_url: Optional[str] = None,
        command: Optional[str] = None,
        args: Optional[List[str]] = None,
    ) -> None:
        """初始化MCP连接。

        参数:
            connection_type: 使用的连接类型 ("stdio" 或 "sse")
            server_url: MCP服务器的URL（用于SSE连接）
            command: 要运行的命令（用于stdio连接）
            args: 命令的参数（用于stdio连接）
        """
        if connection_type:
            self.connection_type = connection_type

        # 根据连接类型连接到MCP服务器
        if self.connection_type == "sse":
            if not server_url:
                raise ValueError("SSE连接需要服务器URL")
            await self.mcp_clients.connect_sse(server_url=server_url)
        elif self.connection_type == "stdio":
            if not command:
                raise ValueError("stdio连接需要命令")
            await self.mcp_clients.connect_stdio(command=command, args=args or [])
        else:
            raise ValueError(f"不支持的连接类型: {self.connection_type}")

        # 将available_tools设置为我们的MCP实例
        self.available_tools = self.mcp_clients

        # 存储初始工具模式
        await self._refresh_tools()

        # 添加关于可用工具的系统消息
        tool_names = list(self.mcp_clients.tool_map.keys())
        tools_info = ", ".join(tool_names)

        # 添加系统提示和可用工具信息
        self.memory.add_message(
            Message.system_message(
                f"{self.system_prompt}\n\n可用MCP工具: {tools_info}"
            )
        )

    async def _refresh_tools(self) -> Tuple[List[str], List[str]]:
        """从MCP服务器刷新可用工具列表。

        返回:
            一个包含(新增工具, 移除工具)的元组
        """
        if not self.mcp_clients.session:
            return [], []

        # 直接从服务器获取当前工具模式
        response = await self.mcp_clients.session.list_tools()
        current_tools = {tool.name: tool.inputSchema for tool in response.tools}

        # 确定新增、移除和更改的工具
        current_names = set(current_tools.keys())
        previous_names = set(self.tool_schemas.keys())

        added_tools = list(current_names - previous_names)
        removed_tools = list(previous_names - current_names)

        # 检查现有工具的模式更改
        changed_tools = []
        for name in current_names.intersection(previous_names):
            if current_tools[name] != self.tool_schemas.get(name):
                changed_tools.append(name)

        # 更新存储的模式
        self.tool_schemas = current_tools

        # 记录并通知更改
        if added_tools:
            logger.info(f"新增MCP工具: {added_tools}")
            self.memory.add_message(
                Message.system_message(f"新工具可用: {', '.join(added_tools)}")
            )
        if removed_tools:
            logger.info(f"移除MCP工具: {removed_tools}")
            self.memory.add_message(
                Message.system_message(
                    f"不再可用的工具: {', '.join(removed_tools)}"
                )
            )
        if changed_tools:
            logger.info(f"更改的MCP工具: {changed_tools}")

        return added_tools, removed_tools

    async def think(self) -> bool:
        """处理当前状态并决定下一步行动。"""
        # 检查MCP会话和工具可用性
        if not self.mcp_clients.session or not self.mcp_clients.tool_map:
            logger.info("MCP服务不再可用，结束交互")
            self.state = AgentState.FINISHED
            return False

        # 定期刷新工具
        if self.current_step % self._refresh_tools_interval == 0:
            await self._refresh_tools()
            # 所有工具被移除表示关闭
            if not self.mcp_clients.tool_map:
                logger.info("MCP服务已关闭，结束交互")
                self.state = AgentState.FINISHED
                return False

        # 使用父类的think方法
        return await super().think()

    async def _handle_special_tool(self, name: str, result: Any, **kwargs) -> None:
        """处理特殊工具执行和状态更改"""
        # 首先用父类处理器处理
        await super()._handle_special_tool(name, result, **kwargs)

        # 处理多媒体响应
        if isinstance(result, ToolResult) and result.base64_image:
            self.memory.add_message(
                Message.system_message(
                    MULTIMEDIA_RESPONSE_PROMPT.format(tool_name=name)
                )
            )

    def _should_finish_execution(self, name: str, **kwargs) -> bool:
        """确定工具执行是否应结束代理"""
        # 如果工具名称为'terminate'则终止
        return name.lower() == "terminate"

    async def cleanup(self) -> None:
        """完成时清理MCP连接。"""
        if self.mcp_clients.session:
            await self.mcp_clients.disconnect()
            logger.info("MCP连接已关闭")

    async def run(self, request: Optional[str] = None) -> str:
        """运行代理并在完成后进行清理。"""
        try:
            result = await super().run(request)
            return result
        finally:
            # 确保即使发生错误也进行清理
            await self.cleanup()
