from googlesearch import search

from app.logger import logger  # 导入日志记录器
from app.tool.search.base import WebSearchEngine


class GoogleSearchEngine(WebSearchEngine):
    def perform_search(self, query, num_results=10, *args, **kwargs):
        """Google search engine."""
        return search(query, num_results=num_results)
