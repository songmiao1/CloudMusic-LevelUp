#!/usr/bin/env python3
import os, sys, logging, json, time
try:
    import requests
except:
    print("pip install requests")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger()

cookie = os.environ.get("NETEASE_COOKIE", "")
user_id = os.environ.get("NETEASE_USER_ID", "")

if not cookie:
    log.error("未找到 Cookie 配置：NETEASE_COOKIE")
    sys.exit(1)

s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://music.163.com/",
    "Content-Type": "application/x-www-form-urlencoded",
    "Cookie": cookie,
    "Origin": "https://music.163.com"
})

def check_in_daily():
    try:
        url = "https://music.163.com/api/point/dailyTask"
        data = "type=1" if os.environ.get("SIGN_TYPE", "0") == "1" else "type=0"
        resp = s.post(url, data=data)
        result = resp.json()
        if result.get("code") == 200:
            log.info(f"签到成功：{result.get(msg, )}")
        elif result.get("code") == -2:
            log.info("今日已签到")
        else:
            log.error(f"签到失败：{result}")
    except Exception as e:
        log.error(f"签到异常：{e}")

def listen_music():
    try:
        url = "https://music.163.com/api/feedback/weblog"
        for i in range(3):
            logs = json.dumps([{"action": "play", "type": "song", "trackId": 1393534242, "time": 300}])
            s.post(url, data={"logs": logs}, headers={"Content-Type": "application/x-www-form-urlencoded"})
            time.sleep(1)
        log.info("播放任务完成")
    except Exception as e:
        log.error(f"播放异常：{e}")

def main():
    log.info("="*50)
    log.info("网易云音乐自动签到")
    log.info("="*50)
    check_in_daily()
    listen_music()
    log.info("="*50)
    log.info("完成")
    log.info("="*50)

if __name__ == "__main__":
    main()
