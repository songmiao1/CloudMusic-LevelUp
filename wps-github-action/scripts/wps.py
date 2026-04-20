#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WPS daily task runner for GitHub Actions."""

from __future__ import annotations

import json
import os
import random
import smtplib
import sys
import time
from dataclasses import dataclass
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Any, Dict, List, Optional, Tuple

import requests
import urllib3
from loguru import logger


PAGE_INFO_URL = (
    "https://personal-act.wps.cn/activity-rubik/activity/page_info"
    "?activity_number=HD2025031821201822"
    "&page_number=YM2025040908558269"
    "&filter_params=%7B%22cs_from%22:%22web_vipcenter_banner_inpublic%22,"
    "%22mk_key%22:%224b9deqIfqNO3KCZrgH17WPH1kdzMoKUEvya%22,"
    "%22position%22:%22pc_aty_ban3_kaixue_test_b%22%7D"
)
COMPONENT_ACTION_URL = "https://personal-act.wps.cn/activity-rubik/activity/component_action"
TASK_INFO_URL = "https://personal-act.wps.cn/activity-rubik/user/task_center/task_info"
TASK_FINISH_URL = "https://personal-act.wps.cn/activity-rubik/user/task_center/task_finish"
SIGN_PUBLIC_KEY_URL = "https://personal-bus.wps.cn/sign_in/v1/encrypt/key"
SIGN_IN_URL = "https://personal-bus.wps.cn/sign_in/v1/sign_in"
SIGN_PAYLOAD_URL = "https://py.leishennb.icu/v1/rnl-2-gather/get-wps-publickey"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36 Edg/134.0.0.0"
)
COMMON_FILTER_PARAMS = {
    "cs_from": "web_vipcenter_banner_inpublic",
    "mk_key": "4b9deqIfqNO3KCZrgH17WPH1kdzMoKUEvya",
    "position": "pc_aty_ban3_kaixue_test_b",
}
TASK_COMPONENT = {
    "activity_number": "HD2025031821201822",
    "page_number": "YM2025040908558269",
    "component_number": "ZJ2025040709458367",
    "component_node_id": "FN1744160180RthG",
    "filter_params": COMMON_FILTER_PARAMS,
}
LOTTERY_COMPONENT = {
    "activity_number": "HD2025031821201822",
    "page_number": "YM2025040908558269",
    "component_number": "ZJ2025092916516585",
    "component_node_id": "FN1762345949vdR1",
    "filter_params": COMMON_FILTER_PARAMS,
}
SKIP_KEYWORDS = ("消费", "邀请", "微博", "苏宁易购", "开通会员")
REQUEST_TIMEOUT = 20
MAX_RETRIES = 3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def random_sleep(start: float, end: Optional[float] = None) -> float:
    if end is None:
        end = start + 1.0
    low = int(round(min(start, end) * 1000))
    high = int(round(max(start, end) * 1000))
    delay_ms = random.randint(max(low, 0), max(high, 0))
    delay = delay_ms / 1000
    time.sleep(delay)
    return delay


def parse_cookie(cookie_str: str) -> Dict[str, str]:
    cookie_dict: Dict[str, str] = {}
    for pair in cookie_str.split(";"):
        pair = pair.strip()
        if not pair:
            continue
        if "=" in pair:
            key, value = pair.split("=", 1)
            cookie_dict[key.strip()] = value.strip()
        else:
            cookie_dict[pair] = ""
    return cookie_dict


def proxy_config() -> Dict[str, str]:
    http_proxy = (
        os.getenv("WPS_HTTP_PROXY")
        or os.getenv("HTTP_PROXY")
        or os.getenv("http_proxy")
        or ""
    ).strip()
    https_proxy = (
        os.getenv("WPS_HTTPS_PROXY")
        or os.getenv("HTTPS_PROXY")
        or os.getenv("https_proxy")
        or http_proxy
    ).strip()
    proxies: Dict[str, str] = {}
    if http_proxy:
        proxies["http"] = http_proxy
    if https_proxy:
        proxies["https"] = https_proxy
    return proxies


