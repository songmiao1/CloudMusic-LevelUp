#!/usr/bin/env python3
"""网易云音乐自动签到 - 使用真实API"""
import os
import sys
import json
import time
import random
import hashlib
import logging
from urllib.parse import urlencode

try:
 import requests
except ImportError:
 print("请安装: pip install requests")
 sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)

class NetEaseSign:
 def __init__(self, cookie):
 self.cookie = cookie
 self.session = requests.Session()
 self.session.headers.update({
 "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
 "Accept": "*/*",
 "Accept-Language": "zh-CN,zh;q=0.9",
 "Accept-Encoding": "gzip, deflate, br",
 "Connection": "keep-alive",
 })
