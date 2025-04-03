import multiprocessing  # 导入多进程模块
import sys  # 导入系统模块
from io import StringIO  # 导入字符串IO模块，用于捕获输出
from typing import Dict  # 导入类型提示模块

from app.tool.base import BaseTool  # 从基础工具类导入BaseTool
from app.logger import logger  # 导入日志记录器

class PythonExecute(BaseTool):
    """一个用于执行Python代码的工具，具有超时和安全限制。"""

    name: str = "python_execute"
    description: str = "Executes Python code string. Note: Only print outputs are visible, function return values are not captured. Use print statements to see results."
    parameters: dict = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "The Python code to execute.",
            },
        },
        "required": ["code"],
    }

    def _run_code(self, code: str, result_dict: dict, safe_globals: dict) -> None:
        """执行代码并捕获输出或错误。"""
        original_stdout = sys.stdout  # 保存原始标准输出
        try:
            output_buffer = StringIO()  # 创建字符串IO缓冲区
            sys.stdout = output_buffer  # 将标准输出重定向到缓冲区
            exec(code, safe_globals, safe_globals)  # 执行代码
            result_dict["observation"] = output_buffer.getvalue()  # 获取输出结果
            result_dict["success"] = True  # 设置执行成功标志
        except Exception as e:  # 捕获异常
            result_dict["observation"] = str(e)  # 记录错误信息
            result_dict["success"] = False  # 设置执行失败标志
        finally:
            sys.stdout = original_stdout  # 恢复原始标准输出

    async def execute(
        self,
        code: str,
        timeout: int = 5,
    ) -> Dict:
        """
        执行提供的Python代码，并设置超时时间。

        参数:
            code (str): 要执行的Python代码。
            timeout (int): 执行超时时间（秒）。

        返回:
            Dict: 包含执行输出或错误信息和执行成功状态的字典。
        """
        with multiprocessing.Manager() as manager:  # 使用Manager创建一个可以在进程间共享的字典
            result = manager.dict({"observation": "", "success": False})  # 初始化结果字典
            if isinstance(__builtins__, dict):
                safe_globals = {"__builtins__": __builtins__}  # 确保__builtins__是字典类型
            else:
                safe_globals = {"__builtins__": __builtins__.__dict__.copy()}  # 复制__builtins__以避免修改原始数据
            proc = multiprocessing.Process(
                target=self._run_code, args=(code, result, safe_globals)  # 创建进程，目标函数为_run_code
            )
            proc.start()  # 启动进程
            proc.join(timeout)  # 等待进程完成，最多等待timeout秒

            # 处理超时情况
            if proc.is_alive():
                proc.terminate()  # 终止进程
                proc.join(1)  # 等待进程终止
                return {
                    "observation": f"执行超时，超过 {timeout} 秒",
                    "success": False,
                }
            return dict(result)  # 返回结果字典