def github_summary(text: str) -> None:
    path = os.getenv("GITHUB_STEP_SUMMARY", "").strip()
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(text.rstrip() + "\n")


def smtp_config() -> Dict[str, str]:
    return {
        "server": os.getenv("SMTP_SERVER", "").strip(),
        "ssl": os.getenv("SMTP_SSL", "false").strip().lower(),
        "email": os.getenv("SMTP_EMAIL", "").strip(),
        "password": os.getenv("SMTP_PASSWORD", "").strip(),
        "name": os.getenv("SMTP_NAME", "").strip(),
        "to": os.getenv("SMTP_TO", "").strip() or os.getenv("SMTP_EMAIL", "").strip(),
    }


def send_success_email(content: str) -> bool:
    cfg = smtp_config()
    if not all([cfg["server"], cfg["email"], cfg["password"], cfg["name"], cfg["to"]]):
        logger.warning("SMTP not configured completely, skip email notification")
        return False

    subject = f"WPS Daily Success - {time.strftime('%Y-%m-%d %H:%M:%S')}"
    msg = MIMEText(content, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header(cfg["name"], "utf-8")), cfg["email"]))
    msg["To"] = cfg["to"]

    try:
        if cfg["ssl"] == "true":
            server = smtplib.SMTP_SSL(cfg["server"])
        else:
            server = smtplib.SMTP(cfg["server"])
        server.login(cfg["email"], cfg["password"])
        server.sendmail(cfg["email"], [addr.strip() for addr in cfg["to"].split(",") if addr.strip()], msg.as_string())
        server.quit()
        logger.success("success email sent to {}", cfg["to"])
        return True
    except Exception as exc:
        logger.error("send email failed: {}", exc)
        return False


@dataclass
class Account:
    name: str
    cookie: str


