from typing import Dict, List, Optional, Union
from pydantic import Field

from app.agent.toolcall import ToolCallAgent
from app.config import config
from app.logger import logger
from app.schema import Message
from app.tool import Terminate, ToolCollection
from app.tool.wireframe_generator import WireframeGenerator
from app.tool.wireframe_to_html import WireframeToHTML
from app.tool.html_to_api_doc import HTMLToAPIDoc
from app.tool.html_to_vue import HTMLToVue
from app.tool.html_to_springboot import HTMLToSpringboot
from app.prompt.pipeline import NEXT_STEP_PROMPT, SYSTEM_PROMPT


class PipelineAgent(ToolCallAgent):
    """
    Pipeline代理类，用于自动化执行从UI设计到代码生成的全流程。

    该代理能够串联多个工具，按顺序执行工作流程，自动将一个工具的输出作为下一个工具的输入。
    """

    name: str = "pipeline_agent"
    description: str = "自动化执行从UI设计到代码生成的端到端流程"

    system_prompt: str = SYSTEM_PROMPT.format(directory=config.workspace_root)
    next_step_prompt: str = NEXT_STEP_PROMPT

    # 可用工具集合
    available_tools: ToolCollection = Field(
        default_factory=lambda: ToolCollection(
            WireframeGenerator(),
            WireframeToHTML(),
            HTMLToAPIDoc(),
            HTMLToVue(),
            HTMLToSpringboot(),
            Terminate()
        )
    )

    # 特殊工具名称列表
    special_tool_names: List[str] = Field(default_factory=lambda: [Terminate().name])

    # 工作流程状态跟踪
    pipeline_status: Dict[str, Union[str, Dict]] = Field(default_factory=dict)
    output_files: Dict[str, str] = Field(default_factory=dict)

    # 最大步骤数限制
    max_steps: int = 30

    async def initialize(self, input_image_path: Optional[str] = None, project_name: Optional[str] = None, description_text: Optional[str] = None, package_name: Optional[str] = "com.demo"):
        """
        初始化Pipeline代理

        参数:
            input_image_path: 输入的UI图像路径
            project_name: 项目名称
            description_text: 项目需求描述文本
            package_name: 后端项目的基础包名
        """
        # 初始化工作流状态
        self.pipeline_status = {
            "wireframe_generation": "pending",
            "html_creation": "pending",
            "api_doc_generation": "pending",
            "frontend_generation": "pending",
            "backend_generation": "pending",
            "status": "initialized"
        }

        # 存储输出文件路径
        self.output_files = {
            "image_path": input_image_path,
            "wireframe_desc": "",
            "html_path": "",
            "api_doc_path": "",
            "frontend_path": "",
            "backend_path": "",
            "project_name": project_name or "auto_generated_project",
            "description_text": description_text or "",
            "package_name": package_name or "com.demo"
        }

        # 添加初始系统消息
        self.memory.add_message(
            Message.system_message(content=self.system_prompt)
        )

        # 添加用户输入消息
        init_message = f"请使用图像路径 '{input_image_path}' 执行完整的从UI设计到代码生成的流程，项目名称为 '{self.output_files['project_name']}'。"

        if description_text:
            init_message += f"\n\n项目描述：\n{description_text}"

        if package_name and package_name != "com.demo":
            init_message += f"\n\n后端项目使用包名：{package_name}"

        self.memory.add_message(
            Message.user_message(content=init_message)
        )

    async def think(self) -> bool:
        """处理当前状态并决定下一步行动"""
        # 更新提示信息中的工作流状态
        status_text = "\n".join([f"{step}: {status}" for step, status in self.pipeline_status.items() if step != "status"])
        self.next_step_prompt = NEXT_STEP_PROMPT.format(
            pipeline_status=status_text
        )

        # 调用父类的think方法继续处理
        return await super().think()

    async def update_pipeline_status(self, step: str, status: str, output: Optional[str] = None):
        """
        更新工作流状态

        参数:
            step: 工作流步骤名称
            status: 状态值 (pending, in_progress, completed, failed)
            output: 可选的输出信息
        """
        if step in self.pipeline_status:
            self.pipeline_status[step] = status

            if output and step in ["wireframe_generation", "html_creation", "api_doc_generation",
                                 "frontend_generation", "backend_generation"]:
                # 根据步骤存储相应的输出路径
                if step == "wireframe_generation":
                    self.output_files["wireframe_desc"] = output
                elif step == "html_creation":
                    # 从输出中提取HTML文件路径
                    if "保存到:" in output:
                        html_path = output.split("保存到:")[-1].strip()
                        self.output_files["html_path"] = html_path
                elif step == "api_doc_generation":
                    # 从输出中提取API文档路径
                    if "保存到:" in output:
                        api_doc_path = output.split("保存到:")[-1].strip()
                        self.output_files["api_doc_path"] = api_doc_path
                elif step == "frontend_generation":
                    # 从输出中提取前端项目路径
                    if "保存到:" in output:
                        frontend_path = output.split("保存到:")[-1].strip().split("\n")[0]
                        self.output_files["frontend_path"] = frontend_path
                elif step == "backend_generation":
                    # 从输出中提取后端项目路径
                    if "保存到:" in output:
                        backend_path = output.split("保存到:")[-1].strip().split("\n")[0]
                        self.output_files["backend_path"] = backend_path

        # 更新整体状态
        all_completed = all(status == "completed" for key, status in self.pipeline_status.items()
                           if key != "status")
        if all_completed:
            self.pipeline_status["status"] = "completed"
        elif any(status == "failed" for key, status in self.pipeline_status.items()
                if key != "status"):
            self.pipeline_status["status"] = "failed"
        else:
            self.pipeline_status["status"] = "in_progress"

        logger.info(f"Pipeline状态更新: {step} -> {status}")

    async def execute_tool(self, command):
        """执行工具并更新工作流状态"""
        tool_name = command.function.name

        # 增强工具调用参数
        if tool_name == "html_to_api_doc" and "description_text" not in command.function.arguments:
            # 如果有项目描述但未传递，添加description_text参数
            if self.output_files.get("description_text"):
                command.function.arguments["description_text"] = self.output_files["description_text"]
                logger.info(f"自动为html_to_api_doc添加description_text参数")

        elif tool_name == "html_to_springboot" and "package_name" not in command.function.arguments:
            # 如果有自定义包名但未传递，添加package_name参数
            if self.output_files.get("package_name"):
                command.function.arguments["package_name"] = self.output_files["package_name"]
                logger.info(f"自动为html_to_springboot添加package_name参数: {self.output_files['package_name']}")

        # 根据工具名称更新对应步骤状态为进行中
        if tool_name == "wireframe_generator":
            await self.update_pipeline_status("wireframe_generation", "in_progress")
        elif tool_name == "wireframe_html":
            await self.update_pipeline_status("html_creation", "in_progress")
        elif tool_name == "html_to_api_doc":
            await self.update_pipeline_status("api_doc_generation", "in_progress")
        elif tool_name == "html_to_vue":
            await self.update_pipeline_status("frontend_generation", "in_progress")
        elif tool_name == "html_to_springboot":
            await self.update_pipeline_status("backend_generation", "in_progress")

        # 执行工具
        result = await super().execute_tool(command)

        # 根据工具名称更新对应步骤状态
        success = "Error:" not in result and "错误:" not in result and "失败:" not in result
        status = "completed" if success else "failed"

        if tool_name == "wireframe_generator":
            await self.update_pipeline_status("wireframe_generation", status, result)
        elif tool_name == "wireframe_html":
            await self.update_pipeline_status("html_creation", status, result)
        elif tool_name == "html_to_api_doc":
            await self.update_pipeline_status("api_doc_generation", status, result)
        elif tool_name == "html_to_vue":
            await self.update_pipeline_status("frontend_generation", status, result)
        elif tool_name == "html_to_springboot":
            await self.update_pipeline_status("backend_generation", status, result)

        return result

    async def run(self, input_image_path: Optional[str] = None, project_name: Optional[str] = None, description_text: Optional[str] = None, package_name: Optional[str] = "com.demo") -> str:
        """
        运行Pipeline代理

        参数:
            input_image_path: 输入的UI图像路径
            project_name: 项目名称
            description_text: 项目需求描述文本
            package_name: 后端项目的基础包名

        返回:
            执行结果摘要
        """
        # 初始化代理
        await self.initialize(input_image_path, project_name, description_text, package_name)

        # 运行代理
        result = await super().run()

        # 返回执行结果摘要
        summary = f"""
Pipeline执行完成! 状态: {self.pipeline_status['status']}

生成的资源:
- 线框图描述: {self.output_files.get('wireframe_desc', '未生成')}
- HTML原型: {self.output_files.get('html_path', '未生成')}
- API文档: {self.output_files.get('api_doc_path', '未生成')}
- 前端项目: {self.output_files.get('frontend_path', '未生成')}
- 后端项目: {self.output_files.get('backend_path', '未生成')}

项目配置:
- 项目名称: {self.output_files.get('project_name')}
- 后端包名: {self.output_files.get('package_name')}
- 使用项目描述: {'是' if self.output_files.get('description_text') else '否'}
        """

        return summary
