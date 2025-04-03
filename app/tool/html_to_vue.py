import os
import re
import zipfile
import shutil
import json
from typing import Dict, List, Optional
import time
import asyncio
import aiofiles
import hashlib

from app.tool.base import BaseTool, ToolResult  # 从基础工具类导入
from app.logger import logger  # 导入日志记录器
from app.config import config  # 导入配置模块
from app.llm import LLM  # 导入LLM模块


class HTMLToVue(BaseTool):
    """一个用于将HTML原型界面和API接口文档转换为Vue前端项目的工具。"""

    name: str = "html_to_vue"
    description: str = "Generates a complete Vue frontend project based on HTML prototype interfaces and API documentation. The project includes all necessary components such as views, components, routers, and API services."
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
                "description": "Name of the generated Vue project.",
            },
            "vue_version": {
                "type": "string",
                "description": "Vue version to use (2 or 3). Default is Vue 3.",
                "default": "3",
            },
            "use_typescript": {
                "type": "boolean",
                "description": "Whether to use TypeScript in the project. Default is true.",
                "default": True,
            },
            "output_path": {
                "type": "string",
                "description": "Path where to save the generated project. Default is 'vue_projects' folder in workspace.",
                "default": "vue_projects",
            },
        },
        "required": ["html_path", "project_name"],
    }

    # 综合项目生成提示词
    _generate_project_prompt = """请基于以下HTML原型界面和API接口文档，生成一个完整的Vue{vue_version}项目。

项目名称: {project_name}
是否使用TypeScript: {use_typescript}

HTML原型界面:
```html
{html_content}
```

{api_doc_section}

请生成一个完整的项目，包括以下内容：
1. 所有基础配置文件(package.json, tsconfig.json等)
2. 所有组件、视图、路由、API服务等
3. 完整的状态管理实现
4. 完整的样式文件
5. 工具类和辅助函数
6. 类型定义(如使用TypeScript)
7. 必须包含入口文件index.html(Vue 3项目在根目录，Vue 2项目在public目录)

请以JSON格式返回完整的项目文件结构:
```json
{{
  "files": [
    {{
      "path": "文件路径",
      "content": "文件内容"
    }}
  ]
}}
```

特别注意：
1. 请确保生成所有必要的文件
2. 确保所有代码都是完整的，不要省略任何实现
3. 生成的代码需要可直接运行
4. 确保各组件之间的关联正确
5. 必须包括完整的路由设置和状态管理
6. 必须生成项目入口HTML文件(index.html)，这是项目的关键文件
"""

    def __init__(self):
        super().__init__()
        self._llm_cache = {}
        self._cache_ttl = 3600
        self._progress = 0
        self._total_steps = 2  # 总步骤数：1.创建目录 2.生成文件

    def _update_progress(self, step: int, message: str) -> None:
        """更新进度并输出信息"""
        self._progress = (step / self._total_steps) * 100
        logger.info(f"进度: {self._progress:.1f}% - {message}")

    def _get_cache_key(self, prompt: str) -> str:
        """生成缓存键"""
        return hashlib.md5(prompt.encode()).hexdigest()

    def _get_cached_result(self, cache_key: str) -> Optional[Dict]:
        """获取缓存的结果"""
        if cache_key in self._llm_cache:
            cache_data = self._llm_cache[cache_key]
            if time.time() - cache_data["timestamp"] < self._cache_ttl:
                logger.info("使用缓存的LLM生成结果")
                return cache_data["result"]
            else:
                # 清除过期缓存
                del self._llm_cache[cache_key]
        return None

    def _cache_result(self, cache_key: str, result: Dict) -> None:
        """缓存结果"""
        self._llm_cache[cache_key] = {
            "result": result,
            "timestamp": time.time()
        }
        logger.info("已缓存LLM生成结果")

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

    def _create_project_dirs(self, output_path: str, project_name: str) -> str:
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

        # 创建基本目录结构
        for directory in [
            "src", "src/assets", "src/components", "src/views", "src/router",
            "src/store", "src/api", "src/utils", "src/styles", "src/constants",
            "src/types", "public"
        ]:
            os.makedirs(os.path.join(project_dir, directory), exist_ok=True)

        logger.info(f"已创建项目基本目录结构: {project_dir}")
        return project_dir

    async def _write_files(self, files: List[Dict[str, str]], project_dir: str) -> List[str]:
        """一次性写入所有文件"""
        start_time = time.time()
        logger.info(f"开始写入文件，总文件数: {len(files)}")

        created_files = []
        for file_info in files:
            file_path = os.path.join(project_dir, file_info["path"])
            dir_path = os.path.dirname(file_path)

            # 确保目录存在
            os.makedirs(dir_path, exist_ok=True)

            # 获取文件内容
            content = file_info["content"]

            # 检查内容类型并转换
            if isinstance(content, dict):
                content = json.dumps(content, ensure_ascii=False, indent=2)
            elif not isinstance(content, str):
                content = str(content)

            # 写入文件
            async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
                await f.write(content)

            created_files.append(file_info["path"])

        duration = time.time() - start_time
        logger.info(f"文件写入完成，共写入 {len(created_files)} 个文件，耗时: {duration:.2f}秒")
        return created_files

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

    async def execute(
        self,
        html_path: str,
        project_name: str,
        api_doc_path: str = "",
        vue_version: str = "3",
        use_typescript: bool = True,
        output_path: str = "vue_projects",
    ) -> ToolResult:
        """执行Vue项目生成"""
        try:
            self._progress = 0
            self._update_progress(0, "开始生成Vue项目...")

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

            # 验证Vue版本
            if vue_version not in ["2", "3"]:
                return ToolResult(
                    error="Vue版本必须是2或3",
                    success=False,
                )

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

            # 步骤1: 创建项目目录
            self._update_progress(1, "创建项目目录结构...")
            project_dir = self._create_project_dirs(output_path, project_name)
            logger.info(f"项目目录结构创建完成: {project_dir}")

            # 步骤2: 一次性生成所有项目文件
            self._update_progress(1.5, "开始生成所有项目文件...")

            # 准备文件扩展名和配置文件
            js_ext = "ts" if use_typescript else "js"
            vue_config_file = "vite.config.ts" if vue_version == "3" and use_typescript else "vite.config.js" if vue_version == "3" else "vue.config.js"

            # API文档部分
            api_doc_section = f"""
请分析以下API接口文档：
```markdown
{api_doc_content}
```
""" if api_doc_content else ""

            # 准备生成提示词
            prompt = self._generate_project_prompt.format(
                project_name=project_name,
                vue_version=vue_version,
                use_typescript=str(use_typescript),
                html_content=html_content,
                api_doc_section=api_doc_section
            )

            # 生成所有文件，最多重试5次
            max_retries = 5
            all_files = None

            for retry in range(1, max_retries + 1):
                try:
                    logger.info(f"尝试生成项目文件 (第{retry}/{max_retries}次)")
                    start_time = time.time()

                    result = await self._generate_with_llm(prompt, timeout=600)  # 增加超时时间

                    # 检查结果
                    all_files = result.get("files", [])
                    if not all_files or not isinstance(all_files, list) or len(all_files) < 5:
                        raise ValueError(f"生成的文件数量不足: {len(all_files) if all_files else 0}个")

                    # 检查入口文件是否存在
                    index_html_paths = ["index.html", "public/index.html"]
                    has_index_html = any(file_info["path"] in index_html_paths for file_info in all_files)

                    if not has_index_html:
                        logger.warning("缺少入口文件index.html，重新尝试生成")
                        if retry == max_retries:
                            # 在最后一次尝试中，手动添加一个简单的index.html
                            logger.info("手动添加基础index.html文件")
                            index_path = "index.html" if vue_version == "3" else "public/index.html"
                            basic_index_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{project_name}</title>
