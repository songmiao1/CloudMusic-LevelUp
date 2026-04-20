# CloudMusic-LevelUp

网易云音乐自动签到与任务领奖项目。

## 当前自动化内容

- ✅ 安卓端/网页端每日签到
- ✅ 播放上报
- ✅ 云贝签到
- ✅ 云贝任务列表拉取
- ✅ 云贝已完成任务自动领奖
- ✅ 黑胶签到
- ✅ 黑胶任务列表拉取
- ✅ 黑胶成长值任务自动领奖（当接口返回可领奖状态时）
- ✅ 音乐人签到
- ✅ 音乐人任务列表拉取
- ✅ 音乐人已完成任务自动领奖
- ✅ GitHub Actions 每日自动执行
- ✅ GitHub Actions 定时巡检与漏触发自动补跑
- ✅ WPS 每日签到、任务、抽奖

## 当前不会自动做的任务

以下任务会被拉取并打印到日志里，但默认不会主动替你完成，因为它们需要额外的用户行为或会对账号内容产生副作用：

- 浏览会员中心
- 红心歌曲
- 关注歌手
- 发布图文笔记
- 浏览黑胶时光机
- 其他需要跳转页面、投稿或抽奖的音乐人任务

## 使用说明

1. Fork 此仓库到你的 GitHub 账户
2. 在 `Settings > Secrets` 中配置：
   - `NETEASE_USER_ID`: 网易云音乐用户 ID
   - `NETEASE_COOKIE`: 网易云音乐 Cookie（至少应包含 `MUSIC_U` 与 `__csrf`）
   - `WPS_TASK_CK`: WPS Cookie，格式为 `备注#cookie`，多账号按行分隔
   - `SMTP_SERVER`: 发信服务器，例如 `smtp.qq.com:465`
   - `SMTP_SSL`: `true` 或 `false`
   - `SMTP_EMAIL`: 发件邮箱
   - `SMTP_PASSWORD`: SMTP 授权码
   - `SMTP_NAME`: 发件人名称
   - `SMTP_TO`: 收件邮箱，不填时默认发给 `SMTP_EMAIL`
3. 启用 GitHub Actions 工作流

## 自动执行时间

仓库目前包含四个定时工作流：

- 网易云：每天 `UTC 23:17`，对应北京时间 `07:17`
- Bing Rewards：每天 `UTC 23:24`，对应北京时间 `07:24`
- WPS：每天 `UTC 23:31`，对应北京时间 `07:31`
- Schedule Watchdog：每天 `UTC 23:43`、`23:53`、`00:08`、`00:18`、`00:28`，对应北京时间 `07:43`、`07:53`、`08:08`、`08:18`、`08:28`

`Schedule Watchdog` 会检查当天三个主任务是否已经生成 workflow run；如果没有，就自动触发一次 `workflow_dispatch` 作为补跑。

## 技术说明

- `signin.py` 负责基础签到和播放上报
- `tasks.js` 基于 [`@neteasecloudmusicapienhanced/api`](https://www.npmjs.com/package/@neteasecloudmusicapienhanced/api) 拉取扩展任务并领取可领奖励
- `wps-github-action/scripts/wps.py` 负责 WPS 签到、任务、抽奖与成功邮件通知

## 声明

本项目仅供学习交流使用，请勿用于商业用途。
使用本项目产生的任何后果由使用者自行承担。
