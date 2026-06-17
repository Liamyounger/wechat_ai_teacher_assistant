"""Quark cloud storage QR code login via official API.

Runs entirely on the server, so cookies are bound to the server's IP.
"""
import json
import time
import uuid
import sys
from pathlib import Path
from typing import Optional

import httpx

QR_TOKEN_URL = "https://uop.quark.cn/cas/ajax/getTokenForQrcodeLogin"
QR_STATUS_URL = "https://uop.quark.cn/cas/ajax/getServiceTicketByQrcodeToken"
QR_BASE = "https://su.quark.cn/4_eMHBJ"
USER_INFO_URL = "https://pan.quark.cn/account/info"
POLL_INTERVAL = 2
CLIENT_ID = "532"


class QuarkQrLogin:
    def __init__(self, cookies_path: str, timeout: int = 300):
        self.cookies_path = Path(cookies_path)
        self.timeout = timeout
        self.client = httpx.Client(timeout=30.0, follow_redirects=True)

    def get_qr_token(self) -> str:
        resp = self.client.get(QR_TOKEN_URL, params={
            "client_id": CLIENT_ID,
            "v": "1.2",
            "request_id": str(uuid.uuid4()),
        })
        data = resp.json()
        if data.get("status") != 2000000:
            raise RuntimeError(f"获取二维码失败: {data.get('message', data)}")
        token = data["data"]["members"]["token"]
        return token

    def build_qr_url(self, token: str) -> str:
        import urllib.parse
        params = {
            "token": token,
            "client_id": CLIENT_ID,
            "ssb": "weblogin",
            "uc_param_str": "",
            "uc_biz_str": "S:custom|OPT:SAREA@0|OPT:IMMERSIVE@1|OPT:BACK_BTN_STYLE@0",
        }
        return f"{QR_BASE}?{urllib.parse.urlencode(params)}"

    def print_qr(self, url: str):
        try:
            import qrcode
            qr = qrcode.QRCode(border=1)
            qr.add_data(url)
            qr.make(fit=True)
            qr.print_ascii(invert=True)
        except Exception:
            pass
        print(f"\n二维码链接: {url}\n")

    def check_status(self, token: str) -> Optional[str]:
        """Return service_ticket if login succeeded, None if still waiting."""
        resp = self.client.get(QR_STATUS_URL, params={
            "client_id": CLIENT_ID,
            "v": "1.2",
            "token": token,
            "request_id": str(uuid.uuid4()),
        })
        data = resp.json()
        status = data.get("status")
        if status == 2000000 and data.get("message") == "ok":
            return data["data"]["members"]["service_ticket"]
        if status == 50004001:
            return None  # still waiting
        status_msg = data.get("message", "")
        if "expired" in status_msg.lower() or status in (50004002, 50004003, 50004004):
            raise RuntimeError("二维码已过期，请重试")
        return None

    def fetch_cookies(self, service_ticket: str) -> dict[str, str]:
        """Use service_ticket to get session cookies."""
        resp = self.client.get(USER_INFO_URL, params={"st": service_ticket, "lw": "scan"})
        resp.raise_for_status()
        cookies = {}
        for cookie in self.client.cookies.jar:
            if cookie.domain and "quark.cn" in cookie.domain:
                cookies[cookie.name] = cookie.value
        if not cookies:
            raise RuntimeError("未能获取到夸克Cookie")
        return cookies

    def save_cookies(self, cookies: dict[str, str]):
        data = {
            "cookies": [{"name": k, "value": v, "domain": ".quark.cn"} for k, v in cookies.items()],
            "created_at": time.time(),
        }
        self.cookies_path.parent.mkdir(parents=True, exist_ok=True)
        self.cookies_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def run(self):
        print("正在获取夸克登录二维码...\n")
        token = self.get_qr_token()
        qr_url = self.build_qr_url(token)
        self.print_qr(qr_url)
        print("请使用夸克APP扫描上方二维码登录\n")

        start = time.time()
        while time.time() - start < self.timeout:
            try:
                ticket = self.check_status(token)
                if ticket:
                    print("扫码成功，正在获取Cookie...")
                    cookies = self.fetch_cookies(ticket)
                    self.save_cookies(cookies)
                    print(f"已保存 {len(cookies)} 个Cookie到 {self.cookies_path}")
                    return
            except RuntimeError as e:
                print(f"错误: {e}")
                sys.exit(1)
            time.sleep(POLL_INTERVAL)

        print("登录超时，请重试")
        sys.exit(1)


def run_quark_setup(cookies_path: str = "config/cookies.json"):
    QuarkQrLogin(cookies_path).run()
