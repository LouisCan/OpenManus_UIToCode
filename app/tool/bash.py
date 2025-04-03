import asyncio  # 异步IO库
import os  # 操作系统相关功能
from typing import Optional  # 类型提示

from app.exceptions import ToolError  # 自定义异常类
from app.tool.base import BaseTool, CLIResult  # 基础工具类和命令行结果类


_BASH_DESCRIPTION = """Execute a bash command in the terminal.
* Long running commands: For commands that may run indefinitely, it should be run in the background and the output should be redirected to a file, e.g. command = `python3 app.py > server.log 2>&1 &`.
* Interactive: If a bash command returns exit code `-1`, this means the process is not yet finished. The assistant must then send a second call to terminal with an empty `command` (which will retrieve any additional logs), or it can send additional text (set `command` to the text) to STDIN of the running process, or it can send command=`ctrl+c` to interrupt the process.
* Timeout: If a command execution result says "Command timed out. Sending SIGINT to the process", the assistant should retry running the command in the background.
"""


class _BashSession:
    """bash shell的一个会话。"""

    _started: bool  # 标记会话是否已启动
    _process: asyncio.subprocess.Process  # 子进程对象

    command: str = "/bin/bash"  # 默认执行的bash命令
    _output_delay: float = 0.2  # 输出延迟时间，单位秒
    _timeout: float = 120.0  # 命令执行超时时间，单位秒
    _sentinel: str = "<<exit>>"  # 用于标记命令执行结束的特殊字符串

    def __init__(self):
        self._started = False  # 初始化时，会话未启动
        self._timed_out = False  # 初始化时，未发生超时

    async def start(self):
        """启动bash shell会话。"""
        if self._started:
            return  # 如果已启动，则直接返回
        # 创建子进程，执行bash命令
        self._process = await asyncio.create_subprocess_shell(
            self.command,
            preexec_fn=os.setsid,  # 设置进程组ID
            shell=True,  # 使用shell执行命令
            bufsize=0,  # 缓冲区大小
            stdin=asyncio.subprocess.PIPE,  # 标准输入为管道
            stdout=asyncio.subprocess.PIPE,  # 标准输出为管道
            stderr=asyncio.subprocess.PIPE,  # 标准错误为管道
        )
        self._started = True  # 标记会话已启动

    def stop(self):
        """终止bash shell会话。"""
        if not self._started:
            raise ToolError("会话尚未启动。")  # 如果会话未启动，则抛出异常
        if self._process.returncode is not None:
            return  # 如果进程已结束，则直接返回
        self._process.terminate()  # 终止进程

    async def run(self, command: str):
        """在bash shell中执行命令。"""
        if not self._started:
            raise ToolError("Session has not started.")
        if self._process.returncode is not None:
            return CLIResult(
                system="tool must be restarted",
                error=f"bash has exited with returncode {self._process.returncode}",
            )
        if self._timed_out:
            raise ToolError(
                f"超时：bash在 {self._timeout} 秒内未返回，必须重启",
            )

        # 确认标准输入、输出和错误不是None，因为我们用PIPE创建了进程
        assert self._process.stdin
        assert self._process.stdout
        assert self._process.stderr

        # 向进程发送命令，并添加结束标记
        self._process.stdin.write(
            command.encode() + f"; echo '{self._sentinel}'\n".encode()
        )
        await self._process.stdin.drain()  # 等待数据写入完成

        # 读取进程输出，直到找到结束标记
        try:
            async with asyncio.timeout(self._timeout):
                while True:
                    await asyncio.sleep(self._output_delay)  # 等待一段时间
                    # 直接从stdout/stderr读取会永远等待EOF，使用StreamReader缓冲区直接读取
                    output = (
                        self._process.stdout._buffer.decode()
                    )  # 忽略属性访问警告
                    if self._sentinel in output:
                        # 找到结束标记，截断并退出循环
                        output = output[: output.index(self._sentinel)]
                        break
        except asyncio.TimeoutError:
            self._timed_out = True
            raise ToolError(
                f"超时：bash在 {self._timeout} 秒内未返回，必须重启",
            ) from None

        # 处理输出和错误信息
        if output.endswith("\n"):
            output = output[:-1]

        error = (
            self._process.stderr._buffer.decode()
        )  # 忽略属性访问警告
        if error.endswith("\n"):
            error = error[:-1]

        # 清空缓冲区，以便下次读取
        self._process.stdout._buffer.clear()  # 忽略属性访问警告
        self._process.stderr._buffer.clear()  # 忽略属性访问警告

        return CLIResult(output=output, error=error)  # 返回命令执行结果


class Bash(BaseTool):
    """用于执行bash命令的工具类。"""

    name: str = "bash"  # 工具名称
    description: str = _BASH_DESCRIPTION  # 工具描述
    parameters: dict = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The bash command to execute. Can be empty to view additional logs when previous exit code is `-1`. Can be `ctrl+c` to interrupt the currently running process.",
            },
        },
        "required": ["command"],  # 必需参数
    }

    _session: Optional[_BashSession] = None  # bash会话对象

    async def execute(
        self, command: str | None = None, restart: bool = False, **kwargs
    ) -> CLIResult:
        if restart:
            if self._session:
                self._session.stop()  # 如果会话存在，则停止
            self._session = _BashSession()  # 创建新的会话
            await self._session.start()  # 启动会话

            return CLIResult(system="工具已重启。")

        if self._session is None:
            self._session = _BashSession()  # 如果会话不存在，则创建
            await self._session.start()  # 启动会话

        if command is not None:
            return await self._session.run(command)  # 执行命令

        raise ToolError("未提供命令。")  # 如果没有命令，则抛出异常


if __name__ == "__main__":
    bash = Bash()  # 创建Bash工具实例
    rst = asyncio.run(bash.execute("ls -l"))  # 执行ls -l命令
    print(rst)  # 打印执行结果
