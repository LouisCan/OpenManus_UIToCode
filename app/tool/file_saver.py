import os  # 导入os模块，用于文件和目录操作

import aiofiles  # 导入aiofiles模块，用于异步文件操作

from app.config import WORKSPACE_ROOT  # 从配置中导入工作区根目录路径
from app.tool.base import BaseTool  # 导入基础工具类
from app.logger import logger  # 导入日志记录器

class FileSaver(BaseTool):
    name: str = "file_saver"
    description: str = """Save content to a local file at a specified path.
Use this tool when you need to save text, code, or generated content to a file on the local filesystem.
The tool accepts content and a file path, and saves the content to that location.
"""
    parameters: dict = {
        "type": "object",
        "properties": {
            "content": {  # 要保存的内容
                "type": "string",
                "description": "(required) The content to save to the file.",
            },
            "file_path": {  # 文件保存路径
                "type": "string",
                "description": "(required) The path where the file should be saved, including filename and extension.",
            },
            "mode": {  # 文件打开模式
                "type": "string",
                "description": "(optional) The file opening mode. Default is 'w' for write. Use 'a' for append.",
                "enum": ["w", "a"],
                "default": "w",
            },
        },
        "required": ["content", "file_path"],  # 必填参数
    }

    async def execute(self, content: str, file_path: str, mode: str = "w") -> str:
        """
        将内容保存到指定路径的文件。

        参数:
            content (str): 要保存到文件的内容。
            file_path (str): 文件应保存的路径。
            mode (str, 可选): 文件打开模式。默认是 'w' 表示写入。使用 'a' 表示追加。

        返回:
            str: 操作结果的提示信息。
        """
        try:
            # 如果文件路径是绝对路径，则只使用文件名，与工作区根目录拼接
            if os.path.isabs(file_path):
                file_name = os.path.basename(file_path)
                full_path = os.path.join(WORKSPACE_ROOT, file_name)
            else:
                full_path = os.path.join(WORKSPACE_ROOT, file_path)

            # 确保目录存在，如果不存在则创建
            directory = os.path.dirname(full_path)
            if directory and not os.path.exists(directory):
                os.makedirs(directory)

            # 异步写入文件
            async with aiofiles.open(full_path, mode, encoding="utf-8") as file:
                await file.write(content)

            return f"Content successfully saved to {full_path}"
        except Exception as e:
            return f"Error saving file: {str(e)}"
