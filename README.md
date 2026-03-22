# CloudMusic-LevelUp

网易云音乐自动签到项目 - 2026年可用版本

## 功能特性

- ✅ 每日自动签到
- ✅ 音乐合伙人测评
- ✅ 云贝签到
- ✅ VIP每日签到
- ✅ 歌曲播放计数增加
- ✅ GitHub Actions自动化执行

## 使用说明

1. Fork此仓库到您的GitHub账户
2. 在Settings > Secrets中配置：
   - `NETEASE_USER_ID`: 您的网易云音乐用户ID
   - `NETEASE_COOKIE`: 您的网易云音乐Cookie（包含MUSIC_U和__csrf）
3. 启用GitHub Actions工作流

## 自动执行

工作流配置为每天UTC时间08:00自动执行（北京时间16:00）

## 声明

本项目仅供学习交流使用，请勿用于商业用途。
使用本项目产生的任何后果由使用者自行承担。
