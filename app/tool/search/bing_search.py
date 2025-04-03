from typing import List

import requests
from bs4 import BeautifulSoup

from app.logger import logger
from app.tool.search.base import WebSearchEngine

# 定义一个常量，表示摘要的最大长度
ABSTRACT_MAX_LENGTH = 300

# 定义一个用户代理列表，用于在HTTP请求中设置不同的User-Agent
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/68.0.3440.106 Safari/537.36",
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Ubuntu Chromium/49.0.2623.108 Chrome/49.0.2623.108 Safari/537.36",
    "Mozilla/5.0 (Windows; U; Windows NT 5.1; pt-BR) AppleWebKit/533.3 (KHTML, like Gecko) QtWeb Internet Browser/3.7 http://www.QtWeb.net",
    "Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/41.0.2228.0 Safari/537.36",
    "Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US) AppleWebKit/532.2 (KHTML, like Gecko) ChromePlus/4.0.222.3 Chrome/4.0.222.3 Safari/532.2",
    "Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US; rv:1.8.1.4pre) Gecko/20070404 K-Ninja/2.1.3",
    "Mozilla/5.0 (Future Star Technologies Corp.; Star-Blade OS; x86_64; U; en-US) iNet Browser 4.7",
    "Mozilla/5.0 (Windows; U; Windows NT 6.1; rv:2.2) Gecko/20110201",
    "Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US; rv:1.8.1.13) Gecko/20080414 Firefox/2.0.0.13 Pogo/2.0.0.13.6866",
]

# 定义一个字典，包含请求头信息
HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": USER_AGENTS[0],  # 设置默认的用户代理为列表中的第一个
    "Referer": "https://www.bing.com/",  # 设置Referer为Bing的主页
    "Accept-Encoding": "gzip, deflate",  # 接受gzip和deflate压缩
    "Accept-Language": "zh-CN,zh;q=0.9",  # 设置接受的语言为简体中文
}

# 定义Bing的主机URL和搜索URL的基地址
BING_HOST_URL = "https://www.bing.com"
BING_SEARCH_URL = "https://www.bing.com/search?q="

# 定义一个Bing搜索引擎类，继承自WebSearchEngine
class BingSearchEngine(WebSearchEngine):
    session: requests.Session = None  # 初始化一个requests.Session对象，用于发送HTTP请求

    def __init__(self, **data):
        """
        初始化Bing搜索工具，使用一个requests session。

        Args:
            **data: 可以包含任何初始化所需的参数。
        """
        super().__init__(**data)  # 调用父类的初始化方法
        self.session = requests.Session()  # 创建一个新的requests session
        self.session.headers.update(HEADERS)  # 更新session的headers

    def _search_sync(self, query: str, num_results: int = 10) -> List[str]:
        """
        同步实现Bing搜索，检索与查询匹配的URL列表。

        Args:
            query (str): 提交给Bing的搜索查询，不能为空。
            num_results (int, optional): 要返回的最大URL数量，默认为10。

        Returns:
            List[str]: 包含搜索结果的URL列表，最多返回`num_results`个。
                       如果查询为空或没有找到结果，则返回空列表。

        Notes:
            - 通过增加`first`参数并跟随`next_url`链接来处理分页。
            - 如果结果少于`num_results`，则返回所有找到的URL。
        """
        if not query:  # 如果查询为空，则返回空列表
            return []

        list_result = []  # 初始化结果列表
        first = 1  # 初始化页码
        next_url = BING_SEARCH_URL + query  # 构建第一页的搜索URL

        # 当结果数量少于num_results时，继续循环
        while len(list_result) < num_results:
            data, next_url = self._parse_html(  # 解析下一页的HTML
                next_url, rank_start=len(list_result), first=first
            )  # 传递当前页码和结果数量
            if data:  # 如果有数据
                list_result.extend([item["url"] for item in data])  # 将结果添加到结果列表
            if not next_url:  # 如果没有下一页
                break  # 结束循环
            first += 10  # 准备请求下一页

        return list_result[:num_results]  # 返回最多num_results个结果

    def _parse_html(self, url: str, rank_start: int = 0, first: int = 1) -> tuple:
        """
        同步解析Bing搜索结果的HTML，提取搜索结果和下一页的URL。

        Args:
            url (str): 要解析的Bing搜索结果页面的URL。
            rank_start (int, optional): 结果的起始排名，默认为0。
            first (int, optional): 可能的遗留参数，默认为1。

        Returns:
            tuple: 包含以下内容的元组：
                - list: 包含每个结果的'title', 'abstract', 'url', 和 'rank'的字典列表。
                - str 或 None: 下一页的URL，或者如果没有下一页则为None。
        """
        try:
            res = self.session.get(url=url)  # 发送GET请求
            res.encoding = "utf-8"  # 设置响应的编码为utf-8
            root = BeautifulSoup(res.text, "lxml")  # 使用BeautifulSoup解析HTML

            list_data = []  # 初始化结果列表
            ol_results = root.find("ol", id="b_results")  # 查找搜索结果的ol元素
            if not ol_results:  # 如果没有找到，则返回空列表和None
                return [], None

            for li in ol_results.find_all("li", class_="b_algo"):  # 查找所有class为b_algo的li元素
                title = ""  # 初始化标题
                url = ""  # 初始化URL
                abstract = ""  # 初始化摘要
                try:
                    h2 = li.find("h2")  # 查找h2元素
                    if h2:  # 如果有
                        title = h2.text.strip()  # 获取标题
                        url = h2.a["href"].strip()  # 获取链接

                    p = li.find("p")  # 查找p元素
                    if p:  # 如果有
                        abstract = p.text.strip()  # 获取摘要

                    if ABSTRACT_MAX_LENGTH and len(abstract) > ABSTRACT_MAX_LENGTH:  # 如果摘要超过最大长度
                        abstract = abstract[:ABSTRACT_MAX_LENGTH]  # 截断摘要

                    rank_start += 1  # 更新结果排名
                    list_data.append(  # 将结果添加到列表
                        {
                            "title": title,
                            "abstract": abstract,
                            "url": url,
                            "rank": rank_start,
                        }
                    )
                except Exception:
                    continue

            next_btn = root.find("a", title="Next page")
            if not next_btn:
                return list_data, None

            next_url = BING_HOST_URL + next_btn["href"]
            return list_data, next_url
        except Exception as e:
            logger.warning(f"Error parsing HTML: {e}")
            return [], None

    def perform_search(self, query, num_results=10, *args, **kwargs):
        """Bing search engine."""
        return self._search_sync(query, num_results=num_results)
