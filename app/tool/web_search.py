import asyncio  # 导入异步I/O库
from typing import List  # 导入类型提示中的列表类型

from tenacity import retry, stop_after_attempt, wait_exponential  # 导入重试装饰器及其参数

from app.logger import logger  # 导入日志记录器
from app.config import config  # 导入配置模块
from app.tool.base import BaseTool  # 导入基础工具类
from app.tool.search import (
    BaiduSearchEngine,
    BingSearchEngine,
    DuckDuckGoSearchEngine,
    GoogleSearchEngine,
    WebSearchEngine,
)  # 导入各种搜索引擎类


class WebSearch(BaseTool):
    name: str = "web_search"
    description: str = """Perform a web search and return a list of relevant links.
    This function attempts to use the primary search engine API to get up-to-date results.
    If an error occurs, it falls back to an alternative search engine."""
    parameters: dict = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "(required) The search query to submit to the search engine.",
            },
            "num_results": {
                "type": "integer",
                "description": "(optional) The number of search results to return. Default is 10.",
                "default": 10,
            },
        },
        "required": ["query"],
    }
    _search_engine: dict[str, WebSearchEngine] = {
        "google": GoogleSearchEngine(),
        "baidu": BaiduSearchEngine(),
        "duckduckgo": DuckDuckGoSearchEngine(),
        "bing": BingSearchEngine(),
    }  # 定义搜索引擎字典

    async def execute(self, query: str, num_results: int = 10) -> List[str]:
        """
        执行网络搜索并返回URL列表。

        参数:
            query (str): 提交给搜索引擎的搜索查询。
            num_results (int, 可选): 要返回的搜索结果数量。默认为10。

        返回:
            List[str]: 匹配搜索查询的URL列表。
        """
        engine_order = self._get_engine_order()  # 获取搜索引擎尝试顺序
        for engine_name in engine_order:
            engine = self._search_engine[engine_name]  # 获取当前搜索引擎实例
            try:
                links = await self._perform_search_with_engine(
                    engine, query, num_results
                )  # 使用当前搜索引擎执行搜索
                if links:
                    return links  # 如果获取到链接，则返回
            except Exception as e:
                print(f"搜索引擎 '{engine_name}' 失败，错误: {e}")  # 打印错误信息
        return []  # 如果所有搜索引擎都失败，则返回空列表

    def _get_engine_order(self) -> List[str]:
        """
        确定尝试搜索引擎的顺序。
        首选引擎优先（基于配置），然后是其余引擎。

        返回:
            List[str]: 搜索引擎名称的有序列表。
        """
        preferred = "google"  # 默认首选搜索引擎
        if config.search_config and config.search_config.engine:
            preferred = config.search_config.engine.lower()  # 根据配置设置首选引擎

        engine_order = []  # 初始化搜索引擎顺序列表
        if preferred in self._search_engine:
            engine_order.append(preferred)  # 添加首选引擎到列表
        for key in self._search_engine:
            if key not in engine_order:
                engine_order.append(key)  # 添加其余引擎到列表
        return engine_order  # 返回搜索引擎顺序列表

    @retry(
        stop=stop_after_attempt(3),  # 重试停止条件：最多尝试3次
        wait=wait_exponential(multiplier=1, min=1, max=10),  # 重试等待时间：指数增长，最小1秒，最大10秒
    )
    async def _perform_search_with_engine(
        self,
        engine: WebSearchEngine,
        query: str,
        num_results: int,
    ) -> List[str]:
        loop = asyncio.get_event_loop()  # 获取事件循环
        # 在执行器中运行搜索引擎的搜索功能，并返回结果列表
        return await loop.run_in_executor(
            None, lambda: list(engine.perform_search(query, num_results=num_results))
        )
