#!/usr/bin/env python3
import os
import sys
import logging
import json
import time
import hashlib
import base64
from Crypto.Cipher import AES
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5
import requests

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)

# 网易云音乐 API 相关配置
API_BASE = "https://music.163.com"
WEAPI_BASE = f"{API_BASE}/weapi"

# 加密相关常量
MODULUS = (
    "00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace619bb76329"
    "f5503f035ce0603d06980e46ea5461d3e837d0d354b85a5a63e491c69180b"
)
PUBKEY = "010001"
NONCE = b"0CoJUm6Qyw8W8jud"


c Encrypt:
    """AES 加密"""
    def __init__(self):
        self.key = NONCE

    def encrypt(self, text):
        pad = 16 - len(text) % 16
        text = text + chr(pad) * pad
        cipher = AES.new(self.key, AES.MODE_CBC, b"0102030405060708")
        encrypted = cipher.encrypt(text.encode())
        return base64.b64encode(encrypted).decode()


class RSAEncrypt:
    """RSA 加密"""
    def __init__(self):
        self.rsa_key = RSA.construct((int(MODULUS, 16), int(PUBKEY, 16)))
        self.cipher = PKCS1_v1_5.new(self.rsa_key)

    def encrypt(self, text):
        return base64.b64encode(self.cipher.encrypt(text.encode())).decode()


class NetEaseAPI:
    """网易云音乐 API 封装"""
    def __init__(self, cookie):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://music.163.com/",
            "Origin": "https://music.163.com",
            "Cookie": cookie,
            "Content-Type": "application/x-www-form-urlencoded"
        })
        self.encrypt = Encrypt().encrypt

    def _request(self, method, url, data=None):
        """发送请求"""
        try:
            if method == "POST":
                resp = self.session.post(url, data=data)
            else:
                resp = self.session.get(url, params=data)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            log.error(f"请求失败：{e}")
            return None

    def daily_signin(self, song_type=0):
        """每日签到"""
        url = f"{WEAPI_BASE}/point/dailyTask"
        data = {"type": song_type}
        result = self._request("POST", url, data)
        if result:
            code = result.get("code", -1)
            if code == 200:
                log.info(f"签到成功：{result.get('msg', '获得积分')}")
                return True
            elif code == -2:
                log.info("今日已签到")
                return True
            else:
                log.error(f"签到失败：{result}")
        return False

    def listen_music(self, song_id=1393534242, count=3):
        """模拟播放歌曲"""
        url = f"{WEAPI_BASE}/feedback/weblog"
        logs = []
        for i in range(count):
            logs.append({
                "action": "play",
                "sourceId": "",
                "alg": "",
                "type": "song",
                "trackId": song_id,
                "time": 300
            })
        data = {"logs": json.dumps(logs)}
        result = self._request("POST", url, data)
        if result:
            log.info(f"播放任务完成：播放了{count}首歌曲")
            return True
        return False


def main():
    """主函数"""
    log.info("=" * 50)
    log.info("网易云音乐自动签到")
    log.info("=" * 50)

    # 获取环境变量
    cookie = os.environ.get("NETEASE_COOKIE", "")
    user_id = os.environ.get("NETEASE_USER_ID", "")

    if not cookie:
        log.error("未找到 Cookie 配置：NETEASE_COOKIE")
        sys.exit(1)

    # 创建 API 实例
    api = NetEaseAPI(cookie)

    # 每日签到
    api.daily_signin(song_type=0)  # 手机端签到
    time.sleep(1)
    api.daily_signin(song_type=1)  # PC 端签到

    # 模拟播放
    api.listen_music(count=3)

    log.info("=" * 50)
    log.info("签到完成")
    log.info("=" * 50)


if __name__ == "__main__":
    main()
