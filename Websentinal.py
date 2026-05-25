import argparse
import asyncio
import json
import re
import time
import random
import sys
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from urllib.parse import urljoin, urldefrag, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


def parse_args():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python Websentinal.py -u https://example.com
  python Websentinal.py -u https://example.com --depth 3 --threads 20
  python Websentinal.py -u https://example.com --no-endpoints
  python Websentinal.py -u https://example.com --wordlist my_wordlist.txt -o results
        """
    )
    parser.add_argument("-u", "--url",         required=True,  help="Target URL")
    parser.add_argument("--depth",             type=int, default=2,  help="Crawl depth (default: 2)")
    parser.add_argument("--threads",           type=int, default=15, help="Concurrent threads (default: 15)")
    parser.add_argument("--delay",             type=float, default=0.0, help="Delay between requests in seconds (default: 0)")
    parser.add_argument("--timeout",           type=int, default=8,  help="Request timeout in seconds (default: 8)")
    parser.add_argument("--wordlist",          default=None,   help="Path to custom hidden-endpoint wordlist file")
    parser.add_argument("--no-endpoints",      action="store_true",  help="Skip endpoint discovery phase")
    parser.add_argument("--no-dynamic",        action="store_true",  help="Skip dynamic (Playwright) endpoint scanning")
    parser.add_argument("-o", "--output",      default="websentinal", help="Output file prefix (default: websentinal)")
    parser.add_argument("--no-save",           action="store_true",  help="Don't save output files")
    return parser.parse_args()


DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

BLOCKED_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".ico", ".webp", ".css", ".woff", ".woff2", ".ttf", ".eot", ".pdf", 
    ".zip", ".tar", ".gz", ".rar", ".mp4", ".mp3", ".avi", ".mov",
)

DEFAULT_WORDLIST = [
    "api", "admin", "internal", "debug", "v1", "v2", "v3", "private", "secret", "config", "settings", "dashboard",
    "login", "logout", "register", "signup", "auth", "oauth", "graphql", "rest", "docs", "swagger", "openapi",
    "health", "status", "metrics", "monitor", "actuator", "user", "users", "account", "accounts", "profile", "upload", "uploads", 
    "files", "assets", "static", "backup", "test", "dev", "staging", "beta", "robots.txt"
]

ENDPOINT_PATTERNS = [
    re.compile(r'''["'`](\/api\/[^"'`\s<>]+)["'`]'''),
    re.compile(r'''["'`](\/v\d+\/[^"'`\s<>]+)["'`]'''),
    re.compile(r'''["'`](\/graphql[^"'`\s<>]*)["'`]'''),
    re.compile(r'https?://[^\s"\'<>]+/(?:api|v\d+)/[^\s"\'<>]+'),
    re.compile(r'''fetch\s*\(\s*["'`]([^"'`]+)["'`]'''),
    re.compile(r'''axios\.\w+\s*\(\s*["'`]([^"'`]+)["'`]'''),
]


def clean_url(url: str) -> str:
    return urldefrag(url.split("#")[0])[0]

def is_same_domain(url: str, netloc: str) -> bool:
    return urlparse(url).netloc == netloc

def is_blocked(url: str) -> bool:
    return url.lower().endswith(BLOCKED_EXTENSIONS)

def make_session(timeout: int) -> requests.Session:
    s = requests.Session()
    s.headers.update(DEFAULT_HEADERS)
    return s

def log(msg: str, level: str = "INFO"):
    colors = {"INFO": "\033[94m", "OK": "\033[92m", "WARN": "\033[93m", "ERR": "\033[91m", "HEAD": "\033[96m"}
    reset = "\033[0m"
    prefix = colors.get(level, "") + f"[{level}]" + reset
    print(f"{prefix} {msg}")

#Extraction functions.

def extract_links(soup: BeautifulSoup, base_url: str) -> set:
    links = set()
    for tag in soup.find_all(["a", "area"], href=True):
        url = clean_url(urljoin(base_url, tag["href"]))
        if url.startswith("http"):
            links.add(url)
    return links


def extract_images(soup: BeautifulSoup, base_url: str) -> set:
    imgs = set()
    for tag in soup.find_all(["img", "source"], src=True):
        imgs.add(urljoin(base_url, tag["src"]))
    return imgs


def extract_resources(soup: BeautifulSoup, base_url: str) -> set:
    res = set()
    for tag in soup.find_all("link", href=True):
        res.add(urljoin(base_url, tag["href"]))
    return res


def extract_scripts(soup: BeautifulSoup, base_url: str) -> set:
    scripts = set()
    for tag in soup.find_all("script", src=True):
        scripts.add(urljoin(base_url, tag["src"]))
    return scripts


def extract_inputs(soup: BeautifulSoup) -> list:
    inputs = []
    for tag in soup.find_all("input"):
        inputs.append({
            "name": tag.get("name"),
            "type": tag.get("type", "text"),
            "id":   tag.get("id"),
        })
    return inputs


def extract_forms(soup: BeautifulSoup, base_url: str) -> list:
    forms = []
    for form in soup.find_all("form"):
        action = urljoin(base_url, form.get("action") or base_url)
        method = form.get("method", "get").upper()
        fields = []
        for inp in form.find_all(["input", "textarea", "select"]):
            fields.append({
                "name":  inp.get("name"),
                "type":  inp.get("type", "text"),
                "value": inp.get("value", ""),
            })
        forms.append({"action": action, "method": method, "fields": fields})
    return forms


def extract_parameters(url: str) -> dict:
    return {k: list(v) for k, v in parse_qs(urlparse(url).query).items()}


def extract_comments(soup: BeautifulSoup) -> list:
    from bs4 import Comment
    return [str(c).strip() for c in soup.find_all(string=lambda t: isinstance(t, Comment)) if str(c).strip()]


def extract_meta(soup: BeautifulSoup) -> dict:
    meta = {}
    for tag in soup.find_all("meta"):
        name = tag.get("name") or tag.get("property")
        content = tag.get("content")
        if name and content:
            meta[name] = content
    return meta


#JS detection.

def requires_js(base_url: str, session: requests.Session, timeout: int) -> bool:
    try:
        r = session.get(base_url, timeout=timeout)
        static_text = BeautifulSoup(r.text, "lxml").get_text(strip=True)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(base_url, timeout=15000, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            rendered_text = BeautifulSoup(page.content(), "lxml").get_text(strip=True)
            browser.close()

        return len(rendered_text) > len(static_text) * 1.8
    except Exception:
        return False


class Crawler:
    def __init__(self, start_url: str, depth: int, threads: int, timeout: int, delay: float):
        self.start_url   = start_url
        self.start_netloc = urlparse(start_url).netloc
        self.max_depth   = depth
        self.threads     = threads
        self.timeout     = timeout
        self.delay       = delay

        self.visited     = set()
        self.queue       = deque([(start_url, 0)])
        self.lock        = Lock()
        self.session     = make_session(timeout)

        self.links      = set()
        self.images     = set()
        self.resources  = set()
        self.scripts    = set()
        self.inputs     = []
        self.forms      = []
        self.parameters = {}
        self.comments   = []
        self.meta       = {}

    def _should_visit(self, url: str, depth: int) -> bool:
        return (
            url not in self.visited
            and depth <= self.max_depth
            and is_same_domain(url, self.start_netloc)
            and not is_blocked(url)
            and url.startswith("http")
        )

    def _fetch_and_parse(self, url: str, depth: int):
        if self.delay > 0:
            time.sleep(self.delay + random.uniform(0, self.delay * 0.5))
        try:
            r = self.session.get(url, timeout=self.timeout)
            if not r.ok:
                return
            ct = r.headers.get("content-type", "")
            if "html" not in ct:
                return

            soup = BeautifulSoup(r.text, "lxml")

            new_links  = extract_links(soup, url)
            images     = extract_images(soup, url)
            resources  = extract_resources(soup, url)
            scripts    = extract_scripts(soup, url)
            inputs     = extract_inputs(soup)
            forms      = extract_forms(soup, url)
            params     = extract_parameters(url)
            comments   = extract_comments(soup)
            meta       = extract_meta(soup)

            with self.lock:
                self.images.update(images)
                self.resources.update(resources)
                self.scripts.update(scripts)
                self.inputs.extend(inputs)
                self.forms.extend(forms)
                self.comments.extend(comments)
                self.meta.update(meta)
                for k, v in params.items():
                    self.parameters.setdefault(k, set()).update(v)

                for link in new_links:
                    link = clean_url(link)
                    self.links.add(link)
                    if self._should_visit(link, depth + 1):
                        self.queue.append((link, depth + 1))

        except Exception as e:
            pass

    def run(self) -> dict:
        log(f"Starting crawl on {self.start_url} (depth={self.max_depth}, threads={self.threads})", "HEAD")
        t0 = time.time()

        with ThreadPoolExecutor(max_workers=self.threads) as pool:
            futures = {}

            def submit_pending():
                while self.queue:
                    url, depth = self.queue.popleft()
                    url = clean_url(url)
                    with self.lock:
                        if not self._should_visit(url, depth):
                            continue
                        self.visited.add(url)
                    f = pool.submit(self._fetch_and_parse, url, depth)
                    futures[f] = url

            submit_pending()

            while futures:
                done = set()
                for f in as_completed(list(futures.keys())):
                    done.add(f)
                futures = {k: v for k, v in futures.items() if k not in done}
                submit_pending()

        elapsed = time.time() - t0
        log(f"Crawl complete in {elapsed:.2f}s — "
            f"{len(self.visited)} pages | {len(self.links)} links | "
            f"{len(self.scripts)} scripts | {len(self.forms)} forms | "
            f"{len(self.inputs)} inputs | {len(self.images)} images", "OK")

        return {
            "links":      self.links,
            "images":     self.images,
            "resources":  self.resources,
            "scripts":    self.scripts,
            "inputs":     self.inputs,
            "forms":      self.forms,
            "parameters": {k: list(v) for k, v in self.parameters.items()},
            "comments":   self.comments,
            "meta":       self.meta,
        }

#Endpoint discovery functions.

def static_endpoint_scan(js_urls: list, session: requests.Session, threads: int) -> set:
    endpoints = set()
    lock = Lock()

    def scan_one(js_url):
        try:
            r = session.get(js_url, timeout=8)
            for pattern in ENDPOINT_PATTERNS:
                for match in pattern.findall(r.text):
                    with lock:
                        endpoints.add(match)
        except Exception:
            pass

    with ThreadPoolExecutor(max_workers=threads) as pool:
        list(pool.map(scan_one, js_urls))

    return endpoints


def dynamic_endpoint_scan(url: str) -> set:
    dynamic = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=DEFAULT_HEADERS["User-Agent"],
            ignore_https_errors=True,
        )
        page = context.new_page()

        def on_request(req):
            if req.resource_type in ("xhr", "fetch"):
                dynamic.add(req.url)

        def on_response(resp):
            try:
                ct = resp.headers.get("content-type", "")
                if "application/json" in ct:
                    dynamic.add(resp.url)
            except Exception:
                pass

        page.on("request",  on_request)
        page.on("response", on_response)

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(2500)

            # Click common interactive elements to trigger more requests
            for selector in ["button", '[role="button"]', 'a[href="#"]']:
                try:
                    btns = page.query_selector_all(selector)
                    for btn in btns[:5]:
                        try:
                            text = btn.inner_text().lower()
                            if any(w in text for w in ("login", "submit", "search", "load", "more")):
                                if btn.is_visible() and btn.is_enabled():
                                    btn.click()
                                    page.wait_for_timeout(800)
                        except Exception:
                            pass
                except Exception:
                    pass

        except Exception as e:
            log(f"Dynamic scan error: {e}", "WARN")
        finally:
            browser.close()

    return dynamic


def hidden_endpoint_scan(base_url: str, wordlist: list, session: requests.Session, threads: int) -> set:
    found = set()
    lock = Lock()

    def probe(word):
        test_url = urljoin(base_url, f"/{word}")
        try:
            r = session.get(test_url, timeout=6, allow_redirects=False)
            if r.status_code in (200, 201, 204, 301, 302, 401, 403, 405):
                with lock:
                    found.add(f"{test_url} [{r.status_code}]")
        except Exception:
            pass

    with ThreadPoolExecutor(max_workers=threads) as pool:
        list(pool.map(probe, wordlist))

    return found


def contextual_endpoint_scan(all_links: list) -> set:
    return {link for link in all_links if urlparse(link).query}


def run_endpoint_discovery(
    url: str,
    scripts: list,
    links: list,
    session: requests.Session,
    threads: int,
    wordlist: list,
    skip_dynamic: bool,
) -> dict:
    log("Starting endpoint discovery...", "HEAD")
    t0 = time.time()

    results = {
        "static": [],
        "dynamic": [], 
        "hidden": [],
        "contextual": [],
    }

    with ThreadPoolExecutor(max_workers=3) as pool:
        f_static  = pool.submit(static_endpoint_scan,  scripts, session, threads)
        f_hidden  = pool.submit(hidden_endpoint_scan,  url, wordlist, session, threads)
        f_context = pool.submit(contextual_endpoint_scan, links)

        results["static"]      = sorted(f_static.result())
        results["hidden"]      = sorted(f_hidden.result())
        results["contextual"]  = sorted(f_context.result())

    if not skip_dynamic:
        results["dynamic"] = sorted(dynamic_endpoint_scan(url))

    elapsed = time.time() - t0
    log(f"Endpoint discovery done in {elapsed:.2f}s — "
        f"static={len(results['static'])} | dynamic={len(results['dynamic'])} | "
        f"hidden={len(results['hidden'])} | contextual={len(results['contextual'])}", "OK")

    return results

#Output

def save_json(data: dict, filepath: str):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=list)
    log(f"Saved → {filepath}", "OK")


def save_txt(data: dict, filepath: str):
    with open(filepath, "w", encoding="utf-8") as f:

        for key, value in data.items():
            f.write(f"\n{'=' * 40}\n  {key.upper()}\n{'=' * 40}\n")

            if isinstance(value, dict):
                for k, v in value.items():
                    if isinstance(v, (list, set)):
                        f.write(f"\n{k}:\n")
                        for item in sorted(map(str, v)):
                            f.write(f"  {item}\n")
                    else:
                        f.write(f"{k}: {v}\n")

            elif isinstance(value, (list, set)):
                for item in value:
                    if isinstance(item, dict):
                        f.write(json.dumps(item, indent=2))
                        f.write("\n")
                    else:
                        f.write(f"{item}\n")
            else:
                f.write(f"{value}\n")
    log(f"Saved → {filepath}", "OK")


def print_summary(crawl_data: dict, endpoint_data: dict | None):
    print("  WEBSENTINAL — SUMMARY")
    print(f"Links : {len(crawl_data['links'])}")
    print(f"Scripts : {len(crawl_data['scripts'])}")
    print(f"Images : {len(crawl_data['images'])}")
    print(f"Resources : {len(crawl_data['resources'])}")
    print(f"Forms : {len(crawl_data['forms'])}")
    print(f"Inputs : {len(crawl_data['inputs'])}")
    print(f"Parameters : {len(crawl_data['parameters'])}")
    print(f"Comments : {len(crawl_data['comments'])}")
    if endpoint_data:
        print(f"  Static Endpoints : {len(endpoint_data['static'])}")
        print(f"  Dynamic Endpoints : {len(endpoint_data['dynamic'])}")
        print(f"  Hidden Endpoints : {len(endpoint_data['hidden'])}")
        print(f"  Contextual Endpoints : {len(endpoint_data['contextual'])}")


def main():
    args = parse_args()

    target = args.url.strip()
    if not target.startswith("http"):
        target = "https://" + target

    session = make_session(args.timeout)

    if args.wordlist:
        try:
            with open(args.wordlist, "r") as f:
                wordlist = [line.strip() for line in f if line.strip()]
            log(f"Loaded {len(wordlist)} words from {args.wordlist}")
        except FileNotFoundError:
            log(f"Wordlist file not found: {args.wordlist}. Using default.", "WARN")
            wordlist = DEFAULT_WORDLIST
    else:
        wordlist = DEFAULT_WORDLIST

    #Phase 1: Crawling
    crawler = Crawler(
        start_url=target,
        depth=args.depth,
        threads=args.threads,
        timeout=args.timeout,
        delay=args.delay,
    )
    crawl_data = crawler.run()

    endpoint_data = None

    #Phase 2: Endpoint
    if not args.no_endpoints:
        if not args.no_dynamic:
            log("Checking if site is JS-heavy...", "INFO")
            js_heavy = requires_js(target, session, args.timeout)
            if js_heavy:
                log("JS-heavy site detected — dynamic scan may take longer.", "WARN")

        endpoint_data = run_endpoint_discovery(
            url=target,
            scripts=crawl_data["scripts"],
            links=crawl_data["links"],
            session=session,
            threads=args.threads,
            wordlist=wordlist,
            skip_dynamic=args.no_dynamic,
        )
    else:
        endpoint_data = {"static": [], "dynamic": [], "hidden": [], "contextual": []}

    print_summary(crawl_data, endpoint_data)

    if not args.no_save:
        prefix = args.output
        save_json(crawl_data,    f"{prefix}_crawl.json")
        save_txt(crawl_data,     f"{prefix}_crawl.txt")
        save_json(endpoint_data, f"{prefix}_endpoints.json")
        save_txt(endpoint_data,  f"{prefix}_endpoints.txt")

if __name__ == "__main__":
    main()