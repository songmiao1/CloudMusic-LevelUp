#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bing Rewards 自动化脚本 - 浏览器自动化版 v1.0.7

包含以下功能:
1. 多账号顺序执行 (基于 bing_accounts.json 配置文件)
2. 浏览器自动登录 (支持邮箱+密码+TOTP两步验证+Authenticator，Cookie持久化免重复登录)
3. 全任务自动覆盖 (搜索、打卡、活动、积分领取、APP签到/阅读)
4. 智能防风控系统 (拟人化搜索间隔、真实热搜词库)

与旧版 (必应.py) 的区别:
- 旧版使用 Cookie + requests 纯接口方式，需手动抓取 Cookie
- 新版使用 DrissionPage 驱动 Chromium 浏览器，密码+TOTP+Authenticator自动登录
- 新版支持页面活动任务 (旧版仅支持接口可达的任务)

更新说明:

### 20260419
v1.0.7:
- 基于 v1.0.3 输出独立脚本文件 `bingRewards_v1.0.7.py`。
- 调整搜索进度解释逻辑，`0/60` 按 60 次搜索处理，不再折算成 20 次。
- 移除“积分短时间未增长即提前停止搜索”的中断逻辑，搜索任务按目标次数完整执行。
- 统一移动端状态、页面解析和最终汇总中的搜索次数展示。

### 20260418
v1.0.5:
- 由摸鱼哥：958655269@qq.com调教AI修复
- 修复新版积分页任务流程异常，补全 Punch Card 与领奖相关方法绑定。
- 重构 Punch Card 执行逻辑，提升多任务场景下的稳定性。
- 优化积分页活动任务处理，降低页面连接断开风险。
- 修复最终积分可能被异常结果覆盖为 0 的问题。
- 优化搜索进度获取方式，改为优先读取移动端接口数据。
- 优化通知推送逻辑，支持每次执行均推送结果。
- 优化青龙环境下的 notify.py 兼容性。
- 优化登录、Token 缓存、Edge 浏览打卡等流程稳定性。
- 当前版本已实测：登录、搜索、Punch Card、活动任务、积分检查、APP 签到、Edge 打卡、APP 阅读、推送均正常。

### 20260308
v1.0.0:
- 基于旧版重构为浏览器自动化版，支持自动登录、页面活动、积分领取等全流程
- 修复登录检测、积分领取、日志输出等多项问题


配置说明:
1. 账号配置文件: bing_accounts.json (与脚本同目录)
   格式:
   [
     {
       "username": "your_email@example.com",
       "password": "your_password",
       "otpauth": "otpauth://totp/...?secret=YOUR_SECRET"  // 可选，2FA 密钥
     }
   ]

2. 运行环境要求:
   - Linux: 需安装 chromium、chromium-chromedriver、xvfb
   - Windows: 需安装 Chrome/Edge 浏览器
   - 青龙面板: 添加上述系统依赖

3. 数据存储:
   - user_data_<用户名>/: 浏览器用户数据 (Cookie 持久化)
   - user_data_<用户名>/app_token.txt: APP 刷新令牌
   - debug/: 调试截图和 HTML

定时规则建议 (Cron):
10 0-22 * * *

⚠️ 依赖安装:
pip3 install requests loguru pyotp DrissionPage pyvirtualdisplay