class WpsClient:
    def __init__(self, account: Account) -> None:
        self.account = account
        self.cookie_dict = parse_cookie(account.cookie)
        self.user_id = self.cookie_dict.get("uid", "")
        self.csrf = self.cookie_dict.get("act_csrf_token", "")
        if not self.user_id or not self.csrf:
            raise ValueError("cookie 缺少 uid 或 act_csrf_token")

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.session.cookies.update(self.cookie_dict)
        proxies = proxy_config()
        if proxies:
            self.session.proxies.update(proxies)
            logger.info("[{}] use proxies: {}", self.account.name, proxies)
        self.logs: List[str] = []

    def _record(self, level: str, message: str) -> None:
        self.logs.append(message)
        if level == "success":
            logger.success("[{}] {}", self.account.name, message)
        elif level == "warning":
            logger.warning("[{}] {}", self.account.name, message)
        elif level == "error":
            logger.error("[{}] {}", self.account.name, message)
        else:
            logger.info("[{}] {}", self.account.name, message)

    def request(self, method: str, url: str, **kwargs: Any) -> Optional[requests.Response]:
        kwargs.setdefault("timeout", REQUEST_TIMEOUT)
        kwargs.setdefault("verify", False)
        last_error: Optional[Exception] = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return self.session.request(method=method, url=url, **kwargs)
            except requests.RequestException as exc:
                last_error = exc
                if attempt < MAX_RETRIES:
                    wait_time = 1 + attempt
                    self._record(
                        "warning",
                        f"请求失败，{wait_time} 秒后重试（第 {attempt}/{MAX_RETRIES} 次）：{exc}",
                    )
                    time.sleep(wait_time)
        self._record("error", f"请求失败：{last_error}")
        return None

    def json_or_none(self, response: Optional[requests.Response], context: str) -> Optional[Any]:
        if response is None:
            self._record("error", f"{context}失败：接口无响应")
            return None
        try:
            return response.json()
        except ValueError:
            text = response.text[:300].strip()
            self._record(
                "error",
                f"{context}失败：响应不是 JSON，status={response.status_code} body={text}",
            )
            return None

    def page_info(self) -> Optional[Dict[str, Any]]:
        headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
            "priority": "u=1, i",
            "referer": (
                "https://personal-act.wps.cn/rubik2/portal/HD2025031821201822/"
                "YM2025040908558269?cs_from=web_vipcenter_banner_inpublic"
                "&mk_key=4b9deqIfqNO3KCZrgH17WPH1kdzMoKUEvya"
                "&position=pc_aty_ban3_kaixue_test_b"
            ),
            "sec-ch-ua": '"Chromium";v="134", "Not:A-Brand";v="24", "Microsoft Edge";v="134"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
        }
        data = self.json_or_none(self.request("GET", PAGE_INFO_URL, headers=headers), "获取用户信息")
        if not data or data.get("result") != "ok":
            self._record("error", f"获取用户信息失败：{data}")
            return None

        lottery_times = None
        integral = None
        task_list = None
        for item in data.get("data", []):
            if lottery_times is None and item.get("type") == 45 and item.get("lottery_v2"):
                for session in item["lottery_v2"].get("lottery_list", []):
                    if session.get("session_id") == 2:
                        lottery_times = session.get("times")
                        break
            if integral is None:
                if item.get("task_center_user_info"):
                    integral = item["task_center_user_info"].get("integral")
                elif item.get("integral_waterfall"):
                    integral = item["integral_waterfall"].get("user_integral")
            if task_list is None and item.get("task_center"):
                task_list = item["task_center"].get("task_list")
            if lottery_times is not None and integral is not None and task_list is not None:
                break

        self._record("info", f"积分：{integral}，抽奖次数：{lottery_times}")
        return {
            "integral": integral,
            "lottery_times": lottery_times or 0,
            "task_list": task_list or [],
        }

    def get_public_key(self) -> Optional[str]:
        headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
            "origin": "https://personal-act.wps.cn",
            "priority": "u=1, i",
            "referer": "https://personal-act.wps.cn/",
            "sec-ch-ua": '"Chromium";v="134", "Not:A-Brand";v="24", "Microsoft Edge";v="134"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
        }
        data = self.json_or_none(self.request("GET", SIGN_PUBLIC_KEY_URL, headers=headers), "获取加密密钥")
        if data and data.get("code") == 1000000:
            self._record("success", "获取加密密钥成功")
            return data.get("data")
        self._record("error", f"获取加密密钥失败：{data}")
        return None

    def get_sign_payload(self, encrypt_data: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        payload = {"encryptData": encrypt_data, "userId": int(self.user_id)}
        for attempt in range(1, MAX_RETRIES + 1):
            data = self.json_or_none(
                self.request("POST", SIGN_PAYLOAD_URL, json=payload),
                "获取签到参数",
            )
            params_obj = (data or {}).get("data")
            token = None
            json_payload = None
            if isinstance(params_obj, dict):
                token = params_obj.get("token") or data.get("token")
                json_payload = params_obj.get("data")
            if token and isinstance(json_payload, dict):
                return token, json_payload
            if attempt < MAX_RETRIES:
                self._record("warning", f"获取签到参数失败，第 {attempt} 次重试")
                random_sleep(2, 3)
        self._record("error", "获取签到参数失败")
        return None, None

    def sign_in(self, encrypt_data: str) -> bool:
        token, payload = self.get_sign_payload(encrypt_data)
        if not token or not payload:
            self._record("error", "签到参数获取失败，跳过签到")
            return False
        headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
            "content-type": "application/json",
            "origin": "https://personal-act.wps.cn",
            "priority": "u=1, i",
            "referer": "https://personal-act.wps.cn/",
            "sec-ch-ua": '"Chromium";v="134", "Not:A-Brand";v="24", "Microsoft Edge";v="134"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
            "token": token,
        }
        data = self.json_or_none(self.request("POST", SIGN_IN_URL, headers=headers, json=payload), "签到")
        if not data:
            return False
        if data.get("code") == 1000000:
            rewards = ((data.get("data") or {}).get("rewards") or [{}])[0]
            reward_name = rewards.get("reward_name") or "签到奖励已到账"
            self._record("success", f"签到成功：{reward_name}")
            return True
        if "has sign" in str(data.get("msg", "")):
            self._record("info", "今天已签到")
            return True
        self._record("error", f"签到失败：{data.get('msg', '未知错误')}")
        return False

    def component_action(self, task_id: int, title: str, component_action: str) -> Any:
        headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
            "content-type": "application/json",
            "origin": "https://personal-act.wps.cn",
            "priority": "u=1, i",
            "referer": (
                "https://personal-act.wps.cn/rubik2/portal/HD2025031821201822/"
                "YM2025040908558269?cs_from=web_vipcenter_banner_inpublic"
                "&mk_key=4b9deqIfqNO3KCZrgH17WPH1kdzMoKUEvya"
                "&position=pc_aty_ban3_kaixue_test_b"
            ),
            "sec-ch-ua": '"Chromium";v="134", "Not:A-Brand";v="24", "Microsoft Edge";v="134"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "x-act-csrf-token": self.csrf,
        }
        payload = {
            "component_uniq_number": TASK_COMPONENT,
            "component_type": 35,
            "component_action": component_action,
            "task_center": {"task_id": task_id},
        }
        data = self.json_or_none(
            self.request("POST", COMPONENT_ACTION_URL, headers=headers, json=payload),
            f"执行任务 {title}",
        )
        if not data:
            return False
        if data.get("result") != "ok":
            self._record("error", f"执行任务 [{title}] 失败：{data}")
            return False
        task_center = data.get("data", {}).get("task_center", {})
        if task_center.get("success"):
            return task_center.get("token") or True
        self._record("error", f"执行任务 [{title}] 失败：{task_center.get('reason')}")
        return False

    def reward_task(self, task_id: int, title: str) -> bool:
        result = self.component_action(task_id, title, "task_center.reward")
        if result:
            self._record("success", f"领取 [{title}] 奖励成功")
            return True
        self._record("error", f"领取 [{title}] 奖励失败")
        return False

    def task_info(self, token: str) -> Optional[int]:
        headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
            "priority": "u=1, i",
            "referer": (
                "https://personal-act.wps.cn/rubik2/portal/HD2025091109421588/"
                "YM2025091121369865?cs_from=android_ucsty_rwzx&positon=ad_rwzx_task"
            ),
            "sec-ch-ua": '"Chromium";v="134", "Not:A-Brand";v="24", "Microsoft Edge";v="134"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
        }
        batch_tag = int(time.time() * 1000)
        data = self.json_or_none(
            self.request("GET", TASK_INFO_URL, headers=headers, params={"batch_tag": batch_tag, "token": token}),
            "获取浏览任务信息",
        )
        if data and data.get("result") == "ok":
            return batch_tag + data["data"]["start_at"]
        self._record("error", f"获取浏览任务信息失败：{data}")
        return None

    def task_finish(self, token: str, title: str, batch_tag: int) -> bool:
        headers = {
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json",
            "origin": "https://personal-act.wps.cn",
            "referer": (
                "https://personal-act.wps.cn/rubik2/portal/HD2025031721339450/"
                "YM2025031721331326?cs_from=ad_ucsty_rwzx&position=ad_ucsty_rwzx"
            ),
        }
        payload = {"batch_tag": batch_tag, "token": token}
        data = self.json_or_none(
            self.request("POST", TASK_FINISH_URL, headers=headers, json=payload),
            f"完成浏览任务 {title}",
        )
        if data and data.get("result") == "ok":
            self._record("success", f"任务 {title} 完成成功")
            return True
        self._record("error", f"任务 {title} 完成失败：{data}")
        return False

    def lottery(self) -> bool:
        headers = {
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json",
            "referer": (
                "https://personal-act.wps.cn/rubik2/portal/HD2025031821201822/"
                "YM2025040908558269?cs_from=web_vipcenter_banner_inpublic"
                "&mk_key=4b9deqIfqNO3KCZrgH17WPH1kdzMoKUEvya"
                "&position=pc_aty_ban3_kaixue_test_b"
            ),
            "x-act-csrf-token": self.csrf,
        }
        payload = {
            "component_uniq_number": LOTTERY_COMPONENT,
            "component_type": 45,
            "component_action": "lottery_v2.exec",
            "lottery_v2": {"session_id": 2},
        }
        data = self.json_or_none(
            self.request("POST", COMPONENT_ACTION_URL, headers=headers, json=payload),
            "抽奖",
        )
        if data and data.get("result") == "ok":
            reward_name = data["data"]["lottery_v2"]["reward_name"]
            self._record("success", f"抽奖成功：{reward_name}")
            return True
        self._record("error", f"抽奖失败：{data}")
        return False

    def run(self) -> Tuple[bool, str]:
        page = self.page_info()
        if not page:
            return False, "\n".join(self.logs)

        self._record("info", "开始执行 WPS 任务")
        random_sleep(1, 1.5)

        public_key = self.get_public_key()
        if not public_key:
            return False, "\n".join(self.logs)

        sign_ok = self.sign_in(public_key)
        random_sleep(1, 1.5)

        for task in page["task_list"]:
            task_id = task["task_id"]
            title = task["title"]
            task_status = task["task_status"]
            if task_status == 2:
                self._record("info", f"任务 [{title}] 已完成")
                continue
            if any(keyword in title for keyword in SKIP_KEYWORDS):
                self._record("info", f"跳过任务 [{title}]")
                continue
            if "浏览" in title:
                token = self.component_action(task_id, title, "task_center.start")
                if token:
                    self._record("success", f"完成任务 [{title}] 成功")
                    batch_tag = self.task_info(str(token))
                    if batch_tag:
                        random_sleep(11, 13)
                        if self.task_finish(str(token), title, batch_tag):
                            random_sleep(1, 1.5)
                            self.reward_task(task_id, title)
                    random_sleep(1.5, 2.2)
                continue

            if self.component_action(task_id, title, "task_center.finish"):
                self._record("success", f"完成任务 [{title}] 成功")
                random_sleep(1, 1.5)
                self.reward_task(task_id, title)
            random_sleep(1.5, 2.2)

        page_after = self.page_info()
        if page_after and page_after["lottery_times"] > 0:
            self._record("info", f"开始执行抽奖（剩余次数：{page_after['lottery_times']}）")
            for _ in range(page_after["lottery_times"]):
                if not self.lottery():
                    break
                random_sleep(1.5, 2.5)
        else:
            self._record("info", "无可用抽奖次数")

        self.page_info()
        self._record("info", "WPS 任务执行完成")
        summary = f"用户ID：{self.user_id}\n" + "\n".join(self.logs)
        return sign_ok, summary


