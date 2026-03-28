#!/usr/bin/env python3
"""
Global Finance News Terminal - News Fetcher
Refactored for GitHub Actions with RSS-only fetching and AI translation.

Usage:
    from news_fetcher import fetch_news_bundle

    data = fetch_news_bundle()  # uses LLM_API_KEY from env
    print(data["total"])
    print(data["items"][:3])
"""

import json
import os
import queue
import re
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False


BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

RSS_SOURCES = {
    "cnbc": {
        "name": "CNBC",
        "feeds": [
            "https://www.cnbc.com/id/100003114/device/rss/rss.html",
            "https://www.cnbc.com/id/10000664/device/rss/rss.html",
        ],
        "category": "财经",
        "color": "#ff9f40",
    },
    "cnn": {
        "name": "CNN",
        "feeds": [
            "http://rss.cnn.com/rss/edition_world.rss",
            "http://rss.cnn.com/rss/money_news_international.rss",
        ],
        "category": "综合",
        "color": "#ff5a5a",
    },
    "wsj": {
        "name": "WSJ",
        "feeds": [
            "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
            "https://feeds.a.dj.com/rss/RSSWorldNews.xml",
        ],
        "category": "财经",
        "color": "#c8a96e",
    },
    "ft": {
        "name": "FT",
        "feeds": [
            "https://www.ft.com/rss/home/uk",
        ],
        "category": "财经",
        "color": "#f0c058",
    },
    "bloomberg": {
        "name": "Bloomberg",
        "feeds": [
            "https://feeds.bloomberg.com/markets/news.rss",
            "https://feeds.bloomberg.com/politics/news.rss",
        ],
        "category": "财经",
        "color": "#7ab8ff",
    },
    "yahoo": {
        "name": "Yahoo Finance",
        "feeds": [
            "https://finance.yahoo.com/news/rssindex",
        ],
        "category": "财经",
        "color": "#9058f0",
    },
    "axios": {
        "name": "Axios",
        "feeds": [
            "https://api.axios.com/feed/",
        ],
        "category": "综合",
        "color": "#a07af0",
    },
    "scmp": {
        "name": "SCMP",
        "feeds": [
            "https://www.scmp.com/rss/91/feed",
            "https://www.scmp.com/rss/4/feed",
        ],
        "category": "亚太",
        "color": "#58c8f0",
    },
}

DEFAULT_LLM_PROVIDER = "deepseek"
DEFAULT_LLM_MODEL = "DeepSeek-V3.2 Thinking"
SUPPORTED_LLM_PROVIDERS = {"anthropic", "deepseek", "openai", "openai_compatible"}


def normalize_llm_config(api_key="", provider="", model="", base_url=""):
    provider = (provider or DEFAULT_LLM_PROVIDER).strip().lower()
    if provider not in SUPPORTED_LLM_PROVIDERS:
        provider = DEFAULT_LLM_PROVIDER

    model = (model or "").strip()
    if not model:
        model = DEFAULT_LLM_MODEL

    return {
        "api_key": (api_key or os.environ.get("LLM_API_KEY") or "").strip(),
        "provider": provider,
        "model": model,
        "base_url": (base_url or os.environ.get("LLM_BASE_URL") or "").strip(),
    }


def llm_ready(config):
    if not config:
        return False
    if not config.get("api_key") or not config.get("model"):
        return False
    if config.get("provider") == "openai_compatible" and not config.get("base_url"):
        return False
    return True


def extract_text_from_content(content):
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, dict):
        if isinstance(content.get("text"), str):
            return content["text"].strip()
        if "content" in content:
            return extract_text_from_content(content.get("content"))
        return ""

    if isinstance(content, list):
        parts = []
        for part in content:
            text = extract_text_from_content(part)
            if text:
                parts.append(text)
        return "".join(parts).strip()

    return ""


def read_json_response(resp):
    raw = resp.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    return json.loads(raw)


def extract_openai_text(data):
    if isinstance(data.get("output_text"), str) and data["output_text"].strip():
        return data["output_text"].strip()

    for item in data.get("output", []):
        text = extract_text_from_content(item.get("content"))
        if text:
            return text

    choices = data.get("choices") or []
    if choices:
        text = extract_text_from_content((choices[0].get("message") or {}).get("content"))
        if text:
            return text

    raise ValueError("未从模型响应中提取到文本")


