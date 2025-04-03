from duckduckgo_search import DDGS

from app.logger import logger  # 导入日志记录器
from app.tool.search.base import WebSearchEngine


class DuckDuckGoSearchEngine(WebSearchEngine):
    async def perform_search(self, query, num_results=10, *args, **kwargs):
        """DuckDuckGo search engine."""
        return DDGS.text(query, num_results=num_results)