def read_accounts() -> List[Account]:
    raw = os.getenv("WPS_TASK_CK", "").strip()
    accounts: List[Account] = []
    for index, line in enumerate(raw.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        if "#" in line:
            name, cookie = line.split("#", 1)
            accounts.append(Account(name=name.strip() or f"account-{index}", cookie=cookie.strip()))
        else:
            accounts.append(Account(name=f"account-{index}", cookie=line))
    return accounts


def main() -> int:
    logger.remove()
    logger.add(sys.stderr, level="INFO")

    accounts = read_accounts()
    if not accounts:
        logger.error("未配置 WPS_TASK_CK")
        github_summary("## WPS Daily\n\n- 状态: 失败\n- 原因: 未配置 `WPS_TASK_CK`")
        return 1

    logger.info("共读取到 {} 个账号", len(accounts))
    results: List[str] = []
    failed = 0

    for index, account in enumerate(accounts, start=1):
        logger.info("开始处理第 {} 个账号: {}", index, account.name)
        try:
            ok, message = WpsClient(account).run()
            results.append(f"### {account.name}\n\n```text\n{message}\n```")
            if not ok:
                failed += 1
        except Exception as exc:
            failed += 1
            error_text = f"账号 {account.name} 执行异常: {exc}"
            logger.exception(error_text)
            results.append(f"### {account.name}\n\n```text\n{error_text}\n```")

    summary = "## WPS Daily\n\n" + "\n\n".join(results)
    github_summary(summary)
    if failed == 0:
        send_success_email(summary.replace("## WPS Daily\n\n", "WPS Daily\n\n"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
