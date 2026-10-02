"""Small, dependency-free web connectors used by the discovery tools.

The app is deliberately a connector rather than a marketplace.  Live searches use
public search-engine RSS endpoints and direct marketplace/job-board search links.
When a remote source is slow, blocked, or has no usable result, the UI still gets
a useful fallback link instead of a dead-end page.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
from html.parser import HTMLParser
import re
from urllib.parse import quote_plus, urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

PRODUCT_SOURCES = [
    ("Jumia", "jumia.co.ke", "https://www.jumia.co.ke/catalog/?q={q}"),
    ("Alibaba", "alibaba.com", "https://www.alibaba.com/trade/search?SearchText={q}"),
    ("AliExpress", "aliexpress.com", "https://www.aliexpress.com/wholesale?SearchText={q}"),
    ("Kilimall", "kilimall.co.ke", "https://www.kilimall.co.ke/new/commoditysearch?keyword={q}"),
    ("Jiji", "jiji.co.ke", "https://jiji.co.ke/search?query={q}"),
]

JOB_SOURCES = [
    ("LinkedIn Jobs", "linkedin.com/jobs", "https://www.linkedin.com/jobs/search/?keywords={q}&location={loc}"),
    ("Indeed", "indeed.com", "https://www.indeed.com/jobs?q={q}&l={loc}"),
    ("Jooble", "jooble.org", "https://jooble.org/SearchResult?ukw={q}&rgns={loc}"),
    ("Glassdoor", "glassdoor.com", "https://www.glassdoor.com/Job/jobs.htm?sc.keyword={q}&locT=C&locId={loc}"),
]
KENYA_JOB_SOURCES = [
    ("MyJobMag", "myjobmag.co.ke", "https://www.myjobmag.co.ke/search/jobs?q={q}"),
    ("BrighterMonday", "brightermonday.co.ke", "https://www.brightermonday.co.ke/jobs?q={q}"),
    ("Fuzu", "fuzu.com", "https://www.fuzu.com/search/jobs?query={q}"),
]

PRICE_RE = re.compile(r"(?i)(?:ksh\.?|kes\s*|ksh\s*|kshs\s*)\s*([0-9][0-9,]*(?:\.\d{1,2})?)|(?:usd\s*|\$\s*)([0-9][0-9,]*(?:\.\d{1,2})?)")


def _clean_html(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _price(text):
    m = PRICE_RE.search(text or "")
    if not m:
        return None, ""
    if m.group(1):
        raw = m.group(1).replace(",", "")
        try:
            return float(raw), f"KSh {int(float(raw)):,}"
        except ValueError:
            return None, ""
    raw = m.group(2).replace(",", "")
    try:
        return float(raw), f"US$ {float(raw):,.0f}"
    except ValueError:
        return None, ""


def search_rss(query, limit=6):
    url = "https://www.bing.com/search?format=rss&setlang=en&q=" + quote_plus(query)
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 OpenRoadFinder/1.0"})
    try:
        with urlopen(req, timeout=6) as res:
            raw = res.read()
        root = ET.fromstring(raw)
    except Exception:
        return []
    out = []
    for item in root.findall('.//item')[:limit]:
        title = _clean_html(item.findtext('title', ''))
        link = (item.findtext('link', '') or '').strip()
        desc = _clean_html(item.findtext('description', ''))
        if not title or not link:
            continue
        value, price_text = _price(title + " " + desc)
        out.append({"title": title, "url": link, "snippet": desc, "price": value, "price_text": price_text})
    return out


def _source_search(source, domain, q, budget_words=""):
    query = f"site:{domain} {q} {budget_words}".strip()
    rows = search_rss(query, 5)
    return source, domain, rows


def product_search(query, budget="affordable"):
    words = {"affordable": "cheap budget deal", "moderate": "best value", "high": "premium high end"}.get(budget, "best deal")
    rows = []
    with ThreadPoolExecutor(max_workers=len(PRODUCT_SOURCES) + 1) as pool:
        futures = [pool.submit(_source_search, source, domain, query, words) for source, domain, _ in PRODUCT_SOURCES]
        futures.append(pool.submit(lambda: ("Web", "the-web", search_rss(f"{query} {words}", 8))))
        for fut in as_completed(futures):
            try:
                source, domain, found = fut.result()
            except Exception:
                continue
            for row in found:
                row["source"] = source
                row["domain"] = domain
                rows.append(row)
    seen = set()
    unique = []
    for row in rows:
        key = (row["title"].lower()[:120], urlparse(row["url"]).netloc.lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    # KSh listings can be compared directly; entries with no detected price stay visible.
    unique.sort(key=lambda r: (0 if r.get("price") is not None else 1, r.get("price") if r.get("price") is not None else 10**18))
    return unique[:24]


def product_fallback_links(query):
    encoded = quote_plus(query)
    links = [{"source": s, "url": template.format(q=encoded)} for s, _, template in PRODUCT_SOURCES]
    links.append({"source": "Search the web", "url": "https://www.google.com/search?q=" + encoded})
    return links


def job_search(query, country, location=""):
    loc = location or country or ""
    sources = list(JOB_SOURCES)
    if (country or "").strip().lower() in {"kenya", "ke"}:
        sources += KENYA_JOB_SOURCES
    rows = []
    with ThreadPoolExecutor(max_workers=len(sources) + 1) as pool:
        futures = []
        for source, domain, _ in sources:
            futures.append(pool.submit(_source_search, source, domain, f"{query} {country} {loc}".strip(), "job vacancy"))
        futures.append(pool.submit(lambda: ("Web", "the-web", search_rss(f"{query} jobs {country} {loc}".strip(), 10))))
        for fut in as_completed(futures):
            try:
                source, domain, found = fut.result()
            except Exception:
                continue
            for row in found:
                row["source"] = source
                row["domain"] = domain
                rows.append(row)
    seen = set()
    unique = []
    for row in rows:
        key = (row["title"].lower()[:120], urlparse(row["url"]).netloc.lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique[:30]


def job_fallback_links(query, country, location=""):
    q = quote_plus(query)
    loc = quote_plus(location or country or "")
    sources = list(JOB_SOURCES)
    if (country or "").strip().lower() in {"kenya", "ke"}:
        sources += KENYA_JOB_SOURCES
    links = []
    for source, _, template in sources:
        links.append({"source": source, "url": template.format(q=q, loc=loc)})
    links.append({"source": "Search the web", "url": "https://www.google.com/search?q=" + q + "+jobs+" + quote_plus(country)})
    return links
