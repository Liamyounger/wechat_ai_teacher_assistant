import re
import logging
import httpx

logger = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    " (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

SHARE_PATTERNS = [
    (r'https?://pan\.quark\.cn/s/[a-zA-Z0-9]+', "夸克网盘"),
    (r'https?://pan\.baidu\.com/s/[a-zA-Z0-9_-]+', "百度网盘"),
    (r'https?://www\.aliyundrive\.com/s/[a-zA-Z0-9]+', "阿里云盘"),
    (r'https?://www\.alipan\.com/s/[a-zA-Z0-9]+', "阿里云盘"),
    (r'https?://[a-z]+\.lanzou[ix]\.com/[a-zA-Z0-9]+', "蓝奏云"),
    (r'https?://lanzou[ix]\.com/[a-zA-Z0-9]+', "蓝奏云"),
]

EXTRACT_CODE_PATTERNS = [
    r'提取码[：:]\s*([a-zA-Z0-9]{4,6})',
    r'密码[：:]\s*([a-zA-Z0-9]{4,6})',
    r'访问码[：:]\s*([a-zA-Z0-9]{4,6})',
]


class ArticleExtractor:
    def __init__(self):
        self.client = httpx.Client(timeout=30.0, follow_redirects=True)

    def extract_links(self, article_url: str) -> dict:
        """Fetch a WeChat article and extract sharing links + extraction codes."""
        resp = self.client.get(
            article_url,
            headers={
                "User-Agent": UA,
                "Referer": "https://weixin.sogou.com/",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
        )
        resp.raise_for_status()
        html = resp.text

        # Extract title
        title_match = re.search(
            r'<h1[^>]*class="rich_media_title"[^>]*>(.*?)</h1>',
            html, re.DOTALL
        )
        if not title_match:
            title_match = re.search(r'<title>(.*?)</title>', html)
        title = _clean_html(title_match.group(1)) if title_match else ""

        # Extract content area
        content_match = re.search(
            r'<div[^>]*id="js_content"[^>]*>(.*?)</div>\s*</div>',
            html, re.DOTALL
        )
        if not content_match:
            content_match = re.search(
                r'<div[^>]*class="rich_media_content"[^>]*>(.*?)</div>',
                html, re.DOTALL
            )
        content = content_match.group(1) if content_match else html

        # Find all sharing links
        links = []
        for pattern, platform in SHARE_PATTERNS:
            for match in re.finditer(pattern, content):
                link_url = match.group(0)
                # Avoid duplicates
                if not any(l["url"] == link_url for l in links):
                    links.append({"url": link_url, "platform": platform})

        # Find extraction codes
        extract_codes = []
        for pattern in EXTRACT_CODE_PATTERNS:
            for match in re.finditer(pattern, content):
                code = match.group(1)
                if code not in extract_codes:
                    extract_codes.append(code)

        # Extract the account name
        account_match = re.search(
            r'id="js_name"[^>]*>(.*?)</',
            html, re.DOTALL
        )
        account = _clean_html(account_match.group(1)) if account_match else ""

        return {
            "title": title,
            "account": account,
            "article_url": article_url,
            "links": links,
            "extract_codes": extract_codes,
        }

    def close(self):
        self.client.close()


def _clean_html(html: str) -> str:
    text = re.sub(r'<[^>]+>', '', html)
    text = text.replace("&ldquo;", "“").replace("&rdquo;", "”")
    text = text.replace("&hellip;", "…").replace("&mdash;", "—")
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&nbsp;", " ").replace("&quot;", '"')
    text = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), text)
    return text.strip()
