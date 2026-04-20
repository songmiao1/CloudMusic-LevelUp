# Bing GitHub Action

这个目录下的实现是给 GitHub 官方 `ubuntu-latest` runner 用的，不依赖本地青龙目录。

必需 Secrets：

- `BING_ACCOUNTS_JSON` 或 `BING_ACCOUNTS_JSON_B64`
  内容是 `bing_accounts.json` 的完整 JSON。

可选 Secrets：

- `BING_COOKIE_SNAPSHOT` 或 `BING_COOKIE_SNAPSHOT_B64`
  首个账号的 `browser_cookies.txt` 内容，用于首次恢复登录态。
- `BING_APP_REFRESH_TOKEN` 或 `BING_APP_REFRESH_TOKEN_B64`
  首个账号的 `app_token.txt` 内容。提供后，云端可直接执行 APP/移动端相关接口，不必依赖网页重新换 token。
- `BING_RUNTIME_SEED_TGZ_B64`
  `.tar.gz` 压缩后的运行时种子目录，解压后应包含 `bing_accounts.json`、`bing_cache.json`、`user_data_*` 等文件。

邮件通知 Secrets：

- `SMTP_SERVER`
- `SMTP_PORT`
- `SMTP_SSL`
- `SMTP_EMAIL`
- `SMTP_PASSWORD`
- `SMTP_NAME`
- `SMTP_TO`

推荐：

1. 第一次先提供 `BING_ACCOUNTS_JSON` 和 `BING_COOKIE_SNAPSHOT`。
2. 跑通后依赖 Actions Cache 持久化 `runtime/`，后续不再每次重新登录。
3. 如果要提高首次成功率，直接把本地 `.bing-runtime` 打包后作为 `BING_RUNTIME_SEED_TGZ_B64` 上传到 Secrets。
