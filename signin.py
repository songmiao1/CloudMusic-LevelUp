#!/usr/bin/env python3
import json
import logging
import os
import sys
import time

import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

class NetEaseAPI:
    def __init__(self, cookie):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://music.163.com/",
            "Origin": "https://music.163.com",
            "Cookie": cookie,
            "Content-Type": "application/x-www-form-urlencoded"
        })

    def daily_signin(self, song_type=0, label="签到", optional=False):
        try:
            url = "https://music.163.com/api/point/dailyTask"
            data = f"type={song_type}"
            resp = self.session.post(url, data=data)
            result = resp.json()
            code = result.get("code", -1)
            if code == 200:
                log.info(f"{label}成功：{result.get('msg', '获得积分')}")
                return True
            elif code == -2:
                log.info(f"{label}：今日已签到")
                return True
            else:
                if optional:
                    log.warning(f"{label}未完成：{result}")
                else:
                    log.error(f"{label}失败：{result}")
        except Exception as e:
            if optional:
                log.warning(f"{label}异常：{e}")
            else:
                log.error(f"{label}异常：{e}")
        return False

    def listen_music(self, count=3):
        try:
            url = "https://music.163.com/api/feedback/weblog"
            logs = []
            for i in range(count):
                logs.append({"action": "play", "type": "song", "trackId": 1393534242, "time": 300})
            data = {"logs": json.dumps(logs)}
            resp = self.session.post(url, data=data)
            result = resp.json()
            if resp.ok:
                log.info(f"播放任务完成：播放了{count}首歌曲")
                log.info(f"播放任务响应：{result}")
                return True
            log.error(f"播放任务失败：{result}")
        except Exception as e:
            log.error(f"播放异常：{e}")
        return False

def main():
    log.info("=" * 50)
    log.info("网易云音乐自动签到")
    log.info("=" * 50)

    cookie = os.environ.get("NETEASE_COOKIE", "")
    if not cookie:
        log.error("未找到 Cookie 配置：NETEASE_COOKIE")
        sys.exit(1)

    api = NetEaseAPI(cookie)
    api.daily_signin(0, label="手机端签到")  # 手机端
    time.sleep(1)
    api.daily_signin(1, label="网页端签到", optional=True)  # PC 端
    api.listen_music(6)

    log.info("=" * 50)
    log.info("签到完成")
    log.info("=" * 50)

if __name__ == "__main__":
    main()
