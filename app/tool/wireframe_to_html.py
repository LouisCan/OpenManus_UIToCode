import base64
import io
import os
import re
from typing import Dict, List, Optional, Union
import json
import random

from app.tool.base import BaseTool, ToolResult  # 从基础工具类导入
from app.logger import logger  # 导入日志记录器
from app.config import config  # 导入配置模块
from app.llm import LLM  # 导入LLM模块


class WireframeToHTML(BaseTool):
    """一个用于将文字描述转换为HTML原型界面的工具。"""

    name: str = "wireframe_html"
    description: str = "Converts text descriptions of UI wireframes into HTML prototypes and saves them locally. Supports flexible text input formats."
    parameters: dict = {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "Text description of the UI wireframe to convert to HTML.",
            },
            "output_path": {
                "type": "string",
                "description": "Path where to save the HTML file. Default is 'wireframes' folder in workspace.",
                "default": "wireframes",
            },
            "filename": {
                "type": "string",
                "description": "Filename for the generated HTML (without extension). Default is a generated name based on content.",
                "default": "",
            },
            "style": {
                "type": "string",
                "enum": ["modern", "minimal", "corporate"],
                "description": "Visual style to apply to the wireframe. Options: modern, minimal, corporate.",
                "default": "modern",
            },
        },
        "required": ["description"],
    }

    _themes = {
        "modern": {
            "font_family": "'Segoe UI', Roboto, 'Helvetica Neue', sans-serif",
            "primary_color": "#4285F4",
            "secondary_color": "#34A853",
            "background_color": "#FFFFFF",
            "text_color": "#202124",
        },
        "minimal": {
            "font_family": "'Roboto', 'Arial', sans-serif",
            "primary_color": "#555555",
            "secondary_color": "#777777",
            "background_color": "#F8F8F8",
            "text_color": "#333333",
        },
        "corporate": {
            "font_family": "'Open Sans', 'Arial', sans-serif",
            "primary_color": "#0078D4",
            "secondary_color": "#106EBE",
            "background_color": "#F5F5F5",
            "text_color": "#252525",
        },
    }

    _css_styles = """<style>
        /* 全局样式 */
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: "Microsoft YaHei", Arial, sans-serif;
        }

        body {
            background-color: #f5f5f5;
            color: #333;
            line-height: 1.5;
        }

        .navbar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            background-color: #1e467c;
            color: white;
            padding: 0 20px;
            height: 60px;
        }

        .navbar .left {
            display: flex;
            align-items: center;
        }

        .navbar .left i {
            font-size: 24px;
            margin-right: 15px;
            cursor: pointer;
        }

        .navbar .left span {
            font-size: 18px;
            font-weight: bold;
        }

        .navbar .search {
            flex: 1;
            margin: 0 30px;
        }

        .navbar .search input {
            width: 100%;
            padding: 8px 15px;
            border: none;
            border-radius: 4px;
            outline: none;
        }

        .navbar .right {
            display: flex;
            align-items: center;
        }

        .navbar .right span {
            margin-left: 20px;
            font-size: 14px;
            cursor: pointer;
        }

        .secondary-nav {
            background-color: #fff;
            padding: 10px 20px;
            border-bottom: 1px solid #e0e0e0;
            display: flex;
        }

        .secondary-nav span {
            margin-right: 20px;
            padding: 5px 10px;
            cursor: pointer;
            border-radius: 4px;
        }

        .secondary-nav span.active {
            background-color: #e6f2ff;
            color: #1890ff;
            border: 1px solid #1890ff;
        }

        .secondary-nav span i {
            margin-left: 5px;
            font-size: 12px;
        }

        .filter-area {
            background-color: #fff;
            padding: 15px 20px;
            margin: 15px;
            border-radius: 4px;
            display: flex;
            flex-wrap: wrap;
            align-items: center;
        }

        .filter-area label {
            margin-right: 10px;
            font-weight: normal;
        }

        .filter-area input[type="text"],
        .filter-area select,
        .filter-area input[type="date"] {
            padding: 8px 10px;
            border: 1px solid #d9d9d9;
            border-radius: 4px;
            margin-right: 10px;
            margin-bottom: 10px;
        }

        .filter-area .filter-option {
            margin-left: 10px;
        }

        .filter-area button {
            padding: 8px 15px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            margin-right: 10px;
        }

        .filter-area .primary {
            background-color: #1890ff;
            color: white;
        }

        .filter-area .secondary {
            background-color: #f5f5f5;
            color: #666;
        }

        .function-buttons {
            margin: 15px 20px;
            display: flex;
        }

        .function-buttons button {
            padding: 8px 15px;
            margin-right: 10px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
        }

        .function-buttons .primary {
            background-color: #1890ff;
            color: white;
        }

        .function-buttons .secondary {
            background-color: #f5f5f5;
            color: #666;
        }

        .data-table {
            width: 100%;
            margin: 0 20px 20px;
            border-collapse: collapse;
            background-color: #fff;
        }

        .data-table th,
        .data-table td {
            padding: 12px 15px;
            text-align: left;
            border-bottom: 1px solid #e8e8e8;
        }

        .data-table th {
            background-color: #fafafa;
            font-weight: bold;
        }

        .data-table tr:hover {
            background-color: #f5f5f5;
        }

        .data-table input[type="checkbox"] {
            margin: 0;
        }

        .pagination {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 15px 20px;
            background-color: #fff;
            border-top: 1px solid #e8e8e8;
        }

        .pagination div {
            display: flex;
            align-items: center;
        }

        .pagination button {
            width: 30px;
            height: 30px;
            border: 1px solid #d9d9d9;
            background-color: #fff;
            border-radius: 4px;
            margin: 0 5px;
            cursor: pointer;
        }

        .pagination span {
            margin: 0 10px;
        }

        .pagination input {
            width: 50px;
            padding: 5px;
            text-align: center;
            border: 1px solid #d9d9d9;
            border-radius: 4px;
        }
    </style>"""

    _prompt_template = """请根据以下要求生成一个基于文字版原型图的HTML代码，确保代码完整且可直接用于开发：
1. 使用Figma进行设计，确保设计符合现代UI/UX标准，界面美观且易用。
2. 使用Figma的组件库进行设计，确保组件的复用性和一致性。
3. 使用Figma的插件进行设计，提升设计效率和功能丰富度。
4. 作为产品经理，设计一个完整的原型图，包括但不限于首页、列表页、详情页等，并给出详细的设计思路，包括用户流程、功能布局、交互逻辑等。
5. 作为思考设计师，对设计的原型图进行合理性思考，分析其在用户体验、功能完整性、视觉效果等方面的优缺点，并提出改进建议。
6. 作为测试工程师，对原型图的测试方式进行思考，包括功能测试、性能测试、兼容性测试等，确保原型图在各种设备和浏览器上的正常运行。
7. 使用HTML在一个界面上生成所有的原型界面，确保代码结构清晰、语义化良好，符合Web开发标准。
8. 确保生成的HTML代码可以直接拿去进行开发，无需额外调整。
9. 必须使用下面提供的CSS样式，不要自行创建CSS样式：
{css_styles}

原型图文字描述:
{description}

请只返回完整的HTML代码，不要包含任何解释或说明。确保代码是有效的、可直接运行的HTML。
"""

    def _save_html_file(self, html_content: str, output_path: str, filename: str = "") -> str:
        """保存HTML文件到指定路径。"""
        # 确保输出目录存在
        if os.path.isabs(output_path):
            full_output_path = output_path
        else:
            full_output_path = os.path.join(config.workspace_root, output_path)

        os.makedirs(full_output_path, exist_ok=True)

        # 生成文件名
        if not filename:
            # 根据内容生成文件名
            import hashlib
            hash_obj = hashlib.md5(html_content.encode('utf-8'))
            filename = f"wireframe_{hash_obj.hexdigest()[:8]}"

        # 确保文件名不包含扩展名
        if filename.endswith(".html"):
            filename = filename[:-5]

        file_path = os.path.join(full_output_path, f"{filename}.html")

        # 写入文件
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        return file_path

    async def _generate_html_with_llm(self, description: str) -> str:
        """使用大模型生成HTML。"""
        prompt = self._prompt_template.format(
            description=description,
            css_styles=self._css_styles
        )

        try:
            # 创建LLM实例
            llm = LLM("doubao")

            # 使用LLM生成HTML
            messages = [{"role": "user", "content": prompt}]
            response = await llm.ask(messages, stream=False)

            # 提取HTML代码（如果响应包含解释或其他文本）
            html_match = re.search(r'```html\s*([\s\S]*?)\s*```', response)
            if html_match:
                return html_match.group(1).strip()

            # 如果没有使用代码块格式，则直接使用完整响应
            if response.strip().startswith("<!DOCTYPE html>") or response.strip().startswith("<html"):
                return response

            # 尝试寻找HTML开始标签
            html_start = response.find("<html")
            if html_start != -1:
                return response[html_start:]

            # 如果上述方法都失败，则假设整个响应就是HTML
            return response
        except Exception as e:
            logger.error(f"使用LLM生成HTML失败: {str(e)}")
            # 返回一个错误页面
            return f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>错误</title>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                {self._css_styles}
            </head>
            <body>
                <div class="filter-area">
                    <h1 style="color: #ff0000;">生成HTML时出错</h1>
                    <p>在处理您的请求时发生了错误：</p>
                    <pre>{str(e)}</pre>
                    <p>请修改您的描述并重试。</p>
                </div>
            </body>
            </html>
            """

    async def execute(
        self,
        description: str,
        output_path: str = "wireframes",
        filename: str = "",
        style: str = "modern",
    ) -> ToolResult:
        """
        将文字描述转换为HTML原型并保存到本地。

        参数:
            description (str): UI界面的文字描述，可以是自由格式。
            output_path (str, optional): 保存HTML文件的路径，默认为工作区中的wireframes目录。
            filename (str, optional): 生成的HTML文件名，不包含扩展名。如不提供则自动生成。
            style (str, optional): 应用的视觉风格，可选值：modern、minimal、corporate。默认为modern。

        返回:
            ToolResult: 包含HTML文件路径和操作状态的结果对象。
        """
        try:
            # 验证参数
            if not description:
                return ToolResult(
                    error="必须提供UI界面描述",
                    success=False,
                )

            # 验证样式参数
            if style not in self._themes:
                return ToolResult(
                    error=f"样式参数必须是以下之一: {', '.join(self._themes.keys())}",
                    success=False,
                )

            # 使用LLM生成HTML - 不再使用主题设置，直接使用提供的CSS
            html_content = await self._generate_html_with_llm(description)

            # 保存HTML文件
            file_path = self._save_html_file(html_content, output_path, filename)

            # 返回结果
            return ToolResult(
                output=f"HTML原型已生成并保存到: {file_path}",
                success=True,
            )

        except Exception as e:
            logger.error(f"HTML原型生成失败: {str(e)}")
            return ToolResult(
                error=f"HTML原型生成失败: {str(e)}",
                success=False,
            )
