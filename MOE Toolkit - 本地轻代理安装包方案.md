# MOE Toolkit 本地轻代理安装包方案

文档版本：v1.0  
更新时间：2026-03-08

## 1. 目标

本文档定义首版用户侧交付物：`macOS Shell 一键安装器 + moe-connector 本地轻代理`。

首版目标不是让用户本地执行工具链，而是让用户：

- 一条命令完成安装
- 在 Claude Code / Codex CLI 中使用 MOE
- 按需选择本地文件上传到云端处理
- 自动把结果下载回本地

## 2. 安装入口

Beta 安装命令固定为：

```bash
curl -fsSL ${MOE_PUBLIC_BASE_URL}/install.sh | bash
```

安装完成后，用户使用：

```bash
moe-connector configure --server-url ${MOE_PUBLIC_BASE_URL} --api-key <YOUR_KEY>
moe-connector doctor
```

## 3. 本地交付物

安装后本地应具备：

- `moe-connector` 命令
- `~/.moe-connector/config.toml`
- `~/.moe-connector/logs/`
- `~/MOE Outputs/`

## 4. CLI 命令定义

### 4.1 `install`

```bash
moe-connector install --host claude-code
moe-connector install --host codex-cli
```

职责：

- 将 connector 注册到指定宿主
- 校验本地配置是否存在
- 给出下一步使用提示

### 4.2 `configure`

```bash
moe-connector configure \
  --server-url ${MOE_PUBLIC_BASE_URL} \
  --api-key sk_beta_xxx
```

职责：

- 保存云端地址
- 保存 API Key
- 设置默认输出目录

### 4.3 `doctor`

```bash
moe-connector doctor
```

职责：

- 检查配置文件
- 检查输出目录权限
- 调用 `/v1/service/health`
- 验证 API Key 是否可用

### 4.4 `uninstall`

```bash
moe-connector uninstall
```

职责：

- 删除本地 connector 配置
- 移除宿主接入配置
- 保留或删除输出目录由用户确认

## 5. 宿主接入职责

首版优先支持：

- Claude Code
- Codex CLI

安装器职责是：

- 自动检测用户已安装的宿主
- 写入对应的 MCP 或命令代理配置
- 不要求用户手工编辑配置文件

如果自动接入失败，安装器必须输出：

- 宿主配置文件位置
- 建议写入内容
- 重试命令

## 6. 文件上传行为

### 6.1 用户交互原则

- connector 只能上传用户明确指定的文件或目录
- 目录先打包再上传
- 不做后台自动同步

### 6.2 默认限制

- 单文件最大 100 MB
- 最多 5 个附件
- 仅支持 CSV、TSV、XLSX、ZIP

### 6.3 产物下载

- 所有产物下载到 `~/MOE Outputs/`
- 文件名追加 `run_id` 避免覆盖
- 下载完成后在宿主中返回摘要和本地路径

## 7. 本地配置文件

`~/.moe-connector/config.toml` 固定包含：

```toml
server_url = "${MOE_PUBLIC_BASE_URL}"
api_key = "sk_beta_xxx"
host_client = "codex-cli"
output_dir = "/Users/yourname/MOE Outputs"
request_timeout_seconds = 60
max_upload_size_mb = 100
```

要求：

- 文件权限必须为 `0600`
- 禁止把上传历史长期保存到本地

## 8. 错误处理

安装包必须对以下情况提供明确报错：

- 无法连接云端 API
- API Key 无效
- 输出目录不可写
- 用户选择了超大文件
- 上传超时
- 产物下载失败

错误信息必须包含：

- 原因
- 用户可执行修复动作
- 重试命令

## 9. 首版体验红线

- 不让用户手工部署云服务
- 不让用户本地安装工具镜像
- 不让用户自己维护 PostgreSQL 或 Redis
- 不默认读取或上传整个项目目录
- 不把 API Key 以宽权限文件保存
