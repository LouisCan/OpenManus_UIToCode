import os
import re
import json
import time
from typing import Dict, List, Optional, Tuple, Any

from app.tool.base import BaseTool, ToolResult  # 从基础工具类导入
from app.logger import logger  # 导入日志记录器
from app.config import config  # 导入配置模块
from app.llm import LLM  # 导入LLM模块


class HTMLToAPIDoc(BaseTool):
    """一个根据HTML原型界面和文字描述生成前端使用的API接口文档的工具。"""

    name: str = "html_to_api_doc"
    description: str = "Generates a comprehensive API documentation based on HTML prototype interfaces. The documentation includes request URLs, parameters, response formats, etc., in Markdown format."
    parameters: dict = {
        "type": "object",
        "properties": {
            "html_path": {
                "type": "string",
                "description": "Path to the HTML prototype file. Can be absolute or relative to workspace.",
            },
            "project_name": {
                "type": "string",
                "description": "Name of the API project.",
            },
            "description_text": {
                "type": "string",
                "description": "Additional text description about the project requirements and API needs.",
                "default": "",
            },
            "output_path": {
                "type": "string",
                "description": "Path where to save the generated API documentation. Default is 'api_docs' folder in workspace.",
                "default": "api_docs",
            },
            "output_filename": {
                "type": "string",
                "description": "Filename for the generated API documentation (without extension). Default is '[project_name]_api_doc'.",
                "default": "",
            },
        },
        "required": ["html_path", "project_name"],
    }

    # 步骤1：分析提示词 - 分析HTML原型和文字描述，确定功能和所需接口数量
    _analyze_features_prompt = """请分析下面的HTML原型界面和文字描述，提取所有功能点并确定需要实现的API接口数量。

项目名称: {project_name}

{description_section}

请分析以下HTML原型界面，提取所有功能点:
```html
{html_content}
```

请详细分析并列出：
1. 所有需要实现的功能点
2. 每个功能点需要的API接口数量
3. 每个接口的基本目的和用途

请以JSON格式返回分析结果：
```json
{{
  "features": [
    {{
      "name": "功能名称",
      "description": "功能描述",
      "apis": [
        {{
          "purpose": "接口用途描述",
          "suggested_path": "/api/建议路径"
        }}
      ]
    }}
  ],
  "total_apis": 接口总数量,
  "authentication_required": true/false,
  "data_entities": ["实体1", "实体2"]
}}
```

请确保分析全面、不遗漏任何功能点，每个显示在界面上的功能都应该有对应的API支持。
"""

    # 步骤2：API规划提示词 - 基于第一步结果，详细规划所有接口路径和方法
    _plan_apis_prompt = """基于之前的功能分析结果，请详细规划所有API接口的路径、方法和基本参数。

项目名称: {project_name}

第一步分析的功能和接口概况:
```json
{analysis_result}
```

HTML原型界面:
```html
{html_content}
```

{description_section}

请为每个功能点详细设计API接口，包括：
1. 完整的接口URL路径
2. HTTP方法（GET、POST、PUT、DELETE等）
3. 接口的主要功能描述
4. 基本请求参数和响应数据结构

请以JSON格式返回API规划结果：
```json
{{
  "api_base_path": "/api",
  "authentication": {{
    "type": "认证类型（如JWT、OAuth等）",
    "endpoints": [
      {{
        "path": "/auth/login",
        "method": "POST",
        "description": "用户登录接口"
      }}
    ]
  }},
  "apis": [
    {{
      "path": "/api/完整路径",
      "method": "HTTP方法",
      "feature": "所属功能",
      "description": "接口描述",
      "request_params": ["参数1", "参数2"],
      "response_entities": ["返回实体1", "返回实体2"]
    }}
  ]
}}
```

请确保API设计符合RESTful规范，路径命名清晰、一致，并且覆盖所有功能点。
"""

    # 步骤3：详细API文档生成提示词 - 基于前两步结果，生成完整API文档
    _generate_api_doc_prompt = """请基于前面的功能分析和API规划，生成完整详细的API接口文档。

项目名称: {project_name}

功能分析结果:
```json
{analysis_result}
```

API规划结果:
```json
{api_plan}
```

{description_section}

请生成一个全面、专业的API文档，包括：
1. 项目介绍和API概述
2. 认证与授权机制详细说明
3. 通用请求/响应格式规范
4. 错误码及处理机制
5. 每个API的详细说明，包括：
   - 完整URL
   - HTTP方法
   - 详细功能描述
   - 请求参数（包括路径参数、查询参数、请求体）的名称、类型、是否必填、描述等
   - 响应数据格式、状态码、示例响应
   - 可能的错误情况
6. 数据模型/实体定义

文档必须包含所有已规划的API接口（总计{total_apis}个），每个接口需有完整的请求参数和响应数据说明。

请以Markdown格式输出完整的API文档。文档必须包含以下所有部分，不要省略任何章节：
1. 标题和简介
2. 目录
3. 接口规范（包括请求/响应格式，状态码等）
4. 认证与授权机制
5. 完整的接口列表（按功能模块分组）
6. 每个接口的详细说明（包括URL、方法、参数、响应等）
7. 错误码说明
8. 数据模型/实体定义（如适用）
"""

    def __init__(self):
        super().__init__()
        self._progress = 0
        self._total_steps = 3  # 总步骤数：1.分析功能 2.规划API 3.生成文档

    def _update_progress(self, step: int, message: str) -> None:
        """更新进度并输出信息"""
        self._progress = (step / self._total_steps) * 100
        logger.info(f"进度: {self._progress:.1f}% - {message}")

    def _read_html_file(self, html_path: str) -> str:
        """读取HTML文件内容"""
        # 确定完整路径
        if os.path.isabs(html_path):
            full_path = html_path
        else:
            full_path = os.path.join(config.workspace_root, html_path)

        # 检查文件是否存在
        if not os.path.exists(full_path):
            raise FileNotFoundError(f"HTML文件未找到: {full_path}")

        # 读取文件内容
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()

    def _create_output_dir(self, output_path: str) -> str:
        """创建输出目录"""
        # 确定完整输出路径
        if os.path.isabs(output_path):
            full_output_path = output_path
        else:
            full_output_path = os.path.join(config.workspace_root, output_path)

        # 创建目录
        os.makedirs(full_output_path, exist_ok=True)

        return full_output_path

    def _save_markdown_file(self, content: str, output_path: str, filename: str) -> str:
        """保存Markdown文件"""
        # 确保目录存在
        output_dir = self._create_output_dir(output_path)

        # 确定文件路径
        file_path = os.path.join(output_dir, f"{filename}.md")

        # 写入文件
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        return file_path

    def _save_json_file(self, content: Dict, output_path: str, filename: str) -> str:
        """保存JSON中间结果文件"""
        # 确保目录存在
        output_dir = self._create_output_dir(output_path)

        # 确定文件路径
        file_path = os.path.join(output_dir, f"{filename}.json")

        # 写入文件
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False, indent=2)

        return file_path

    async def _execute_llm_step(self, prompt: str, step_name: str, max_retries: int = 3) -> str:
        """执行LLM调用步骤，带重试机制，提取JSON或Markdown内容"""
        logger.info(f"执行步骤: {step_name}，最大重试次数: {max_retries}")

        for retry in range(max_retries):
            try:
                # 创建LLM实例
                llm = LLM("doubao")

                logger.info(f"正在执行{step_name} (尝试 {retry+1}/{max_retries})...")
                start_time = time.time()

                # 使用LLM生成内容
                messages = [{"role": "user", "content": prompt}]
                response = await llm.ask(messages, stream=False)

                # 计算耗时
                duration = time.time() - start_time
                logger.info(f"{step_name}完成，耗时: {duration:.2f}秒，生成内容长度: {len(response)}字符")

                # 根据步骤名判断应该返回的内容类型
                if step_name == "功能接口分析(步骤1)" or step_name == "API接口规划(步骤2)" or "json" in step_name.lower():
                    # 尝试提取JSON内容
                    try:
                        json_content = self._extract_json_content(response)
                        logger.info(f"成功提取JSON内容，键: {list(json_content.keys())}")
                        return json_content
                    except Exception as e:
                        logger.error(f"JSON提取失败: {str(e)}，尝试重新生成")
                        raise ValueError(f"无法从响应中提取有效的JSON数据: {str(e)}")
                else:
                    # 尝试提取Markdown内容
                    markdown_content = self._extract_markdown_content(response)
                    logger.info(f"成功提取Markdown内容，长度: {len(markdown_content)}字符")
                    return markdown_content

            except Exception as e:
                logger.error(f"{step_name}失败 (尝试 {retry+1}/{max_retries}): {str(e)}")

                if retry == max_retries - 1:
                    raise RuntimeError(f"{step_name}失败，已重试{max_retries}次: {str(e)}")

                # 等待后重试
                import asyncio
                await asyncio.sleep(1)

        raise RuntimeError(f"{step_name}失败，超过最大重试次数")

    def _extract_json_content(self, response: str) -> Dict:
        """从响应中提取JSON内容"""
        # 提取JSON内容
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', response)
        if json_match:
            json_content = json_match.group(1).strip()
        else:
            # 尝试直接从响应中解析JSON
            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            if json_start != -1 and json_end != -1:
                json_content = response[json_start:json_end]
            else:
                raise ValueError("无法从响应中提取JSON内容")

        # 尝试解析JSON
        try:
            return json.loads(json_content)
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {str(e)}")

            # 尝试修复常见的JSON问题
            fixed_content = self._fix_json_content(json_content)
            try:
                return json.loads(fixed_content)
            except json.JSONDecodeError:
                raise ValueError(f"无法解析JSON内容，即使尝试修复后仍失败")

    def _fix_json_content(self, json_content: str) -> str:
        """尝试修复常见的JSON格式问题"""
        # 修复未加引号的键名
        fixed = re.sub(r'([{,]\s*)(\w+)(\s*:)', r'\1"\2"\3', json_content)
        # 修复末尾多余的逗号
        fixed = re.sub(r',\s*}', '}', fixed)
        fixed = re.sub(r',\s*]', ']', fixed)
        # 修复错误的单引号
        fixed = fixed.replace("'", '"')
        return fixed

    def _extract_markdown_content(self, response: str) -> str:
        """从响应中提取Markdown内容"""
        # 尝试提取Markdown代码块
        markdown_match = re.search(r'```markdown\s*([\s\S]*?)\s*```', response)
        if markdown_match:
            return markdown_match.group(1).strip()

        # 如果没有Markdown标记，尝试提取文档内容
        doc_start = re.search(r'# .* API接口文档', response)
        if doc_start:
            return response[doc_start.start():]

        # 如果没有明确标记，返回整个响应
        return response

    async def _analyze_features(self, html_content: str, project_name: str, description_text: str = "") -> Dict:
        """步骤1: 分析HTML原型和文字描述，确定功能和所需接口"""
        # 构建描述部分
        description_section = ""
        if description_text:
            description_section = f"""项目需求描述:
```
{description_text}
```
"""

        # 构建提示词
        prompt = self._analyze_features_prompt.format(
            project_name=project_name,
            description_section=description_section,
            html_content=html_content
        )

        # 使用LLM分析功能
        analysis_result = await self._execute_llm_step(prompt, "功能接口分析(步骤1)", max_retries=3)
        return analysis_result

    async def _plan_apis(self, html_content: str, project_name: str, analysis_result: Dict, description_text: str = "") -> Dict:
        """步骤2: 基于功能分析，规划所有API接口"""
        # 构建描述部分
        description_section = ""
        if description_text:
            description_section = f"""项目需求描述:
```
{description_text}
```
"""

        # 构建提示词
        prompt = self._plan_apis_prompt.format(
            project_name=project_name,
            analysis_result=json.dumps(analysis_result, ensure_ascii=False, indent=2),
            description_section=description_section,
            html_content=html_content
        )

        # 使用LLM规划API
        api_plan = await self._execute_llm_step(prompt, "API接口规划(步骤2)", max_retries=3)
        return api_plan

    async def _generate_api_doc(self, project_name: str, analysis_result: Dict, api_plan: Dict, description_text: str = "") -> str:
        """步骤3: 生成详细API文档"""
        # 构建描述部分
        description_section = ""
        if description_text:
            description_section = f"""项目需求描述:
```
{description_text}
```
"""

        # 获取API总数
        total_apis = len(api_plan.get("apis", []))
        if "authentication" in api_plan and "endpoints" in api_plan["authentication"]:
            total_apis += len(api_plan["authentication"]["endpoints"])

        # 构建提示词
        prompt = self._generate_api_doc_prompt.format(
            project_name=project_name,
            analysis_result=json.dumps(analysis_result, ensure_ascii=False, indent=2),
            api_plan=json.dumps(api_plan, ensure_ascii=False, indent=2),
            description_section=description_section,
            total_apis=total_apis
        )

        # 使用LLM生成API文档
        api_doc = await self._execute_llm_step(prompt, "API文档生成(步骤3)", max_retries=4)
        return api_doc

    async def execute(
        self,
        html_path: str,
        project_name: str,
        description_text: str = "",
        output_path: str = "api_docs",
        output_filename: str = "",
    ) -> ToolResult:
        """
        根据HTML原型界面和文字描述生成API接口文档。

        参数:
            html_path (str): HTML原型文件的路径，可以是绝对路径或相对于工作区的路径。
            project_name (str): API项目名称。
            description_text (str, optional): 项目需求的文字描述，提供额外的API设计信息。
            output_path (str, optional): 保存生成文档的路径，默认为工作区中的api_docs目录。
            output_filename (str, optional): 生成的文档文件名，不包含扩展名。默认为[project_name]_api_doc。

        返回:
            ToolResult: 包含文档生成路径和操作状态的结果对象。
        """
        try:
            # 初始化进度
            self._progress = 0
            self._update_progress(0, "开始生成API接口文档...")

            # 验证参数
            if not html_path:
                return ToolResult(
                    error="必须提供HTML原型文件路径",
                    success=False,
                )

            if not project_name:
                return ToolResult(
                    error="必须提供项目名称",
                    success=False,
                )

            # 如果未提供输出文件名，默认使用项目名称
            if not output_filename:
                output_filename = f"{project_name}_api_doc"

            # 读取HTML文件内容
            html_content = self._read_html_file(html_path)
            logger.info(f"已读取HTML文件，大小: {len(html_content)}字节")

            # 记录是否提供了描述文本
            if description_text:
                logger.info(f"提供了项目描述文本，长度: {len(description_text)}字节")
            else:
                logger.info("未提供项目描述文本，将仅使用HTML原型生成API文档")

            # 步骤1: 分析功能和所需接口
            self._update_progress(0.3, "步骤1: 分析功能和所需接口...")
            start_time = time.time()
            analysis_result = await self._analyze_features(html_content, project_name, description_text)
            step1_duration = time.time() - start_time

            # 保存步骤1结果
            analysis_file = self._save_json_file(analysis_result, output_path, f"{project_name}_api_analysis")

            # 统计信息
            feature_count = len(analysis_result.get("features", []))
            total_apis = analysis_result.get("total_apis", 0)
            logger.info(f"步骤1完成 - 分析出{feature_count}个功能，预计需要{total_apis}个API接口，耗时: {step1_duration:.2f}秒")
            logger.info(f"分析结果已保存到: {analysis_file}")

            # 步骤2: 规划API接口
            self._update_progress(1, "步骤2: 规划API接口...")
            start_time = time.time()
            api_plan = await self._plan_apis(html_content, project_name, analysis_result, description_text)
            step2_duration = time.time() - start_time

            # 保存步骤2结果
            plan_file = self._save_json_file(api_plan, output_path, f"{project_name}_api_plan")

            # 统计信息
            api_count = len(api_plan.get("apis", []))
            auth_endpoints = len(api_plan.get("authentication", {}).get("endpoints", []))
            logger.info(f"步骤2完成 - 规划了{api_count}个API接口和{auth_endpoints}个认证接口，耗时: {step2_duration:.2f}秒")
            logger.info(f"API规划已保存到: {plan_file}")

            # 步骤3: 生成API文档
            self._update_progress(2, "步骤3: 生成完整API文档...")
            start_time = time.time()
            api_doc_content = await self._generate_api_doc(project_name, analysis_result, api_plan, description_text)
            step3_duration = time.time() - start_time

            # 保存最终文档
            doc_file = self._save_markdown_file(api_doc_content, output_path, output_filename)

            # 计算总耗时
            total_duration = step1_duration + step2_duration + step3_duration
            logger.info(f"步骤3完成 - 生成了完整的API文档，耗时: {step3_duration:.2f}秒")
            logger.info(f"API文档已保存到: {doc_file}")

            self._update_progress(3, "API接口文档生成完成!")

            # 返回结果
            desc_info = "结合文字描述" if description_text else ""
            summary = f"""基于HTML原型{desc_info}的API接口文档已生成并保存到: {doc_file}

生成过程摘要:
- 步骤1 (功能分析): 分析出{feature_count}个功能，预计需要{total_apis}个API接口，耗时: {step1_duration:.2f}秒
- 步骤2 (API规划): 规划了{api_count}个业务API和{auth_endpoints}个认证接口，耗时: {step2_duration:.2f}秒
- 步骤3 (文档生成): 生成完整API文档，耗时: {step3_duration:.2f}秒
- 总耗时: {total_duration:.2f}秒

中间结果文件:
- 功能分析: {analysis_file}
- API规划: {plan_file}
- 最终文档: {doc_file}
"""
            return ToolResult(
                output=summary,
                success=True,
            )

        except FileNotFoundError as e:
            logger.error(f"HTML文件未找到: {str(e)}")
            return ToolResult(
                error=f"HTML文件未找到: {str(e)}",
                success=False,
            )

        except Exception as e:
            logger.error(f"API文档生成失败: {str(e)}")
            import traceback
            logger.error(f"详细错误: {traceback.format_exc()}")
            return ToolResult(
                error=f"API文档生成失败: {str(e)}",
                success=False,
            )
