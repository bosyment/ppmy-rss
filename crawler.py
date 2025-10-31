#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from zoneinfo import ZoneInfo
from feedgen.feed import FeedGenerator

# ------------------------------
# 配置区域
# ------------------------------
BASE_URL = "https://www.ppmy.cn/news"
MAX_TRY = 300           # 每次抓取最多尝试多少个编号
LAST_ID_FILE = "last_id.json"
DOCS_DIR = "docs"
RSS_FILE = "ppmy_rss.xml"
USE_BEIJING_TIME = False   # True 写北京时间 pubDate，False 用 UTC

# ------------------------------
# 工具函数
# ------------------------------
def read_last_id():
    if os.path.exists(LAST_ID_FILE):
        with open(LAST_ID_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("last_id", 1540000)
    return 1540000  # 默认起始编号

def write_last_id(last_id):
    with open(LAST_ID_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_id": last_id}, f)

def fetch_article(article_id):
    url = f"{BASE_URL}/{article_id}.html"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200 or len(r.text) < 1000:
            print(f"[WARN] 可能为防护页或空页面: {url} (len={len(r.text)})")
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        # 这里根据页面实际结构解析标题和内容
        title_tag = soup.select_one("h1") or soup.title
        content_tag = soup.select_one(".article-content") or soup.select_one("body")
        if not title_tag or not content_tag:
            return None
        title = title_tag.get_text(strip=True)
        content = content_tag.get_text(strip=True)
        return {"id": article_id, "title": title, "content": content, "link": url}
    except Exception as e:
        print(f"[ERROR] 抓取文章 {article_id} 出错: {e}")
        return None

# ------------------------------
# 主逻辑
# ------------------------------
def main():
    # 确保 docs 文件夹存在
    os.makedirs(DOCS_DIR, exist_ok=True)
    rss_path = os.path.join(DOCS_DIR, RSS_FILE)

    last_id = read_last_id()
    print(f"[INFO] 上次抓取文章编号: {last_id}")

    fg = FeedGenerator()
    fg.title("PPMY RSS")
    fg.link(href="https://www.ppmy.cn/news")
    fg.description("PPMY 网站文章 RSS")
    fg.language("zh-cn")
    # lastBuildDate 使用 UTC
    fg.lastBuildDate(datetime.now(tz=ZoneInfo("UTC")))

    new_last_id = last_id
    count = 0

    for i in range(last_id + 1, last_id + 1 + MAX_TRY):
        print(f"[TRY] 抓取文章 {i} ...")
        article = fetch_article(i)
        if article:
            fe = fg.add_entry()
            fe.title(article["title"])
            fe.link(href=article["link"])
            fe.description(article["content"])
            if USE_BEIJING_TIME:
                fe.pubDate(datetime.now(tz=ZoneInfo("Asia/Shanghai")))
            else:
                fe.pubDate(datetime.now(tz=ZoneInfo("UTC")))
            new_last_id = i
            count += 1

    if count == 0:
        print("[INFO] 本次没有抓到新文章")
    else:
        rss_text = fg.rss_str(pretty=True)
        with open(rss_path, "w", encoding="utf-8") as f:
            f.write(rss_text)
        print("[INFO] 生成 RSS 到：", rss_path)
        write_last_id(new_last_id)
        print(f"[INFO] 更新 last_id 为 {new_last_id}")

if __name__ == "__main__":
    main()
