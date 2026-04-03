#!/usr/bin/env python3
import os, sys, logging
try:
 import requests
except:
 print("pip install requests")
 sys.exit(1)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger()
cookie = os.environ.get("NETEASE_COOKIE", "")
if not cookie:
 log.error("No NETEASE_COOKIE")
 sys.exit(1)
s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0", "Referer": "https://music.163.com/"})
s.headers["Cookie"] = cookie
csrf = ""
for c in cookie.split(";"):
 if "__csrf=" in c:
 csrf = c.split("=")[1]
print("=" * 50)
print("网易云音乐自动签到")
print("=" * 50)
url1 = "https://music.163.com/weapi/point/dailyTask"
try:
 data = {"csrf_token": csrf}
 r = s.post(url1, data=data, timeout=30)
 js = r.json() if r.status_code == 200 else {}
 code2 = js.get("code", -1)
 if code2 == 200:
 log.info("云贝签到: 成功") n elif code2 == -2: n log.info("云贝签到: 今日已签") n else: n log.warning("云贝签到: 失败 " + str(js)) nexcept Exception as e: n log.error("云贝签到异常: " + str(e)) nurl2 = "https://music.163.com/weapi/point/vipDailyTask" ntry: n data = {"csrf_token": csrf} n r = s.post(url2, data=data, timeout=30) n js = r.json() if r.status_code == 200 else {} n code2 = js.get("code", -1) n if code2 == 200: n log.info("VIP签到: 成功") n elif code2 == -2: n log.info("VIP签到: 今日已签") n else: n log.warning("VIP签到: 失败 " + str(js)) nexcept Exception as e: n log.error("VIP签到异常: " + str(e)) nprint("=" * 50) nprint("完成")