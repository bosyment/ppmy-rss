# crawler.py
import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator
from datetime import datetime, timezone
import time, random, os, re

BASE_URL = "https://www.ppmy.cn/news/"
ARTICLE_URL_TEMPLATE = BASE_URL + "{}.html"

RSS_FILE = "ppmy_rss.xml"
LAST_ID_FILE = "last_id.txt"
DEFAULT_START_ID = 1540000
MAX_TRY = 200          # 每次最多尝试多少编号
MAX_CONSECUTIVE_FAIL = 5  # 连续失败几次后停止（跳过被删文章）

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/140.0.0.0 Safari/537.36 ppmy-rss-bot/2.0",
    "Referer": "https://www.ppmy.cn/",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
}

DELAY_MIN, DELAY_MAX = 1.0, 3.0

def read_last_id():
    if os.path.exists(LAST_ID_FILE):
        try:
            with open(LAST_ID_FILE, "r", encoding="utf-8") as f:
                return int(f.read().strip() or DEFAULT_START_ID)
        except:
            return DEFAULT_START_ID
    return DEFAULT_START_ID

def update_last_id(last_id):
    with open(LAST_ID_FILE, "w", encoding="utf-8") as f:
        f.write(str(last_id))

def fetch_article(article_id, session):
    url = ARTICLE_URL_TEMPLATE.format(article_id)
    try:
        r = session.get(url, headers=HEADERS, timeout=12)
    except Exception as e:
        print(f"[ERROR] 请求 {url} 失败: {e}")
        return None

    if r.status_code != 200:
        print(f"[INFO] {url} 返回状态 {r.status_code}")
        return None
    if len(r.text) < 500 or "访问受限" in r.text:
        print(f"[WARN] 防护页或空页面: {url} (len={len(r.text)})")
        return None

    soup = BeautifulSoup(r.text, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else f"文章 {article_id}"

    meta_time = soup.find("meta", property="article:published_time")
    pub_dt = None
    if meta_time and meta_time.get("content"):
        try:
            pub_dt = datetime.fromisoformat(meta_time["content"].strip())
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
        except:
            pass

    if not pub_dt:
        m = re.search(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})", soup.get_text())
        if m:
            try:
                pub_dt = datetime.fromisoformat(m.group(1))
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
            except:
                pass

    selectors = [
        ("div", {"class": "article-content"}),
        ("div", {"id": "content"}),
        ("div", {"class": "content"}),
        ("div", {"class": "news-content"}),
        ("article", {}),
    ]
    content = ""
    for tag, attrs in selectors:
        el = soup.find(tag, attrs=attrs)
        if el and el.get_text(strip=True):
            content = el.get_text(separator="\n", strip=True)
            break
    if not content:
        p = soup.find("p")
        content = p.get_text(strip=True) if p else ""

    return {
        "id": article_id,
        "title": title,
        "link": url,
        "content": content,
        "pub_dt": pub_dt or datetime.now(timezone.utc)
    }

def build_rss(items):
    fg = FeedGenerator()
    fg.title("PPMY 新闻订阅")
    fg.link(href=BASE_URL)
    fg.description("自动抓取 https://www.ppmy.cn/news/ 的最新文章")
    fg.language("zh-cn")
    fg.lastBuildDate(datetime.now(timezone.utc))

    for item in sorted(items, key=lambda x: x["id"], reverse=True):
        fe = fg.add_entry()
        fe.id(item["link"])
        fe.title(item["title"])
        fe.link(href=item["link"])
        fe.description(item["content"] or "")
        fe.pubDate(item["pub_dt"])

    fg.rss_file(RSS_FILE)
    print(f"[OK] 已生成 RSS: {RSS_FILE}")

def main():
    last_id = read_last_id()
    print(f"[INFO] 上次抓取文章编号: {last_id}")

    session = requests.Session()
    discovered = []
    consecutive_fail = 0

    for i in range(last_id + 1, last_id + 1 + MAX_TRY):
        print(f"[TRY] 抓取文章 {i} ...")
        art = fetch_article(i, session)
        if not art:
            consecutive_fail += 1
            print(f"[MISS] 文章 {i} 不存在 ({consecutive_fail}/{MAX_CONSECUTIVE_FAIL})")
            if consecutive_fail >= MAX_CONSECUTIVE_FAIL:
                print(f"[STOP] 连续 {MAX_CONSECUTIVE_FAIL} 篇不存在，停止抓取。")
                break
            continue
        discovered.append(art)
        consecutive_fail = 0
        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

    if not discovered:
        print("[INFO] 没有新文章")
        return

    new_last = max(a["id"] for a in discovered)
    update_last_id(new_last)
    print(f"[INFO] 更新 last_id 为 {new_last}")

    build_rss(discovered)

if __name__ == "__main__":
    main()
