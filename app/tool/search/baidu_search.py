from baidusearch.baidusearch import search

from app.logger import logger  # 导入日志记录器
from app.tool.search.base import WebSearchEngine


class BaiduSearchEngine(WebSearchEngine):
    def perform_search(self, query, num_results=10, *args, **kwargs):
        """Baidu search engine."""
        return search(query, num_results=num_results)