</head>
<body>
  <div id="app"></div>
  <script type="module" src="/src/main.{js_ext}"></script>
</body>
</html>"""
                            all_files.append({
                                "path": index_path,
                                "content": basic_index_html
                            })
                            has_index_html = True
                        else:
                            # 强化提示并重试
                            prompt += "\n\n特别强调：项目必须包含入口HTML文件(index.html)，这是运行项目的必要文件！"
                            raise ValueError("生成的项目缺少入口文件index.html")

                    # 计算耗时
                    duration = time.time() - start_time
                    logger.info(f"项目文件生成成功，共{len(all_files)}个文件，耗时: {duration:.2f}秒")
                    break

                except Exception as e:
                    logger.error(f"生成项目文件失败 (尝试 {retry}/{max_retries}): {str(e)}")
                    if retry == max_retries:
                        return ToolResult(
                            error=f"项目文件生成失败，已重试{max_retries}次: {str(e)}",
                            success=False,
                        )
                    # 等待后重试
                    await asyncio.sleep(2 * retry)

            # 写入所有文件
            self._update_progress(1.8, "写入项目文件...")
            created_files = await self._write_files(all_files, project_dir)

            # 创建ZIP文件
            zip_path = self._create_zip_file(project_dir)

            self._update_progress(2, "项目生成完成！")

            # 返回结果
            api_doc_info = f"并结合API文档 {api_doc_path}" if api_doc_path else ""
            ts_info = "TypeScript" if use_typescript else "JavaScript"

            # 检查是否成功生成了入口文件
            index_html_file = "index.html" if vue_version == "3" else "public/index.html"
            index_html_status = "✅ 已生成入口文件 " + index_html_file if os.path.exists(os.path.join(project_dir, index_html_file)) else "⚠️ 未找到入口文件 " + index_html_file

            result_output = f"""基于HTML原型{api_doc_info}的Vue {vue_version} ({ts_info})项目已生成并保存到: {project_dir}
