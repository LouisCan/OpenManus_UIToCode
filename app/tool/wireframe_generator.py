import base64
import io
import json
from typing import Dict, Optional, Union
import os
import requests
import toml

from PIL import Image

from app.tool.base import BaseTool, ToolResult  # 从基础工具类导入
from app.logger import logger  # 导入日志记录器
from app.config import config  # 导入配置模块


class WireframeGenerator(BaseTool):
    """一个用于分析UI图像并生成线框原型设计描述的工具。"""

    name: str = "wireframe_generator"
    description: str = "Analyzes UI images and generates wireframe prototype descriptions. Can create low or medium fidelity wireframe descriptions with detailed component analysis."
    parameters: dict = {
        "type": "object",
        "properties": {
            "image_path": {
                "type": "string",
                "description": "Path to the UI image file to analyze. Can be absolute or relative to workspace.",
            },
            "base64_image": {
                "type": "string",
                "description": "Base64 encoded image data (alternative to image_path).",
            },
            "fidelity": {
                "type": "string",
                "enum": ["low", "medium"],
                "description": "Fidelity level of the wireframe description. 'low' for simple outlines, 'medium' for more detailed components.",
                "default": "medium",
            },
        },
        "required": [],
    }

    # 配置参数
    _config = None

    def _load_config(self):
        """从config.toml加载配置"""
        try:
            # 获取配置文件路径
            config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config", "config.toml")
            if not os.path.exists(config_path):
                logger.error(f"配置文件不存在: {config_path}")
                raise FileNotFoundError(f"配置文件不存在: {config_path}")

            # 读取配置文件
            self._config = toml.load(config_path)

            # 检查必要的配置项
            if "llm" not in self._config or "vl" not in self._config["llm"]:
                logger.error("配置文件中缺少[llm.vl]部分")
                raise ValueError("配置文件中缺少[llm.vl]部分")

            logger.info("成功加载配置文件")
        except Exception as e:
            logger.error(f"加载配置文件失败: {str(e)}")
            raise

    def _get_image(self, image_path: Optional[str] = None, base64_image: Optional[str] = None) -> str:
        """从路径或Base64数据获取图像，并返回base64编码的图像。"""
        if base64_image:
            # 如果已经是Base64字符串，直接返回
            return base64_image

        elif image_path:
            # 处理相对路径和绝对路径
            if os.path.isabs(image_path):
                full_path = image_path
            else:
                # 相对于工作区的路径
                full_path = os.path.join(config.workspace_root, image_path)

            if not os.path.exists(full_path):
                raise ValueError(f"图像文件不存在: {full_path}")

            try:
                # 读取图像文件并转换为base64
                with open(full_path, "rb") as img_file:
                    return base64.b64encode(img_file.read()).decode('utf-8')
            except Exception as e:
                raise ValueError(f"无法打开图像文件: {str(e)}")
        else:
            raise ValueError("必须提供image_path或base64_image参数")

    async def _analyze_image_with_qwen(self, image_base64: str, fidelity: str = "medium") -> str:
        """使用在线Qwen-VL模型分析图像并生成原型描述。"""
        if not self._config:
            self._load_config()

        # 从配置中获取API信息
        vision_config = self._config["llm"]["vl"]
        model = vision_config.get("model", "qwen-vl-max")
        api_key = vision_config.get("api_key")
        base_url = vision_config.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        max_tokens = vision_config.get("max_tokens", 2048)
        temperature = vision_config.get("temperature", 0.0)

        # 检查必要的参数
        if not api_key:
            raise ValueError("配置中缺少API密钥")

        # 构建API请求URL
        url = f"{base_url.rstrip('/')}/chat/completions"

        # 构建更加详细的提示词
        if fidelity == "low":
            prompt = """请详细分析这个UI界面，并将其描述为一个低保真线框图。你的描述必须具体明确，不要使用含糊的表述。

请遵循以下要求：
1. 清晰描述所有UI组件的位置，例如"顶部导航栏"、"左侧边栏"、"右下角"等具体位置
2. 提供组件的相对尺寸，例如"占页面宽度的80%"、"约占屏幕高度的1/3"等
3. 对于文本框、输入框、按钮等组件，详细说明它们的位置和大小
4. 不要省略图片中的任何文字内容，完整转录所有可见文本
5. 按照从上到下、从左到右的顺序描述界面

最终输出应包含足够详细的信息，使设计师能够根据你的描述精确地重建此UI界面。"""
        else:  # medium
            prompt = """请详细分析这个UI界面，并将其描述为一个中保真线框图。你的描述必须具体明确，不要使用含糊的表述。

请遵循以下要求：
1. 清晰描述所有UI组件的精确位置，例如"距顶部20%处的导航栏"、"左侧边栏占页面宽度的15%"等
2. 提供所有组件的详细尺寸信息，包括相对宽度和高度(如"占页面宽度的30%"、"按钮高度约为文本框高度的一半")
3. 对于文本框、输入框、按钮、下拉菜单等交互元素，精确描述它们的位置、大小和外观
4. 详细描述色彩方案、字体大小的相对关系、间距和对齐方式
5. 完整转录界面中的所有文字内容，一个不漏
6. 按照从上到下、从左到右的顺序描述界面，详细说明各组件间的相互关系和布局层次

最终输出应当详细到足以让开发人员直接按照描述实现界面，无需再查看原图像。"""

        # 准备API请求数据
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}"
                            }
                        }
                    ]
                }
            ],
            "max_tokens": max_tokens,
            "temperature": temperature
        }

        try:
            # 发送API请求
            logger.info(f"使用{model}模型分析UI图像...")
            response = requests.post(url, headers=headers, json=payload, timeout=600)

            # 解析响应
            if response.status_code != 200:
                logger.error(f"API请求失败: {response.status_code}, {response.text}")
                raise ValueError(f"API请求失败: {response.status_code}, {response.text}")

            result = response.json()

            # 提取模型生成的文本
            wireframe_description = result.get("choices", [{}])[0].get("message", {}).get("content", "")

            if not wireframe_description:
                logger.error(f"无法从API响应中提取描述: {result}")
                raise ValueError("无法从API响应中提取描述")

            return wireframe_description

        except Exception as e:
            logger.error(f"调用Qwen-VL模型失败: {str(e)}")
            raise RuntimeError(f"调用Qwen-VL模型失败: {str(e)}")

    def _save_description_to_file(self, description: str, image_path: Optional[str] = None) -> str:
        """将线框图描述保存到本地文件"""
        try:
            # 确定输出目录
            output_dir = os.path.join(config.workspace_root, "wireframe_descriptions")
            os.makedirs(output_dir, exist_ok=True)

            # 生成文件名
            if image_path:
                # 使用图像文件名作为基础
                base_name = os.path.splitext(os.path.basename(image_path))[0]
                import time
                timestamp = int(time.time())
                file_name = f"{base_name}_wireframe_description_{timestamp}.md"
            else:
                # 使用时间戳生成文件名
                import time
                timestamp = int(time.time())
                file_name = f"wireframe_description_{timestamp}.md"

            # 完整的文件路径
            file_path = os.path.join(output_dir, file_name)

            # 写入文件
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(description)

            logger.info(f"线框图描述已保存到: {file_path}")
            return file_path

        except Exception as e:
            logger.error(f"保存线框图描述到文件失败: {str(e)}")
            raise RuntimeError(f"保存线框图描述到文件失败: {str(e)}")

    async def execute(
        self,
        image_path: Optional[str] = None,
        base64_image: Optional[str] = None,
        fidelity: str = "medium",
    ) -> Union[Dict, ToolResult]:
        """
        执行原型图生成，分析UI图像并生成线框描述。

        参数:
            image_path (str, optional): 图像文件的路径，可以是绝对路径或相对于工作区的路径。
            base64_image (str, optional): Base64编码的图像数据，作为image_path的替代选项。
            fidelity (str): 线框图的保真度，可以是"low"或"medium"。默认为"medium"。

        返回:
            ToolResult: 包含线框图描述的结果对象。
        """
        try:
            # 验证参数
            if not image_path and not base64_image:
                return ToolResult(
                    error="必须提供image_path或base64_image参数",
                    success=False,
                )

            # 验证保真度参数
            if fidelity not in ["low", "medium"]:
                return ToolResult(
                    error="fidelity参数必须是'low'或'medium'",
                    success=False,
                )

            # 获取图像的base64编码
            image_base64 = self._get_image(image_path, base64_image)

            # 加载配置（如果尚未加载）
            if not self._config:
                self._load_config()

            # 使用Qwen-VL模型分析图像生成原型描述
            wireframe_description = await self._analyze_image_with_qwen(image_base64, fidelity)

            # 保存描述到文件
            file_path = self._save_description_to_file(wireframe_description, image_path)

            # 返回结果
            return ToolResult(
                output=f"{wireframe_description}\n\n描述已保存到: {file_path}",
                success=True,
            )

        except Exception as e:
            logger.error(f"线框图生成失败: {str(e)}")
            return ToolResult(
                error=f"线框图生成失败: {str(e)}",
                success=False,
            )
