# crawler.py
# 增量抓取 PPMY 新闻 -> 生成 ppmy_rss.xml
# 要求: 安装 requests beautifulsoup4 feedgen

import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator
import datetime
from datetime import datetime, timezone
import time
import random
import os

# -------- 配置 --------
BASE_URL = "https://www.ppmy.cn/news/"
ARTICLE_URL_TEMPLATE = BASE_URL + "{}.html"

RSS_FILE = "ppmy_rss.xml"
LAST_ID_FILE = "last_id.txt"

# 当 last_id.txt 不存在时，从哪个编号开始抓取（你要求的起始编号）
DEFAULT_START_ID = 1540000

# 每次运行最多尝试抓取多少个连续编号（若站点每天仅 +1，设置为 50 足够）
MAX_TRY = 50

# 请求头（可按需扩展）
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 ppmy-rss-bot/1.0",
    "Referer": "https://www.ppmy.cn/",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
}

# 最大重试次数（遇到 503/429 等短暂错误时）
RETRY_TIMES = 2
RETRY_DELAY_SECONDS = 2

# 随机延时范围（秒）
DELAY_MIN = 1.0
DELAY_MAX = 3.0
# -----------------------

def read_last_id():
    if os.path.exists(LAST_ID_FILE):
        try:
            with open(LAST_ID_FILE, "r", encoding="utf-8") as f:
                val = f.read().strip()
                return int(val) if val else DEFAULT_START_ID
        except Exception:
            return DEFAULT_START_ID
    return DEFAULT_START_ID

def update_last_id(last_id):
    with open(LAST_ID_FILE, "w", encoding="utf-8") as f:
        f.write(str(last_id))

def safe_get(session, url):
    """带简单重试的 GET"""
    for attempt in range(1, RETRY_TIMES + 1):
        try:
            r = session.get(url, headers=HEADERS, timeout=12)
            return r
        except Exception as e:
            if attempt < RETRY_TIMES:
                time.sleep(RETRY_DELAY_SECONDS)
            else:
                print(f"[ERROR] 请求失败: {url} -> {e}")
                return None

def fetch_article(article_id, session):
    url = ARTICLE_URL_TEMPLATE.format(article_id)
    r = safe_get(session, url)
    if r is None:
        return None
    # 非 200 则视为不存在或被阻断
    if r.status_code != 200:
        # 打印一些调试信息
        print(f"[INFO] {url} 返回状态: {r.status_code}")
        return None

    # 有时页面会返回一个反爬页面，简单判断页面长度或是否包含关键字
    if len(r.text) < 200 or "访问受限" in r.text or "403" in r.text:
        print(f"[WARN] 可能为防护页或空页面: {url} (len={len(r.text)})")
        return None

    soup = BeautifulSoup(r.text, "html.parser")

    # 尝试提取标题，优先使用 <meta property="og:title"> 或 <title>
    title = None
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = og_title["content"].strip()
    if not title:
        ttag = soup.find("title")
        title = ttag.get_text(strip=True) if ttag else f"文章 {article_id}"

    # 尝试提取发布日期（多种常见位置）
    pub_dt = None
    # 常见：meta property article:published_time
    meta_time = soup.find("meta", property="article:published_time")
    if meta_time and meta_time.get("content"):
        try:
            pub_dt = datetime.fromisoformat(meta_time["content"].strip())
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
        except Exception:
            pub_dt = None

    if not pub_dt:
        # 搜索文本中的日期格式 yyyy-mm-dd 或 yyyy年mm月dd日
        txt = soup.get_text()
        import re
        m = re.search(r'(\d{4}[-/]\d{1,2}[-/]\d{1,2})', txt)
        if m:
            try:
                pub_dt = datetime.fromisoformat(m.group(1))
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
            except Exception:
                pub_dt = None

    # 正文提取，尝试几种常见容器
    content = ""
    # 优先尝试一些常见 class/id，按需要可扩展
    selectors = [
        ("div", {"class": "article-content"}),
        ("div", {"id": "content"}),
        ("div", {"class": "content"}),
        ("div", {"class": "news-content"}),
        ("article", {}),
    ]
    for tag, attrs in selectors:
        el = soup.find(tag, attrs=attrs)
        if el and el.get_text(strip=True):
            content = el.get_text(separator="\n", strip=True)
            break
    if not content:
        # 回退为取页面前面的一段文本
        p = soup.find("p")
        content = p.get_text(strip=True) if p else ""

    # 返回结构
    return {
        "id": article_id,
        "title": title,
        "link": url,
        "content": content,
        "pub_dt": pub_dt  # 可能为 None
    }

def build_rss(all_items):
    fg = FeedGenerator()
    fg.title("PPMY 新闻订阅")
    fg.link(href=BASE_URL)
    fg.description("自动抓取 https://www.ppmy.cn/news/ 的最新文章")
    fg.language("zh-cn")

    # 使用带时区的 now 作为 lastBuildDate
    now_tz = datetime.now(timezone.utc)
    fg.lastBuildDate(now_tz)

    # 添加条目（保持逆序：最新的先）
    for item in sorted(all_items, key=lambda x: x["id"], reverse=True):
        fe = fg.add_entry()
        fe.id(item["link"])        # 使用文章链接作 guid（唯一）
        fe.title(item["title"])
        fe.link(href=item["link"])
        # description 不能为 None
        fe.description(item["content"] or "")
        # pubDate 优先用解析到的真实发布时间，否则用抓取时间
        dt = item.get("pub_dt") or now_tz
        # feedgen 要求带时区
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        fe.pubDate(dt)

    # 输出 RSS 文件
    fg.rss_file(RSS_FILE)
    print(f"[OK] 已生成 RSS: {RSS_FILE}")

def main():
    last_id = read_last_id()
    print(f"[INFO] 上次抓取文章编号: {last_id}")

    session = requests.Session()
    discovered = []

    # 从 last_id+1 开始增量尝试连续编号，若遇到首个缺失编号则停止（假设编号连续）
    for i in range(last_id + 1, last_id + 1 + MAX_TRY):
        print(f"[TRY] 抓取文章 {i} ...")
        art = fetch_article(i, session)
        if not art:
            print(f"[STOP] 文章 {i} 不存在或不可访问，停止增量抓取")
            break
        discovered.append(art)
        # 延时
        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

    if not discovered:
        print("[INFO] 没有抓到新文章，退出")
        return

    # 更新 last_id 至最新抓到的最大编号
    new_last = max(a["id"] for a in discovered)
    update_last_id(new_last)
    print(f"[INFO] 更新 last_id 为 {new_last}")

    # 如果你想保留历史文章在 RSS 中，需要把之前的历史条目读入并合并
    # 这里我们只把本次抓到的文章写入 RSS（可按需改为合并历史）
    build_rss(discovered)

if __name__ == "__main__":
    main()