同时创建了ZIP文件: {zip_path}

生成的文件数量: {len(created_files)}个
{index_html_status}

项目可直接运行：
1. 进入项目目录: cd {project_dir}
2. 安装依赖: npm install
3. 启动开发服务器: npm run dev
4. 构建生产版本: npm run build

项目特点：
- 使用 Vue {vue_version} + {ts_info}
- 完整的项目结构和必要组件
- 集成了路由、状态管理、API调用等功能
- 已配置代码规范和测试框架
"""
            logger.info("项目生成过程结束")
            return ToolResult(
                output=result_output,
                success=True,
            )

        except Exception as e:
            logger.error(f"Vue项目生成失败: {str(e)}")
            import traceback
            logger.error(f"错误详情: {traceback.format_exc()}")
            return ToolResult(
                error=f"Vue项目生成失败: {str(e)}",
                success=False,
            )

    async def _generate_with_llm(self, prompt: str, timeout: int = 600, max_retries: int = 5) -> Dict:
        """使用大模型生成内容，带有超时控制和重试机制"""
        # 检查缓存
        cache_key = self._get_cache_key(prompt)
        cached_result = self._get_cached_result(cache_key)
        if cached_result:
            return cached_result

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
6. 尽量简化和优化生成的代码，避免不必要的复杂性
"""

        logger.info(f"开始使用LLM生成内容，超时时间: {timeout}秒，最大重试次数: {max_retries}")

        while retry_count < max_retries:
            try:
                # 创建LLM实例
                llm = LLM("online")
                logger.info(f"LLM实例创建完成，开始生成内容 (尝试 {retry_count + 1}/{max_retries})")

                # 使用asyncio.wait_for添加超时控制
                start_time = time.time()
                response = await asyncio.wait_for(
                    llm.ask([{"role": "user", "content": enhanced_prompt}], stream=False),
                    timeout=timeout
                )
                duration = time.time() - start_time
                logger.info(f"LLM生成内容完成，耗时: {duration:.2f}秒，响应长度: {len(response)}字符")

                # 提取JSON内容
                result = await self._extract_json_content(response)
                files_count = len(result.get('files', []))
                logger.info(f"JSON内容解析成功，包含 {files_count} 个文件")

                # 缓存结果
                self._cache_result(cache_key, result)
                return result

            except asyncio.TimeoutError:
                last_error = "LLM生成超时"
                logger.warning(f"LLM生成超时 (尝试 {retry_count + 1}/{max_retries})")
                retry_count += 1
                # 增加超时时间
                timeout *= 1.5

            except Exception as e:
                last_error = str(e)
                retry_count += 1
                logger.warning(f"LLM生成或解析失败 (尝试 {retry_count + 1}/{max_retries}): {str(e)}")

                if retry_count >= max_retries:
                    logger.error(f"已达到最大重试次数({max_retries})，LLM生成失败: {str(e)}")
                    raise

                # 在重试时进一步强化提示
                enhanced_prompt = f"""
{enhanced_prompt}

前一次生成出现了问题，请再次尝试并特别注意：
1. 生成更简洁的代码
2. 确保JSON格式完全正确
3. 减少代码的复杂度
4. 优先生成最基础必要的功能
"""
                # 指数退避
                await asyncio.sleep(2 ** retry_count)

        raise Exception(f"LLM生成失败，已重试{max_retries}次，最后错误: {last_error}")

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

        # 修复常见的JSON格式问题
        # 1. 替换反引号为双引号
        json_content = re.sub(r'`\s*(\{[\s\S]*?\})\s*`', r'"\1"', json_content)
        json_content = json_content.replace('`', '"')

        # 2. 转义内容中的双引号
        def escape_quotes_in_content(match):
            content = match.group(1)
            # 将内容中的双引号转义
            escaped_content = content.replace('"', '\\"')
            return f'"{escaped_content}"'

        json_content = re.sub(r'"content":\s*"([\s\S]*?)"(?=\s*[,}])', escape_quotes_in_content, json_content)

        # 3. 修复其他常见错误
        json_content = re.sub(r'([{,]\s*)(\w+)(\s*:)', r'\1"\2"\3', json_content)  # 修复键名没有引号
        json_content = re.sub(r',\s*}', '}', json_content)  # 修复尾部逗号
        json_content = re.sub(r',\s*]', ']', json_content)  # 修复数组尾部逗号

        # 4. 修复缺少"content"键的问题
        # 匹配"path"后面直接跟着JSON字符串内容的模式
        json_content = re.sub(r'("path"\s*:\s*"[^"]+"\s*,)\s*("(?:\\\"|[^"])*"\s*)', r'\1"content":\2', json_content)
        # 匹配"path"后面直接跟着{开头的内容
        json_content = re.sub(r'("path"\s*:\s*"[^"]+"\s*,)\s*({[\s\S]*?})(?=\s*[,}])', r'\1"content":"\2"', json_content)

        # 尝试解析修复后的JSON
        try:
            logger.info(f"尝试解析修复后的JSON内容")
            result = json.loads(json_content)
            logger.info(f"JSON解析成功，结构: {list(result.keys())}")
            return result
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}")
            logger.error(f"尝试解析的内容前200字符: {json_content[:200]}...")

            # 最后尝试更激进的修复
            try:
                # 检查是否有JS模板字符串或JSON格式内嵌在内容中
                # 这是一个更激进的修复方法，尝试完全重新格式化内容
                # 查找所有"content": 后面跟着的模板字符串
                content_pattern = r'"content":\s*(?:`|\")(\{[\s\S]*?\})(?:`|\")'

                def clean_content(match):
                    content = match.group(1)
                    # 将双引号转义，移除模板字符串标记
                    content = content.replace('"', '\\"').replace('`', '')
                    return f'"content": "{content}"'

                json_content = re.sub(content_pattern, clean_content, json_content)

                # 再次尝试修复缺少"content"键的问题
                json_content = re.sub(r'("path"\s*:\s*"[^"]+"\s*),\s*("(?:\\\"|[^"])*")', r'\1,"content":\2', json_content)
                json_content = re.sub(r'("path"\s*:\s*"[^"]+"\s*),\s*((?:{|\[)[\s\S]*?(?:}|\]))', r'\1,"content":"\2"', json_content)

                # 再次尝试解析
                result = json.loads(json_content)
                logger.info("激进修复后JSON解析成功")
                return result
            except json.JSONDecodeError as e:
                logger.error(f"激进修复后仍然失败: {e}")
                raise ValueError(f"无法解析JSON内容: {e}")
