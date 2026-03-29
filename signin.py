#!/usr/bin/env python3
"""网易云音乐自动签到脚本"""
import os, sys, random, logging
from datetime import datetime
try:
    import requests
except ImportError:
    print("请安装: pip install requests")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)

class NetEaseAPI:
    def __init__(self, cookie, user_id):
        self.cookie = cookie
        self.user_id = user_id
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://music.163.com/",
            "Cookie": cookie
        })
        self.base = "https://music.163.com/api"

    def _csrf(self):
        for x in self.cookie.split(";"):
            if "__csrf=" in x:
                return x.split("=")[1]
        return ""

    def _post(self, url):
        d = {"csrf_token": self._csrf()}
        try:
            r = self.s.post(url, data=d, timeout=30)
            return r.json() if r.status_code == 200 else {}
        except:
            return {}

    def cloud_bean(self):
        logger.info("云贝签到...")
        res = self._post(f"{self.base}/point/dailyTask")
        if res.get("code") in [200, 200002]:
            logger.info(f"云贝签到成功 +{res.get('point', 0)}")
            return True
        if res.get("code") == -2:
            logger.info("今日已签到")
            return True
        logger.warning(f"云贝签到失败: {res}")
        return False

    def vip_sign(self):
        logger.info("VIP签到...")
        res = self._post(f"{self.base}/point/vipDailyTask")
        if res.get("code") in [200, 200002]:
            logger.info(f"VIP签到成功 +{res.get('point', 0)}")
            return True
        if res.get("code") == -2:
            logger.info("今日已签到")
            return True
        logger.warning(f"VIP签到失败: {res}")
        return False

    def partner(self):
        logger.info("音乐合伙人测评...")
        try:
            r = self.s.get(f"{self.base}/music/partner/song/list", timeout=30)
            songs = r.json().get("data", []) if r.status_code == 200 else []
            cnt = 0
            for s in songs[:3]:
                sid = s.get("songId") or s.get("id")
                d = {"songId": sid, "score": random.randint(60, 100), "csrf_token": self._csrf()}
                rp = self.s.post(f"{self.base}/music/partner/score/submit", data=d, timeout=30)
                if rp.status_code == 200 and rp.json().get("code") == 200:
                    cnt += 1
            if cnt > 0:
                logger.info(f"评估了{cnt}首歌曲")
            else:
                logger.info("暂无待评歌曲")
            return True
        except Exception as e:
            logger.error(f"合伙人测评异常: {e}")
            return False

def main():
    uid = os.environ.get("NETEASE_USER_ID", "")
    ck = os.environ.get("NETEASE_COOKIE", "")
    if not uid or not ck:
        logger.error("缺少环境变量 NETEASE_USER_ID 或 NETEASE_COOKIE")
        sys.exit(1)
    
    api = NetEaseAPI(ck, uid)
    
    print("=" * 50)
    print("网易云音乐自动签到任务开始")
    print("=" * 50)
    
    results = []
    results.append(("云贝签到", api.cloud_bean()))
    results.append(("VIP签到", api.vip_sign()))
    results.append(("音乐合伙人", api.partner()))
    
    print("=" * 50)
    ok = sum(1 for _, s in results if s)
    print(f"执行完成: {ok}/{len(results)} 成功")
    
    for name, succ in results:
        print(f"{'✅' if succ else '❌'} {name}")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())