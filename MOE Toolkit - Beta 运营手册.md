# MOE Toolkit - Beta 运营手册

本文档面向 Beta 阶段的运营者和维护者，目标是把 API Key 发放、发布包生成、云端同步、用户接入说明统一下来。

## 1. 当前 Beta 入口

- 云端地址：`${MOE_PUBLIC_BASE_URL}`
- 安装说明页：`${MOE_PUBLIC_BASE_URL}/beta`
- 运营后台：`${MOE_PUBLIC_BASE_URL}/admin/login`
- 安装脚本：`${MOE_PUBLIC_BASE_URL}/install.sh`
- 发布包：`${MOE_PUBLIC_BASE_URL}/releases/moe-connector-macos.tar.gz`

## 2. API Key 管理

### 2.1 本地存储位置

默认使用：

```text
~/.moe-toolkit-beta/api_keys.json
```

也可以通过 `--store-path` 指向项目内的自定义文件。

### 2.2 发放新 Key

```bash
moe-beta-admin issue \
  --owner-name "Alice" \
  --contact "alice@example.com" \
  --note "design partner"
```

输出内容包括：

- `key_id`
- `api_key`
- 一条可直接发送给用户的安装命令

### 2.3 查看当前 Key

```bash
moe-beta-admin list --status active
moe-beta-admin list --status all
```

### 2.4 吊销 Key

```bash
moe-beta-admin revoke --key-id <KEY_ID>
```

### 2.5 批量发放 Key

准备一个 CSV，至少包含 `owner_name` 列。推荐列：

```csv
owner_name,contact,note,host
Alice,alice@example.com,design partner,codex-cli
Bob,bob@example.com,founding user,claude-code
Carol,carol@example.com,openclaw pilot,openclaw
```

然后执行：

```bash
moe-beta-admin bulk-issue \
  --input-csv ./beta-users.csv \
  --output-dir ./beta-batch-2026-03-09
```

输出目录会生成：

- `issued_keys.csv`：本批次发出的 key、宿主类型、安装命令
- `email_manifest.csv`：邮件主题、联系人、模板路径清单
- `emails/*.txt`：可直接复制发送给用户的单独邮件模板

### 2.6 导出已有用户的邮件模板

如果 key 已经存在，只想重新导出邮件模板：

```bash
moe-beta-admin export-emails \
  --output-dir ./beta-email-export \
  --status active
```

如需只导出某几个用户：

```bash
moe-beta-admin export-emails \
  --output-dir ./beta-email-export \
  --key-id <KEY_ID_1> \
  --key-id <KEY_ID_2>
```

## 3. 云端 Key 生效方式

现在有两种运营路径：

- 本地 CLI 路径：本地发 key，然后通过部署脚本把 active keys 同步到云端
- 云端后台路径：直接在 `${MOE_PUBLIC_BASE_URL}/admin/login` 发 key / 吊销 key，变更会立即写入云端持久化 key 文件并即时生效

### 3.1 本地 CLI 同步到云端

如果你仍然使用本地 `moe-beta-admin` 发 key，需要执行一次部署同步：

```bash
cd /Users/weisen/Documents/small-project/MOE_toolkit
MOE_API_KEYS_RAW="$(moe-beta-admin render-env)" bash scripts/deploy-cloud.sh
```

说明：

- `render-env` 只会输出当前状态为 `active` 的 key
- `deploy-cloud.sh` 会重新构建发布包、同步 release archive 到服务器、重启 `moe-api/moe-worker/cleanup-job`

### 3.2 启用最小运营后台

后台依赖以下环境变量：

```bash
export MOE_ADMIN_USERNAME='<admin-username>'
export MOE_ADMIN_PASSWORD='<strong-password>'
export MOE_ADMIN_SESSION_SECRET='<long-random-secret>'
```

然后执行：