From: yaohuo8648
Email: zheyizzf@188.com
Update: 2026.03.08
"""

import os
import json
import random
import time
import functools
import sys
import re
import subprocess
from http.cookies import SimpleCookie
import pyotp
import requests
import secrets
import threading
import uuid
from datetime import datetime, date
from enum import Enum
from loguru import logger
from dataclasses import dataclass
from typing import Dict, Any, Optional, List

VERSION = "v1.0.7"

SCRIPT_DIR = os.path.dirname(__file__)
BASE_DIR = os.path.abspath(os.environ.get("BING_DATA_DIR", SCRIPT_DIR))
DEBUG_DIR = os.path.abspath(os.environ.get("BING_DEBUG_DIR", os.path.join(BASE_DIR, "debug")))


def _data_path(*parts: str) -> str:
    return os.path.join(BASE_DIR, *parts)


def _user_data_dir(username: str) -> str:
    return _data_path(f"user_data_{email_name(username)}")


# 任务执行配置
REQUEST_TIMEOUT = 15
CACHE_FILE = _data_path("bing_cache.json")

# 日志配置
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> <level>| {level: <7} |</level> <level>{message}</level>",
    level="INFO"
)

# 日志常量
class LogTag:
    SYSTEM   = "[System]"
    LOGIN    = "[Login]"
    ACCOUNT  = "[Account]"
    POINTS   = "[Points]"
    SEARCH   = "[Search]"
    ACTIVITY = "[Activity]"
    READ     = "[Read]"

class LogIcon:
    START   = "🚀"
    SUCCESS = "✅"
    FAIL    = "❌"
    WARN    = "⚠️"
    INFO    = "📋"
    DATA    = "📊"
    NOTE    = "📝"
    STAR    = "✨"
    UP      = "📈"
    TARGET  = "🎯"
    GIFT    = "🎁"
    KEY     = "🔑"
    CLEAN   = "🧹"
    SEARCH  = "🔍"
    READ    = "📖"
    MOBILE  = "📱"
    BELL    = "🔔"  # <--- 新增这一行

class LogIndent:
    ITEM = "   ├── "
    END  = "   └── "

def email_mask(email):
    """邮箱打码：显示前3位和@后的域名，中间用***代替"""
    if not email or '@' not in email:
        return email
    local, domain = email.split('@', 1)
    if len(local) <= 3:
        return f"{local}***@{domain}"
    return f"{local[:3]}***{local[-2:]}@{domain}"

def email_name(email):
    if not email or '@' not in email:
        return email
    return email.split('@')[0]


try:
    from pyvirtualdisplay import Display
    HAS_DISPLAY = True
except ImportError:
    logger.warning(f"{LogIcon.WARN} {LogTag.SYSTEM} 未安装 pyvirtualdisplay")
    HAS_DISPLAY = False


def retry_decorator(retries=3):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == retries - 1:
                        logger.error(f"{LogIcon.FAIL} {LogTag.SYSTEM} 函数 [{func.__name__}] 最终失败: {str(e)}")
                    else:
                        logger.warning(f"{LogIcon.WARN} {LogTag.SYSTEM} 函数 [{func.__name__}] 第 {attempt+1}/{retries} 次尝试失败")
                        time.sleep(2)
            return None
        return wrapper
    return decorator

os.environ.pop("DISPLAY", None)

os.makedirs(BASE_DIR, exist_ok=True)
os.makedirs(DEBUG_DIR, exist_ok=True)

ACCOUNTS_FILE = _data_path("bing_accounts.json")

BING_DOMAIN = "bing.com"
REWARDS_DOMAIN = "rewards.bing.com"
BING_URL = "https://www.bing.com/"
REWARDS_BASE_URL = "https://rewards.bing.com"
SEARCH_HOME_CN_URL = "https://cn.bing.com/?form=ML2PCO"
SEARCH_REQUEST_URL = "https://cn.bing.com/search"
REWARDS_URL = f"{REWARDS_BASE_URL}/dashboard"
REWARDS_EARN_URL = f"{REWARDS_BASE_URL}/earn"
REWARDS_POINTS_URL = f"{REWARDS_BASE_URL}/pointsbreakdown"
DESKTOP_EDGE_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0"
)

OAUTH_CLIENT_ID = "0000000040170455"
OAUTH_REDIRECT_URI = "https://login.live.com/oauth20_desktop.srf"
OAUTH_SCOPE = "service::prod.rewardsplatform.microsoft.com::MBI_SSL"
OAUTH_AUTHORIZE_URL = (
    f"https://login.live.com/oauth20_authorize.srf"
    f"?client_id={OAUTH_CLIENT_ID}"
    f"&scope={OAUTH_SCOPE}"
    f"&response_type=code"
    f"&redirect_uri={OAUTH_REDIRECT_URI}"
)
OAUTH_TOKEN_URL = "https://login.live.com/oauth20_token.srf"


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


SKIP_DEVICE_SECURITY = _env_bool(
    "BING_SKIP_DEVICE_SECURITY",
    default=(os.environ.get("QL_DIR") is not None or "ql/data/scripts" in os.path.abspath(__file__))
)
SCHEDULE_RUN = _env_bool("BING_SCHEDULE_RUN", default=False)



def request_oauth_token(token_data: dict, timeout: int = 20, retries: int = 3) -> Optional[dict]:
    headers = {
        "Connection": "close",
        "User-Agent": "Mozilla/5.0",
    }

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(OAUTH_TOKEN_URL, data=token_data, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                result = resp.json()
                if isinstance(result, dict):
                    return result
            last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
        except Exception as e:
            last_error = str(e)
        time.sleep(min(2 * attempt, 5))

    try:
        cmd = ["curl", "-sS", "--http1.1", "--max-time", str(timeout), OAUTH_TOKEN_URL]
        for key, value in token_data.items():
            cmd.extend(["-d", f"{key}={value}"])
        resp = subprocess.run(cmd, capture_output=True, text=True, check=False)
        output = (resp.stdout or resp.stderr or "").strip()
        if resp.returncode == 0 and output:
            result = json.loads(output)
            if isinstance(result, dict):
                return result
        last_error = output[:200] if output else f"curl exit {resp.returncode}"
    except Exception as e:
        last_error = f"curl fallback failed: {e}"

    if last_error:
        logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} OAuth token 请求失败: {last_error}")
    return None


class NotificationManager:
    """推送通知管理器（兼容青龙面板 notify 模块）"""
    
    def __init__(self):
        self._client = self._init_client()
    
    def _init_client(self):
        try:
            import notify
            return notify
        except ImportError:
            return self._create_mock()
    
    def _create_mock(self):
        class MockNotify:
            def send(self, title, content):
                print(f"\n--- [通知] ---")
                print(f"标题: {title}")
                print(f"内容:\n{content}")
                print("-------------------------------")
        return MockNotify()
    
    def send(self, title: str, content: str) -> bool:
        try:
            return bool(self._client.send(title, content))
        except Exception as e:
            logger.warning(f"{LogIcon.WARN} 推送通知失败: {e}")
            return False


class CacheManager:
    """缓存管理器 - 原子写入 + 兼容旧字段"""

    def __init__(self):
        self.cache_file = CACHE_FILE
        self.lock = threading.Lock()

    def _load(self) -> dict:
        if not os.path.exists(self.cache_file):
            return {}
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                return json.loads(content) if content else {}
        except Exception:
            return {}

    def _save(self, data: dict):
        temp_file = f"{self.cache_file}.tmp.{threading.get_ident()}"
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(temp_file, self.cache_file)
        except Exception as e:
            logger.warning(f"{LogIcon.WARN} 缓存保存失败: {e}")
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except Exception:
                pass

    def _clean_expired(self, data: dict) -> dict:
        today = date.today().isoformat()
        cleaned = {}
        for k, v in data.items():
            if k.startswith("push_") or k.startswith("complete_"):
                continue
            if k in ("push", "push_date", "tasks_complete", "tasks_complete_date"):
                continue
            cleaned[k] = v
        if cleaned.get("daily_date") != today:
            cleaned["daily_date"] = today
            cleaned.pop("daily_push", None)
            cleaned.pop("daily_complete", None)
        return cleaned

    def has_pushed_today(self) -> bool:
        today = date.today().isoformat()
        data = self._load()
        if data.get("daily_date") == today:
            return bool(data.get("daily_push", False))
        return bool(data.get(f"push_{today}", False) or (data.get("push") and data.get("push_date") == today))

    def mark_pushed_today(self):
        with self.lock:
            data = self._clean_expired(self._load())
            data["daily_date"] = date.today().isoformat()
            data["daily_push"] = True
            self._save(data)

    def get_complete_count(self) -> int:
        today = date.today().isoformat()
        data = self._load()
        if data.get("daily_date") == today:
            try:
                return max(0, int(data.get("daily_complete", 0)))
            except Exception:
                return 0
        legacy_val = data.get(f"complete_{today}")
        if legacy_val is not None:
            try:
                return max(0, int(legacy_val))
            except Exception:
                return 0
        if data.get("tasks_complete_date") == today:
            try:
                return max(0, int(data.get("tasks_complete", 0)))
            except Exception:
                return 0
        return 0

    def increment_complete_count(self):
        with self.lock:
            data = self._clean_expired(self._load())
            current = self.get_complete_count()
            new_count = current + 1
            data["daily_date"] = date.today().isoformat()
            data["daily_complete"] = new_count
            self._save(data)
            return new_count

    def should_skip(self) -> bool:
        return False


# 全局实例
notify_mgr = NotificationManager()
cache_mgr = CacheManager()


class AccountStorage:
    """账号和Token存储管理"""
    
    @staticmethod
    def get_accounts():
        if not os.path.exists(ACCOUNTS_FILE):
            logger.error(f"{LogIcon.FAIL} {LogTag.ACCOUNT} 未找到账号文件: {ACCOUNTS_FILE}")
            return []
        try:
            with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            accounts = []
            for i, acc in enumerate(data):
                if acc.get("username") and acc.get("password"):
                    accounts.append({
                        "index": i + 1,
                        "username": acc["username"],
                        "password": acc["password"],
                        "otpauth": acc.get("otpauth", "")
                    })
            return accounts
        except Exception as e:
            logger.error(f"{LogIcon.FAIL} {LogTag.ACCOUNT} 读取账号文件异常: {e}")
            return []
    
    @staticmethod
    def _get_token_path(username):
        return os.path.join(_user_data_dir(username), "app_token.txt")
    
    @staticmethod
    def get_token(username):
        token_path = AccountStorage._get_token_path(username)
        if not os.path.exists(token_path):
            return None
        try:
            with open(token_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception as e:
            logger.error(f"{LogIcon.FAIL} {LogTag.LOGIN} 读取Token失败: {e}")
        return None

    @staticmethod
    def save_token(username, token):
        token_path = AccountStorage._get_token_path(username)
        try:
            os.makedirs(os.path.dirname(token_path), exist_ok=True)
            with open(token_path, "w", encoding="utf-8") as f:
                f.write(token)
            logger.success(f"{LogIcon.SUCCESS} {LogTag.LOGIN} Token 已保存")
            return True
        except Exception as e:
            logger.error(f"{LogIcon.FAIL} {LogTag.LOGIN} 保存Token异常: {e}")
        return False

class HotWordsManager:
    def __init__(self):
        self.hot_words = []
        self._fetched = False

    def _fetch_hot_words(self, max_count=40):
        apis = [
            ("https://dailyapi.eray.cc/", ["weibo", "douyin", "baidu", "toutiao", "thepaper", "qq-news", "netease-news", "zhihu"]),
            ("https://cnxiaobai.com/DailyHotApi/", ["weibo", "douyin", "baidu", "toutiao", "thepaper", "qq-news", "netease-news", "zhihu"]),
            ("https://hotapi.nntool.cc/", ["weibo", "douyin", "baidu", "toutiao", "thepaper", "qq-news", "netease-news", "zhihu"]),
        ]
        random.shuffle(apis)
        for base_url, sources in apis:
            random.shuffle(sources)
            for source in sources:
                try:
                    resp = requests.get(base_url + source, timeout=10)
                    if resp.status_code == 200:
                        data = resp.json()
                        if isinstance(data, dict) and 'data' in data:
                            titles = [item.get('title') for item in data['data'] if isinstance(item, dict) and item.get('title')]
                            if titles:
                                random.shuffle(titles)
                                logger.info(f"{LogIcon.DATA} {LogTag.SEARCH} 获取热搜词 {len(titles)} 条")
                                return titles[:max_count]
                except Exception:
                    continue
        fallback = ["微软必应积分", "今天天气", "科技新闻", "人工智能", "国际新闻", "体育新闻"]
        random.shuffle(fallback)
        return fallback[:max_count]

    def ensure_loaded(self):
        if not self._fetched or not self.hot_words:
            self.hot_words = self._fetch_hot_words()
            self._fetched = True

    def refresh_hot_words(self):
        self.hot_words = self._fetch_hot_words()
        self._fetched = True

    def get_random_word(self):
        self.ensure_loaded()
        if not self.hot_words:
            self.refresh_hot_words()
        return self.hot_words.pop() if self.hot_words else "微软必应"


class BrowserManager:
    """浏览器和虚拟显示器管理"""
    
    _active_browsers = []
    
    def __init__(self, username: str = ""):
        self.display = None
        self.browser = None
        self.page = None
        self.username = username
        self._init_display()
        self._init_browser()
        BrowserManager._active_browsers.append(self)

    def _init_display(self):
        if HAS_DISPLAY and sys.platform.startswith("linux"):
            try:
                self.display = Display(visible=0, size=(1920, 1080))
                self.display.start()
                logger.info(f"{LogTag.SYSTEM} 虚拟显示器启动成功")
            except Exception as e:
                logger.error(f"{LogIcon.FAIL} {LogTag.SYSTEM} 虚拟显示器启动失败: {e}")

    def _init_browser(self):
        from DrissionPage import ChromiumOptions, Chromium
        co = ChromiumOptions()
        co.headless(False)
        if self.username:
            co.set_user_data_path(_user_data_dir(self.username))
        
        co.set_argument("--no-sandbox")
        co.set_argument("--disable-gpu")
        co.set_argument("--disable-dev-shm-usage")
        co.set_argument("--window-size=1920,1080")
        co.set_argument("--mute-audio")
        co.set_argument("--lang=zh-CN")
        co.set_argument("--accept-lang=zh-CN,zh;q=0.9")
        co.set_argument("--disable-blink-features=AutomationControlled")
        co.set_argument("--disable-features=AutomationControlled")
        co.set_argument(f"--user-agent={DESKTOP_EDGE_UA}")
        proxy_server = os.environ.get("BING_BROWSER_PROXY_SERVER", "").strip()
        if proxy_server:
            co.set_argument(f"--proxy-server={proxy_server}")
            logger.info(f"{LogTag.SYSTEM} 浏览器代理已启用: {proxy_server}")
        co.set_pref("intl.accept_languages", "zh-CN,zh")
        co.set_argument("--disable-password-manager-reauthentication")
        co.set_pref("profile.managed_default_content_settings.images", 2)
        co.set_argument("--autoplay-policy=no-user-gesture-required")
        co.set_pref("profile.managed_default_content_settings.media_stream", 2)

        for path in ["/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome"]:
            if os.path.exists(path):
                co.set_browser_path(path)
                break

        try:
            self.browser = Chromium(co)
            self.page = self.browser.latest_tab
            logger.info(f"{LogTag.SYSTEM} 浏览器启动成功")
        except Exception as e:
            logger.error(f"{LogIcon.FAIL} {LogTag.SYSTEM} 浏览器启动失败: {e}")
            self.cleanup()
            sys.exit(1)

    def save_screenshot(self, filename_prefix="debug"):
        try:
            timestamp = time.strftime("%m%d%H%M%S")
            filepath = os.path.join(DEBUG_DIR, f"{filename_prefix}_{timestamp}.png")
            self.page.get_screenshot(path=filepath)
            logger.info(f"{LogTag.SYSTEM} 截图已保存: {filepath}")
            return filepath
        except Exception as e:
            logger.info(f"{LogTag.SYSTEM} 保存截图失败: {e}")
            return None

    def save_html(self, filename_prefix="debug"):
        try:
            timestamp = time.strftime("%m%d%H%M%S")
            filepath = os.path.join(DEBUG_DIR, f"{filename_prefix}_{timestamp}.html")
            content = self.page.html or ""
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            logger.info(f"{LogTag.SYSTEM} HTML已保存: {filepath}")
            return filepath
        except Exception as e:
            logger.info(f"{LogTag.SYSTEM} 保存HTML失败: {e}")
            return None

    def cleanup(self):
        try:
            if self.browser:
                self.browser.quit()
        except:
            pass
        try:
            if self.display:
                self.display.stop()
        except:
            pass
        logger.info(f"{LogIcon.CLEAN} {LogTag.SYSTEM} 浏览器已关闭")
        if self in BrowserManager._active_browsers:
            BrowserManager._active_browsers.remove(self)
    
    @staticmethod
    def cleanup_all():
        for mgr in list(BrowserManager._active_browsers):
            try:
                mgr.cleanup()
            except:
                pass
        BrowserManager._active_browsers.clear()


class SiteType(Enum):
    BING = "bing"
    REWARDS = "rewards"
    LIVE = "live"

@dataclass
class SiteConfig:
    name: str
    home_url: str

LIVE_DOMAIN = "account.live.com"
LIVE_URL = "https://account.live.com/"

SITE_CONFIGS = {
    SiteType.BING: SiteConfig(BING_DOMAIN, BING_URL),
    SiteType.REWARDS: SiteConfig(REWARDS_DOMAIN, REWARDS_URL),
    SiteType.LIVE: SiteConfig(LIVE_DOMAIN, LIVE_URL),
}


class AuthManager:
    """统一认证管理器"""
    
    def __init__(self, browser_mgr):
        self.browser_mgr = browser_mgr
        self.page = browser_mgr.page
        self._login_status: Dict[SiteType, bool] = {
            SiteType.BING: False,
            SiteType.REWARDS: False,
            SiteType.LIVE: False
        }

    def is_site_logged_in(self, site: SiteType) -> bool:
        return bool(self._login_status.get(site, False))

    def _get_cookie_snapshot_path(self, username: str) -> str:
        return os.path.join(_user_data_dir(username), "browser_cookies.txt")

    def _restore_site_cookies_from_snapshot(self, username: str, site: SiteType) -> bool:
        snapshot_path = self._get_cookie_snapshot_path(username)
        if not os.path.exists(snapshot_path):
            return False

        try:
            raw = open(snapshot_path, "r", encoding="utf-8", errors="ignore").read().strip()
            if not raw:
                return False

            parsed = SimpleCookie()
            parsed.load(raw)
            if "_U" not in parsed:
                return False

            cookies = []
            for name in ("_U", "MUID", "MUIDB", "SRCHUID", "SRCHUSR", "SRCHHPGUSR", "_RwBf", "ANON", "MSCC"):
                if name not in parsed:
                    continue
                cookies.append({
                    "name": name,
                    "value": parsed[name].value,
                    "domain": ".bing.com",
                    "path": "/",
                })

            if "WLS" in parsed:
                cookies.append({
                    "name": "WLS",
                    "value": parsed["WLS"].value,
                    "domain": ".live.com",
                    "path": "/",
                })

            if "MSPRequ" in parsed:
                cookies.append({
                    "name": "MSPRequ",
                    "value": parsed["MSPRequ"].value,
                    "domain": ".login.live.com",
                    "path": "/",
                })

            if not cookies:
                return False

            self.page.set.cookies(cookies)
            logger.info(f"{LogIndent.ITEM}{LogIcon.SUCCESS} 已从本地 Cookie 快照恢复 {SITE_CONFIGS[site].name} 登录态")
            return True
        except Exception as e:
            logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 恢复 {SITE_CONFIGS[site].name} Cookie 快照失败: {e}")
            return False

    def ensure_site_logged_in(self, site: SiteType, username: str, password: str, 
                               otpauth: str = "", account_index: int = 1) -> bool:
        """确保站点已登录: 访问 -> 检查 -> 未登录则登录 -> 再检查（含整体重试）"""
        config = SITE_CONFIGS[site]
        max_site_attempts = 2
        
        for attempt in range(max_site_attempts):
            if attempt > 0:
                logger.info(f"{LogIndent.ITEM}{LogTag.LOGIN} 重新尝试 {config.name} ({attempt+1}/{max_site_attempts})...")
            else:
                logger.info(f"{LogIndent.ITEM}{LogTag.LOGIN} 访问 {config.name}...")
            
            try:
                # 1. 访问
                self.page.get(config.home_url)
                try:
                    self.page.wait.load_start(timeout=30)
                except:
                    pass
                time.sleep(random.uniform(2, 3))

                if site in (SiteType.BING, SiteType.REWARDS, SiteType.LIVE):
                    restored = self._restore_site_cookies_from_snapshot(username, site)
                    if restored:
                        time.sleep(random.uniform(1, 2))
                        try:
                            self.page.refresh()
                            time.sleep(random.uniform(3, 5))
                        except Exception:
                            pass
                        if not self._is_logged_in(site):
                            revisit_urls = [config.home_url]
                            if site == SiteType.REWARDS:
                                revisit_urls = [REWARDS_URL, REWARDS_EARN_URL, config.home_url]
                            elif site == SiteType.LIVE:
                                revisit_urls = [LIVE_URL, "https://account.microsoft.com/"]
                            for revisit_url in revisit_urls:
                                try:
                                    self.page.get(revisit_url)
                                    time.sleep(random.uniform(3, 5))
                                    if self._is_logged_in(site):
                                        logger.info(f"{LogIndent.ITEM}{LogIcon.SUCCESS} {config.name} 快照恢复后复检成功")
                                        self._login_status[site] = True
                                        return True
                                except Exception:
                                    continue
                
                # 2. 检查登录
                if self._is_logged_in(site):
                    logger.info(f"{LogIndent.ITEM}{LogIcon.SUCCESS} {config.name} 已登录")
                    self._login_status[site] = True
                    return True
                
                logger.info(f"{LogIndent.ITEM}{LogTag.LOGIN} {config.name} 未登录，开始登录...")
                
                # 3. 跳转登录页
                if not self._goto_login_page(site):
                    logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 无法跳转到登录页面")
                    if attempt < max_site_attempts - 1:
                        logger.info(f"{LogIndent.ITEM}{LogTag.LOGIN} 等待后重试...")
                        time.sleep(random.uniform(3, 5))
                        continue
                    logger.error(f"{LogIndent.ITEM}{LogIcon.FAIL} 无法跳转到登录页面（已重试）")
                    break
                
                # 4. 执行登录
                if not self._do_login(username, password, otpauth):
                    logger.error(f"{LogIndent.ITEM}{LogIcon.FAIL} {config.name} 登录失败")
                    break
                
                # 5. 登录完成，再次检查
                logger.info(f"{LogIndent.ITEM}{LogTag.LOGIN} 登录完成，再次检查 {config.name}...")
                for verify_attempt in range(3):
                    self.page.get(config.home_url)
                    try:
                        self.page.wait.load_start(timeout=30)
                    except:
                        pass
                    time.sleep(random.uniform(3, 5))
                    
                    if self._is_logged_in(site):
                        logger.info(f"{LogIndent.ITEM}{LogIcon.SUCCESS} {config.name} 登录成功")
                        self._login_status[site] = True
                        return True
                    
                    if verify_attempt < 2:
                        logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 第 {verify_attempt+1} 次验证未通过，刷新重试...")
                        try:
                            self.page.refresh()
                            time.sleep(random.uniform(3, 5))
                            if self._is_logged_in(site):
                                logger.info(f"{LogIndent.ITEM}{LogIcon.SUCCESS} {config.name} 刷新后登录成功")
                                self._login_status[site] = True
                                return True
                        except:
                            pass
                
                logger.error(f"{LogIndent.ITEM}{LogIcon.FAIL} {config.name} 登录后检查失败")
                self.browser_mgr.save_screenshot(f"login_verify_fail_{site.value}")
                self.browser_mgr.save_html(f"login_verify_fail_{site.value}")
                break
            except Exception as e:
                logger.error(f"{LogIndent.ITEM}{LogIcon.FAIL} {config.name} 登录过程异常: {e}")
                if attempt < max_site_attempts - 1:
                    logger.info(f"{LogIndent.ITEM}{LogTag.LOGIN} 等待后重试...")
                    time.sleep(random.uniform(3, 5))
                    continue
                break
        
        self._login_status[site] = False
        return False
    
    def ensure_all_logged_in(self, username: str, password: str, 
                              otpauth: str = "", account_index: int = 1) -> bool:
        """确保核心站点已登录，Bing 站点允许降级"""
        logger.info(f"{LogIcon.KEY} {LogTag.LOGIN} 账号{account_index} 开始登录流程...")
        logger.info(f"{LogIndent.ITEM}邮箱: {email_mask(username)}")

        bing_ok = self.ensure_site_logged_in(SiteType.BING, username, password, otpauth, account_index)
        rewards_ok = self.ensure_site_logged_in(SiteType.REWARDS, username, password, otpauth, account_index)
        live_ok = self.ensure_site_logged_in(SiteType.LIVE, username, password, otpauth, account_index)

        if not rewards_ok:
            saved_token = AccountStorage.get_token(username)
            if SKIP_DEVICE_SECURITY and saved_token:
                logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} rewards.bing.com 未登录，定时任务模式降级为接口任务继续执行")
            else:
                logger.error(f"{LogIndent.END}{LogIcon.FAIL} 核心站点 rewards.bing.com 登录失败")
                return False

        if not bing_ok:
            logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} bing.com 未登录，继续执行非搜索任务")
        if not live_ok:
            logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} account.live.com 未登录，继续执行主流程")

        logger.info(f"{LogIndent.END}{LogIcon.SUCCESS} 核心站点登录完成")
        return True

    def _is_logged_in(self, site: SiteType) -> bool:
        """检查是否已登录"""
        current_url = ""
        page_html = ""
        for content_retry in range(3):
            try:
                current_url = self.page.url or ""
                page_html = self.page.html or ""
                break
            except Exception:
                if content_retry < 2:
                    logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 获取页面内容超时，刷新重试 ({content_retry+1}/2)...")
                    try:
                        self.page.refresh()
                        time.sleep(random.uniform(3, 5))
                    except Exception:
                        time.sleep(3)
                else:
                    logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 获取页面内容多次超时，跳过检查")
                    return False
        
        if "login.live.com" in current_url or "login.microsoftonline.com" in current_url:
            return False
        if "signin" in current_url.lower():
            return False
        
        has_user_info = '"displayName":"' in page_html or '"userDisplayName":"' in page_html
        
        if site == SiteType.BING:
            user_name_ele = self.page.ele('#id_n', timeout=2)
            if user_name_ele and user_name_ele.text and user_name_ele.text.strip():
                return True
            avatar_ele = self.page.ele('#id_p', timeout=1)
            if avatar_ele:
                avatar_src = avatar_ele.attr('src') or ""
                if avatar_src and 'base64' not in avatar_src and avatar_src.startswith('http'):
                    return True
            try:
                for cookie in self.page.cookies(all_domains=True):
                    if cookie.get("name") == "_U" and "bing.com" in str(cookie.get("domain", "")):
                        return True
            except Exception:
                pass
            login_btn = self.page.ele('#id_l', timeout=1)
            if login_btn:
                btn_text = (login_btn.text or "").strip().lower()
                aria = (login_btn.attr('aria-label') or "").strip().lower()
                title = (login_btn.attr('title') or "").strip().lower()
                login_markers = ("登录", "sign in", "signin")
                if any(marker in btn_text for marker in login_markers) or any(marker in aria for marker in login_markers) or any(marker in title for marker in login_markers):
                    return False
            if has_user_info:
                return True
            return False
        elif site == SiteType.REWARDS:
            if '"balance"' in page_html or "availablePoints" in page_html:
                return True
            return REWARDS_DOMAIN in current_url
        elif site == SiteType.LIVE:
            if has_user_info:
                return True
            if "account.live.com" in current_url or "account.microsoft.com" in current_url:
                return True
            if REWARDS_DOMAIN in current_url and ("availablePoints" in page_html or '"balance"' in page_html):
                return True
        return False

    def _goto_login_page(self, site: SiteType) -> bool:
        current_url = self.page.url or ""
        if "login.live.com" in current_url or "login.microsoftonline.com" in current_url:
            return True
        
        if site == SiteType.BING:
            login_btn = self.page.ele('#id_l', timeout=3)
            if login_btn:
                logger.info(f"{LogIndent.ITEM}{LogTag.LOGIN} 点击登录按钮...")
                login_btn.click()
                time.sleep(random.uniform(5, 8))
        
        return self._wait_for_login_page(timeout=15)
    
    def _wait_for_login_page(self, timeout: int = 15) -> bool:
        for _ in range(timeout):
            current_url = self.page.url or ""
            if "login.live.com" in current_url or "login.microsoftonline.com" in current_url:
                return True
            if self.page.ele("#usernameEntry", timeout=0.3) or self.page.ele("#i0116", timeout=0.3):
                return True
            time.sleep(1)
        return False
    def _do_login(self, username: str, password: str, otpauth: str) -> bool:
        time.sleep(2)
        last_page_type = None
        repeat_count = 0
        
        for _ in range(15):
            page_type = self._detect_page_type()
            logger.info(f"{LogIndent.ITEM}当前页面: {page_type}")

            if page_type == last_page_type:
                repeat_count += 1
                # 放宽重复判定到 3 次，防止网络卡顿被误判死循环
                if repeat_count >= 3:
                    logger.error(f"{LogIndent.ITEM}{LogIcon.FAIL} 页面类型重复出现 {repeat_count} 次，终止登录")
                    self.browser_mgr.save_screenshot(f"login_repeat_{page_type}")
                    self.browser_mgr.save_html(f"login_repeat_{page_type}")
                    return False
            else:
                repeat_count = 0
                last_page_type = page_type
            
            if page_type == "success":
                return True
            elif page_type == "error":
                self.browser_mgr.save_screenshot("login_error_page")
                self.browser_mgr.save_html("login_error_page")
                return False
            elif page_type == "email":
                if not self._input_email(username):
                    return False
            elif page_type == "select_method":
                self._select_password_login()
            elif page_type == "password":
                if not self._input_password(password):
                    return False
            elif page_type == "authenticator":
                # [新增] 处理 Authenticator 验证分支
                if not self._handle_authenticator():
                    return False
            elif page_type == "device_security":
                if SKIP_DEVICE_SECURITY:
                    logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 定时任务模式跳过 device_security，放弃当前站点网页登录")
                    return False
                if not self._handle_device_security():
                    return False
            elif page_type == "2fa":
                if not self._handle_2fa(otpauth):
                    return False
            elif page_type == "stay_signed_in":
                self._click_stay_signed_in()
            elif page_type == "msa_upsell":
                self._handle_msa_upsell()
            elif page_type == "send_code_page":
                self._click_use_password()
            elif page_type == "account_confirm":
                self._click_account_confirm()
            else:
                time.sleep(2)
            time.sleep(2)
        return False
    
    def _detect_page_type(self) -> str:
        current_url = self.page.url or ""
        page_html = self.page.html or ""
        page_text_lower = page_html.lower()
        page_title = self.page.title or ""

        from urllib.parse import urlparse
        parsed = urlparse(current_url)
        url_host_path = (parsed.netloc + parsed.path).lower()
        
        is_login_page = "login." in url_host_path or "/login" in url_host_path or "signin" in url_host_path
        
        if not is_login_page:
            if any(x in current_url for x in [BING_DOMAIN, "account.live.com", "account.microsoft.com"]):
                return "success"

        error_patterns = [
            "已被锁定", "密码不正确", "your account has been locked",
            "account doesn't exist", "that microsoft account doesn't exist",
            "账户不存在", "sign-in was blocked", "登录被阻止",
        ]
        for e in error_patterns:
            if e.lower() in page_text_lower:
                return "error"

        if self.page.ele("#usernameEntry", timeout=0.3) or self.page.ele("#i0116", timeout=0.3):
            return "email"
        
        if self._find_password_input(timeout=0.3):
            return "password"
        
        device_security_patterns = [
            "人脸、指纹、pin 或安全密钥",
            "你的设备将打开一个安全窗口",
            "按照该处的说明登录",
            "security window",
            "passkey",
        ]
        if self.page.ele('#idBtn_Back', timeout=0.2) and self.page.ele('#idSIButton9', timeout=0.2):
            for marker in device_security_patterns:
                if marker.lower() in page_text_lower:
                    return "device_security"

        # [新增] 检测 Authenticator
        if "authenticator" in page_text_lower or "displaysign" in page_text_lower or "检查" in page_title:
            return "authenticator"

        if self.page.ele('#idTxtBx_SAOTCC_OTC', timeout=0.3) or self.page.ele('#otc-confirmation-input', timeout=0.3):
            return "2fa"

        # [增强] 检测保持登录 (涵盖 KMSI)
        if "kmsi" in current_url.lower() or "post.srf" in current_url.lower() or self.page.ele('#idSIButton9', timeout=0.3) or self.page.ele('#acceptButton', timeout=0.3) or self.page.ele('css:[data-testid="primaryButton"]', timeout=0.3):
            title_el = self.page.ele('#title', timeout=0.2) or self.page.ele('css:[data-testid="title"]', timeout=0.2)
            if title_el:
                title_text = title_el.text.lower() if title_el.text else ""
                if "stay signed in" in title_text or "保持" in title_text:
                    return "stay_signed_in"
            if "stay signed in" in page_text_lower or "保持" in page_text_lower:
                return "stay_signed_in"

        if "other ways to sign in" in page_text_lower or "sign in another way" in page_text_lower or "其他登录方式" in page_text_lower or "显示更多选项" in page_text_lower:
            return "select_method"

        if "get a code to sign in" in page_text_lower or "获取代码以登录" in page_html or "获取用于登录的代码" in page_html:
            return "send_code_page"

        identity_badge = self.page.ele('css:[data-testid="identityBanner"]', timeout=0.3) or self.page.ele('#identityBadge', timeout=0.3)
        if identity_badge:
            primary_btn = self.page.ele('css:[data-testid="primaryButton"]', timeout=0.3)
            if primary_btn:
                return "account_confirm"

        if self.page.ele('#msa_upsell', timeout=0.3) or self.page.ele('#positive_cta', timeout=0.3) or self.page.ele('#postpone_cta', timeout=0.3):
            return "msa_upsell"

        security_patterns = [
            "help us protect your account", "帮助我们保护你的帐户",
            "帮助我们保护你的账户", "保护你的帐户", "verify your identity", "验证你的身份",
        ]
        for e in security_patterns:
            if re.search(e, page_html, re.IGNORECASE):
                logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 检测到安全验证页面")
                self.browser_mgr.save_screenshot("login_security_verify")
                is_headless = HAS_DISPLAY or (os.environ.get("QL_DIR") is not None) or (not sys.platform.startswith("win"))
                if is_headless:
                    logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 无头环境，跳过安全验证")
                    return "error"
                else:
                    logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 请手动完成验证（30秒超时）...")
                    for wait_i in range(6):
                        time.sleep(5)
                        try:
                            new_html = (self.page.html or '').lower()
                            still_on_security = False
                            for sp in security_patterns:
                                if re.search(sp, new_html, re.IGNORECASE):
                                    still_on_security = True
                                    break
                            if not still_on_security:
                                logger.info(f"{LogIndent.ITEM}{LogIcon.SUCCESS} 安全验证已通过，继续登录流程")
                                return self._detect_page_type()
                        except Exception:
                            pass
                    logger.error(f"{LogIndent.ITEM}{LogIcon.FAIL} 安全验证超时，登录失败")
                    return "error"
        
        return "unknown"

    def _handle_authenticator(self) -> bool:
        """[新增] 阻塞式等待 Authenticator 验证，剥离容错逻辑防止日志被吞"""
        logger.info(f"{LogIndent.ITEM}{LogTag.LOGIN} 正在监控 Authenticator 验证或寻找切回密码的途径...")
        last_auth_num = None
        end_time = time.time() + 45  # 给定 45 秒宽限期
        
        while time.time() < end_time:
            current_url = self.page.url or ""
            page_html = self.page.html or ""
            page_text_lower = page_html.lower()
            page_title = self.page.title or ""

            if "login.live.com" not in current_url and "microsoftonline.com" not in current_url:
                logger.success(f"{LogIndent.ITEM}{LogIcon.SUCCESS} {LogTag.LOGIN} 手机端验证已通过！")
                return True

            if "kmsi" in current_url.lower() or "post.srf" in current_url.lower() or "stay signed in" in page_text_lower or "保持" in page_text_lower:
                logger.success(f"{LogIndent.ITEM}{LogIcon.SUCCESS} {LogTag.LOGIN} 手机端验证已通过！准备确认保持登录...")
                return True

            if self._find_password_input(timeout=0.2):
                logger.info(f"{LogIndent.ITEM}{LogIcon.SUCCESS} {LogTag.LOGIN} 成功切回密码输入模式")
                return True

            if "authenticator" in page_text_lower or "displaysign" in page_text_lower or "检查" in page_title:
                num_str = None
                try:
                    for sel in ['#displaySign', '.displaySign', 'css:[data-testid="displaySign"]']:
                        ele = self.page.ele(sel, timeout=0.1)
                        if ele:
                            txt = ele.text
                            if txt and txt.strip().isdigit():
                                num_str = txt.strip()
                                break
                except Exception:
                    pass
                
                if not num_str:
                    try:
                        js_code = """
                            var els = document.querySelectorAll('div, span, strong, h1, h2');
                            for (var e of els) {
                                var txt = (e.innerText || '').trim();
                                if (/^\\d{1,2}$/.test(txt)) {
                                    try {
                                        var style = window.getComputedStyle(e);
                                        var fs = parseInt(style.fontSize) || 0;
                                        if (fs >= 20 || style.fontWeight === 'bold' || style.fontWeight > 600) {
                                            return txt;
                                        }
                                    } catch(err) {}
                                }
                            }
                            return null;
                        """
                        res = self.page.run_js(js_code)
                        if res and str(res).strip().isdigit():
                            num_str = str(res).strip()
                    except Exception:
                        pass
                
                if num_str:
                    if num_str != last_auth_num:
                        logger.warning(f"{LogIndent.ITEM}{LogIcon.BELL} {LogTag.LOGIN} ⚠️ 请在手机 Authenticator 上选择数字: 【 {num_str} 】")
                        last_auth_num = num_str
                else:
                    if last_auth_num != "waiting":
                        logger.warning(f"{LogIndent.ITEM}{LogIcon.BELL} {LogTag.LOGIN} ⚠️ 等待手机确认中（若屏幕无数字，请直接在手机点“批准”）...")
                        last_auth_num = "waiting"
                
                try:
                    switch_pwd = (
                        self.page.ele('#idA_PWD_SwitchToPassword', timeout=0.1) or
                        self.page.ele('css:[data-testid="authenticatorToPasswordCta"]', timeout=0.1) or
                        self.page.ele('text:改用密码', timeout=0.1) or
                        self.page.ele('text:使用密码', timeout=0.1) or
                        self.page.ele('text:Use a password', timeout=0.1)
                    )
                    if switch_pwd:
                        logger.info(f"{LogIndent.ITEM}{LogTag.LOGIN} 发现「改用密码」选项，尝试切回自动输入...")
                        switch_pwd.click()
                        time.sleep(2)
                        continue
                except Exception:
                    pass
            else:
                return True
            
            time.sleep(1)

        logger.error(f"{LogIndent.ITEM}{LogIcon.FAIL} {LogTag.LOGIN} 等待 Authenticator 确认超时 (45s)")
        return False

    def _handle_device_security(self) -> bool:
        logger.info(f"{LogIndent.ITEM}{LogTag.LOGIN} 检测到 Passkey/设备安全页，尝试点击后退返回登录流...")
        try:
            start_url = self.page.url or ""
            self.page.run_js("""
                var b = document.getElementById('idBtn_Back');
                if (b) { b.click(); return true; }
                return false;
            """)
            for _ in range(8):
                time.sleep(1)
                current_url = self.page.url or ""
                if "/fido/get" not in current_url.lower() and current_url != start_url:
                    return True
                if self.page.ele("#usernameEntry", timeout=0.2) or self.page.ele("#i0116", timeout=0.2):
                    return True
        except Exception as e:
            logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 设备安全页后退失败: {e}")
        return False

    def _select_password_login(self):
        """[增强版] 自动选择展开更多选项和密码登录"""
        logger.info(f"{LogIndent.ITEM}{LogTag.LOGIN} 选择密码登录...")
        try:
            self.page.run_js("""
                var els = document.querySelectorAll('span[role="button"], a, button, div[role="button"]');
                for (var el of els) {
                    var t = (el.textContent || '').toLowerCase();
                    if (t.includes('other ways') || t.includes('其他登录') || t.includes('显示更多选项') || t.includes('show more options')) { el.click(); break; }
                }
            """)
            time.sleep(2)
            self.page.run_js("""
                var els = document.querySelectorAll('[data-testid="credential-picker-password"], [data-testid="tile"], button, a, div[role="button"]');
                for (var el of els) {
                    var t = (el.textContent || '').toLowerCase();
                    if (t.includes('use a password') || t.includes('use your password') || t.includes('使用密码') || t.includes('改用密码')) { el.click(); break; }
                }
            """)
            time.sleep(1)
        except:
            pass

    def _input_email(self, email: str) -> bool:
        logger.info(f"{LogIndent.ITEM}{LogTag.LOGIN} 输入邮箱...")
        el = self.page.ele("#usernameEntry", timeout=5) or self.page.ele("#i0116", timeout=3)
        if not el:
            logger.error(f"{LogIndent.ITEM}{LogIcon.FAIL} 未找到邮箱输入框")
            self.browser_mgr.save_screenshot("login_email_input_not_found")
            self.browser_mgr.save_html("login_email_input_not_found")
            return False
        try:
            el.run_js('this.value=""')
            el.run_js('''
                var nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
                nativeInputValueSetter.call(this, "");
                this.dispatchEvent(new Event("input", { bubbles: true }));
            ''')
        except Exception:
            pass
        el.clear()
        time.sleep(0.5)
        el.input(email)
        time.sleep(1)
        try:
            current_value = el.run_js('return this.value') or ""
            if email in current_value and current_value != email:
                logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 检测到邮箱重复输入，重新清空...")
                el.run_js(f'this.value=""')
                el.run_js('''
                    var nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
                    nativeInputValueSetter.call(this, "");
                    this.dispatchEvent(new Event("input", {{ bubbles: true }}));
                ''')
                time.sleep(0.3)
                el.input(email)
                time.sleep(1)
        except Exception:
            pass
        return self._click_next()
    
    def _input_password(self, password: str) -> bool:
        logger.info(f"{LogIndent.ITEM}{LogTag.LOGIN} 输入密码...")
        el = self._find_password_input(timeout=5)
        if not el:
            logger.error(f"{LogIndent.ITEM}{LogIcon.FAIL} 未找到密码输入框")
            self.browser_mgr.save_screenshot("login_password_input_not_found")
            self.browser_mgr.save_html("login_password_input_not_found")
            return False
        try:
            el.run_js('this.value=""')
            el.run_js('''
                var nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
                nativeInputValueSetter.call(this, "");
                this.dispatchEvent(new Event("input", { bubbles: true }));
            ''')
        except Exception:
            pass
        el.clear()
        time.sleep(0.5)
        el.input(password)
        time.sleep(1)
        try:
            current_value = el.run_js('return this.value') or ""
            if not current_value:
                logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 密码输入框为空，尝试使用 JS 直接设置...")
                escaped_pwd = password.replace('\\', '\\\\').replace("'", "\\'").replace('"', '\\"').replace('\n', '\\n')
                el.run_js(f'''
                    var nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
                    nativeInputValueSetter.call(this, "{escaped_pwd}");
                    this.dispatchEvent(new Event("input", {{ bubbles: true }}));
                    this.dispatchEvent(new Event("change", {{ bubbles: true }}));
                ''')
                time.sleep(0.5)
        except Exception:
            pass
        return self._click_next()
    
    def _find_password_input(self, timeout: float = 1):
        for sel in ['#i0118', '#passwordEntry', 'input[name="passwd"]', 'input[type="password"]']:
            el = self.page.ele(f'css:{sel}', timeout=timeout)
            if el:
                return el
        return None

    def _handle_2fa(self, otpauth: str) -> bool:
        logger.info(f"{LogIndent.ITEM}{LogTag.LOGIN} 处理两步验证...")
        if not otpauth:
            logger.error(f"{LogIndent.ITEM}{LogIcon.FAIL} 未配置 otpauth")
            self.browser_mgr.save_screenshot("login_2fa_no_otpauth")
            self.browser_mgr.save_html("login_2fa_no_otpauth")
            return False
        try:
            totp = pyotp.parse_uri(otpauth)
            code = totp.now()
            logger.info(f"{LogIndent.ITEM}验证码: {code}")
            el = self.page.ele('#idTxtBx_SAOTCC_OTC', timeout=3) or self.page.ele('#otc-confirmation-input', timeout=3)
            if el:
                el.clear()
                el.input(code)
                time.sleep(1)
                return self._click_next()
        except Exception as e:
            logger.error(f"{LogIndent.ITEM}{LogIcon.FAIL} 2FA异常: {e}")
            self.browser_mgr.save_screenshot("login_2fa_exception")
            self.browser_mgr.save_html("login_2fa_exception")
        return False
    
    def _click_stay_signed_in(self):
        logger.info(f"{LogIndent.ITEM}{LogTag.LOGIN} 点击保持登录...")
        btn = self.page.ele('#idSIButton9', timeout=3) or self.page.ele('css:[data-testid="primaryButton"]', timeout=2)
        if btn:
            btn.click()
            time.sleep(2)
    
    def _handle_msa_upsell(self):
        logger.info(f"{LogIndent.ITEM}{LogTag.LOGIN} 处理登录确认页面...")
        btn = self.page.ele('#postpone_cta', timeout=3) or self.page.ele('#positive_cta', timeout=2)
        if btn:
            btn.click()
            time.sleep(2)
    
    def _click_use_password(self):
        logger.info(f"{LogIndent.ITEM}{LogTag.LOGIN} 点击'使用密码登录'...")
        other_methods = self.page.ele('text:其他登录方法', timeout=2) or self.page.ele('text:Other ways to sign in', timeout=1) or self.page.ele('text:其他登录方式', timeout=1)
        if other_methods:
            other_methods.click()
            time.sleep(2)
        else:
            self.page.run_js("""
                var els = document.querySelectorAll('[data-testid="viewFooter"] span[role="button"], a, button, span[role="button"]');
                for (var el of els) {
                    var t = (el.textContent || '').trim();
                    if (t.includes('其他登录') || t.includes('Other ways') || t.includes('other ways')) {
                        el.click();
                        break;
                    }
                }
            """)
            time.sleep(2)
        
        link = self.page.ele('text:Use your password', timeout=3) or self.page.ele('text:使用密码', timeout=2) or self.page.ele('text:Use a password', timeout=1)
        if link:
            link.click()
            time.sleep(2)
        else:
            self.page.run_js("""
                var links = document.querySelectorAll('a, button, span[role="button"], div[role="button"], [data-testid="credential-picker-password"], [data-testid="tile"]');
                for (var link of links) {
                    var t = (link.textContent || '').toLowerCase();
                    if (t.includes('use your password') || t.includes('use a password') || t.includes('使用密码')) {
                        link.click();
                        break;
                    }
                }
            """)
            time.sleep(2)
    
    def _click_account_confirm(self):
        logger.info(f"{LogIndent.ITEM}{LogTag.LOGIN} 点击账号确认按钮...")
        btn = self.page.ele('css:[data-testid="primaryButton"]', timeout=3) or self.page.ele('#idSIButton9', timeout=2)
        if btn:
            btn.click()
            time.sleep(2)
        else:
            logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 未找到账号确认按钮")
    
    def _click_next(self) -> bool:
        btn = self.page.ele('css:button[data-testid="primaryButton"]', timeout=2)
        if btn:
            btn.click()
            return True
        btn = self.page.ele('#idSIButton9', timeout=2)
        if btn:
            btn.click()
            return True
        for text in ['下一步', '登录', 'Next', 'Sign in', '验证']:
            btn = self.page.ele(f'tag:button@@text()={text}', timeout=1)
            if btn:
                btn.click()
                return True
        return False


class TokenManager:
    """OAuth Token 管理"""
    
    def __init__(self, browser_mgr):
        self.browser_mgr = browser_mgr
        self.page = browser_mgr.page

    def get_refresh_token(self, account_index=1):
        """获取 OAuth refresh_token"""
        logger.info(f"{LogIcon.KEY} {LogTag.LOGIN} 账号{account_index} 获取刷新令牌...")
        try:
            from urllib.parse import urlparse, parse_qs
            auth_code = None
            try:
                self.page.listen.start("oauth20_desktop.srf")
                self.page.get(OAUTH_AUTHORIZE_URL)
                time.sleep(3)
                
                for packet in self.page.listen.steps(timeout=15):
                    req_url = packet.url if hasattr(packet, 'url') else str(packet)
                    if "code=" in req_url and "oauth20_desktop.srf" in req_url:
                        parsed = urlparse(req_url)
                        params = parse_qs(parsed.query)
                        if "code" in params:
                            auth_code = params["code"][0]
                            break
                self.page.listen.stop()
            except Exception as e:
                logger.warning(f"{LogIndent.ITEM}[Token] 监听异常: {e}")
                try:
                    self.page.listen.stop()
                except:
                    pass

            if not auth_code:
                current_url = ""
                try:
                    current_url = str(getattr(self.page, "url", "") or "")
                except Exception:
                    current_url = ""

                if "code=" in current_url and "oauth20_desktop.srf" in current_url:
                    parsed = urlparse(current_url)
                    params = parse_qs(parsed.query)
                    if "code" in params:
                        auth_code = params["code"][0]

            # 备用: 历史记录方式
            if not auth_code:
                try:
                    entries = self.page.run_js("""
                        var entries = performance.getEntriesByType('navigation').concat(performance.getEntriesByType('resource'));
                        return entries.filter(e => e.name && e.name.includes('oauth20_desktop.srf')).map(e => e.name);
                    """)
                    if entries and len(entries) > 0:
                        parsed = urlparse(entries[0])
                        params = parse_qs(parsed.query)
                        if "code" in params:
                            auth_code = params["code"][0]
                except:
                    pass

            if not auth_code:
                logger.error(f"{LogIcon.FAIL} {LogTag.LOGIN} 未能获取授权码")
                self.browser_mgr.save_screenshot("token_auth_code_fail")
                self.browser_mgr.save_html("token_auth_code_fail")
                return None

            # auth_code 换取 token
            token_data = {
                "client_id": OAUTH_CLIENT_ID,
                "code": auth_code,
                "grant_type": "authorization_code",
                "redirect_uri": OAUTH_REDIRECT_URI,
                "scope": OAUTH_SCOPE,
            }
            result = request_oauth_token(token_data, timeout=20, retries=3)
            if result and result.get("refresh_token"):
                logger.success(f"{LogIcon.SUCCESS} {LogTag.LOGIN} 刷新令牌获取成功!")
                return {"refresh_token": result["refresh_token"], "access_token": result.get("access_token")}
            return None
        except Exception as e:
            logger.error(f"{LogIcon.FAIL} {LogTag.LOGIN} 获取刷新令牌异常: {e}")
            self.browser_mgr.save_screenshot("token_refresh_exception")
            self.browser_mgr.save_html("token_refresh_exception")
            return None


class PointsManager:
    """积分获取和解析"""
    
    def __init__(self, browser_mgr):
        self.browser_mgr = browser_mgr
        self.page = browser_mgr.page

    def get_rewards_points(self, account_index=1, silent=False):
        try:
            rsc_data = ''
            is_new_version = False

            # 先尝试新版 /earn
            try:
                self.page.get(REWARDS_EARN_URL)
                try:
                    self.page.wait.load_start(timeout=30)
                except:
                    pass
                time.sleep(random.uniform(2, 3))
                
                rsc_data = (self.page.html or '').replace('\\"', '"').replace('\\\\', '\\')
                if "rewards-404-error" in rsc_data or "积分商城错误" in rsc_data or '"statusCode":404' in rsc_data:
                    if not silent:
                        logger.info(f"{LogTag.POINTS} /earn 返回404，切换到旧版 /pointsbreakdown")
                    is_new_version = False
                else:
                    is_new_version = True
            except Exception as e:
                if not silent:
                    logger.warning(f"{LogIcon.WARN} {LogTag.POINTS} 访问 /earn 失败: {e}")

            if not is_new_version:
                try:
                    self.page.get(REWARDS_POINTS_URL)
                    try:
                        self.page.wait.load_start(timeout=30)
                    except:
                        pass
                    time.sleep(random.uniform(2, 3))
                    
                    rsc_data = (self.page.html or '').replace('\\"', '"').replace('\\\\', '\\')
                    
                    if "积分商城错误" in rsc_data or "rewards-404-error" in rsc_data:
                        if not silent:
                            logger.warning(f"{LogIcon.WARN} {LogTag.POINTS} 遇到积分商城错误")
                except Exception as e:
                    if not silent:
                        logger.warning(f"{LogIcon.WARN} {LogTag.POINTS} 获取积分页面失败: {e}")

            self._last_rsc_data = rsc_data
            if is_new_version:
                return self._parse_new_version(rsc_data)
            else:
                return self._parse_old_version(rsc_data)
                
        except Exception as e:
            logger.error(f"{LogIcon.FAIL} {LogTag.POINTS} 获取积分异常: {e}")
            self.browser_mgr.save_screenshot("points_get_exception")
            self.browser_mgr.save_html("points_get_exception")
            return None
    
    def _parse_new_version(self, rsc_data):
        points = self._extract_int(r'balance"\s*:\s*(\d+)', rsc_data)
        if not points:
            points = self._extract_int(r'"balance"\s*:\s*(\d+)', rsc_data)

        today_points = self._extract_int(r'totalPoints"\s*:\s*(\d+)', rsc_data)
        search_progress = 0
        search_max = 0
        
        counters_match = re.search(r'pointsCounters"\s*:\s*\{[^}]*"pc"\s*:\s*\{([^}]+)\}', rsc_data)
        if counters_match:
            pc_block = counters_match.group(1)
            max_m = re.search(r'"max"\s*:\s*(\d+)', pc_block)
            prog_m = re.search(r'"progress"\s*:\s*(\d+)', pc_block)
            if max_m:
                search_max = int(max_m.group(1))
            if prog_m:
                search_progress = int(prog_m.group(1))

        if search_max == 0:
            pc_match = re.search(r'"pc"\s*:\s*\{[^}]*"max"\s*:\s*(\d+)[^}]*"progress"\s*:\s*(\d+)', rsc_data)
            if not pc_match:
                pc_match = re.search(r'"pc"\s*:\s*\{[^}]*"progress"\s*:\s*(\d+)[^}]*"max"\s*:\s*(\d+)', rsc_data)
                if pc_match:
                    search_progress = int(pc_match.group(1))
                    search_max = int(pc_match.group(2))
            else:
                search_max = int(pc_match.group(1))
                search_progress = int(pc_match.group(2))
        
        search_points_per = 3
        count_state = SearchManager._build_search_count_state(search_progress, search_max, search_points_per)
        remaining = count_state["remaining_searches"]
        
        quests = self._parse_quests(rsc_data)
        return {
            "points": points,
            "today_points": today_points,
            "search": {
                "progress": search_progress,
                "max": search_max,
                "remaining": remaining,
                "per_search_points": search_points_per,
                "progress_searches": count_state["progress_searches"],
                "max_searches": count_state["max_searches"],
            },
            "quests": quests,
            "is_new_version": True,
        }
    
    def _parse_old_version(self, rsc_data):
        points = self._extract_int(r'"availablePoints"\s*:\s*(\d+)', rsc_data)
        daily_matches = re.findall(r'"bingSearchDailyPoints"\s*:\s*(\d+)', rsc_data)
        today_points = max([int(x) for x in daily_matches]) if daily_matches else 0
        search_progress = 0
        search_max = 0
        
        pc_match = re.search(r'"pcSearch"\s*:\s*\[([^\]]+)\]', rsc_data)
        if pc_match:
            pc_section = pc_match.group(1)
            max_m = re.search(r'"pointProgressMax"\s*:\s*(\d+)', pc_section)
            prog_m = re.search(r'"pointProgress"\s*:\s*(\d+)', pc_section)
            if max_m and prog_m:
                search_max = int(max_m.group(1))
                search_progress = int(prog_m.group(1))
            else:
                max_m = re.search(r'"max"\s*:\s*"(\d+)"', pc_section)
                prog_m = re.search(r'"progress"\s*:\s*"(\d+)"', pc_section)
                if max_m:
                    search_max = int(max_m.group(1))
                if prog_m:
                    search_progress = int(prog_m.group(1))

        search_points_per = 3
        count_state = SearchManager._build_search_count_state(search_progress, search_max, search_points_per)
        remaining = count_state["remaining_searches"]
        
        quests = self._parse_quests(rsc_data)
        return {
            "points": points,
            "today_points": today_points,
            "search": {
                "progress": search_progress,
                "max": search_max,
                "remaining": remaining,
                "per_search_points": search_points_per,
                "progress_searches": count_state["progress_searches"],
                "max_searches": count_state["max_searches"],
            },
            "quests": quests,
            "is_new_version": False,
        }

    def _extract_int(self, pattern, text, default=0):
        m = re.search(pattern, text)
        return int(m.group(1)) if m else default
    
    def _parse_quests(self, rsc_data):
        quests = {"earned": 0, "total": 0, "progress": 0, "max": 0}
        try:
            quest_idx = rsc_data.find('Earn_QuestSection')
            if quest_idx != -1:
                quest_section = rsc_data[quest_idx:min(len(rsc_data), quest_idx + 15000)]
                m_prog = re.search(r'(\d+)\s*/\s*(\d+)', quest_section)
                if m_prog:
                    quests["progress"] = int(m_prog.group(1))
                    quests["max"] = int(m_prog.group(2))
                m_pts = re.search(r'\[\s*"\+"\s*,\s*"(\d+)"\s*\]', quest_section)
                if m_pts:
                    quests["total"] = int(m_pts.group(1))
                if quests["progress"] >= quests["max"] and quests["max"] > 0:
                    quests["earned"] = quests["total"]
        except:
            pass
        return quests


class SearchManager:
    """搜索任务管理"""
    
    def __init__(self, browser_mgr, points_mgr, hot_words_mgr):
        self.browser_mgr = browser_mgr
        self.page = browser_mgr.page
        self.points_mgr = points_mgr
        self.hot_words_mgr = hot_words_mgr

    def _get_points_from_page(self):
        try:
            points_el = self.page.ele('.points-container', timeout=2)
            if points_el:
                points_text = points_el.text.strip()
                if points_text.isdigit():
                    return int(points_text)
        except:
            pass
        return None

    def _apply_search_page_stealth(self):
        try:
            self.page.run_js("""
            try {
              Object.defineProperty(navigator, 'webdriver', {get: () => undefined, configurable: true});
              Object.defineProperty(navigator, 'platform', {get: () => 'Win32', configurable: true});
              Object.defineProperty(navigator, 'language', {get: () => 'zh-CN', configurable: true});
              Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en-US', 'en'], configurable: true});
            } catch (e) {}
            return true;
            """)
        except Exception:
            pass

    def _find_search_input(self, timeout=2):
        selectors = [
            '#sb_form_q',
            'css:input[name="q"]',
            'xpath://input[@name="q"]',
        ]
        for selector in selectors:
            try:
                el = self.page.ele(selector, timeout=timeout)
                if el:
                    return el
            except Exception:
                continue
        return None

    def _simulate_search_result_browse(self):
        try:
            total_height = self.page.run_js(
                "return Math.max(document.body.scrollHeight || 0, document.documentElement.scrollHeight || 0);"
            ) or 0
            total_height = int(total_height) if str(total_height).isdigit() else 0
        except Exception:
            total_height = 0

        if total_height <= 0:
            time.sleep(random.uniform(2.5, 4.0))
            return

        steps = random.randint(2, 4)
        for step in range(steps):
            ratio = (step + 1) / (steps + 1)
            target = int(total_height * ratio)
            try:
                self.page.run_js(f"window.scrollTo({{top: {target}, behavior: 'instant'}});")
            except Exception:
                pass
            time.sleep(random.uniform(1.0, 2.2))

        try:
            self.page.run_js("window.scrollTo({top: 0, behavior: 'instant'});")
        except Exception:
            pass
        time.sleep(random.uniform(1.0, 2.0))

    def _submit_search_interactive(self, query: str) -> bool:
        try:
            input_el = self._find_search_input(timeout=3)
            if not input_el:
                return False

            self._apply_search_page_stealth()
            try:
                input_el.click()
            except Exception:
                pass

            try:
                input_el.run_js('this.value=""')
                input_el.run_js("""
                this.dispatchEvent(new Event('input', {bubbles: true}));
                this.dispatchEvent(new Event('change', {bubbles: true}));
                """)
            except Exception:
                pass

            input_el.input(query)
            time.sleep(random.uniform(0.8, 1.6))

            submit_btn = None
            for selector in ('#sb_form_go', '#search_icon', 'css:button[type="submit"]'):
                try:
                    submit_btn = self.page.ele(selector, timeout=1)
                    if submit_btn:
                        break
                except Exception:
                    continue

            if submit_btn:
                submit_btn.click()
            else:
                try:
                    self.page.run_js("""
                    const form = document.querySelector('#sb_form') || document.querySelector('form[action*="/search"]');
                    if (form) { form.submit(); return true; }
                    return false;
                    """)
                except Exception:
                    return False

            try:
                self.page.wait.load_start(timeout=20)
            except Exception:
                pass
            time.sleep(random.uniform(3.5, 5.5))
            self._simulate_search_result_browse()
            return True
        except Exception:
            return False

    def _submit_search_via_url(self, query: str) -> bool:
        from urllib.parse import quote

        try:
            self.page.get(f"{SEARCH_REQUEST_URL}?q={quote(query)}")
            try:
                self.page.wait.load_start(timeout=20)
            except Exception:
                pass
            time.sleep(random.uniform(3.5, 5.5))
            self._apply_search_page_stealth()
            self._simulate_search_result_browse()
            return True
        except Exception:
            return False

    def _get_verified_search_status(self, refresh_token: str, account_index: int) -> dict:
        if not refresh_token:
            return {"valid": False}
        try:
            mobile_mgr = AppTaskManager(refresh_token, account_index)
            return mobile_mgr.get_pc_search_status()
        except Exception:
            return {"valid": False}

    @staticmethod
    def _build_search_count_state(progress, maximum, per_search_points=3):
        try:
            progress = int(progress or 0)
        except Exception:
            progress = 0
        try:
            maximum = int(maximum or 0)
        except Exception:
            maximum = 0
        try:
            per_search_points = int(per_search_points or 3)
        except Exception:
            per_search_points = 3

        progress = max(0, progress)
        maximum = max(0, maximum)
        per_search_points = max(1, per_search_points)

        completed_searches = (progress + per_search_points - 1) // per_search_points if progress > 0 else 0
        remaining_searches = max(0, maximum - completed_searches) if maximum > 0 else 0

        return {
            "progress_points": progress,
            "max_points": maximum,
            "progress_searches": completed_searches,
            "max_searches": maximum,
            "remaining_searches": remaining_searches,
            "per_search_points": per_search_points,
        }

    def complete_search_tasks(self, account_index=1, refresh_token=""):
        logger.info(f"{LogIcon.SEARCH} {LogTag.SEARCH} 账号{account_index} 准备执行搜索任务")

        progress = 0
        max_points = 0
        remaining = 0
        per_search_points = 3
        progress_searches = 0
        max_searches = 0

        # 优先使用移动端 promotions 查询 PC 搜索状态
        if refresh_token:
            try:
                mobile_mgr = AppTaskManager(refresh_token, account_index)
                pc_status = mobile_mgr.get_pc_search_status()
                if pc_status.get("valid"):
                    progress = pc_status.get("progress", 0)
                    max_points = pc_status.get("max", 0)
                    remaining = pc_status.get("remaining", 0)
                    per_search_points = max(1, pc_status.get("per_search_points", 3))
                    count_state = self._build_search_count_state(progress, max_points, per_search_points)
                    progress_searches = pc_status.get("progress_searches", count_state["progress_searches"])
                    max_searches = pc_status.get("max_searches", count_state["max_searches"])
                    remaining = pc_status.get("remaining", count_state["remaining_searches"])
                    logger.info(
                        f"{LogIndent.ITEM}{LogIcon.NOTE} 搜索进度(移动端): "
                        f"{progress_searches}/{max_searches}次，原始积分进度 {progress}/{max_points}分，"
                        f"按 {per_search_points} 分/次，剩余 {remaining} 次搜索"
                    )
                else:
                    logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 移动端未获取到有效搜索状态，回退页面解析")
            except Exception as e:
                logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 移动端搜索状态读取失败，回退页面解析: {e}")

        # 回退到旧版页面解析
        if max_points <= 0:
            points_data = self.points_mgr.get_rewards_points(account_index, silent=True)
            if not points_data:
                return 0

            remaining = points_data.get("search", {}).get("remaining", 0)
            progress = points_data.get("search", {}).get("progress", 0)
            max_points = points_data.get("search", {}).get("max", 0)
            per_search_points = max(1, points_data.get("search", {}).get("per_search_points", 3))
            count_state = self._build_search_count_state(progress, max_points, per_search_points)
            progress_searches = points_data.get("search", {}).get("progress_searches", count_state["progress_searches"])
            max_searches = points_data.get("search", {}).get("max_searches", count_state["max_searches"])
            remaining = points_data.get("search", {}).get("remaining", count_state["remaining_searches"])
            logger.info(
                f"{LogIndent.ITEM}{LogIcon.NOTE} 搜索进度(页面): "
                f"{progress_searches}/{max_searches}次，原始积分进度 {progress}/{max_points}分，"
                f"按 {per_search_points} 分/次，剩余 {remaining} 次搜索"
            )

        if remaining <= 0:
            logger.success(f"{LogIndent.ITEM}{LogIcon.SUCCESS} 搜索任务已完成")
            return 0

        self.hot_words_mgr.ensure_loaded()
        try:
            self.page.get(SEARCH_HOME_CN_URL)
            time.sleep(random.uniform(2, 4))
            self.page.refresh()
            time.sleep(random.uniform(2, 4))
            self._apply_search_page_stealth()

            login_btn = self.page.ele('#id_l', timeout=2)
            if login_btn:
                login_btn.click()
                time.sleep(random.uniform(8, 10))
        except:
            pass

        batch_size = remaining
        
        total_success = 0
        check_interval = 3
        no_change_count = 0
        start_points = self._get_points_from_page()
        last_points = start_points
        verified_progress = progress_searches
        verified_max = max_searches

        logger.info(f"{LogIndent.ITEM}{LogIcon.INFO} 本批次计划搜索 {batch_size} 次，当前积分: {start_points or '未知'}")

        for i in range(batch_size):
            search_str = self.hot_words_mgr.get_random_word()
            try:
                used_interactive = self._submit_search_interactive(search_str)
                used_fallback = False
                if not used_interactive:
                    used_fallback = self._submit_search_via_url(search_str)
                if not used_interactive and not used_fallback:
                    logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 搜索提交失败，跳过本次关键词: {search_str}")
                    continue
                total_success += 1
                current_points = self._get_points_from_page()
                points_str = f"，当前积分: {current_points}" if current_points else ""
                logger.info(f"{LogIndent.ITEM}{LogIcon.STAR} 搜索 {i + 1}/{batch_size}: {search_str}{points_str}")
                # 检查积分变化
                if total_success % check_interval == 0 or total_success == batch_size:
                    current_points = self._get_points_from_page()
                    verified_status = self._get_verified_search_status(refresh_token, account_index)
                    if verified_status.get("valid"):
                        current_verified = verified_status.get("progress_searches", verified_progress)
                        verified_max = verified_status.get("max_searches", verified_max)
                        if current_verified > verified_progress:
                            logger.info(
                                f"{LogIndent.ITEM}{LogIcon.UP} API校验: 搜索进度 "
                                f"{verified_progress}/{verified_max} → {current_verified}/{verified_max}"
                            )
                            verified_progress = current_verified
                            no_change_count = 0
                    if current_points is not None and last_points is not None:
                        delta = current_points - last_points
                        if delta > 0:
                            logger.info(f"{LogIndent.ITEM}{LogIcon.UP} 积分检查: {last_points} → {current_points} (+{delta})")
                            last_points = current_points
                            no_change_count = 0
                        else:
                            no_change_count += 1
                            logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 积分未增加: 仍为 {current_points} (连续{no_change_count}次)")
                            logger.info(f"{LogIndent.ITEM}{LogIcon.INFO} 积分暂未刷新，继续按目标次数执行剩余搜索")
            except:
                time.sleep(2)

        final_points = self._get_points_from_page()
        verified_final = self._get_verified_search_status(refresh_token, account_index)
        if verified_final.get("valid"):
            verified_progress = verified_final.get("progress_searches", verified_progress)
            verified_max = verified_final.get("max_searches", verified_max)
        if final_points is not None and start_points is not None:
            total_delta = final_points - start_points
            logger.info(f"{LogIndent.ITEM}{LogIcon.DATA} 本批次结果: 搜索 {total_success} 次，积分 {start_points} → {final_points} (+{total_delta})")
            if total_success > 0 and total_delta <= 0 and verified_progress <= progress_searches:
                logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 搜索已执行 {total_success} 次，但积分与API进度均未增长，保存调试现场")
                self.browser_mgr.save_screenshot("search_no_score")
                self.browser_mgr.save_html("search_no_score")

        logger.success(f"{LogIndent.ITEM}{LogIcon.TARGET} 本批次搜索完成 {total_success}/{batch_size}")
        return total_success


class AppTaskManager:
    """APP 任务管理（签到、阅读、Edge 连续浏览）"""

    API_BASE = "https://prod.rewardsplatform.microsoft.com/dapi"
    TOKEN_URL = "https://login.live.com/oauth20_token.srf"

    def __init__(self, refresh_token: str, account_index: int = 1):
        self.refresh_token = refresh_token
        self.account_index = account_index
        self.access_token = None
        self.session = requests.Session()
        self._result = {
            "app_sign_in": -1,
            "read_progress": 0,
            "edge_checkin_points": -2
        }

    @property
    def result(self):
        return self._result

    def _request(self, method: str, url: str, **kwargs):
        kwargs.setdefault('timeout', REQUEST_TIMEOUT)
        return self.session.request(method, url, **kwargs)

    def _get_access_token(self) -> bool:
        if not self.refresh_token:
            return False
        try:
            data = {
                'client_id': OAUTH_CLIENT_ID,
                'refresh_token': self.refresh_token,
                'scope': OAUTH_SCOPE,
                'grant_type': 'refresh_token'
            }
            json_data = request_oauth_token(data, timeout=max(20, REQUEST_TIMEOUT), retries=3)
            if json_data:
                self.access_token = json_data.get('access_token')
                new_refresh = json_data.get('refresh_token')
                if new_refresh:
                    self.refresh_token = new_refresh
                return bool(self.access_token)
        except Exception as e:
            logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 获取 access_token 失败: {e}")
        return False

    def _get_headers(self, with_content_type: bool = False) -> dict:
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'User-Agent': "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36",
            'Accept': 'application/json',
            'Accept-Encoding': 'gzip',
            'channel': 'SAAndroid',
            'x-rewards-partnerid': 'startapp',
            'x-rewards-appid': 'SAAndroid/32.2.430730002',
            'x-rewards-country': 'cn',
            'x-rewards-language': 'zh-hans',
            'x-rewards-flights': 'rwgobig'
        }
        if with_content_type:
            headers['Content-Type'] = 'application/json'
        return headers

    def _get_edge_headers(self, with_content_type: bool = False) -> dict:
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'X-Rewards-PartnerId': 'EdgeHub',
            'X-Rewards-AppId': 'EdgeDesktop',
            'X-Rewards-Country': 'CN',
            'X-Rewards-Language': 'zh-CN',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0',
            'Accept': 'application/json',
            'Accept-Encoding': 'gzip, deflate, zstd'
        }
        if with_content_type:
            headers['Content-Type'] = 'application/json'
        return headers

    def _safe_int(self, value: Any, default: int = 0) -> int:
        try:
            return int(float(str(value)))
        except Exception:
            return default

    def _safe_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).strip().lower() in ('true', '1', 'yes', 'y')

    def _get_read_progress(self) -> dict:
        try:
            url = f"{self.API_BASE}/me?channel=SAAndroid&options=613"
            resp = self._request('GET', url, headers=self._get_headers())
            if resp.status_code == 200:
                data = resp.json()
                promotions = data.get('response', {}).get('promotions', [])
                for p in promotions:
                    attrs = p.get('attributes', {})
                    if attrs.get('offerid') == 'ENUS_readarticle3_30points':
                        max_val = attrs.get('max')
                        progress_val = attrs.get('progress')
                        if max_val is not None and progress_val is not None:
                            return {'max': int(max_val), 'progress': int(progress_val)}
        except Exception as e:
            logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 获取阅读进度失败: {e}")
        return {'max': 0, 'progress': 0}

    def _get_mobile_promotions(self):
        """获取移动端 promotions 列表，用于读取搜索/阅读等任务状态"""
        try:
            if not self.access_token:
                if not self._get_access_token():
                    return []

            url = f"{self.API_BASE}/me?channel=SAAndroid&options=613"
            resp = self._request('GET', url, headers=self._get_headers())
            if resp.status_code != 200:
                logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 获取移动端任务信息失败: {resp.status_code}")
                return []

            data = resp.json()
            promotions = data.get("response", {}).get("promotions", [])
            return promotions if isinstance(promotions, list) else []
        except Exception as e:
            logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 获取移动端任务信息异常: {e}")
            return []

    def get_pc_search_status(self) -> dict:
        """从移动端 promotions 中提取 PC 搜索状态"""
        promotions = self._get_mobile_promotions()
        if not promotions:
            return {"progress": 0, "max": 0, "remaining": 0, "complete": False, "valid": False}

        def _to_int(value, default=0):
            try:
                return int(float(str(value)))
            except Exception:
                return default

        def _to_bool(value):
            if isinstance(value, bool):
                return value
            if value is None:
                return False
            return str(value).strip().lower() in ("true", "1", "yes", "y")

        per_search_points = 3
        for item in promotions:
            if not isinstance(item, dict):
                continue
            if str(item.get("name", "")).strip() != "level_info":
                continue
            attrs = item.get("attributes", {}) or {}
            per_search_points = _to_int(
                attrs.get("points_per_pc_search", attrs.get("points_per_pc_search_new_levels", 3)),
                3
            )
            if per_search_points <= 0:
                per_search_points = 3
            break

        candidate = None
        for item in promotions:
            if not isinstance(item, dict):
                continue
            attrs = item.get("attributes", {}) or {}
            class_tag = str(attrs.get("Classification.Tag", "")).strip()
            answer_tag = str(attrs.get("AnswerScenario.Tag", "")).strip()
            offerid = str(attrs.get("offerid", "")).strip()
            item_name = str(item.get("name", "")).strip()
            promo_type = str(attrs.get("type", "")).strip().lower()

            if (
                class_tag == "PCSearch"
                or answer_tag == "PCSearch"
                or item_name.endswith("_search_PC")
                or (promo_type == "search" and "search" in offerid.lower() and "pc" in item_name.lower())
            ):
                candidate = item
                break

        if not candidate:
            return {"progress": 0, "max": 0, "remaining": 0, "complete": False, "valid": False}

        attrs = candidate.get("attributes", {}) or {}
        current = _to_int(attrs.get("progress", attrs.get("pointprogress", 0)), 0)
        maximum = _to_int(attrs.get("max", attrs.get("pointmax", 0)), 0)
        complete_flag = _to_bool(attrs.get("complete"))
        is_complete = complete_flag or (maximum > 0 and current >= maximum)

        if is_complete and maximum > 0 and current < maximum:
            current = maximum

        count_state = SearchManager._build_search_count_state(current, maximum, per_search_points)
        remaining = count_state["remaining_searches"]

        return {
            "progress": max(0, current),
            "max": max(0, maximum),
            "remaining": max(0, remaining),
            "complete": is_complete,
            "valid": True,
            "per_search_points": per_search_points,
            "progress_searches": count_state["progress_searches"],
            "max_searches": count_state["max_searches"],
        }

    def get_mobile_summary(self) -> dict:
        try:
            if not self.access_token:
                if not self._get_access_token():
                    return {"valid": False, "points": 0, "today_points": 0}

            url = f"{self.API_BASE}/me?channel=SAAndroid&options=613"
            resp = self._request('GET', url, headers=self._get_headers())
            if resp.status_code != 200:
                return {"valid": False, "points": 0, "today_points": 0}

            data = resp.json()
            response = data.get("response", {}) or {}
            balance = self._safe_int(response.get("balance"), 0)
            today_points = 0
            promotions = response.get("promotions", []) or []
            for item in promotions:
                if not isinstance(item, dict):
                    continue
                if str(item.get("name", "")).strip() != "level_info":
                    continue
                attrs = item.get("attributes", {}) or {}
                today_points = self._safe_int(attrs.get("todays_points"), 0)
                break
            return {"valid": True, "points": balance, "today_points": today_points}
        except Exception:
            return {"valid": False, "points": 0, "today_points": 0}

    @retry_decorator(retries=3)
    def app_sign_in(self) -> int:
        logger.info(f"{LogIcon.MOBILE} {LogTag.READ} 账号{self.account_index} 执行 APP 签到")
        try:
            payload = {
                'amount': 1,
                'id': str(uuid.uuid4()),
                'attributes': {},
                'type': 103,
                'country': 'cn',
                'risk_context': {},
                'channel': 'SAAndroid'
            }
            time.sleep(random.uniform(2, 4))
            resp = self._request('POST', f"{self.API_BASE}/me/activities", headers=self._get_headers(True), json=payload)
            if resp.status_code == 200:
                result = resp.json()
                pts = result.get('response', {}).get('activity', {}).get('p', 0)
                if pts > 0:
                    logger.success(f"{LogIndent.ITEM}{LogIcon.SUCCESS} APP签到成功 +{pts}分")
                else:
                    logger.success(f"{LogIndent.ITEM}{LogIcon.SUCCESS} APP今日已签到")
                self._result['app_sign_in'] = pts
                time.sleep(random.uniform(2, 4))
                return pts
            try:
                error_data = resp.json()
                error_msg = str(error_data.get('error', {}).get('description', '')).lower()
                if 'already' in error_msg or 'duplicate' in error_msg:
                    logger.success(f"{LogIndent.ITEM}{LogIcon.SUCCESS} APP今日已签到")
                    self._result['app_sign_in'] = 0
                    return 0
            except Exception:
                pass
            logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} APP签到失败: HTTP {resp.status_code}")
            return -1
        except Exception as e:
            if 'already' in str(e).lower() or 'duplicate' in str(e).lower():
                logger.success(f"{LogIndent.ITEM}{LogIcon.SUCCESS} APP今日已签到")
                self._result['app_sign_in'] = 0
                return 0
            logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} APP签到异常: {e}")
            return -1

    def _get_edge_checkin_status(self) -> Optional[dict]:
        try:
            resp = self._request('GET', f"{self.API_BASE}/me?channel=edge", headers=self._get_edge_headers())
            if resp.status_code != 200:
                return None
            data = resp.json()
            promotions = data.get('response', {}).get('promotions', [])
            for item in promotions:
                attrs = item.get('attributes', {}) or {}
                offerid = str(attrs.get('offerid', '') or '')
                item_name = str(item.get('name', '') or '')
                if offerid == 'DailyCheckIn_Edge' or item_name == 'edge_browsing_streak_flight':
                    progress = self._safe_int(attrs.get('progress'), -1)
                    max_value = self._safe_int(attrs.get('max'), 0)
                    report_per_minutes = max(1, self._safe_int(attrs.get('report_per_minutes'), 5))
                    complete = self._safe_bool(attrs.get('complete'))

                    has_task = complete or max_value > 0 or progress >= 0
                    return {
                        'has_task': has_task,
                        'complete': complete,
                        'progress': progress,
                        'max': max_value,
                        'report_per_minutes': report_per_minutes
                    }
        except Exception as e:
            logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} Edge浏览打卡状态获取失败: {e}")
        return None

    def complete_edge_checkin(self) -> int:
        logger.info(f"{LogIcon.MOBILE} {LogTag.READ} 账号{self.account_index} 执行 Edge 浏览打卡")
        target_minutes = 30
        status = self._get_edge_checkin_status()

        if not status:
            logger.info(f"{LogIndent.ITEM}{LogIcon.NOTE} 未获取到 Edge 浏览打卡任务，跳过执行")
            self._result['edge_checkin_points'] = -2
            return -2

        if not status.get('has_task'):
            logger.info(f"{LogIndent.ITEM}{LogIcon.NOTE} 当前账号无 Edge 浏览打卡任务，跳过执行")
            self._result['edge_checkin_points'] = -2
            return -2

        if status.get('complete'):
            logger.success(f"{LogIndent.ITEM}{LogIcon.SUCCESS} Edge浏览打卡已完成")
            self._result['edge_checkin_points'] = 0
            return 0

        progress = self._safe_int(status.get('progress'), -1)
        max_value = self._safe_int(status.get('max'), 0)
        report_per_minutes = max(1, self._safe_int(status.get('report_per_minutes'), 5))

        if max_value <= 0 and progress < 0:
            logger.info(f"{LogIndent.ITEM}{LogIcon.NOTE} Edge 任务状态不完整，跳过执行")
            self._result['edge_checkin_points'] = -2
            return -2

        effective_target = max_value if max_value > 0 else target_minutes
        effective_target = min(target_minutes, effective_target) if effective_target > 0 else target_minutes
        base_progress = max(0, min(progress, effective_target)) if progress >= 0 else 0
        remaining_minutes = max(0, effective_target - base_progress)

        if remaining_minutes <= 0:
            logger.success(f"{LogIndent.ITEM}{LogIcon.SUCCESS} Edge浏览打卡已完成")
            self._result['edge_checkin_points'] = 0
            return 0

        remaining_requests = min(6, max(1, (remaining_minutes + report_per_minutes - 1) // report_per_minutes))
        logger.info(f"{LogIndent.ITEM}{LogIcon.NOTE} Edge任务已识别，当前进度 {base_progress}/{effective_target}，预计执行 {remaining_requests} 次")

        payload = {
            'amount': 1,
            'attributes': {'offerid': 'DailyCheckIn_Edge'},
            'request_user_info': True,
            'type': '29'
        }
        last_points = 0
        for i in range(remaining_requests):
            try:
                resp = self._request('POST', f"{self.API_BASE}/me/activities", headers=self._get_edge_headers(True), json=payload)
                if resp.status_code != 200:
                    logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} Edge浏览打卡失败: HTTP {resp.status_code}")
                    self._result['edge_checkin_points'] = -1
                    return -1
                try:
                    result = resp.json()
                    last_points = self._safe_int(result.get('response', {}).get('activity', {}).get('p', last_points), last_points)
                except Exception:
                    pass
                simulated = min(effective_target, base_progress + (i + 1) * report_per_minutes)
                logger.info(f"{LogIndent.ITEM}{LogTag.READ} Edge浏览进度估算: {simulated}/{effective_target} 分钟")
            except Exception as e:
                logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} Edge浏览打卡异常: {e}")
                self._result['edge_checkin_points'] = -1
                return -1
            if i < remaining_requests - 1:
                time.sleep(305)

        if last_points == 0:
            verify_status = self._get_edge_checkin_status()
            if verify_status and verify_status.get('complete'):
                self._result['edge_checkin_points'] = 0
                return 0
        self._result['edge_checkin_points'] = last_points
        return last_points

    def _submit_read_activity(self) -> bool:
        try:
            payload = {
                'amount': 1,
                'country': 'cn',
                'id': secrets.token_hex(32),
                'type': 101,
                'attributes': {'offerid': 'ENUS_readarticle3_30points'}
            }
            resp = self._request('POST', f"{self.API_BASE}/me/activities", headers=self._get_headers(True), json=payload)
            if resp.status_code == 200:
                return True
            try:
                error_data = resp.json()
                if 'already' in str(error_data.get('error', {}).get('description', '')).lower():
                    return True
            except Exception:
                pass
            return False
        except Exception as e:
            return 'already' in str(e).lower()

    @retry_decorator(retries=3)
    def complete_read_tasks(self) -> int:
        logger.info(f"{LogIcon.READ} {LogTag.READ} 账号{self.account_index} 执行 APP 阅读任务")
        try:
            progress_data = self._get_read_progress()
            max_progress = progress_data['max']
            current_progress = progress_data['progress']
            if max_progress == 0:
                logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 无法获取阅读任务数据")
                return 0
            logger.info(f"{LogIndent.ITEM}{LogTag.READ} 阅读进度: {current_progress}/{max_progress}")
            if current_progress >= max_progress:
                logger.success(f"{LogIndent.ITEM}{LogIcon.SUCCESS} 阅读任务已完成")
                self._result['read_progress'] = current_progress
                return current_progress
            for i in range(max_progress - current_progress):
                logger.info(f"{LogIndent.ITEM}{LogTag.READ} 执行第 {i + 1} 次阅读")
                if self._submit_read_activity():
                    time.sleep(random.uniform(5, 10))
                    new_progress = self._get_read_progress().get('progress', current_progress)
                    if new_progress > current_progress:
                        current_progress = new_progress
                        logger.info(f"{LogIndent.ITEM}{LogTag.READ} 阅读进度: {current_progress}/{max_progress}")
                        if current_progress >= max_progress:
                            break
                else:
                    logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 第 {i + 1} 次阅读提交失败")
                    time.sleep(random.uniform(2, 5))
            self._result['read_progress'] = current_progress
            return current_progress
        except Exception as e:
            logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 阅读任务异常: {e}")
            return 0

    def run_all_tasks(self) -> dict:
        if not self._get_access_token():
            logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 无法获取 access_token，跳过 APP 任务")
            return self._result
        self.app_sign_in()
        self.complete_edge_checkin()
        self.complete_read_tasks()
        return self._result


class PointsPageManagerBase:
    """积分页面任务管理基类"""
    
    def __init__(self, browser_mgr):
        self.browser_mgr = browser_mgr
        self.browser = browser_mgr.browser
        self.page = browser_mgr.page
        self.stats = {
            "punch": {"done": 0, "total": 0},
            "activity": {"done": 0, "total": 0}
        }

    def complete_points_tasks(self, account_index=1):
        """完成积分页面上的所有任务 - 子类实现"""
        raise NotImplementedError


def _is_page_alive(self, tab=None):
    target = tab or self.page
    if not target:
        return False
    try:
        _ = target.tab_id
        _ = target.url
        _ = list(self.browser.tab_ids or [])
        return True
    except Exception:
        return False

def _recover_page(self, fallback_url=REWARDS_EARN_URL, activate=True):
    """恢复当前页面句柄，必要时新建标签页。"""
    try:
        if self._is_page_alive(self.page):
            current = self.page
        else:
            current = None
            try:
                latest = self.browser.latest_tab
                if latest and self._is_page_alive(latest):
                    current = latest
            except Exception:
                current = None

            if current is None:
                current = self.browser.new_tab(fallback_url)
                time.sleep(random.uniform(2, 3))

            self.page = current
            self.browser_mgr.page = current

        if activate:
            try:
                self.page.activate()
            except Exception:
                pass

        if fallback_url:
            try:
                current_url = self.page.url or ""
            except Exception:
                current_url = ""
            need_nav = False
            if not current_url:
                need_nav = True
            else:
                expected = fallback_url.split('#')[0]
                if expected not in current_url:
                    need_nav = True
            if need_nav:
                self.page.get(fallback_url)
                try:
                    self.page.wait.load_start(timeout=20)
                except Exception:
                    pass
                time.sleep(random.uniform(2, 4))
        return True
    except Exception as e:
        logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 页面恢复失败: {e}")
        return False

def _close_extra_tabs(self, keep_tab=None):
    try:
        keep_ids = set()

        if keep_tab:
            try:
                keep_ids.add(keep_tab.tab_id)
            except Exception:
                pass

        try:
            if self.page:
                keep_ids.add(self.page.tab_id)
        except Exception:
            pass

        tabs = list(self.browser.tab_ids or [])
        closed = 0
        for tab_id in tabs:
            if tab_id in keep_ids:
                continue
            try:
                self.browser.get_tab(tab_id).close()
                closed += 1
            except Exception:
                pass

        if keep_tab and self._is_page_alive(keep_tab):
            try:
                self.page = keep_tab
                self.browser_mgr.page = keep_tab
                keep_tab.activate()
                return closed
            except Exception:
                pass

        try:
            latest = self.browser.latest_tab
            if latest and self._is_page_alive(latest):
                self.page = latest
                self.browser_mgr.page = latest
        except Exception:
            pass

        return closed
    except Exception as e:
        logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 关闭多余标签页异常: {e}")
        return 0

def _close_new_tabs(self, before_tab_ids, keep_tab=None):
    try:
        current_ids = set(self.browser.tab_ids or [])
    except Exception as e:
        logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 读取标签页失败: {e}")
        return 0

    keep_ids = set(before_tab_ids or set())
    if keep_tab:
        try:
            keep_ids.add(keep_tab.tab_id)
        except Exception:
            pass

    close_ids = [tab_id for tab_id in current_ids if tab_id not in keep_ids]
    closed = 0
    for tab_id in close_ids:
        try:
            self.browser.get_tab(tab_id).close()
            closed += 1
        except Exception:
            pass

    if keep_tab and self._is_page_alive(keep_tab):
        self.page = keep_tab
        self.browser_mgr.page = keep_tab
    return closed

    def claim_dashboard_rewards(self, account_index=1):
        claim_points = 0
        try:
            logger.info(f"{LogIcon.INFO} {LogTag.POINTS} 账号{account_index} 检查待领取积分...")
            if not self._recover_page(REWARDS_URL):
                logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 无法恢复积分页面，跳过领取")
                return claim_points
            # 通过 #user-pointclaim 容器定位
            claim_container = self.page.ele('#user-pointclaim', timeout=5)
            if claim_container:
                title_ele = claim_container.ele('tag:p', timeout=2)
                if title_ele:
                    title_text = title_ele.text or ""
                    nums = re.findall(r'领取\s*(\d[\d,]*)\s*(?:奖励)?积分', title_text)
                    if nums:
                        claim_points = int(nums[0].replace(',', ''))
                
                if claim_points > 0:
                    logger.info(f"{LogIndent.ITEM}{LogTag.POINTS} 发现待领取: {claim_points} 分")
                    claim_btn = claim_container.ele('tag:button', timeout=2)
                    if claim_btn:
                        claim_btn.click()
                        time.sleep(random.uniform(3, 5))
                        logger.success(f"{LogIndent.ITEM}{LogIcon.SUCCESS} 已领取 {claim_points} 分")
                    else:
                        logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 容器内未找到领取按钮")
                else:
                    logger.info(f"{LogIndent.ITEM}{LogTag.POINTS} 当前无待领取积分")
                return claim_points
            # 通过 aria-label 查找
            claim_btn = self.page.ele('css:button[aria-label="领取"]', timeout=2)
            if not claim_btn:
                claim_btn = self.page.ele('css:button[aria-label*="Claim"]', timeout=1)
            if claim_btn:
                parent = claim_btn.parent()
                if parent:
                    parent_text = parent.text or ""
                    nums = re.findall(r'(\d[\d,]*)', parent_text)
                    for n in nums:
                        val = int(n.replace(',', ''))
                        if val > 0 and val < 100000:  # 合理的积分范围
                            claim_points = val
                            break
                
                if claim_points > 0:
                    logger.info(f"{LogIndent.ITEM}{LogTag.POINTS} 发现待领取(备用): {claim_points} 分")
                    claim_btn.click()
                    time.sleep(random.uniform(3, 5))
                    logger.success(f"{LogIndent.ITEM}{LogIcon.SUCCESS} 已领取 {claim_points} 分")
                else:
                    logger.info(f"{LogIndent.ITEM}{LogTag.POINTS} 当前无待领取积分")
                return claim_points
            
            # 旧版页面兼容
            claim_card = self.page.ele('xpath://div[contains(@class,"rewardsBgAlpha1")]/ancestor::button', timeout=2)
            if not claim_card:
                text_ele = self.page.ele('text:可领取', timeout=1)
                if text_ele:
                    claim_card = text_ele.parent(2)
            if claim_card:
                text = claim_card.text.replace(',', '')
                nums = re.findall(r'\d+', text)
                if nums:
                    claim_points = int(nums[0])
                if claim_points > 0:
                    logger.info(f"{LogIndent.ITEM}{LogTag.POINTS} 发现待领取(旧版): {claim_points} 分")
                    claim_card.click()
                    time.sleep(random.uniform(3, 5))
                    logger.success(f"{LogIndent.ITEM}{LogIcon.SUCCESS} 已领取 {claim_points} 分")
                else:
                    logger.info(f"{LogIndent.ITEM}{LogTag.POINTS} 当前无待领取积分")
                return claim_points
            
            logger.info(f"{LogIndent.ITEM}{LogTag.POINTS} 未发现可领取模块")
            return claim_points
        except Exception as e:
            logger.error(f"{LogIcon.FAIL} {LogTag.POINTS} 领取积分异常: {e}")
            self.browser_mgr.save_screenshot("claim_rewards_exception")
            self.browser_mgr.save_html("claim_rewards_exception")
            return claim_points


class PointsPageManagerOldVersion(PointsPageManagerBase):
    """旧版积分页面任务管理"""

    def complete_points_tasks(self, account_index=1):
        """完成旧版积分页面上的所有任务"""
        logger.info(f"{LogIcon.INFO} {LogTag.ACTIVITY} 账号{account_index} 扫描积分页面任务(旧版)...")
        self.stats = {"punch": {"done": 0, "total": 0}, "activity": {"done": 0, "total": 0}}
        try:
            self.page.get(REWARDS_URL)
            self.page.wait.load_start()
            time.sleep(random.uniform(5, 8))
            
            # 1. 处理打卡任务
            self._process_punch_cards()
            # 打卡后恢复页面连接
            try:
                self.page.get(REWARDS_URL)
                self.page.wait.load_start()
                time.sleep(random.uniform(3, 5))
            except Exception:
                try:
                    logger.info(f"{LogIndent.ITEM}{LogIcon.WARN} 页面连接断开，正在恢复...")
                    latest = self.browser.latest_tab
                    if latest:
                        self.page = latest
                        self.browser_mgr.page = latest
                    else:
                        self.page = self.browser.new_tab(REWARDS_URL)
                        self.browser_mgr.page = self.page
                    self.page.get(REWARDS_URL)
                    self.page.wait.load_start()
                    time.sleep(random.uniform(3, 5))
                    logger.info(f"{LogIndent.ITEM}{LogIcon.SUCCESS} 页面连接已恢复")
                except Exception as e2:
                    logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 恢复页面连接失败: {e2}")
            # 2. 处理浏览任务和每日活动
            self._process_browse_activities()
            
            logger.success(f"{LogIndent.ITEM}{LogIcon.SUCCESS} {LogTag.ACTIVITY} 积分页面任务处理完毕")
        except Exception as e:
            logger.error(f"{LogIcon.FAIL} {LogTag.ACTIVITY} 任务流程异常: {e}")
            self.browser_mgr.save_screenshot("points_tasks_exception")
            self.browser_mgr.save_html("points_tasks_exception")


def _process_punch_cards(self):
    """处理打卡任务"""
    try:
        punch_links = self.page.run_js("""
        const links = [];
        const punchSection = document.querySelector('#punch-cards');
        if (punchSection) {
            const allLinks = punchSection.querySelectorAll('a[href*="/dashboard/"]');
            allLinks.forEach(link => {
                const href = link.getAttribute('href');
                if (href) links.push(href);
            });
        }
        return links;
        """)

        if not punch_links:
            logger.info(f"{LogIndent.ITEM}{LogTag.ACTIVITY} 未发现打卡任务")
            return

        logger.info(f"{LogIndent.ITEM}{LogTag.ACTIVITY} 发现 {len(punch_links)} 个打卡任务")

        for i, href in enumerate(punch_links, 1):
            try:
                full_url = f"{REWARDS_BASE_URL}{href}" if href.startswith('/') else href
                logger.info(f"{LogIndent.ITEM}{LogTag.ACTIVITY} 打卡任务 ({i}/{len(punch_links)})")

                if not self._recover_page(full_url):
                    logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 无法打开打卡任务页面: {full_url}")
                    continue

                self._process_punch_card_tasks(self.page, full_url)
                self._recover_page(REWARDS_URL)
                time.sleep(random.uniform(1, 2))
            except Exception as e:
                logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} {LogTag.ACTIVITY} 打卡任务处理失败: {e}")
                self._recover_page(REWARDS_URL)
    except Exception as e:
        logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} {LogTag.ACTIVITY} 打卡任务流程异常: {e}")

    def _process_punch_card_tasks(self, tab, punch_url=None):
        """处理打卡详情页的子任务"""
        try:
            tasks = tab.run_js("""
            const tasks = [];
            const rows = document.querySelectorAll('.punchcard-row');
            rows.forEach((row, idx) => {
                const incompleteIcon = row.querySelector('.mee-icon-InkingColorOutline');
                const completedIcon = row.querySelector('.mee-icon-CompletedSolid');
                const isCompleted = !!completedIcon && !incompleteIcon;
                
                const link = row.querySelector('a.offer-cta');
                if (link) {
                    const href = link.getAttribute('href') || '';
                    tasks.push({href, isCompleted, index: idx});
                }
            });
            return tasks;
            """)
            
            if not tasks:
                return
            
            pending = [t for t in tasks if not t['isCompleted']]
            completed = len([t for t in tasks if t['isCompleted']])
            total = len(tasks)
            
            self.stats["punch"]["total"] += total
            self.stats["punch"]["done"] += completed
            
            if not pending:
                logger.info(f"{LogIndent.ITEM}       └── 子任务已全部完成 ({completed}/{total})")
                return
            
            executed = 0
            for i, task in enumerate(pending, 1):
                try:
                    task_index = task['index']
                    task_href = task.get('href', '')
                    logger.info(f"{LogIndent.ITEM}       ├── 执行 ({i}/{len(pending)})")
                    
                    # 获取子任务链接
                    if not task_href:
                        try:
                            task_href = tab.run_js(f'''
                                var rows = document.querySelectorAll('.punchcard-row');
                                var targetRow = rows[{task_index}];
                                if (targetRow) {{
                                    var link = targetRow.querySelector('a.offer-cta');
                                    if (link) return link.getAttribute('href') || '';
                                }}
                                return '';
                            ''')
                        except Exception:
                            task_href = ''
                    
                    if task_href:
                        if task_href.startswith('/'):
                            full_url = f"{REWARDS_BASE_URL}{task_href}"
                        elif task_href.startswith('http'):
                            full_url = task_href
                        else:
                            full_url = f"{BING_URL}/{task_href}"
                        
                        # 新标签页打开
                        try:
                            new_tab = self.browser.new_tab(full_url)
                            time.sleep(random.uniform(5, 8))
                            try:
                                new_tab.close()
                            except Exception:
                                pass
                        except Exception:
                            pass
                        time.sleep(random.uniform(1, 2))
                        executed += 1
                    else:
                        logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 未找到打卡任务链接")
                except Exception as e:
                    logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} {LogTag.ACTIVITY} 子任务失败: {e}")
                    # 连接断开时跳出
                    if "disconnected" in str(e).lower():
                        logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 页面连接断开，停止剩余子任务")
                        break
            
            self.stats["punch"]["done"] += executed
        except Exception as e:
            logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} {LogTag.ACTIVITY} 打卡子任务异常: {e}")

    def _process_browse_activities(self):
        """处理 '在必应上浏览' 和 '每日活动' 任务"""
        try:
            tasks = self.page.run_js("""
            const tasks = [];
            
            const exploreSection = document.querySelector('#explore-on-bing');
            if (exploreSection) {
                const exploreCards = exploreSection.querySelectorAll('mee-card');
                exploreCards.forEach(card => {
                    const link = card.querySelector('a[href]');
                    if (!link) return;
                    const href = link.getAttribute('href') || '';
                    if (!href || href === '#') return;
                    
                    const titleEl = card.querySelector('h3');
                    const text = titleEl ? titleEl.innerText.trim() : '';
                    const pointsEl = card.querySelector('.pointsString');
                    const points = pointsEl ? pointsEl.innerText.trim() : '?';
                    
                    const addIcon = card.querySelector('.mee-icon-AddMedium');
                    const checkIcon = card.querySelector('.mee-icon-StatusCircleCheckmark');
                    const isCompleted = !!checkIcon && !addIcon;
                    
                    tasks.push({href, text: text.substring(0, 30), points, isCompleted, section: 'browse'});
                });
            }
            
            const activitiesSection = document.querySelector('#more-activities');
            if (activitiesSection) {
                const activityCards = activitiesSection.querySelectorAll('mee-card');
                activityCards.forEach(card => {
                    const link = card.querySelector('a[href]');
                    if (!link) return;
                    const href = link.getAttribute('href') || '';
                    if (!href || href === '#') return;
                    
                    const titleEl = card.querySelector('h3');
                    const text = titleEl ? titleEl.innerText.trim() : '';
                    const pointsEl = card.querySelector('.pointsString');
                    const points = pointsEl ? pointsEl.innerText.trim() : '?';
                    
                    const addIcon = card.querySelector('.mee-icon-AddMedium');
                    const checkIcon = card.querySelector('.mee-icon-StatusCircleCheckmark');
                    const isCompleted = !!checkIcon && !addIcon;
                    
                    tasks.push({href, text: text.substring(0, 30), points, isCompleted, section: 'activity'});
                });
            }
            
            return tasks;
            """)
            
            if not tasks:
                logger.info(f"{LogIndent.ITEM}{LogTag.ACTIVITY} 未发现浏览/活动任务")
                return
            
            seen = set()
            unique = []
            for t in tasks:
                if t['href'] not in seen:
                    seen.add(t['href'])
                    unique.append(t)
            
            pending = [t for t in unique if not t['isCompleted'] and t.get('points', '?') != '?']
            skipped = len([t for t in unique if not t['isCompleted'] and t.get('points', '?') == '?'])
            completed = len([t for t in unique if t['isCompleted']])
            total = len(unique)
            
            self.stats["activity"]["total"] = total
            self.stats["activity"]["done"] = completed
            
            logger.info(f"{LogIndent.ITEM}{LogTag.ACTIVITY} 浏览/活动任务: 待处理 {len(pending)}, 已完成 {completed}, 跳过 {skipped}")
            
            if not pending:
                return
            
            executed = 0
            for i, task in enumerate(pending, 1):
                href = task['href']
                text = task['text'] or '未知'
                pts = task['points']
                section = '浏览' if task.get('section') == 'browse' else '活动'
                logger.info(f"{LogIndent.ITEM}{LogTag.ACTIVITY} ({i}/{len(pending)}) [{section}] {text} (+{pts}分)")
                
                try:
                    escaped_href = href.replace("'", "").replace('"', '')
                    js_code = '''
                        var targetHref = '%s';
                        var cards = document.querySelectorAll('mee-card a[href], a[href]');
                        for (var card of cards) {
                            var cardHref = card.getAttribute('href') || '';
                            if (cardHref === targetHref || cardHref.includes(targetHref) || targetHref.includes(cardHref)) {
                                card.click();
                                return true;
                            }
                        }
                        return false;
                    ''' % escaped_href
                    try:
                        clicked = self.page.run_js(js_code)
                    except Exception:
                        clicked = False
                    
                    if clicked:
                        time.sleep(random.uniform(5, 8))
                        try:
                            self._close_extra_tabs(keep_tab=self.page)
                        except Exception:
                            pass
                        time.sleep(random.uniform(1, 2))
                        executed += 1
                    else:
                        logger.info(f"{LogIndent.ITEM}       ├── 未找到卡片，直接访问")
                        if href.startswith('http'):
                            full_url = href
                        elif href.startswith('/'):
                            if '/search' in href or '/images' in href or '/videos' in href:
                                full_url = BING_URL.rstrip('/') + href
                            else:
                                full_url = f"{REWARDS_BASE_URL}{href}"
                        else:
                            full_url = f"{BING_URL}{href}"
                        
                        try:
                            new_tab = self.browser.new_tab(full_url)
                            new_tab.wait.load_start()
                            time.sleep(random.uniform(5, 8))
                            new_tab.close()
                        except Exception:
                            pass
                        time.sleep(random.uniform(1, 2))
                        executed += 1
                except Exception as e:
                    logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} {LogTag.ACTIVITY} 任务失败: {e}")
                    if "disconnected" in str(e).lower():
                        logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 页面连接断开，停止剩余任务")
                        break
            
            self.stats["activity"]["done"] += executed
        except Exception as e:
            logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} {LogTag.ACTIVITY} 浏览/活动任务异常: {e}")


class PointsPageManagerNewVersion(PointsPageManagerBase):
    """新版积分页面任务管理 (/earn 页面)"""

    def complete_points_tasks(self, account_index=1):
        """完成新版积分页面上的所有任务"""
        logger.info(f"{LogIcon.INFO} {LogTag.ACTIVITY} 账号{account_index} 扫描积分页面任务(新版)...")
        self.stats = {"punch": {"done": 0, "total": 0}, "activity": {"done": 0, "total": 0}}
        try:
            self.page.get(REWARDS_EARN_URL)
            self.page.wait.load_start()
            time.sleep(random.uniform(5, 8))
            
            rsc_data = (self.page.html or '').replace('\\"', '"').replace('\\\\', '\\')
            
            # 1. 处理打卡任务
            self._process_punch_cards(rsc_data)
            
            # 2. 处理活动任务
            self._process_activities(rsc_data)
            
            logger.success(f"{LogIndent.ITEM}{LogIcon.SUCCESS} {LogTag.ACTIVITY} 积分页面任务处理完毕")
        except Exception as e:
            logger.error(f"{LogIcon.FAIL} {LogTag.ACTIVITY} 任务流程异常: {e}")
            self.browser_mgr.save_screenshot("points_tasks_exception")
            self.browser_mgr.save_html("points_tasks_exception")


def _process_punch_cards(self, rsc_data):
    try:
        punch_links = self.page.run_js("""
        const links = [];
        const allLinks = document.querySelectorAll('a[href*="/earn/"]');
        allLinks.forEach(link => {
            const href = link.getAttribute('href');
            if (href && href.includes('punchcard')) {
                links.push(href);
            }
        });
        return [...new Set(links)];
        """)

        if not punch_links:
            logger.info(f"{LogIndent.ITEM}{LogTag.ACTIVITY} 未发现打卡任务入口")
            return

        logger.info(f"{LogIndent.ITEM}{LogTag.ACTIVITY} 发现 {len(punch_links)} 个打卡任务")

        for i, href in enumerate(punch_links, 1):
            try:
                full_url = f"{REWARDS_BASE_URL}{href}" if href.startswith('/') else href
                logger.info(f"{LogIndent.ITEM}{LogTag.ACTIVITY} 打卡任务 ({i}/{len(punch_links)})")

                if not self._recover_page(full_url):
                    logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 无法打开打卡任务页面: {full_url}")
                    continue

                self._process_punch_card_tasks(self.page, full_url)
                self._recover_page(REWARDS_EARN_URL)
                time.sleep(random.uniform(1, 2))
            except Exception as e:
                logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} {LogTag.ACTIVITY} 打卡任务处理失败: {e}")
                self._recover_page(REWARDS_EARN_URL)
    except Exception as e:
        logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} {LogTag.ACTIVITY} 打卡任务流程异常: {e}")

    def _process_punch_card_tasks(self, tab, punch_url=None):
        try:
            page_html = (tab.html or '').replace('\\"', '"')
            # 解析打卡子任务
            tasks = []
            pattern = re.compile(
                r'\{[^}]*"href"\s*:\s*"([^"]+)"[^}]*"isCompleted"\s*:\s*(true|false)[^}]*"isLocked"\s*:\s*(true|false)[^}]*\}',
                re.DOTALL
            )
            for match in pattern.finditer(page_html):
                href = match.group(1).replace('\\u0026', '&')
                is_completed = match.group(2) == 'true'
                is_locked = match.group(3) == 'true'
                if href.startswith('http'):
                    tasks.append({'href': href, 'isCompleted': is_completed, 'isLocked': is_locked})
            
            if not tasks:
                logger.info(f"{LogIndent.ITEM}       └── 未发现子任务")
                return
            
            pending = [t for t in tasks if not t['isCompleted'] and not t['isLocked']]
            completed = len([t for t in tasks if t['isCompleted']])
            total = len(tasks)
            
            self.stats["punch"]["total"] += total
            self.stats["punch"]["done"] += completed
            
            if not pending:
                logger.info(f"{LogIndent.ITEM}       └── 子任务已全部完成或锁定 ({completed}/{total})")
                return
            
            logger.info(f"{LogIndent.ITEM}       ├── 子任务: 待处理 {len(pending)}, 已完成 {completed}")
            
            executed = 0
            for i, task in enumerate(pending, 1):
                try:
                    logger.info(f"{LogIndent.ITEM}       ├── 执行 ({i}/{len(pending)})")
                    
                    target_href = task['href'].replace("'", "").replace('"', '')
                    js_code = '''
                        var targetHref = '%s';
                        var buttons = document.querySelectorAll('a[href], button');
                        for (var btn of buttons) {
                            var btnHref = btn.getAttribute('href') || '';
                            if (btnHref.includes('bing.com/search') || btnHref.includes('form=ML')) {
                                if (btnHref === targetHref || targetHref.includes(btnHref.split('?')[0])) {
                                    btn.click();
                                    return true;
                                }
                            }
                        }
                        // 备用：点击第一个可用的按钮
                        var primaryBtn = document.querySelector('a[class*="primary"][href*="bing.com"]');
                        if (primaryBtn && !primaryBtn.disabled) {
                            primaryBtn.click();
                            return true;
                        }
                        return false;
                    ''' % target_href
                    try:
                        clicked = tab.run_js(js_code)
                    except Exception:
                        clicked = False
                    
                    if clicked:
                        time.sleep(random.uniform(5, 8))
                        try:
                            self._close_extra_tabs(keep_tab=tab)
                        except Exception:
                            pass
                        time.sleep(random.uniform(1, 2))
                        executed += 1
                    else:
                        logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 未找到打卡任务按钮")
                except Exception as e:
                    logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} {LogTag.ACTIVITY} 子任务失败: {e}")
                    if "disconnected" in str(e).lower():
                        logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 页面连接断开，停止剩余子任务")
                        break
            
            self.stats["punch"]["done"] += executed
        except Exception as e:
            logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} {LogTag.ACTIVITY} 打卡子任务异常: {e}")


def _process_activities(self, rsc_data):
    try:
        activities = self._parse_activity_cards(rsc_data)

        if not activities:
            logger.info(f"{LogIndent.ITEM}{LogTag.ACTIVITY} 未发现活动任务")
            return

        pending = [
            a for a in activities
            if not a.get('isCompleted', False)
            and not a.get('isPromotional', False)
            and not a.get('isLocked', False)
            and a.get('points', 0) > 0
            and a.get('destination', '').startswith('http')
        ]
        completed = sum(1 for a in activities if a.get('isCompleted', False))
        total = len(activities)

        self.stats["activity"]["total"] = total
        self.stats["activity"]["done"] = completed

        logger.info(f"{LogIndent.ITEM}{LogTag.ACTIVITY} 活动任务: 待处理 {len(pending)}, 已完成 {completed}, 总计 {total}")

        if not pending:
            return

        executed = 0
        for i, task in enumerate(pending, 1):
            title = task.get('title', '未知')[:30]
            pts = task.get('points', 0)
            dest = task.get('destination', '')
            logger.info(f"{LogIndent.ITEM}{LogTag.ACTIVITY} ({i}/{len(pending)}) {title} (+{pts}分)")

            try:
                if not dest.startswith('http'):
                    logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 无有效活动链接: {title}")
                    continue

                if not self._recover_page(dest):
                    logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 无法打开活动链接: {title}")
                    continue

                time.sleep(random.uniform(5, 8))
                self._recover_page(REWARDS_EARN_URL)
                time.sleep(random.uniform(1, 2))
                executed += 1
            except Exception as e:
                logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} {LogTag.ACTIVITY} 任务失败: {e}")
                self._recover_page(REWARDS_EARN_URL)

        self.stats["activity"]["done"] += executed
    except Exception as e:
        logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} {LogTag.ACTIVITY} 新版活动任务异常: {e}")
        self.browser_mgr.save_screenshot("new_version_activities_exception")
        self.browser_mgr.save_html("new_version_activities_exception")

    def _parse_activity_cards(self, rsc_data):
        cards = []
        try:
            anchor_pattern = re.compile(
                r'(?:"|\\")MoreActivities(?:"|\\").{0,1500}?(?:"|\\")activityCards(?:"|\\")\s*:\s*\[',
                re.DOTALL
            )
            match = anchor_pattern.search(rsc_data)
            if not match:
                return cards

            start = match.end() - 1

            depth = 0
            end = -1
            for j in range(start, min(len(rsc_data), start + 120000)):
                if rsc_data[j] == '[':
                    depth += 1
                elif rsc_data[j] == ']':
                    depth -= 1
                    if depth == 0:
                        end = j + 1
                        break

            if end <= 0:
                return cards

            arr_str = rsc_data[start:end]
            clean_arr = arr_str.replace('\\"', '"')
            
            try:
                cards_data = json.loads(clean_arr)
            except:
                cards_data = []

            if isinstance(cards_data, list):
                for item in cards_data:
                    if not isinstance(item, dict):
                        continue
                    is_promo = item.get("isPromotional")
                    is_promo = is_promo is True or is_promo == "true"
                    is_completed = item.get("isCompleted")
                    is_completed = is_completed is True or is_completed == "true"
                    is_locked = item.get("isLocked")
                    is_locked = is_locked is True or is_locked == "true"
                    
                    cards.append({
                        "destination": str(item.get("destination", "")),
                        "title": str(item.get("title", "")),
                        "isCompleted": is_completed,
                        "isPromotional": is_promo,
                        "isLocked": is_locked,
                        "points": int(item.get("points", 0)) if str(item.get("points", 0)).isdigit() else 0,
                    })
        except Exception as e:
            logger.warning(f"{LogIcon.WARN} {LogTag.ACTIVITY} 解析 activityCards 失败: {e}")

        return cards



# ==================== 修复补丁：绑定漏缩进的方法到类 ====================
def _ppm_base_is_page_alive(self, tab=None):
    target = tab or getattr(self, 'page', None)
    if not target:
        return False
    try:
        _ = target.tab_id
        _ = target.url
        _ = list(self.browser.tab_ids or [])
        return True
    except Exception:
        return False


def _ppm_base_recover_page(self, fallback_url=REWARDS_EARN_URL, activate=True):
    """恢复当前页面句柄，必要时新建标签页。"""
    try:
        current = None
        if self._is_page_alive(getattr(self, 'page', None)):
            current = self.page
        else:
            try:
                latest = self.browser.latest_tab
                if latest and self._is_page_alive(latest):
                    current = latest
            except Exception:
                current = None

        if current is None:
            current = self.browser.new_tab(fallback_url)
            time.sleep(random.uniform(2, 3))

        self.page = current
        self.browser_mgr.page = current

        if activate:
            try:
                self.page.activate()
            except Exception:
                pass

        if fallback_url:
            try:
                current_url = self.page.url or ''
            except Exception:
                current_url = ''
            expected = fallback_url.split('#')[0]
            need_nav = not current_url or expected not in current_url
            if need_nav:
                self.page.get(fallback_url)
                try:
                    self.page.wait.load_start(timeout=20)
                except Exception:
                    pass
                time.sleep(random.uniform(2, 4))
        return True
    except Exception as e:
        logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 页面恢复失败: {e}")
        return False


def _ppm_base_close_extra_tabs(self, keep_tab=None):
    try:
        keep_ids = set()
        if keep_tab:
            try:
                keep_ids.add(keep_tab.tab_id)
            except Exception:
                pass
        try:
            if getattr(self, 'page', None):
                keep_ids.add(self.page.tab_id)
        except Exception:
            pass

        tabs = list(self.browser.tab_ids or [])
        closed = 0
        for tab_id in tabs:
            if tab_id in keep_ids:
                continue
            try:
                self.browser.get_tab(tab_id).close()
                closed += 1
            except Exception:
                pass

        if keep_tab and self._is_page_alive(keep_tab):
            try:
                self.page = keep_tab
                self.browser_mgr.page = keep_tab
                keep_tab.activate()
                return closed
            except Exception:
                pass

        try:
            latest = self.browser.latest_tab
            if latest and self._is_page_alive(latest):
                self.page = latest
                self.browser_mgr.page = latest
        except Exception:
            pass
        return closed
    except Exception as e:
        logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 关闭多余标签页异常: {e}")
        return 0


def _ppm_base_close_new_tabs(self, before_tab_ids, keep_tab=None):
    try:
        current_ids = set(self.browser.tab_ids or [])
    except Exception as e:
        logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 读取标签页失败: {e}")
        return 0

    keep_ids = set(before_tab_ids or set())
    if keep_tab:
        try:
            keep_ids.add(keep_tab.tab_id)
        except Exception:
            pass

    close_ids = [tab_id for tab_id in current_ids if tab_id not in keep_ids]
    closed = 0
    for tab_id in close_ids:
        try:
            self.browser.get_tab(tab_id).close()
            closed += 1
        except Exception:
            pass

    if keep_tab and self._is_page_alive(keep_tab):
        self.page = keep_tab
        self.browser_mgr.page = keep_tab
    return closed


def _ppm_base_claim_dashboard_rewards(self, account_index=1):
    claim_points = 0
    try:
        logger.info(f"{LogIcon.INFO} {LogTag.POINTS} 账号{account_index} 检查待领取积分...")
        if not self._recover_page(REWARDS_URL):
            logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 无法恢复积分页面，跳过领取")
            return claim_points

        claim_container = self.page.ele('#user-pointclaim', timeout=5)
        if claim_container:
            title_ele = claim_container.ele('tag:p', timeout=2)
            if title_ele:
                title_text = title_ele.text or ''
                nums = re.findall(r'领取\s*(\d[\d,]*)\s*(?:奖励)?积分', title_text)
                if nums:
                    claim_points = int(nums[0].replace(',', ''))
            if claim_points > 0:
                logger.info(f"{LogIndent.ITEM}{LogTag.POINTS} 发现待领取: {claim_points} 分")
                claim_btn = claim_container.ele('tag:button', timeout=2)
                if claim_btn:
                    claim_btn.click()
                    time.sleep(random.uniform(3, 5))
                    logger.success(f"{LogIndent.ITEM}{LogIcon.SUCCESS} 已领取 {claim_points} 分")
                else:
                    logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 容器内未找到领取按钮")
            else:
                logger.info(f"{LogIndent.ITEM}{LogTag.POINTS} 当前无待领取积分")
            return claim_points

        claim_btn = self.page.ele('css:button[aria-label="领取"]', timeout=2)
        if not claim_btn:
            claim_btn = self.page.ele('css:button[aria-label*="Claim"]', timeout=1)
        if claim_btn:
            parent = claim_btn.parent()
            if parent:
                parent_text = parent.text or ''
                nums = re.findall(r'(\d[\d,]*)', parent_text)
                for n in nums:
                    val = int(n.replace(',', ''))
                    if 0 < val < 100000:
                        claim_points = val
                        break
            if claim_points > 0:
                logger.info(f"{LogIndent.ITEM}{LogTag.POINTS} 发现待领取(备用): {claim_points} 分")
                claim_btn.click()
                time.sleep(random.uniform(3, 5))
                logger.success(f"{LogIndent.ITEM}{LogIcon.SUCCESS} 已领取 {claim_points} 分")
            else:
                logger.info(f"{LogIndent.ITEM}{LogTag.POINTS} 当前无待领取积分")
            return claim_points

        claim_card = self.page.ele('xpath://div[contains(@class,"rewardsBgAlpha1")]/ancestor::button', timeout=2)
        if not claim_card:
            text_ele = self.page.ele('text:可领取', timeout=1)
            if text_ele:
                claim_card = text_ele.parent(2)
        if claim_card:
            text = (claim_card.text or '').replace(',', '')
            nums = re.findall(r'\d+', text)
            if nums:
                claim_points = int(nums[0])
            if claim_points > 0:
                logger.info(f"{LogIndent.ITEM}{LogTag.POINTS} 发现待领取(旧版): {claim_points} 分")
                claim_card.click()
                time.sleep(random.uniform(3, 5))
                logger.success(f"{LogIndent.ITEM}{LogIcon.SUCCESS} 已领取 {claim_points} 分")
            else:
                logger.info(f"{LogIndent.ITEM}{LogTag.POINTS} 当前无待领取积分")
            return claim_points

        logger.info(f"{LogIndent.ITEM}{LogTag.POINTS} 当前无待领取积分")
        return claim_points
    except Exception as e:
        logger.error(f"{LogIcon.FAIL} {LogTag.POINTS} 领取积分异常: {e}")
        self.browser_mgr.save_screenshot('claim_rewards_exception')
        self.browser_mgr.save_html('claim_rewards_exception')
        return claim_points


def _ppmnv_process_punch_cards(self, rsc_data):
    try:
        punch_links = self.page.run_js("""
        const links = [];
        const allLinks = document.querySelectorAll('a[href*="/earn/"]');
        allLinks.forEach(link => {
            const href = link.getAttribute('href');
            if (href && href.includes('punchcard')) links.push(href);
        });
        return [...new Set(links)];
        """) or []

        if not punch_links:
            logger.info(f"{LogIndent.ITEM}{LogTag.ACTIVITY} 未发现打卡任务入口")
            return

        logger.info(f"{LogIndent.ITEM}{LogTag.ACTIVITY} 发现 {len(punch_links)} 个打卡任务")
        for i, href in enumerate(punch_links, 1):
            try:
                full_url = f"{REWARDS_BASE_URL}{href}" if str(href).startswith('/') else str(href)
                logger.info(f"{LogIndent.ITEM}{LogTag.ACTIVITY} 打卡任务 ({i}/{len(punch_links)})")
                if not self._recover_page(full_url):
                    logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 无法打开打卡任务页面: {full_url}")
                    continue
                self._process_punch_card_tasks(self.page, full_url)
                self._recover_page(REWARDS_EARN_URL)
                time.sleep(random.uniform(1, 2))
            except Exception as e:
                logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} {LogTag.ACTIVITY} 打卡任务处理失败: {e}")
                self._recover_page(REWARDS_EARN_URL)
    except Exception as e:
        logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} {LogTag.ACTIVITY} 打卡任务流程异常: {e}")


def _ppmnv_process_punch_card_tasks(self, tab, punch_url=None):
    try:
        page_html = (tab.html or '').replace('\\"', '"')
        tasks = []
        pattern = re.compile(
            r'\{[^}]*"href"\s*:\s*"([^"]+)"[^}]*"isCompleted"\s*:\s*(true|false)[^}]*"isLocked"\s*:\s*(true|false)[^}]*\}',
            re.DOTALL
        )
        for match in pattern.finditer(page_html):
            href = match.group(1).replace('\\u0026', '&')
            is_completed = match.group(2) == 'true'
            is_locked = match.group(3) == 'true'
            if href:
                tasks.append({'href': href, 'isCompleted': is_completed, 'isLocked': is_locked})

        if not tasks:
            logger.info(f"{LogIndent.ITEM}       └── 未发现子任务")
            return

        pending = [t for t in tasks if not t['isCompleted'] and not t['isLocked']]
        completed = len([t for t in tasks if t['isCompleted']])
        total = len(tasks)
        self.stats['punch']['total'] += total
        self.stats['punch']['done'] += completed

        if not pending:
            logger.info(f"{LogIndent.ITEM}       └── 子任务已全部完成或锁定 ({completed}/{total})")
            return

        logger.info(f"{LogIndent.ITEM}       ├── 子任务: 待处理 {len(pending)}, 已完成 {completed}")
        executed = 0
        for i, task in enumerate(pending, 1):
            try:
                logger.info(f"{LogIndent.ITEM}       ├── 执行 ({i}/{len(pending)})")
                href = str(task.get('href', '')).strip()
                if not href:
                    continue
                if href.startswith('http'):
                    target_url = href
                elif href.startswith('/'):
                    if '/search' in href or '/images' in href or '/videos' in href:
                        target_url = BING_URL.rstrip('/') + href
                    else:
                        target_url = REWARDS_BASE_URL.rstrip('/') + href
                else:
                    target_url = BING_URL.rstrip('/') + '/' + href.lstrip('/')

                before_ids = set(self.browser.tab_ids or [])
                # 优先同页打开，避免 punch card 第二组因 tab 生命周期导致断连
                if not self._recover_page(target_url):
                    logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 无法打开打卡子任务链接")
                    continue
                time.sleep(random.uniform(5, 8))
                try:
                    self._close_new_tabs(before_ids, keep_tab=self.page)
                except Exception:
                    pass
                executed += 1
                if punch_url:
                    self._recover_page(punch_url)
                    time.sleep(random.uniform(1, 2))
            except Exception as e:
                logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} {LogTag.ACTIVITY} 子任务失败: {e}")
                if 'disconnected' in str(e).lower():
                    logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 页面连接断开，尝试恢复")
                    self._recover_page(punch_url or REWARDS_EARN_URL)
                    break
        self.stats['punch']['done'] += executed
    except Exception as e:
        logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} {LogTag.ACTIVITY} 打卡子任务异常: {e}")


def _ppmnv_parse_activity_cards(self, rsc_data):
    cards = []
    try:
        anchor_pattern = re.compile(
            r'(?:"|\\")MoreActivities(?:"|\\").{0,1500}?(?:"|\\")activityCards(?:"|\\")\s*:\s*\[',
            re.DOTALL
        )
        match = anchor_pattern.search(rsc_data)
        if not match:
            return cards
        start = match.end() - 1
        depth = 0
        end = -1
        for j in range(start, min(len(rsc_data), start + 120000)):
            if rsc_data[j] == '[':
                depth += 1
            elif rsc_data[j] == ']':
                depth -= 1
                if depth == 0:
                    end = j + 1
                    break
        if end <= 0:
            return cards
        arr_str = rsc_data[start:end]
        clean_arr = arr_str.replace('\\"', '"')
        try:
            cards_data = json.loads(clean_arr)
        except Exception:
            cards_data = []
        if isinstance(cards_data, list):
            for item in cards_data:
                if not isinstance(item, dict):
                    continue
                is_promo = item.get('isPromotional') in (True, 'true')
                is_completed = item.get('isCompleted') in (True, 'true')
                is_locked = item.get('isLocked') in (True, 'true')
                pts_raw = item.get('points', 0)
                pts = int(pts_raw) if str(pts_raw).isdigit() else 0
                cards.append({
                    'destination': str(item.get('destination', '')),
                    'title': str(item.get('title', '')),
                    'isCompleted': is_completed,
                    'isPromotional': is_promo,
                    'isLocked': is_locked,
                    'points': pts,
                })
    except Exception as e:
        logger.warning(f"{LogIcon.WARN} {LogTag.ACTIVITY} 解析 activityCards 失败: {e}")
    return cards


def _ppmnv_process_activities(self, rsc_data):
    try:
        activities = self._parse_activity_cards(rsc_data)
        if not activities:
            logger.info(f"{LogIndent.ITEM}{LogTag.ACTIVITY} 未发现活动任务")
            return

        pending = [
            a for a in activities
            if not a.get('isCompleted', False)
            and not a.get('isPromotional', False)
            and not a.get('isLocked', False)
            and a.get('points', 0) > 0
            and a.get('destination', '').startswith('http')
        ]
        completed = sum(1 for a in activities if a.get('isCompleted', False))
        total = len(activities)
        self.stats['activity']['total'] = total
        self.stats['activity']['done'] = completed
        logger.info(f"{LogIndent.ITEM}{LogTag.ACTIVITY} 活动任务: 待处理 {len(pending)}, 已完成 {completed}, 总计 {total}")
        if not pending:
            return

        executed = 0
        for i, task in enumerate(pending, 1):
            title = task.get('title', '未知')[:30]
            pts = task.get('points', 0)
            dest = task.get('destination', '')
            logger.info(f"{LogIndent.ITEM}{LogTag.ACTIVITY} ({i}/{len(pending)}) {title} (+{pts}分)")
            try:
                if not dest.startswith('http'):
                    logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 无有效活动链接: {title}")
                    continue
                before_ids = set(self.browser.tab_ids or [])
                if not self._recover_page(dest):
                    logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 无法打开活动链接: {title}")
                    continue
                time.sleep(random.uniform(5, 8))
                try:
                    self._close_new_tabs(before_ids, keep_tab=self.page)
                except Exception:
                    pass
                executed += 1
                self._recover_page(REWARDS_EARN_URL)
                time.sleep(random.uniform(1, 2))
            except Exception as e:
                logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} {LogTag.ACTIVITY} 任务失败: {e}")
                self._recover_page(REWARDS_EARN_URL)
        self.stats['activity']['done'] += executed
    except Exception as e:
        logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} {LogTag.ACTIVITY} 新版活动任务异常: {e}")
        self.browser_mgr.save_screenshot('new_version_activities_exception')
        self.browser_mgr.save_html('new_version_activities_exception')


def _ppmov_process_punch_cards(self):
    try:
        punch_links = self.page.run_js("""
        const links = [];
        const punchSection = document.querySelector('#punch-cards');
        if (punchSection) {
            const allLinks = punchSection.querySelectorAll('a[href*="/dashboard/"]');
            allLinks.forEach(link => {
                const href = link.getAttribute('href');
                if (href) links.push(href);
            });
        }
        return links;
        """) or []

        if not punch_links:
            logger.info(f"{LogIndent.ITEM}{LogTag.ACTIVITY} 未发现打卡任务")
            return

        logger.info(f"{LogIndent.ITEM}{LogTag.ACTIVITY} 发现 {len(punch_links)} 个打卡任务")
        for i, href in enumerate(punch_links, 1):
            try:
                full_url = f"{REWARDS_BASE_URL}{href}" if str(href).startswith('/') else str(href)
                logger.info(f"{LogIndent.ITEM}{LogTag.ACTIVITY} 打卡任务 ({i}/{len(punch_links)})")
                if not self._recover_page(full_url):
                    logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 无法打开打卡任务页面: {full_url}")
                    continue
                self._process_punch_card_tasks(self.page, full_url)
                self._recover_page(REWARDS_URL)
                time.sleep(random.uniform(1, 2))
            except Exception as e:
                logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} {LogTag.ACTIVITY} 打卡任务处理失败: {e}")
                self._recover_page(REWARDS_URL)
    except Exception as e:
        logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} {LogTag.ACTIVITY} 打卡任务流程异常: {e}")


def _ppmov_process_punch_card_tasks(self, tab, punch_url=None):
    try:
        tasks = tab.run_js("""
        const tasks = [];
        const rows = document.querySelectorAll('.punchcard-row');
        rows.forEach((row, idx) => {
            const incompleteIcon = row.querySelector('.mee-icon-InkingColorOutline');
            const completedIcon = row.querySelector('.mee-icon-CompletedSolid');
            const isCompleted = !!completedIcon && !incompleteIcon;
            const link = row.querySelector('a.offer-cta');
            if (link) {
                const href = link.getAttribute('href') || '';
                tasks.push({href, isCompleted, index: idx});
            }
        });
        return tasks;
        """) or []

        if not tasks:
            return

        pending = [t for t in tasks if not t['isCompleted']]
        completed = len([t for t in tasks if t['isCompleted']])
        total = len(tasks)
        self.stats["punch"]["total"] += total
        self.stats["punch"]["done"] += completed

        if not pending:
            logger.info(f"{LogIndent.ITEM}       └── 子任务已全部完成 ({completed}/{total})")
            return

        executed = 0
        for i, task in enumerate(pending, 1):
            try:
                task_index = task['index']
                task_href = task.get('href', '')
                logger.info(f"{LogIndent.ITEM}       ├── 执行 ({i}/{len(pending)})")

                if not task_href:
                    try:
                        task_href = tab.run_js(f'''
                            var rows = document.querySelectorAll('.punchcard-row');
                            var targetRow = rows[{task_index}];
                            if (targetRow) {{
                                var link = targetRow.querySelector('a.offer-cta');
                                if (link) return link.getAttribute('href') || '';
                            }}
                            return '';
                        ''')
                    except Exception:
                        task_href = ''

                if task_href:
                    if task_href.startswith('/'):
                        full_url = f"{REWARDS_BASE_URL}{task_href}"
                    elif task_href.startswith('http'):
                        full_url = task_href
                    else:
                        full_url = f"{BING_URL}/{task_href}"

                    try:
                        new_tab = self.browser.new_tab(full_url)
                        time.sleep(random.uniform(5, 8))
                        try:
                            new_tab.close()
                        except Exception:
                            pass
                    except Exception:
                        pass
                    time.sleep(random.uniform(1, 2))
                    executed += 1
                else:
                    logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 未找到打卡任务链接")
            except Exception as e:
                logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} {LogTag.ACTIVITY} 子任务失败: {e}")
                if "disconnected" in str(e).lower():
                    logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 页面连接断开，停止剩余子任务")
                    break

        self.stats["punch"]["done"] += executed
    except Exception as e:
        logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} {LogTag.ACTIVITY} 打卡子任务异常: {e}")


def _ppmov_process_browse_activities(self):
    try:
        tasks = self.page.run_js("""
        const tasks = [];

        const exploreSection = document.querySelector('#explore-on-bing');
        if (exploreSection) {
            const exploreCards = exploreSection.querySelectorAll('mee-card');
            exploreCards.forEach(card => {
                const link = card.querySelector('a[href]');
                if (!link) return;
                const href = link.getAttribute('href') || '';
                if (!href || href === '#') return;

                const titleEl = card.querySelector('h3');
                const text = titleEl ? titleEl.innerText.trim() : '';
                const pointsEl = card.querySelector('.pointsString');
                const points = pointsEl ? pointsEl.innerText.trim() : '?';

                const addIcon = card.querySelector('.mee-icon-AddMedium');
                const checkIcon = card.querySelector('.mee-icon-StatusCircleCheckmark');
                const isCompleted = !!checkIcon && !addIcon;

                tasks.push({href, text: text.substring(0, 30), points, isCompleted, section: 'browse'});
            });
        }

        const activitiesSection = document.querySelector('#more-activities');
        if (activitiesSection) {
            const activityCards = activitiesSection.querySelectorAll('mee-card');
            activityCards.forEach(card => {
                const link = card.querySelector('a[href]');
                if (!link) return;
                const href = link.getAttribute('href') || '';
                if (!href || href === '#') return;

                const titleEl = card.querySelector('h3');
                const text = titleEl ? titleEl.innerText.trim() : '';
                const pointsEl = card.querySelector('.pointsString');
                const points = pointsEl ? pointsEl.innerText.trim() : '?';

                const addIcon = card.querySelector('.mee-icon-AddMedium');
                const checkIcon = card.querySelector('.mee-icon-StatusCircleCheckmark');
                const isCompleted = !!checkIcon && !addIcon;

                tasks.push({href, text: text.substring(0, 30), points, isCompleted, section: 'activity'});
            });
        }

        return tasks;
        """) or []

        if not tasks:
            logger.info(f"{LogIndent.ITEM}{LogTag.ACTIVITY} 未发现浏览/活动任务")
            return

        seen = set()
        unique = []
        for task in tasks:
            if task['href'] not in seen:
                seen.add(task['href'])
                unique.append(task)

        pending = [t for t in unique if not t['isCompleted'] and t.get('points', '?') != '?']
        skipped = len([t for t in unique if not t['isCompleted'] and t.get('points', '?') == '?'])
        completed = len([t for t in unique if t['isCompleted']])
        total = len(unique)

        self.stats["activity"]["total"] = total
        self.stats["activity"]["done"] = completed
        logger.info(f"{LogIndent.ITEM}{LogTag.ACTIVITY} 浏览/活动任务: 待处理 {len(pending)}, 已完成 {completed}, 跳过 {skipped}")

        if not pending:
            return

        executed = 0
        for i, task in enumerate(pending, 1):
            href = task['href']
            text = task['text'] or '未知'
            pts = task['points']
            section = '浏览' if task.get('section') == 'browse' else '活动'
            logger.info(f"{LogIndent.ITEM}{LogTag.ACTIVITY} ({i}/{len(pending)}) [{section}] {text} (+{pts}分)")
            try:
                escaped_href = href.replace("'", "").replace('"', '')
                js_code = '''
                    var targetHref = '%s';
                    var cards = document.querySelectorAll('mee-card a[href], a[href]');
                    for (var card of cards) {
                        var cardHref = card.getAttribute('href') || '';
                        if (cardHref === targetHref || cardHref.includes(targetHref) || targetHref.includes(cardHref)) {
                            card.click();
                            return true;
                        }
                    }
                    return false;
                ''' % escaped_href
                try:
                    clicked = self.page.run_js(js_code)
                except Exception:
                    clicked = False

                if clicked:
                    time.sleep(random.uniform(5, 8))
                    try:
                        self._close_extra_tabs(keep_tab=self.page)
                    except Exception:
                        pass
                    time.sleep(random.uniform(1, 2))
                    executed += 1
                else:
                    logger.info(f"{LogIndent.ITEM}       ├── 未找到卡片，直接访问")
                    if href.startswith('http'):
                        full_url = href
                    elif href.startswith('/'):
                        if '/search' in href or '/images' in href or '/videos' in href:
                            full_url = BING_URL.rstrip('/') + href
                        else:
                            full_url = f"{REWARDS_BASE_URL}{href}"
                    else:
                        full_url = f"{BING_URL}{href}"

                    try:
                        new_tab = self.browser.new_tab(full_url)
                        new_tab.wait.load_start()
                        time.sleep(random.uniform(5, 8))
                        new_tab.close()
                    except Exception:
                        pass
                    time.sleep(random.uniform(1, 2))
                    executed += 1
            except Exception as e:
                logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} {LogTag.ACTIVITY} 任务失败: {e}")
                if "disconnected" in str(e).lower():
                    logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 页面连接断开，停止剩余任务")
                    break

        self.stats["activity"]["done"] += executed
    except Exception as e:
        logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} {LogTag.ACTIVITY} 浏览/活动任务异常: {e}")


# 绑定补丁方法，修复因缩进错误导致的方法缺失
PointsPageManagerBase._is_page_alive = _ppm_base_is_page_alive
PointsPageManagerBase._recover_page = _ppm_base_recover_page
PointsPageManagerBase._close_extra_tabs = _ppm_base_close_extra_tabs
PointsPageManagerBase._close_new_tabs = _ppm_base_close_new_tabs
PointsPageManagerBase.claim_dashboard_rewards = _ppm_base_claim_dashboard_rewards
PointsPageManagerOldVersion._process_punch_cards = _ppmov_process_punch_cards
PointsPageManagerOldVersion._process_punch_card_tasks = _ppmov_process_punch_card_tasks
PointsPageManagerOldVersion._process_browse_activities = _ppmov_process_browse_activities
PointsPageManagerNewVersion._process_punch_cards = _ppmnv_process_punch_cards
PointsPageManagerNewVersion._process_punch_card_tasks = _ppmnv_process_punch_card_tasks
PointsPageManagerNewVersion._parse_activity_cards = _ppmnv_parse_activity_cards
PointsPageManagerNewVersion._process_activities = _ppmnv_process_activities

def get_points_page_manager(browser_mgr, is_new_version):
    if is_new_version:
        return PointsPageManagerNewVersion(browser_mgr)
    else:
        return PointsPageManagerOldVersion(browser_mgr)

def process_account(browser_mgr, account, hot_words_mgr):
    idx = account["index"]
    username = account["username"]
    password = account["password"]
    otpauth = account["otpauth"]

    logger.info(f"{'='*50}")
    logger.info(f"{LogIcon.START} {LogTag.ACCOUNT} 处理账号 {idx}: {email_mask(username)}")
    logger.info(f"{'='*50}")

    auth_mgr = AuthManager(browser_mgr)
    token_mgr = TokenManager(browser_mgr)
    points_mgr = PointsManager(browser_mgr)
    search_mgr = SearchManager(browser_mgr, points_mgr, hot_words_mgr)
    
    # 登录
    if not auth_mgr.ensure_all_logged_in(username, password, otpauth, idx):
        logger.error(f"{LogIndent.END}{LogIcon.FAIL} {LogTag.LOGIN} 账号{idx} 登录失败")
        return None, None
    
    # 获取 token
    saved_token = AccountStorage.get_token(username)
    if not saved_token:
        token_result = token_mgr.get_refresh_token(idx)
        if token_result and token_result.get("refresh_token"):
            saved_token = token_result["refresh_token"]
            AccountStorage.save_token(username, saved_token)

    rewards_logged_in = auth_mgr.is_site_logged_in(SiteType.REWARDS)
    result = {}
    if rewards_logged_in:
        result = points_mgr.get_rewards_points(idx) or {}
    else:
        logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} rewards.bing.com 未登录，跳过网页积分页任务")

    # 搜索任务
    if auth_mgr.is_site_logged_in(SiteType.BING):
        search_done = search_mgr.complete_search_tasks(idx, saved_token or "")
        result["search_done"] = search_done
        if saved_token:
            try:
                post_search_mgr = AppTaskManager(saved_token, idx)
                post_search_status = post_search_mgr.get_pc_search_status()
                if post_search_status.get("valid"):
                    result["search"] = {
                        "progress": post_search_status.get("progress", 0),
                        "max": post_search_status.get("max", 0),
                        "remaining": post_search_status.get("remaining", 0),
                        "per_search_points": post_search_status.get("per_search_points", 3),
                        "progress_searches": post_search_status.get("progress_searches", 0),
                        "max_searches": post_search_status.get("max_searches", 0),
                    }
            except Exception as e:
                logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 搜索后刷新 API 状态失败: {e}")
    else:
        logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} bing.com 未登录，跳过搜索任务")
        result["search_done"] = 0
    
    result.setdefault("punch_stats", {"done": 0, "total": 0})
    result.setdefault("activity_stats", {"done": 0, "total": 0})
    result.setdefault("claimed_points", 0)

    if rewards_logged_in:
        # 积分页面任务
        is_new_version = result.get("is_new_version", False)
        points_page_mgr = get_points_page_manager(browser_mgr, is_new_version)
        points_page_mgr.complete_points_tasks(idx)
        result["punch_stats"] = points_page_mgr.stats["punch"]
        result["activity_stats"] = points_page_mgr.stats["activity"]
        
        # 领取积分
        claimed = 0
        try:
            claimed = points_page_mgr.claim_dashboard_rewards(idx)
        except Exception as e:
            logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 领取积分异常: {e}")
        result["claimed_points"] = claimed
        # 获取最终积分
        points_mgr.page = browser_mgr.page
        prev_search = result.get("search", {}).copy()
        final_points = points_mgr.get_rewards_points(idx, silent=True)
        if final_points:
            if final_points.get("points", 0) > 0:
                result.update(final_points)
            else:
                logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 最终积分解析异常，保留之前的积分结果")
                if "search" in final_points and final_points.get("search", {}).get("max", 0) > 0:
                    result["search"] = final_points["search"]
                if "quests" in final_points:
                    result["quests"] = final_points["quests"]
                if "is_new_version" in final_points:
                    result["is_new_version"] = final_points["is_new_version"]

        cur_search = result.get("search", {})
        if cur_search.get("max", 0) == 0 and prev_search.get("max", 0) > 0:
            result["search"] = prev_search

    return result, saved_token


def main():
    import signal
    import atexit
    
    def _signal_handler(signum, frame):
        logger.warning(f"\n{LogIcon.WARN} {LogTag.SYSTEM} 收到终止信号 ({signum})，正在清理浏览器...")
        BrowserManager.cleanup_all()
        sys.exit(1)
    
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
    atexit.register(BrowserManager.cleanup_all)

    if SCHEDULE_RUN and cache_mgr.get_complete_count() > 0:
        logger.info(f"{LogTag.SYSTEM} 今日定时任务已成功执行过，跳过重复触发")
        return

    if sys.platform != "win32":
        try:
            import subprocess
            result = subprocess.run(["pkill", "-f", "chrome"], capture_output=True, timeout=5)
            result2 = subprocess.run(["pkill", "-f", "chromium"], capture_output=True, timeout=5)
            if result.returncode == 0 or result2.returncode == 0:
                logger.info(f"{LogTag.SYSTEM} 已清理残余的 Chrome 进程")
                time.sleep(1)
        except Exception:
            pass
    
    accounts = AccountStorage.get_accounts()
    if not accounts:
        logger.error(f"{LogTag.SYSTEM} 未检测到账号配置!")
        return

    logger.info(f"{LogTag.SYSTEM} 检测到 {len(accounts)} 个账号")
    hot_words_mgr = HotWordsManager()
    browser_results = []
    
    # 浏览器任务
    for account in accounts:
        browser_mgr = BrowserManager(username=account["username"])
        logger.info(f"{LogIcon.START} 启动 Bing Rewards (版本: {VERSION})...")
        try:
            result, token = process_account(browser_mgr, account, hot_words_mgr)
            browser_results.append({
                "index": account["index"],
                "username": account["username"],
                "result": result,
                "token": token
            })
            if account != accounts[-1]:
                time.sleep(random.uniform(5, 10))
        except Exception as e:
            logger.error(f"{LogIcon.FAIL} 账号{account['index']} 执行异常: {e}")
            browser_results.append({
                "index": account["index"],
                "username": account["username"],
                "result": None,
                "token": None
            })
        finally:
            browser_mgr.cleanup()

    logger.info(f"{'='*50}")
    logger.info(f"{LogIcon.MOBILE} {LogTag.READ} 执行 APP 任务")
    logger.info(f"{'='*50}")
    
    for item in browser_results:
        if not item["result"]:
            continue
        
        token = item["token"]
        if not token:
            logger.warning(f"{LogIndent.ITEM}{LogIcon.WARN} 账号{item['index']} 无 token，跳过 APP 任务")
            item["result"]["app_sign_in"] = -1
            item["result"]["read_progress"] = 0
            item["result"]["edge_checkin_points"] = -2
            continue
        
        app_mgr = AppTaskManager(token, item["index"])
        app_result = app_mgr.run_all_tasks()
        
        item["result"]["app_sign_in"] = app_result.get("app_sign_in", -1)
        item["result"]["read_progress"] = app_result.get("read_progress", 0)
        item["result"]["edge_checkin_points"] = app_result.get("edge_checkin_points", -2)
        mobile_summary = app_mgr.get_mobile_summary()
        if mobile_summary.get("valid"):
            item["result"]["points"] = max(
                int(item["result"].get("points", 0) or 0),
                int(mobile_summary.get("points", 0) or 0),
            )
            item["result"]["today_points"] = max(
                int(item["result"].get("today_points", 0) or 0),
                int(mobile_summary.get("today_points", 0) or 0),
            )
        
        if app_mgr.refresh_token != token:
            AccountStorage.save_token(item["username"], app_mgr.refresh_token)

    logger.info(f"{'='*50}")
    logger.info(f"{LogIcon.DATA} {LogTag.POINTS} 任务总结")
    logger.info(f"{'='*50}")
    
    push_lines = []
    any_failed = False
    
    for r in browser_results:
        idx = r["index"]
        if r["result"]:
            res = r["result"]
            pts = res.get("points", "?")
            today = res.get("today_points", 0)
            search = res.get("search", {})
            s_progress = search.get("progress_searches", search.get("progress", "?"))
            s_max = search.get("max_searches", search.get("max", "?"))
            remaining = search.get("remaining", "?")
            token = r.get("token")
            if token:
                try:
                    mobile_mgr = AppTaskManager(token, idx)
                    pc_status = mobile_mgr.get_pc_search_status()
                    if pc_status.get("valid"):
                        s_progress = pc_status.get("progress_searches", pc_status.get("progress", 0))
                        s_max = pc_status.get("max_searches", pc_status.get("max", 0))
                        remaining = pc_status.get("remaining", 0)
                except Exception:
                    pass
            app_sign = res.get("app_sign_in", -1)
            read_pts = res.get("read_progress", 0)
            edge_pts = res.get("edge_checkin_points", -2)
            claimed = res.get("claimed_points", 0)
            punch_stats = res.get("punch_stats", {})
            activity_stats = res.get("activity_stats", {})
            
            app_str = "今日已签到" if app_sign == 0 else (f"+{app_sign}分" if app_sign > 0 else "失败")
            edge_str = "未执行" if edge_pts == -2 else ("今日已完成" if edge_pts == 0 else (f"+{edge_pts}分" if edge_pts > 0 else "失败"))
            claim_str = f"+{claimed}分" if claimed > 0 else "无"
            app_icon = "✅" if app_sign >= 0 else "❌"
            edge_icon = "✅" if edge_pts >= 0 else "❌"
            
            logger.info(f"{LogIcon.SUCCESS} 账号{idx} ({email_mask(r['username'])})")
            logger.info(f"   ├── {LogIcon.DATA} 总积分: {pts}")
            logger.info(f"   ├── {LogIcon.DATA} 今日积分: +{today}")
            logger.info(f"   ├── {LogIcon.GIFT} 积分领取: {claim_str}")
            logger.info(f"   ├── {LogIcon.MOBILE} APP签到: {app_str}")
            logger.info(f"   ├── {LogIcon.MOBILE} Edge打卡: {edge_str}")
            logger.info(f"   ├── {LogIcon.READ} APP阅读: {read_pts}分")
            logger.info(f"   ├── {LogIcon.SEARCH} 搜索进度: {s_progress}/{s_max} (剩余{remaining}次)")
            logger.info(f"   ├── {LogIcon.INFO} 打卡任务: {punch_stats.get('done', 0)}/{punch_stats.get('total', 0)}")
            logger.info(f"   └── {LogIcon.INFO} 活动任务: {activity_stats.get('done', 0)}/{activity_stats.get('total', 0)}")
            
            # 推送消息行
            push_lines.append(
                f"👤{email_mask(r['username'])} | 💰{pts}(+{today})\n"
                f"   🔍{s_progress}/{s_max}  📖{read_pts}/30  {app_icon}签到  {edge_icon}Edge  🎁{claim_str}"
            )
        else:
            logger.error(f"{LogIcon.FAIL} 账号{idx} ({email_mask(r['username'])}): 登录失败")
            push_lines.append(f"👤{email_mask(r['username'])} | ❌登录失败")
            any_failed = True

    if any_failed:
        logger.info(f"{LogTag.SYSTEM} 存在登录失败的账号，跳过推送（等待下次重试）")
    else:
        complete_count = cache_mgr.increment_complete_count()
        logger.info(f"{LogTag.SYSTEM} 今日任务完成次数: {complete_count}")

        if push_lines:
            try:
                title = f"Bing Rewards 任务日报 ({date.today().strftime('%m-%d')})"
                content = "\n" + "-" * 30 + "\n"
                content += "\n".join(push_lines)
                content += "\n" + "-" * 30
                sent = notify_mgr.send(title, content)
                if sent:
                    logger.success(f"{LogIcon.SUCCESS} {LogTag.SYSTEM} 推送通知已发送")
                else:
                    logger.warning(f"{LogIcon.WARN} {LogTag.SYSTEM} 推送通知发送失败")
            except Exception as e:
                logger.warning(f"{LogIcon.WARN} {LogTag.SYSTEM} 推送失败: {e}")


# ==================== v1.0.7 hard patch: ensure methods are bound before main ====================
def _ensure_points_manager_methods_bound():
    PointsPageManagerBase._is_page_alive = _ppm_base_is_page_alive
    PointsPageManagerBase._recover_page = _ppm_base_recover_page
    PointsPageManagerBase._close_extra_tabs = _ppm_base_close_extra_tabs
    PointsPageManagerBase._close_new_tabs = _ppm_base_close_new_tabs
    PointsPageManagerBase.claim_dashboard_rewards = _ppm_base_claim_dashboard_rewards
    PointsPageManagerNewVersion._process_punch_cards = _ppmnv_process_punch_cards
    PointsPageManagerNewVersion._process_punch_card_tasks = _ppmnv_process_punch_card_tasks
    PointsPageManagerNewVersion._parse_activity_cards = _ppmnv_parse_activity_cards
    PointsPageManagerNewVersion._process_activities = _ppmnv_process_activities


def _verify_points_manager_methods():
    missing = []
    for cls, names in [
        (PointsPageManagerBase, ['_is_page_alive', '_recover_page', '_close_extra_tabs', '_close_new_tabs', 'claim_dashboard_rewards']),
        (PointsPageManagerOldVersion, ['_process_punch_cards', '_process_punch_card_tasks', '_process_browse_activities']),
        (PointsPageManagerNewVersion, ['_process_punch_cards', '_process_punch_card_tasks', '_parse_activity_cards', '_process_activities']),
    ]:
        for name in names:
            if not hasattr(cls, name):
                missing.append(f'{cls.__name__}.{name}')
    if missing:
        raise RuntimeError('missing required methods: ' + ', '.join(missing))


_ensure_points_manager_methods_bound()
_verify_points_manager_methods()


if __name__ == "__main__":
    main()
