# MOE Toolkit - Beta 用户接入说明

本文档面向收到邀请码或 API Key 的 Beta 用户。

## 1. 前提

- 当前仅支持 macOS
- 本机需要 `python3`
- 你需要从运营方拿到个人专属 API Key
- 云端地址当前固定为 `${MOE_PUBLIC_BASE_URL}`

公开入口：

- 安装说明页：`${MOE_PUBLIC_BASE_URL}/beta`
- 一键安装脚本：`${MOE_PUBLIC_BASE_URL}/install.sh`
- 发布包下载：`${MOE_PUBLIC_BASE_URL}/releases/moe-connector-macos.tar.gz`

## 2. 推荐安装命令

将下面命令中的 `<YOUR_KEY>` 替换成你的个人 API Key：

```bash
curl -fsSL ${MOE_PUBLIC_BASE_URL}/install.sh | \
  bash -s -- \
  --server-url ${MOE_PUBLIC_BASE_URL} \
  --api-key <YOUR_KEY> \
  --host codex-cli
```

如果你使用 Claude Code：

```bash
curl -fsSL ${MOE_PUBLIC_BASE_URL}/install.sh | \
  bash -s -- \
  --server-url ${MOE_PUBLIC_BASE_URL} \
  --api-key <YOUR_KEY> \
  --host claude-code
```

如果你使用 OpenClaw：

```bash
curl -fsSL ${MOE_PUBLIC_BASE_URL}/install.sh | \
  bash -s -- \
  --server-url ${MOE_PUBLIC_BASE_URL} \
  --api-key <YOUR_KEY> \
  --host openclaw
```

说明：

- 安装脚本会自动扫描本地 OpenClaw agent workspace，并要求你确认目标 workspace
- 如果自动发现失败，可以补：

```bash
curl -fsSL ${MOE_PUBLIC_BASE_URL}/install.sh | \
  bash -s -- \
  --server-url ${MOE_PUBLIC_BASE_URL} \
  --api-key <YOUR_KEY> \
  --host openclaw \
  --openclaw-workspace ~/.openclaw/workspace-your-agent
```

## 3. 安装后会发生什么

- 创建 `~/.moe-connector/`
- 写入 `~/.moe-connector/config.toml`
- 创建 `~/MOE Outputs`
- 安装本地命令 `~/.local/bin/moe-connector`
- 把 MOE connector 注册进 `Codex CLI`、`Claude Code`，或者一个 OpenClaw agent workspace
- 自动执行一次 `doctor` 检查

如果你使用 OpenClaw，还会：

- 在选中的 workspace 根目录更新 `TOOLS.md`
- 创建 `<workspace>/.moe-toolkit/bin/moe-openclaw`
- 让该 agent 后续任务结果下载到 `<workspace>/MOE Outputs`

## 4. 手动检查

如果你要手动复查：

```bash
moe-connector doctor --host codex-cli
```

如果 `~/.local/bin` 不在 `PATH` 中，也可以直接运行：

```bash
~/.local/bin/moe-connector doctor --host codex-cli
```

OpenClaw 手动复查：

```bash
~/.local/bin/moe-connector doctor --host openclaw --workspace-path ~/.openclaw/workspace-your-agent
```

预期结果：

- 云端健康检查通过
- `Authenticated: True`
- `Host registration [...] : True`

## 5. 首次使用

安装成功后，重启宿主客户端，然后尝试一个简单请求：

- `分析这个 CSV 并生成趋势图`

生成的文件默认会下载到：

```text
~/MOE Outputs
```

如果你使用 OpenClaw，则默认下载到：

```text
<你的 OpenClaw agent workspace>/MOE Outputs
```

## 6. 常见问题

### 6.1 提示找不到 `python3`

先安装 Python 3.11+，然后重新执行安装命令。

### 6.2 `doctor` 显示认证失败

- 检查 API Key 是否完整
- 确认没有多复制空格或换行
- 向运营方确认该 Key 是否已被吊销

### 6.3 宿主中看不到工具

- 先重启 Codex CLI、Claude Code，或新开一个 OpenClaw agent 会话
- 再执行一次：

```bash
moe-connector doctor --host codex-cli
```

如果你使用 OpenClaw：

```bash
moe-connector doctor --host openclaw --workspace-path ~/.openclaw/workspace-your-agent
```

### 6.4 OpenClaw 自动发现不到 workspace

- 先确认你已经让目标 agent 至少启动过一次
- 确认它的 workspace 根目录里至少已有 `AGENTS.md`、`SOUL.md`、`USER.md`、`TOOLS.md` 中的一个
- 然后补 `--openclaw-workspace <PATH>` 重新安装

### 6.5 需要卸载

```bash
~/.local/bin/moe-connector uninstall --host codex-cli
```

OpenClaw 卸载：

```bash
~/.local/bin/moe-connector uninstall --host openclaw --workspace-path ~/.openclaw/workspace-your-agent
```

如果你是通过发布包安装的，也可以直接运行发布包中的 `uninstall.sh` 做完整清理。