```bash
cd /Users/weisen/Documents/small-project/MOE_toolkit
MOE_API_KEYS_RAW="$(moe-beta-admin render-env)" bash scripts/deploy-cloud.sh
```

启用后可在后台完成：

- 查看当前 beta 用户
- 发放新 key
- 吊销已有 key
- 下载单个用户邮件模板
- 下载 active key 清单 CSV

## 4. 构建并分发安装包

### 4.1 本地生成发布包

```bash
bash scripts/build-connector-release.sh
```

产物：

- `dist/moe-connector-macos.tar.gz`
- `dist/moe-connector-release/`

### 4.2 云端同步

这一步已经包含在：

```bash
bash scripts/deploy-cloud.sh
```

部署脚本会把 release archive 同步到：

```text
/opt/moe-toolkit/data/releases/moe-connector-macos.tar.gz
```

应用会从这里对外暴露下载地址。

## 5. 用户接入标准流程

### 5.1 运营侧步骤

1. 任选一种方式发 key：
   `moe-beta-admin issue/bulk-issue`
   或云端 `/admin/login`
2. 如果走本地 CLI 路径，执行 `moe-beta-admin render-env`
3. 如果走本地 CLI 路径，运行 `scripts/deploy-cloud.sh`
4. 验证 `${MOE_PUBLIC_BASE_URL}/beta`
5. 使用 `emails/*.txt`、`email_manifest.csv` 或后台下载模板发给用户

### 5.2 用户侧命令模板

```bash
curl -fsSL ${MOE_PUBLIC_BASE_URL}/install.sh | \
  bash -s -- \
  --server-url ${MOE_PUBLIC_BASE_URL} \
  --api-key <USER_KEY> \
  --host codex-cli
```

OpenClaw 用户模板：

```bash
curl -fsSL ${MOE_PUBLIC_BASE_URL}/install.sh | \
  bash -s -- \
  --server-url ${MOE_PUBLIC_BASE_URL} \
  --api-key <USER_KEY> \
  --host openclaw
```

## 6. 建议发送给用户的模板

```text
MOE Toolkit Beta 已为你开通。

云端地址：
${MOE_PUBLIC_BASE_URL}

你的 API Key：
<USER_KEY>

安装说明页：
${MOE_PUBLIC_BASE_URL}/beta

推荐安装命令：
curl -fsSL ${MOE_PUBLIC_BASE_URL}/install.sh | bash -s -- --server-url ${MOE_PUBLIC_BASE_URL} --api-key <USER_KEY> --host codex-cli
```

说明：

- 如果已经用 `bulk-issue` 或 `export-emails`，这段模板会自动写入 `emails/*.txt`
- `email_manifest.csv` 适合导入表格后统一跟踪发送状态
- OpenClaw 用户的邮件模板会自动带上 `--host openclaw`，并提示他们确认目标 agent workspace

## 7. 发布前检查

每次发新版或变更 key 后，至少检查：

- `curl ${MOE_PUBLIC_BASE_URL}/v1/service/health`
- `curl ${MOE_PUBLIC_BASE_URL}/beta`
- `curl -I ${MOE_PUBLIC_BASE_URL}/admin/login`
- `curl ${MOE_PUBLIC_BASE_URL}/install.sh`
- `curl ${MOE_PUBLIC_BASE_URL}/releases/moe-connector-macos.tar.gz -I`
- `python scripts/smoke-cloud.py --server-url ${MOE_PUBLIC_BASE_URL} --api-key <ADMIN_TEST_KEY>`

## 8. 当前限制

- 仍是 `HTTP + API Key` 的 Beta 方案，不适合高敏感数据
- 当前公开安装包只针对 macOS
- 如果沿用本地 CLI 发 key，新增或吊销 key 后仍需要重新部署
- 运营后台仍是单账号最小实现，没有复杂权限模型
- OpenClaw 用户需要先让目标 agent 启动一次，完成 workspace bootstrap 后再安装
