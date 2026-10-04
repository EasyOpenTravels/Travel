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
from .system_errors import record_error

# Kenya/local-first. International doors remain available, but never outrank a usable local listing.
PRODUCT_SOURCES = [
    ("Jumia Kenya", "jumia.co.ke", "https://www.jumia.co.ke/catalog/?q={q}"),
    ("PigiaMe Kenya", "pigiame.co.ke", "https://www.pigiame.co.ke/search?query={q}"),
    ("Kilimall Kenya", "kilimall.co.ke", "https://www.kilimall.co.ke/new/commoditysearch?keyword={q}"),
    ("Jiji Kenya", "jiji.co.ke", "https://jiji.co.ke/search?query={q}"),
    ("Alibaba", "alibaba.com", "https://www.alibaba.com/trade/search?SearchText={q}"),
    ("AliExpress", "aliexpress.com", "https://www.aliexpress.com/wholesale?SearchText={q}"),
]

COUNTRY_LOCAL_DOMAINS = {
    'kenya': ('.co.ke', '.ke'), 'uganda': ('.co.ug', '.ug'), 'tanzania': ('.co.tz', '.tz'),
    'rwanda': ('.rw',), 'nigeria': ('.ng', '.com.ng'), 'ghana': ('.gh',),
    'south africa': ('.co.za', '.za'), 'united kingdom': ('.co.uk', '.uk'),
    'united states': ('.com',), 'canada': ('.ca',), 'australia': ('.com.au', '.au'),
    'germany': ('.de',), 'india': ('.in',), 'united arab emirates': ('.ae',),
}

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
    except Exception as exc:
        record_error(status_code=502,error_type='RemoteSearchError',message=str(exc),exc=exc,context='RSS/web connector request failed')
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


def _local_score(row, country):
    c = (country or 'Kenya').strip().lower()
    net = urlparse(row.get('url', '')).netloc.lower()
    domains = COUNTRY_LOCAL_DOMAINS.get(c, ())
    # Explicit Kenyan/other country marketplace sources always get the local tier.
    return 0 if any(net.endswith(d) or d in net for d in domains) else 1


def product_search(query, budget="affordable", country="Kenya", location=""):
    words = {"affordable": "cheap budget deal low price", "moderate": "best value mid range", "high": "premium high end"}.get(budget, "best deal")
    context = ' '.join(x for x in [query, country, location] if x).strip()
    rows = []
    with ThreadPoolExecutor(max_workers=len(PRODUCT_SOURCES) + 2) as pool:
        futures = [pool.submit(_source_search, source, domain, context, words) for source, domain, _ in PRODUCT_SOURCES]
        suffixes=COUNTRY_LOCAL_DOMAINS.get((country or 'Kenya').strip().lower(),())
        futures.append(pool.submit(lambda: ("Local web", suffixes[0] if suffixes else 'local', search_rss(f"site:{suffixes[0]} {context} {words}" if suffixes else f"{context} {country} {words}", 10))))
        futures.append(pool.submit(lambda: ("Web", "the-web", search_rss(f"{context} {words}", 10))))
        for fut in as_completed(futures):
            try:
                source, domain, found = fut.result()
            except Exception as exc:
                record_error(status_code=502,error_type='ConnectorWorkerError',message=str(exc),exc=exc,context='product search worker failed')
                continue
            for row in found:
                row["source"] = source
                row["domain"] = domain
                rows.append(row)
    seen = set(); unique = []
    for row in rows:
        key = (row.get("title", "").lower()[:120], urlparse(row.get("url", "")).netloc.lower())
        if key in seen or not key[0]:
            continue
        seen.add(key); unique.append(row)
    priced=[r for r in unique if r.get('price') is not None]
    median=sorted(r['price'] for r in priced)[len(priced)//2] if priced else None
    source_rank={name:i for i,(name,_,_) in enumerate(PRODUCT_SOURCES)}
    def price_rank(r):
        p=r.get('price')
        if p is None: return 10**18
        if budget=='high': return -p
        if budget=='moderate' and median is not None: return abs(p-median)
        return p
    unique.sort(key=lambda r: (_local_score(r,country), 0 if r.get('price') is not None else 1, price_rank(r), source_rank.get(r.get('source'),999)))
    return unique[:30]


def product_fallback_links(query, country='Kenya'):
    encoded = quote_plus(query)
    links = []
    local_suffix=(COUNTRY_LOCAL_DOMAINS.get((country or 'Kenya').strip().lower(),()) or ('',))[0]
    if local_suffix:
        links.append({"source": f"Local {country} web", "url": "https://www.google.com/search?q=" + quote_plus(f"site:{local_suffix} {query}")})
    sources = PRODUCT_SOURCES if (country or '').strip().lower() in {'kenya','ke'} else PRODUCT_SOURCES[4:]
    for source, _, template in sources:
        links.append({"source": source, "url": template.format(q=encoded)})
    links.append({"source": f"Search {country} on the web", "url": "https://www.google.com/search?q=" + quote_plus(query + ' ' + country)})
    return links


def job_search(query, country, location=""):
    loc = location or country or ""
    sources = []
    if (country or "").strip().lower() in {"kenya", "ke"}:
        sources += KENYA_JOB_SOURCES
    sources += list(JOB_SOURCES)
    rows = []
    with ThreadPoolExecutor(max_workers=len(sources) + 1) as pool:
        futures = []
        for source, domain, _ in sources:
            futures.append(pool.submit(_source_search, source, domain, f"{query} {country} {loc}".strip(), "job vacancy"))
        futures.append(pool.submit(lambda: ("Web", "the-web", search_rss(f"{query} jobs {country} {loc}".strip(), 10))))
        for fut in as_completed(futures):
            try:
                source, domain, found = fut.result()
            except Exception as exc:
                record_error(status_code=502,error_type='ConnectorWorkerError',message=str(exc),exc=exc,context='job search worker failed')
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
    source_rank={name:i for i,(name,_,_) in enumerate(KENYA_JOB_SOURCES + JOB_SOURCES)}
    unique.sort(key=lambda r: (_local_score(r,country), source_rank.get(r.get('source'),999)))
    return unique[:36]


def job_fallback_links(query, country, location=""):
    raw_query = str(query or '').strip()
    q = quote_plus(raw_query)
    loc = quote_plus(location or country or "")
    links = []
    if (country or '').strip().lower() in {'kenya','ke'}:
        sources = KENYA_JOB_SOURCES + JOB_SOURCES
    else:
        sources = JOB_SOURCES
    for source, _, template in sources:
        links.append({"source": source, "url": template.format(q=q, loc=loc)})
    local_url="https://www.google.com/search?q=" + quote_plus(raw_query + ' jobs ' + country + ' ' + (location or ''))
    links.insert(0, {"source": f"Local {country} jobs", "url": local_url})
    links.append({"source": "Search the wider web", "url": "https://www.google.com/search?q=" + quote_plus(raw_query + ' jobs ' + country)})
    return links
