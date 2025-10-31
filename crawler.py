import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator
import datetime
import time
import random
import os

BASE_URL = "https://www.ppmy.cn/news/"
ARTICLE_URL_TEMPLATE = BASE_URL + "{}.html"
RSS_FILE = "ppmy_rss.xml"
LAST_ID_FILE = "last_id.txt"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}
MAX_TRY = 20  # 每次最多尝试抓取文章数

def read_last_id():
    if os.path.exists(LAST_ID_FILE):
        with open(LAST_ID_FILE, "r") as f:
            try:
                return int(f.read().strip())
            except:
                return 0
    return 0

def update_last_id(last_id):
    with open(LAST_ID_FILE, "w") as f:
        f.write(str(last_id))

def fetch_article(article_id, session):
    url = ARTICLE_URL_TEMPLATE.format(article_id)
    try:
        resp = session.get(url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")

        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else f"文章 {article_id}"

        content_tag = soup.find("div", class_="article-content")
        if not content_tag:
            content_tag = soup.find("div", id="content")
        content = content_tag.get_text(strip=True) if content_tag else ""

        return {"id": article_id, "title": title, "link": url, "content": content}

    except Exception as e:
        print(f"抓取文章 {article_id} 出错: {e}")
        return None

def main():
    last_id = read_last_id()
    print(f"上次抓取文章编号: {last_id}")

    session = requests.Session()
    articles = []

    for i in range(last_id + 1, last_id + 1 + MAX_TRY):
        print(f"尝试抓取文章 {i} ...")
        art = fetch_article(i, session)
        if not art:
            print(f"文章 {i} 不存在或无法访问，停止抓取")
            break
        articles.append(art)
        time.sleep(random.uniform(1, 3))

    if not articles:
        print("没有新文章可抓取")
        return

    new_last_id = max(art["id"] for art in articles)
    update_last_id(new_last_id)
    print(f"更新 last_id 为 {new_last_id}")

    fg = FeedGenerator()
    fg.title("PPMY 新闻订阅")
    fg.link(href=BASE_URL)
    fg.description("自动抓取 https://www.ppmy.cn/news/ 最新文章")
    fg.language("zh-cn")
    fg.lastBuildDate(datetime.datetime.utcnow())

    for art in articles:
        fe = fg.add_entry()
        fe.id(str(art["id"]))
        fe.title(art["title"])
        fe.link(href=art["link"])
        fe.description(art["content"])
        fe.pubDate(datetime.datetime.utcnow())

    fg.rss_file(RSS_FILE)
    print(f"已抓取 {len(articles)} 篇新文章，生成 {RSS_FILE}")

if __name__ == "__main__":
    main()