def resolve_compatible_url(base_url):
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return ""

    known_suffixes = (
        "/chat/completions",
        "/responses",
        "/v1/chat/completions",
        "/v1/responses",
    )
    if any(base.endswith(suffix) for suffix in known_suffixes):
        return base
    if base.endswith("/v1"):
        return base + "/chat/completions"
    return base + "/v1/chat/completions"


def call_llm(prompt, llm_config, max_tokens=4096):
    if not llm_ready(llm_config):
        raise ValueError("LLM 配置不完整")

    provider = llm_config["provider"]
    model = llm_config["model"]
    api_key = llm_config["api_key"]

    if provider == "anthropic":
        payload = json.dumps({
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8")

        req = urllib.request.Request(
            llm_config.get("base_url") or "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = read_json_response(resp)
            text = extract_text_from_content(data.get("content", []))
            if not text:
                raise ValueError("模型响应为空")
            return text

    if provider == "deepseek":
        payload = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
        }).encode("utf-8")

        req = urllib.request.Request(
            resolve_compatible_url(llm_config.get("base_url") or "https://api.deepseek.com"),
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = read_json_response(resp)
            return extract_openai_text(data)

    if provider == "openai":
        payload = json.dumps({
            "model": model,
            "input": prompt,
            "max_output_tokens": max_tokens,
        }).encode("utf-8")

        req = urllib.request.Request(
            llm_config.get("base_url") or "https://api.openai.com/v1/responses",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = read_json_response(resp)
            return extract_openai_text(data)

    if provider == "openai_compatible":
        payload = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
        }).encode("utf-8")

        req = urllib.request.Request(
            resolve_compatible_url(llm_config.get("base_url")),
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = read_json_response(resp)
            return extract_openai_text(data)

    raise ValueError(f"不支持的 provider: {provider}")


def fetch_rss(url, timeout=12):
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read()
            encoding = resp.headers.get_content_charset() or "utf-8"
            try:
                text = content.decode(encoding)
            except Exception:
                text = content.decode("utf-8", errors="replace")
            return parse_feed(text, url)
    except Exception as e:
        print(f"  [RSS 错误] {url}: {e}")
        return []


def parse_feed(text, source_url=""):
    if HAS_FEEDPARSER:
        d = feedparser.parse(text)
        items = []
        for entry in d.entries[:20]:
            title = getattr(entry, "title", "").strip()
            link = getattr(entry, "link", source_url).strip()
            published = getattr(entry, "published", "") or getattr(entry, "updated", "")
            summary = getattr(entry, "summary", "") or getattr(entry, "description", "")
            if title:
                items.append({
                    "title": title,
                    "link": link,
                    "pubDate": published,
                    "description": summary[:300] if summary else "",
                })
        return items

    items = []
    try:
        root = ET.fromstring(text.encode("utf-8"))

        for item in root.iter("item"):
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            pubdate = item.findtext("pubDate", "").strip()
            desc = item.findtext("description", "").strip()
            if title:
                items.append({
                    "title": title,
                    "link": link,
                    "pubDate": pubdate,
                    "description": desc[:300],
                })

        if not items:
            atom_ns = "http://www.w3.org/2005/Atom"
            for entry in root.iter(f"{{{atom_ns}}}entry"):
                title = entry.findtext(f"{{{atom_ns}}}title", "").strip()
                link_el = entry.find(f"{{{atom_ns}}}link")
                link = link_el.get("href", "") if link_el is not None else ""
                published = entry.findtext(f"{{{atom_ns}}}published", "") or entry.findtext(f"{{{atom_ns}}}updated", "")
                summary = entry.findtext(f"{{{atom_ns}}}summary", "") or entry.findtext(f"{{{atom_ns}}}content", "")
                if title:
                    items.append({
                        "title": title,
                        "link": link,
                        "pubDate": published,
                        "description": (summary or "")[:300],
                    })
    except Exception as e:
        print(f"  [XML 解析错误] {e}")
    return items


def parse_pubdate(date_str):
    if not date_str:
        return int(time.time() * 1000)

    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%d %b %Y %H:%M:%S %z",
    ]

    normalized = date_str.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+0000"

    for fmt in formats:
        try:
            dt = datetime.strptime(normalized, fmt)
            return int(dt.timestamp() * 1000)
        except Exception:
            continue
    return int(time.time() * 1000)


def build_news_items(source_key, source_meta, items, extra_tag=None):
    seen = set()
    unique = []
    for item in items:
        title = item.get("title", "").strip()
        if not title:
            continue
        dedupe_key = title[:80]
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        unique.append(item)

    unique = unique[:15]
    news = []
    for idx, item in enumerate(unique):
        tags = [source_meta["name"], source_meta["category"]]
        if extra_tag:
            tags.append(extra_tag)
        news.append({
            "id": f"{source_key}_{idx}_{int(time.time())}",
            "source": source_key,
            "sourceName": source_meta["name"],
            "title": item["title"],
            "link": item.get("link", "#"),
            "timestamp": parse_pubdate(item.get("pubDate", "")),
            "category": source_meta["category"],
            "description": item.get("description", ""),
            "translated": False,
            "translation": None,
            "tags": tags,
        })
    return news


def generate_fallback_news(source_key, source_meta, llm_config):
    if not llm_ready(llm_config):
        return []

    today = datetime.now().strftime("%Y年%m月%d日")
    lang = "中文" if source_key == "zaobao" else "英文"
    prompt = f"""你是{source_meta['name']}的编辑。请生成{today}该媒体风格的12条真实感新闻标题（{lang}）。

重要：只返回JSON格式，不要任何解释：
{{"items": [{{"title": "标题", "category": "类别", "url": "https://example.com"}}]}}

要求：
- 风格完全符合{source_meta['name']}的报道风格和领域（{source_meta['category']}）
- 内容涵盖：美股、宏观经济、央行政策、地缘政治、企业动态、大宗商品等
- 标题要有新闻价值感，不要太笼统
- 时间戳随机分布在今天过去6小时内"""
    result = call_llm(prompt, llm_config, max_tokens=2000)
    clean = result.replace("```json", "").replace("```", "").strip()
    data = json.loads(clean)
    generated = data.get("items", [])
    now_ms = int(time.time() * 1000)

    normalized = []
    for idx, item in enumerate(generated):
        normalized.append({
            "title": item.get("title", ""),
            "link": item.get("url", source_meta.get("url", "#")),
            "pubDate": str(now_ms - idx * 300000),
            "description": "",
            "category": item.get("category", source_meta["category"]),
        })
    return build_news_items(source_key, source_meta, normalized, extra_tag="AI生成")


def translate_titles(items, llm_config, batch_size=10):
    """Translate English titles to Chinese using LLM, in batches."""
    if not items or not llm_ready(llm_config):
        return items

    def translate_batch(batch):
        titles = [item.get("title", "") for item in batch]
        prompt = """You are a professional finance translator. Translate the following English news titles to Chinese.
Keep the translations accurate, concise, and suitable for a finance news terminal.

Return ONLY a JSON array of translated strings, no explanations:
["标题1", "标题2", ...]"""
        try:
            result = call_llm(prompt + "\n\n" + "\n".join(titles), llm_config, max_tokens=2048)
            clean = result.replace("```json", "").replace("```", "").strip()
            translations = json.loads(clean)
            if not isinstance(translations, list) or len(translations) != len(batch):
                return batch
            for i, item in enumerate(batch):
                item["title_zh"] = translations[i] if i < len(translations) else item.get("title", "")
            return batch
        except Exception as e:
            print(f"  [翻译错误] batch failed: {e}")
            return batch

    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        items[i:i + batch_size] = translate_batch(batch)

    return items


def fetch_source_news(source_key, source_meta, llm_config=None, enable_ai_fallback=True):
    llm_config = llm_config or {}
    items = []

    for feed_url in source_meta.get("feeds", []):
        items.extend(fetch_rss(feed_url))

    news = build_news_items(source_key, source_meta, items)
    if news:
        news = translate_titles(news, llm_config)
        for item in news:
            item["title_en"] = item.get("title", "")
            item["title_zh"] = item.get("title_zh", item.get("title", ""))
            item["title"] = item.get("title_zh", item.get("title", ""))
        return {
            "items": news,
            "status": {"status": "ok", "count": len(news)},
        }

    if enable_ai_fallback and llm_ready(llm_config):
        try:
            fallback_news = generate_fallback_news(source_key, source_meta, llm_config)
            for item in fallback_news:
                item["title_en"] = item.get("title", "")
                item["title_zh"] = item.get("title_zh", item.get("title", ""))
                item["title"] = item.get("title_zh", item.get("title", ""))
            return {
                "items": fallback_news,
                "status": {"status": "fallback", "count": len(fallback_news)},
            }
        except Exception as e:
            print(f"  [AI fallback 失败] {source_key}: {e}")

    return {
        "items": [],
        "status": {"status": "error", "count": 0},
    }


def fetch_all_news(llm_config=None, enable_ai_fallback=True):
    llm_config = llm_config or {}
    all_items = []
    results = {}
    lock = threading.Lock()
    thread_results = {}
    threads = []

    def run(source_key, source_meta):
        result = fetch_source_news(source_key, source_meta, llm_config, enable_ai_fallback=enable_ai_fallback)
        with lock:
            thread_results[source_key] = result["items"]
            results[source_key] = result["status"]

    for source_key, source_meta in RSS_SOURCES.items():
        thread = threading.Thread(target=run, args=(source_key, source_meta))
        threads.append((source_key, thread))
        thread.start()

    for _, thread in threads:
        thread.join(timeout=30)

    for source_key, thread in threads:
        if thread.is_alive():
            results[source_key] = {"status": "error", "count": 0}

    for source_key in RSS_SOURCES:
        all_items.extend(thread_results.get(source_key, []))
        results.setdefault(source_key, {"status": "error", "count": 0})

    all_items.sort(key=lambda item: item["timestamp"], reverse=True)
    return all_items, results


def generate_sql_insert(items):
    """将抓取的新闻生成为 D1 INSERT SQL 语句"""
    stmts = []
    for item in items:
        id_ = item.get("id", "").replace("'", "''")
        source = item.get("source", "").replace("'", "''")
        sourceName = item.get("sourceName", "").replace("'", "''")
        title_en = item.get("title_en", "").replace("'", "''")
        title_zh = item.get("title_zh", "").replace("'", "''")
        link = item.get("link", "#").replace("'", "''")
        ts = item.get("timestamp", 0)
        category = item.get("category", "").replace("'", "''")
        desc = (item.get("description") or "")[:500].replace("'", "''")
        tags = json.dumps(item.get("tags", [])).replace("'", "''")
        stmts.append(
            f"INSERT INTO news (id, source, sourceName, title_en, title_zh, link, timestamp, category, description, tags) "
            f"VALUES ('{id_}', '{source}', '{sourceName}', '{title_en}', '{title_zh}', '{link}', {ts}, '{category}', '{desc}', '{tags}');"
        )
    return "\n".join(stmts)


def generate_cleanup_sql():
    """生成清理7天前数据的 SQL"""
    cutoff = int(time.time() * 1000) - 7 * 24 * 60 * 60 * 1000
    return f"DELETE FROM news WHERE timestamp < {cutoff};"


def fetch_news_bundle(api_key="", provider="", model="", base_url="", enable_ai_fallback=True):
    llm_config = normalize_llm_config(
        api_key=api_key,
        provider=provider,
        model=model,
        base_url=base_url,
    )
    items, source_results = fetch_all_news(llm_config, enable_ai_fallback=enable_ai_fallback)
    return {
        "items": items,
        "sources": source_results,
        "total": len(items),
        "fetchedAt": int(time.time() * 1000),
    }


if __name__ == "__main__":
    data = fetch_news_bundle(enable_ai_fallback=False)

    # 生成 SQL 文件（用于写入 D1）
    insert_sql = generate_sql_insert(data["items"])
    cleanup_sql = generate_cleanup_sql()
    os.makedirs("public/data", exist_ok=True)
    with open("public/data/news.sql", "w", encoding="utf-8") as f:
        f.write(cleanup_sql + "\n" + insert_sql)

    # 保留 JSON 用于调试/备用
    with open("public/data/news.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(json.dumps({
        "total": data["total"],
        "ok_sources": sum(1 for s in data["sources"].values() if s["status"] == "ok"),
        "fallback_sources": sum(1 for s in data["sources"].values() if s["status"] == "fallback"),
        "error_sources": sum(1 for s in data["sources"].values() if s["status"] == "error"),
    }, ensure_ascii=False, indent=2))
