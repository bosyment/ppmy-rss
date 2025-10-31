# -*- coding: utf-8 -*-
import requests, time, re, json, os
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urljoin

HERE = os.path.abspath(os.path.dirname(__file__))
CFG = json.load(open(os.path.join(HERE, "config.json"), "r", encoding="utf-8"))

session = requests.Session()
session.headers.update({"User-Agent": CFG.get("user_agent")})

def fetch(url, allow_404=False):
    try:
        r = session.get(url, timeout=15)
        r.encoding = r.apparent_encoding or 'utf-8'
        if r.status_code == 403:
            print("[WARN] 403 for", url)
            return None
        if r.status_code == 404 and not allow_404:
            return None
        if r.status_code >= 400:
            print("[WARN] status", r.status_code, "for", url)
            return None
        return r.text
    except Exception as e:
        print("fetch error", e, "->", url)
        return None

def extract_links_from_html(html):
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    anchors = soup.find_all("a", href=True)
    links = []
    for a in anchors:
        href = a['href']
        # 只取 /news/{数字}.html 类型
        if re.search(r'/news/\d+\.html', href):
            links.append(href)
    return list(dict.fromkeys(links))  # 去重并保留顺序

def parse_article(url):
    html = fetch(url)
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    # 尝试抓标题
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    h1 = soup.find(["h1","h2"])
    if h1 and not title:
        title = h1.text.strip()
    # 描述：优先 meta description，再取正文前几段
    desc = ""
    meta = soup.find("meta", attrs={"name":"description"}) or soup.find("meta", attrs={"property":"og:description"})
    if meta and meta.get("content"):
        desc = meta["content"].strip()
    else:
        # 尝试抽取正文中第一段
        article = soup.find("div", class_=re.compile(r'article|content|news', re.I)) or soup
        p = article.find("p")
        if p:
            desc = p.get_text().strip()[:400]
    # pubDate 尝试从页面中提取日期
    pubDate = None
    time_texts = soup.find_all(text=re.compile(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}'))
    if time_texts:
        pubDate = time_texts[0].strip()
    # 转成 RFC 822 格式（若无法解析，使用现在时间）
    try:
        if pubDate:
            dt = datetime.strptime(re.sub(r'[年月日]','-', pubDate.split()[0]).strip(), "%Y-%m-%d")
        else:
            dt = datetime.utcnow()
    except Exception:
        dt = datetime.utcnow()
    rfc822 = dt.strftime("%a, %d %b %Y %H:%M:%S GMT")
    return {"title": title or url, "link": url, "description": desc, "pubDate": rfc822}

def build_rss(items, title="PPMY 新闻订阅", link=CFG.get("base_url")):
    now = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")
    rss = '<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0">\n<channel>\n'
    rss += f"<title>{title}</title>\n<link>{link}</link>\n<description>自动生成的 PPMY 新闻订阅</description>\n<lastBuildDate>{now}</lastBuildDate>\n"
    for it in items:
        rss += "<item>\n"
        rss += f"<title>{escape_xml(it['title'])}</title>\n"
        rss += f"<link>{it['link']}</link>\n"
        rss += "<description><![CDATA[" + (it['description'] or '') + "]]></description>\n"
        rss += f"<pubDate>{it['pubDate']}</pubDate>\n"
        rss += "</item>\n"
    rss += "</channel>\n</rss>\n"
    return rss

def escape_xml(s):
    return (s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;") if s else s)

def find_articles_via_list():
    base = CFG["base_url"]
    links = []
    for p in CFG.get("list_pages", []):
        full = urljoin(base, p)
        print("尝试抓取列表页：", full)
        html = fetch(full)
        if not html:
            print("列表页不可用：", full)
            continue
        found = extract_links_from_html(html)
        for f in found:
            links.append(urljoin(base, f))
        time.sleep(CFG.get("delay_seconds", 1))
    return list(dict.fromkeys(links))

def scan_by_number():
    base = CFG["base_url"]
    pattern = CFG["article_path_pattern"]
    start = CFG.get("scan_start", 2000000)
    window = CFG.get("scan_window", 500)
    max_fail = CFG.get("max_consecutive_failures", 30)
    discovered = []
    consecutive_fail = 0
    # 从 start 向下扫描
    i = start
    tried = 0
    while tried < window and consecutive_fail < max_fail:
        url = urljoin(base, pattern.format(id=i))
        html = fetch(url, allow_404=True)
        tried += 1
        if html:
            discovered.append(url)
            consecutive_fail = 0
            print("发现文章：", url)
        else:
            consecutive_fail += 1
        i -= 1
        time.sleep(CFG.get("delay_seconds", 1))
    return list(dict.fromkeys(discovered))

def dedupe_preserve_order(seq):
    seen=set(); out=[]
    for x in seq:
        if x not in seen:
            out.append(x); seen.add(x)
    return out

def main():
    mode = CFG.get("scan_mode","hybrid")
    found_links = []
    if mode in ("list","hybrid"):
        found_links += find_articles_via_list()
    if mode in ("scan","hybrid"):
        # 若 list 没抓到或 hybrid 都尝试扫描
        found_links += scan_by_number()
    found_links = dedupe_preserve_order(found_links)
    print("总共发现文章数：", len(found_links))
    # 限制 items 数量与顺序（最新优先：按 URL 中数字降序）
    def get_id(u):
        m = re.search(r'/news/(\d+)\.html', u)
        return int(m.group(1)) if m else 0
    found_links.sort(key=lambda x: get_id(x), reverse=True)
    found_links = found_links[:CFG.get("max_items",50)]
    items = []
    for link in found_links:
        print("解析：", link)
        art = parse_article(link)
        if art:
            items.append(art)
        time.sleep(CFG.get("delay_seconds", 1))
    rss_text = build_rss(items)
    outpath = os.path.join(HERE, "docs", "ppmy_rss.xml")
    with open(outpath, "w", encoding="utf-8") as f:
        f.write(rss_text)
    print("生成 RSS 到：", outpath)

if __name__ == "__main__":
    main()
