import re
import logging
from urllib.parse import quote
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    " (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

SOGOU_SEARCH_URL = "https://weixin.sogou.com/weixin"


class ArticleSearcher:
    def __init__(self):
        self.client = httpx.Client(timeout=30.0, follow_redirects=True)
        self._last_query = ""

    def search(self, query: str, page: int = 1) -> dict:
        self._last_query = query
        params = {
            "type": "2",
            "query": query,
            "page": str(page),
            "ie": "utf8",
        }
        resp = self.client.get(
            SOGOU_SEARCH_URL,
            params=params,
            headers={"User-Agent": UA},
        )
        resp.raise_for_status()

        articles = self._parse_results(resp.text)
        has_more = self._has_next_page(resp.text)
        return {
            "query": query,
            "page": page,
            "articles": articles,
            "has_more": has_more,
        }

    def _parse_results(self, html: str) -> list[dict]:
        results = []

        li_items = re.findall(
            r'<li[^>]*?id="sogou_vr_\w+_box_\d+"[^>]*?>(.*?)</li>\s*(?:<!-- [a-z] -->)?',
            html, re.DOTALL
        )

        for li_html in li_items:
            article = self._parse_article(li_html)
            if article:
                results.append(article)

        return results

    def _parse_article(self, li_html: str) -> dict | None:
        # Match the <a> tag that has uigs="article_title_*" attribute
        a_match = re.search(
            r'<a\s[^>]*?\buigs="article_title_\d+"[^>]*?>(.*?)</a>',
            li_html, re.DOTALL
        )
        if not a_match:
            return None

        # Extract href from the matched tag (it can be before or after uigs)
        href_match = re.search(r'href="([^"]+)"', a_match.group(0))
        if not href_match:
            return None

        sogou_url = href_match.group(1).replace("&amp;", "&")
        title = _clean_html(a_match.group(1))

        summary_match = re.search(
            r'<p[^>]*?class="txt-info"[^>]*?>(.*?)</p>',
            li_html, re.DOTALL
        )
        summary = _clean_html(summary_match.group(1)) if summary_match else ""

        account_match = re.search(
            r'<span class="all-time-y2">(.*?)</span>',
            li_html
        )
        account = account_match.group(1).strip() if account_match else "未知公众号"

        date_match = re.search(r"timeConvert\('(\d+)'\)", li_html)
        dt_str = ""
        if date_match:
            try:
                dt = datetime.fromtimestamp(int(date_match.group(1)))
                dt_str = dt.strftime("%Y-%m-%d")
            except (ValueError, OSError):
                dt_str = ""

        img_match = re.search(r'<img src="([^"]+)"', li_html)
        cover_img = img_match.group(1) if img_match else ""

        return {
            "title": title,
            "summary": summary[:200],
            "account": account,
            "date": dt_str,
            "sogou_url": sogou_url,
            "cover_img": cover_img,
        }

    def _has_next_page(self, html: str) -> bool:
        return bool(re.search(r'class="np"', html) or re.search(r'id="sogou_next"', html))

    def resolve_article_url(self, sogou_url: str) -> str | None:
        """Resolve a Sogou redirect URL to the real mp.weixin.qq.com article URL.

        Sogou uses JavaScript to decode and redirect. We extract the URL fragments
        from the JS and reconstruct the real URL.
        """
        full_url = (
            f"https://weixin.sogou.com{sogou_url}"
            if sogou_url.startswith("/") else sogou_url
        )
        try:
            referer = (
                "https://weixin.sogou.com/weixin?"
                f"type=2&query={quote(self._last_query)}&ie=utf8"
            )
            resp = self.client.get(
                full_url,
                headers={
                    "User-Agent": UA,
                    "Referer": referer,
                },
            )
            # Sogou redirects to mp.weixin.qq.com via JavaScript, not HTTP 302.
            # The URL is split across multiple `url += '...'` statements.
            fragments = re.findall(r"url \+= '([^']*)'", resp.text)
            if fragments:
                real_url = "".join(fragments)
                if "mp.weixin.qq.com" in real_url:
                    return real_url
            logger.warning("Could not extract mp.weixin.qq.com URL from Sogou link page")
            return None
        except Exception as e:
            logger.error(f"Failed to resolve article URL: {e}")
            return None

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
