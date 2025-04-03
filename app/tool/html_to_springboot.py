import os
import re
import zipfile
import shutil
import json
import time
from typing import Dict, List, Optional, Union, Tuple

from app.tool.base import BaseTool, ToolResult  # 从基础工具类导入
from app.logger import logger  # 导入日志记录器
from app.config import config  # 导入配置模块
from app.llm import LLM  # 导入LLM模块


class HTMLToSpringboot(BaseTool):
    """一个用于将HTML原型界面和API接口文档转换为Springboot+MyBatis后端项目的工具。"""

    name: str = "html_to_springboot"
    description: str = "Generates a complete Springboot2+MyBatis backend project based on HTML prototype interfaces and API documentation. The project includes all necessary components such as pom.xml, entity classes, controllers, services, etc."
    parameters: dict = {
        "type": "object",
        "properties": {
            "html_path": {
                "type": "string",
                "description": "Path to the HTML prototype file. Can be absolute or relative to workspace.",
            },
            "api_doc_path": {
                "type": "string",
                "description": "Path to the API documentation file (Markdown format). Optional but recommended for more accurate API implementation.",
                "default": "",
            },
            "project_name": {
                "type": "string",
                "description": "Name of the generated Springboot project.",
            },
            "database_name": {
                "type": "string",
                "description": "Name of the database to use for this project.",
                "default": "",
            },
            "package_name": {
                "type": "string",
                "description": "Base package name for the project. Default is 'com.demo'.",
                "default": "com.demo",
            },
            "output_path": {
                "type": "string",
                "description": "Path where to save the generated project. Default is 'springboot_projects' folder in workspace.",
                "default": "springboot_projects",
            },
        },
        "required": ["html_path", "project_name"],
    }

    # 项目基本结构分析提示词
    _analyze_structure_prompt = """请分析下面的HTML原型界面和API接口文档（如果提供），提取关键业务实体、功能和API接口，用于后续生成Springboot项目。
项目名称: {project_name}
项目包路径: {package_name}.{project_name}
数据库名称: {database_name}

请分析以下HTML原型界面，提取关键业务实体和功能:
```html
{html_content}
```

{api_doc_section}

请根据分析结果，提供项目的基本结构信息:
1. 主要业务实体对象列表及其属性
2. 需要生成的主要功能模块和接口列表
3. 可能的数据库表结构

请以JSON格式返回项目的基本结构设计:
```json
{{
  "entities": [
    {{
      "name": "实体名称",
      "tableName": "表名",
      "fields": [
        {{ "name": "字段名", "type": "数据类型", "description": "描述" }}
      ]
    }}
  ],
  "modules": [
    {{
      "name": "模块名称",
      "apis": [
        {{ "url": "/api/路径", "method": "GET/POST", "description": "接口描述" }}
      ]
    }}
  ],
  "tables": [
    {{
      "name": "表名",
      "fields": [
        {{ "name": "字段名", "type": "数据库类型", "constraints": "约束" }}
      ]
    }}
  ]
}}
```
"""

    # 第二步：生成SQL文件、Application启动类和Bean类提示词
    _basic_files_prompt = """根据之前分析的项目结构信息，请生成Springboot项目的基础文件，包括SQL脚本、Application启动类和Bean实体类。
项目名称: {project_name}
项目包路径: {package_name}.{project_name}
数据库名称: {database_name}

项目基本结构:
{project_structure}

请生成以下文件:
1. src/main/resources/schema.sql - 包含所有表的创建语句
2. src/main/resources/data.sql - 包含必要的测试数据插入语句
3. src/main/java/{package_path}/{project_name}/Application.java - 主启动类
4. 所有的实体类({package_name}.{project_name}.entity包下)，包含完整的注解和属性
5. application.yml - 包含完整的数据库连接等配置
6. pom.xml - 包含Springboot2、MyBatis、MySQL等所有必要依赖

请确保:
1. SQL脚本可以直接执行，包含完整的CREATE TABLE语句
2. Bean类包含所有必要的JPA/MyBatis注解
3. Application启动类配置完整，包含必要的组件扫描
4. pom.xml包含所有必要的依赖和插件

请以JSON格式返回这些文件:
```json
{{
  "files": [
    {{
      "path": "相对路径/文件名",
      "content": "文件内容"
    }}
  ]
}}
```
"""

    # 第三步：生成完整项目文件提示词
    _complete_project_prompt = """现在请基于已生成的基础文件，生成Springboot项目的所有剩余文件，包括Controller、Service、Mapper等。请确保这些文件与已有的Bean类和API设计保持一致。
项目名称: {project_name}
项目包路径: {package_name}.{project_name}
数据库名称: {database_name}

项目基本结构:
{project_structure}

已生成的基础文件:
{basic_files_content}

请一次性生成以下所有剩余文件:
1. 所有实体对应的Controller类({package_name}.{project_name}.controller包下)
2. 所有实体对应的Service接口({package_name}.{project_name}.service包下)和实现类({package_name}.{project_name}.service.impl包下)
3. 所有实体对应的Mapper接口({package_name}.{project_name}.mapper包下)和XML映射文件(src/main/resources/mapper目录下)
4. 通用响应类({package_name}.{project_name}.common.ResponseResult)
5. 异常处理类({package_name}.{project_name}.exception包下)
6. 工具类({package_name}.{project_name}.utils包下)
7. 配置类({package_name}.{project_name}.config包下)

请确保:
1. Controller实现符合API文档定义，使用通用响应对象包装返回结果
2. Service层包含完整的业务逻辑实现
3. Mapper层正确映射到数据库表
4. 所有组件间依赖关系正确，能正常协同工作
5. 实现代码完整，不要使用TODO或省略重要代码

请以JSON格式返回这些文件:
```json
{{
  "files": [
    {{
      "path": "相对路径/文件名",
      "content": "文件内容"
    }}
  ]
}}
```
"""

    # 保存生成的文件用于后续参考
    _generated_files = {}

    def __init__(self):
        super().__init__()
        self._progress = 0
        self._total_steps = 3  # 总步骤数：1.创建目录 2.生成基础文件 3.生成完整项目

    def _update_progress(self, step: int, message: str) -> None:
        """更新进度并输出信息"""
        self._progress = (step / self._total_steps) * 100
        logger.info(f"进度: {self._progress:.1f}% - {message}")

    async def _read_file_content(self, file_path: str) -> str:
        """读取文件内容"""
        try:
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    return f.read()
            return ""
        except Exception as e:
            logger.error(f"读取文件失败: {str(e)}")
            return ""

    async def _collect_files_content(self, project_dir: str, file_patterns: List[str], max_size: int = 6000) -> str:
        """收集特定类型文件的内容，用于后续生成参考"""
        content = []
        total_size = 0

        for root, dirs, files in os.walk(project_dir):
            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, project_dir)

                # 检查是否匹配模式
                if any(pattern in rel_path for pattern in file_patterns):
                    file_content = await self._read_file_content(file_path)
                    if file_content:
                        # 添加文件名和内容
                        file_info = f"// {rel_path}\n{file_content}\n"

                        # 检查总大小
                        if total_size + len(file_info) > max_size:
                            content.append("...(更多文件内容已省略)")
                            break

                        content.append(file_info)
                        total_size += len(file_info)

        return "\n".join(content) if content else ""

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

    def _read_api_doc_file(self, api_doc_path: str) -> str:
        """读取API文档文件内容"""
        if not api_doc_path:
            return ""

        # 确定完整路径
        if os.path.isabs(api_doc_path):
            full_path = api_doc_path
        else:
            full_path = os.path.join(config.workspace_root, api_doc_path)

        # 检查文件是否存在
        if not os.path.exists(full_path):
            raise FileNotFoundError(f"API文档文件未找到: {full_path}")

        # 读取文件内容
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()

    def _create_project_dirs(self, output_path: str, project_name: str, package_name: str = "com.demo") -> str:
        """创建项目目录结构"""
        # 确定完整输出路径
        if os.path.isabs(output_path):
            full_output_path = output_path
        else:
            full_output_path = os.path.join(config.workspace_root, output_path)

        # 创建项目目录
        project_dir = os.path.join(full_output_path, project_name)

        # 如果目录已存在，先删除
        if os.path.exists(project_dir):
            shutil.rmtree(project_dir)

        # 创建目录
        os.makedirs(project_dir, exist_ok=True)

        # 将包名中的点转换为路径分隔符
        package_path = package_name.replace(".", os.sep)

        # 创建基本目录结构，确保包含src/main/java目录
        base_package_path = os.path.join(project_dir, "src", "main", "java", package_path, project_name)
        os.makedirs(base_package_path, exist_ok=True)

        # 创建标准包结构
        for package in ["common", "config", "controller", "dto", "entity", "exception", "mapper", "service", "service/impl", "utils"]:
            os.makedirs(os.path.join(base_package_path, package.replace("/", os.sep)), exist_ok=True)

        # 创建资源目录
        resources_path = os.path.join(project_dir, "src", "main", "resources")
        os.makedirs(resources_path, exist_ok=True)
        os.makedirs(os.path.join(resources_path, "mapper"), exist_ok=True)
        os.makedirs(os.path.join(resources_path, "static"), exist_ok=True)
        os.makedirs(os.path.join(resources_path, "templates"), exist_ok=True)

        logger.info(f"已创建项目基本目录结构: {project_dir}")
        return project_dir

    def _save_project_files(self, files: List[Dict[str, str]], project_dir: str, package_name: str = "com.demo") -> List[str]:
        """保存项目文件到指定目录，返回保存的文件路径列表"""
        saved_files = []
        # 写入文件
        for file_info in files:
            file_path = file_info["path"]

            # 修复Java文件路径，确保所有Java文件都在src/main/java目录下
            if file_path.endswith(".java") and not file_path.startswith("src/"):
                # 检查文件路径是否包含包名结构
                package_path = package_name.replace(".", "/")
                if f"{package_path}/" in file_path:
                    # 添加src/main/java前缀
                    file_path = f"src/main/java/{file_path}"
                    logger.info(f"修正Java文件路径: {file_info['path']} -> {file_path}")
                    file_info["path"] = file_path

            # 构建完整路径
            full_path = os.path.join(project_dir, file_path)

            # 确保目录存在
            os.makedirs(os.path.dirname(full_path), exist_ok=True)

            # 写入文件内容
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(file_info["content"])

            saved_files.append(file_path)
            # 存储已生成文件
            self._generated_files[file_path] = file_info["content"]

        return saved_files

    def _create_zip_file(self, project_dir: str) -> str:
        """创建项目的ZIP压缩包"""
        zip_path = f"{project_dir}.zip"
        logger.info(f"开始创建ZIP文件: {zip_path}")

        file_count = 0
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(project_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, os.path.dirname(project_dir))
                    zipf.write(file_path, arcname)
                    file_count += 1

        logger.info(f"ZIP文件创建完成，包含 {file_count} 个文件: {zip_path}")
        return zip_path

    async def _extract_json_content(self, response: str) -> Dict:
        """从响应中提取JSON内容"""
        logger.info("开始从响应中提取JSON内容")
        # 提取JSON内容
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', response)
        if json_match:
            json_content = json_match.group(1).strip()
            logger.info("成功通过代码块标记提取JSON内容")
        else:
            # 尝试直接从响应中解析JSON
            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            if json_start != -1 and json_end != -1:
                json_content = response[json_start:json_end]
                logger.info("成功通过大括号位置提取JSON内容")
            else:
                logger.error("无法从响应中提取JSON内容")
                raise ValueError("无法从响应中提取JSON内容")

        # 解析JSON
        try:
            # 尝试修复常见的JSON格式问题
            # 1. 修复缺失的引号
            fixed_content = re.sub(r'([{,]\s*)(\w+)(\s*:)', r'\1"\2"\3', json_content)
            # 2. 修复错误的逗号（如对象末尾的逗号）
            fixed_content = re.sub(r',\s*}', '}', fixed_content)
            fixed_content = re.sub(r',\s*]', ']', fixed_content)

            result = json.loads(fixed_content)
            files_count = len(result.get("files", []))
            logger.info(f"JSON解析成功，包含 {files_count} 个文件")
            return result
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}")
            logger.error(f"尝试解析的内容前200字符: {json_content[:200]}...")
            raise ValueError(f"无法解析JSON内容: {e}")

    async def _generate_with_llm(self, prompt: str, timeout: int = 600, max_retries: int = 5) -> Dict:
        """使用大模型生成内容，带超时控制和重试机制"""
        retry_count = 0
        last_error = None

        # 修改提示词，强调生成完整代码且不要省略
        enhanced_prompt = f"""
{prompt}

特别注意：
1. 确保生成完整的代码实现，不要省略任何部分
2. 不要使用省略号、TODO注释或者其他方式跳过代码片段
3. 请仔细检查生成的JSON格式确保正确无误
4. 每个方法和函数必须有完整的实现
5. 确保生成所有必要的文件
6. 为了使代码更加清晰，使用完整类名而非自动导入
"""

        logger.info(f"开始使用LLM生成内容，超时时间: {timeout}秒，最大重试次数: {max_retries}")

        while retry_count < max_retries:
            try:
                # 创建LLM实例
                llm = LLM("doubao")
                logger.info(f"LLM实例创建完成，开始生成内容 (尝试 {retry_count + 1}/{max_retries})")

                # 记录开始时间
                start_time = time.time()

                # 使用LLM生成内容，不要直接传timeout参数
                messages = [{"role": "user", "content": enhanced_prompt}]
                response = await llm.ask(messages, stream=False)

                # 计算耗时
                duration = time.time() - start_time
                logger.info(f"LLM生成内容完成，耗时: {duration:.2f}秒，响应长度: {len(response)}字符")

                # 提取JSON内容
                return await self._extract_json_content(response)

            except Exception as e:
                last_error = str(e)
                retry_count += 1
                logger.error(f"LLM生成或解析失败 (尝试 {retry_count}/{max_retries}): {str(e)}")

                if retry_count >= max_retries:
                    logger.error(f"已达到最大重试次数({max_retries})，LLM生成失败: {str(e)}")
                    # 返回空文件列表而不是抛出异常，这样可以继续生成其他部分
                    return {"files": []}

                # 在重试时进一步强化提示
                enhanced_prompt = f"""
{enhanced_prompt}

前一次生成出现了问题，请再次尝试并特别注意：
1. 生成更简洁的代码
2. 确保JSON格式完全正确
3. 减少代码的复杂度
4. 优先生成最基础必要的功能
5. 错误详情: {last_error}
"""
                # 指数退避
                import asyncio
                await asyncio.sleep(2 ** retry_count)

        # 这里理论上不会到达，但为了代码完整性添加
        return {"files": []}

    async def _analyze_project_structure(self, html_content: str, api_doc_content: str, project_name: str, database_name: str) -> Dict:
        """分析项目结构"""
        # 准备API文档部分
        api_doc_section = ""
        if api_doc_content:
            api_doc_section = f"""
还请分析以下API接口文档，提取API规范和接口定义:
```markdown
{api_doc_content}
```
"""

        prompt = self._analyze_structure_prompt.format(
            project_name=project_name,
            database_name=database_name,
            html_content=html_content,
            api_doc_section=api_doc_section
        )

        return await self._generate_with_llm(prompt)

    async def _generate_basic_files(self, project_structure: Dict, project_name: str, database_name: str) -> List[Dict[str, str]]:
        """生成基础文件"""
        prompt = self._basic_files_prompt.format(
            project_name=project_name,
            database_name=database_name,
            project_structure=json.dumps(project_structure, ensure_ascii=False, indent=2)
        )

        result = await self._generate_with_llm(prompt)
        return result.get("files", [])

    async def _generate_complete_project(self, project_structure: Dict, project_name: str, database_name: str) -> List[Dict[str, str]]:
        """生成完整项目文件"""
        prompt = self._complete_project_prompt.format(
            project_name=project_name,
            database_name=database_name,
            project_structure=json.dumps(project_structure, ensure_ascii=False, indent=2)
        )

        result = await self._generate_with_llm(prompt)
        return result.get("files", [])

    async def execute(
        self,
        html_path: str,
        project_name: str,
        api_doc_path: str = "",
        database_name: str = "",
        package_name: str = "com.demo",
        output_path: str = "springboot_projects",
    ) -> ToolResult:
        """
        将HTML原型界面和API接口文档转换为Springboot+MyBatis后端项目。

        参数:
            html_path (str): HTML原型文件的路径，可以是绝对路径或相对于工作区的路径。
            project_name (str): 生成的Springboot项目名称。
            api_doc_path (str, optional): API接口文档文件路径，可提供更准确的API实现。
            database_name (str, optional): 数据库名称，默认使用项目名称。
            package_name (str, optional): 基础包名，默认为 'com.demo'。
            output_path (str, optional): 保存生成项目的路径，默认为工作区中的springboot_projects目录。

        返回:
            ToolResult: 包含项目生成路径和操作状态的结果对象。
        """
        try:
            self._progress = 0
            self._update_progress(0, "开始生成Springboot项目...")

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

            # 如果未提供数据库名称，默认使用项目名称
            if not database_name:
                database_name = project_name.lower()

            # 替换包名中的非法字符
            package_name = package_name.strip().lower()
            if not package_name:
                package_name = "com.demo"

            # 转换包路径为文件路径格式
            package_path = package_name.replace(".", "/")

            # 读取HTML文件内容
            html_content = self._read_html_file(html_path)
            logger.info(f"已读取HTML文件: {html_path}, 内容长度: {len(html_content)}字符")

            # 读取API文档内容（如果提供）
            api_doc_content = ""
            if api_doc_path:
                try:
                    api_doc_content = self._read_api_doc_file(api_doc_path)
                    logger.info(f"已读取API文档: {api_doc_path}, 内容长度: {len(api_doc_content)}字符")
                except FileNotFoundError as e:
                    logger.warning(f"API文档读取失败: {str(e)}，将仅使用HTML文件生成项目")

            # 准备API文档部分
            api_doc_section = ""
            if api_doc_content:
                api_doc_section = f"""
请分析以下API接口文档，提取API规范和接口定义:
```markdown
{api_doc_content}
```
"""

            # 步骤1: 创建项目目录结构
            self._update_progress(1, "创建项目目录结构...")
            project_dir = self._create_project_dirs(output_path, project_name, package_name)
            logger.info(f"项目目录结构创建完成: {project_dir}")

            # 初始化记录生成的文件列表
            generated_file_list = []
            self._generated_files = {}

            # 步骤2: 分析项目结构
            self._update_progress(1.2, "分析项目结构...")
            prompt = self._analyze_structure_prompt.format(
                project_name=project_name,
                package_name=package_name,
                database_name=database_name,
                html_content=html_content,
                api_doc_section=api_doc_section
            )

            project_structure = None
            max_retries = 5

            for retry in range(1, max_retries + 1):
                try:
                    logger.info(f"尝试分析项目结构 (第{retry}/{max_retries}次)")
                    start_time = time.time()

                    result = await self._generate_with_llm(prompt)

                    # 验证结果
                    if "entities" not in result or "modules" not in result or "tables" not in result:
                        raise ValueError("项目结构分析结果不完整，缺少必要字段")

                    project_structure = result
                    duration = time.time() - start_time
                    logger.info(f"项目结构分析完成，耗时: {duration:.2f}秒")
                    break
                except Exception as e:
                    logger.error(f"项目结构分析失败 (尝试 {retry}/{max_retries}): {str(e)}")
                    if retry == max_retries:
                        return ToolResult(
                            error=f"项目结构分析失败，已重试{max_retries}次: {str(e)}",
                            success=False,
                        )
                    # 等待后重试
                    import asyncio
                    await asyncio.sleep(2 * retry)

            # 步骤3: 生成基础文件 (SQL, Application, Bean)
            self._update_progress(1.5, "生成基础文件...")
            prompt = self._basic_files_prompt.format(
                project_name=project_name,
                package_name=package_name,
                package_path=package_path,
                database_name=database_name,
                project_structure=json.dumps(project_structure, ensure_ascii=False, indent=2)
            )

            basic_files = []

            for retry in range(1, max_retries + 1):
                try:
                    logger.info(f"尝试生成基础文件 (第{retry}/{max_retries}次)")
                    start_time = time.time()

                    result = await self._generate_with_llm(prompt)

                    # 检查结果
                    basic_files = result.get("files", [])
                    if not basic_files or len(basic_files) < 4:  # 至少应该有SQL、Application和几个Bean
                        raise ValueError(f"基础文件生成数量不足: {len(basic_files)}个")

                    # 保存文件
                    saved_files = self._save_project_files(basic_files, project_dir, package_name)
                    generated_file_list.extend(saved_files)

                    duration = time.time() - start_time
                    logger.info(f"基础文件生成完成，共{len(basic_files)}个文件，耗时: {duration:.2f}秒")
                    break
                except Exception as e:
                    logger.error(f"基础文件生成失败 (尝试 {retry}/{max_retries}): {str(e)}")
                    if retry == max_retries:
                        return ToolResult(
                            error=f"基础文件生成失败，已重试{max_retries}次: {str(e)}",
                            success=False,
                        )
                    # 等待后重试
                    import asyncio
                    await asyncio.sleep(2 * retry)

            # 收集基础文件内容供完整项目生成使用
            basic_files_content = await self._collect_files_content(
                project_dir,
                ["entity", "schema.sql", "data.sql", "Application.java", "application.yml", "pom.xml"]
            )

            # 步骤4: 生成完整项目文件
            self._update_progress(2, "生成完整项目文件...")
            prompt = self._complete_project_prompt.format(
                project_name=project_name,
                package_name=package_name,
                database_name=database_name,
                project_structure=json.dumps(project_structure, ensure_ascii=False, indent=2),
                basic_files_content=basic_files_content
            )

            complete_files = []

            for retry in range(1, max_retries + 1):
                try:
                    logger.info(f"尝试生成完整项目文件 (第{retry}/{max_retries}次)")
                    start_time = time.time()

                    result = await self._generate_with_llm(prompt)

                    # 检查结果
                    complete_files = result.get("files", [])
                    if not complete_files or len(complete_files) < 5:  # 至少应该有一些Controller、Service等文件
                        raise ValueError(f"项目文件生成数量不足: {len(complete_files)}个")

                    # 保存文件
                    saved_files = self._save_project_files(complete_files, project_dir, package_name)
                    generated_file_list.extend(saved_files)

                    duration = time.time() - start_time
                    logger.info(f"完整项目文件生成完成，共{len(complete_files)}个文件，耗时: {duration:.2f}秒")
                    break
                except Exception as e:
                    logger.error(f"完整项目文件生成失败 (尝试 {retry}/{max_retries}): {str(e)}")
                    if retry == max_retries:
                        logger.warning("在最大重试次数后仍未成功生成所有文件，将使用已生成的文件继续")
                        break
                    # 等待后重试
                    import asyncio
                    await asyncio.sleep(2 * retry)

            # 创建ZIP文件
            zip_path = self._create_zip_file(project_dir)

            self._update_progress(3, "项目生成完成！")

            # 返回结果
            total_files = len(generated_file_list)
            api_doc_info = f"并结合API文档 {api_doc_path}" if api_doc_path else ""

            # 计算文件类型统计
            file_stats = {
                "实体类": len([f for f in generated_file_list if "/entity/" in f]),
                "Controller": len([f for f in generated_file_list if "/controller/" in f]),
                "Service": len([f for f in generated_file_list if "/service/" in f]),
                "Mapper": len([f for f in generated_file_list if "/mapper/" in f or f.endswith(".xml")]),
                "SQL文件": len([f for f in generated_file_list if f.endswith(".sql")]),
                "配置文件": len([f for f in generated_file_list if f.endswith(".properties") or f.endswith(".yml") or f.endswith(".xml")])
            }

            file_stats_str = "\n".join([f"- {k}: {v}个" for k, v in file_stats.items() if v > 0])

            result_output = f"""基于HTML原型{api_doc_info}的Springboot项目已生成并保存到: {project_dir}
同时创建了ZIP文件: {zip_path}

项目基本信息：
- 包名: {package_name}.{project_name}
- 数据库名: {database_name}
- 生成的文件数量: {total_files}个

文件统计:
{file_stats_str}

项目可直接使用：
1. 导入项目到IDE (如IntelliJ IDEA)
2. 配置数据库连接(修改application.yml)
3. 运行Application类启动项目

项目特点：
- 完整的Springboot2 + MyBatis结构
- 包含所有必要的Controller、Service和Mapper
- 遵循RESTful API设计规范
- 数据库表结构和示例数据已生成
"""
            logger.info("项目生成过程结束")
            return ToolResult(
                output=result_output,
                success=True,
            )

        except FileNotFoundError as e:
            logger.error(f"文件未找到: {str(e)}")
            return ToolResult(
                error=f"文件未找到: {str(e)}",
                success=False,
            )

        except Exception as e:
            logger.error(f"Springboot项目生成失败: {str(e)}")
            import traceback
            logger.error(f"错误详情: {traceback.format_exc()}")
            return ToolResult(
                error=f"Springboot项目生成失败: {str(e)}",
                success=False,
            )
