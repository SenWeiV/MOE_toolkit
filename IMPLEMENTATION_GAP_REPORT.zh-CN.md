# MOE Toolkit 实现差距对照表

更新时间：2026-03-13

适用范围：

- 本地代码仓库 `/Users/weisen/Documents/opencalw/MOE_toolkit`
- 当前线上实例 `http://120.48.83.123:8080`

目标：

- 对照“设计初衷”和“当前运行时能力”
- 区分 `已实现`、`部分实现`、`仅设计未落地`
- 为下一轮功能开发给出优先级

## 一、总体结论

当前版本已经实现了一个可用的最小闭环：

- 上传文件
- 创建任务
- 返回 `route_plan`
- 轮询运行状态
- 下载产物
- 支持本地 MCP connector 接入宿主

但它仍然是一个“固定 CSV/图表工作流”的首版，而不是“动态云端工具库 + 技能发现 + 精准工具匹配”的通用平台。

## 二、设计目标 vs 当前实现

| 能力 | 设计目标 | 当前实现 | 结论 | 证据 |
| --- | --- | --- | --- | --- |
| 任务路由规划 | 根据任务生成 `route_plan` | 已实现 | 已实现 | `RoutePlan` 在云端创建任务时返回；见 `cloud/services.py` |
| 能力识别 | 识别任务需要的能力标签 | 已实现，但规则固定 | 部分实现 | 当前只会产出 `csv_parse`、`data_analysis`，以及在命中图表关键词时追加 `visualization` |
| 多工具组合 | 根据任务组合多个工具 | 已实现，但组合固定 | 部分实现 | 当前最多固定组合 `moe-tool-pandas + moe-tool-matplotlib` |
| 执行解释 | 返回为什么选择这些工具 | 已实现，但解释固定 | 部分实现 | `explanation` 固定为 `Curated CSV analysis route selected.` |
| 云端工具库检索 | 动态搜索 curated tools | 未实现 | 未实现 | 设计稿列出 `/v1/registry/...`，但当前代码和线上实例都没有 |
| Skill / Tool 发现机制 | 返回完整工具/skill 列表或发现接口 | 未实现 | 未实现 | 当前没有 registry / discovery API；只有 OpenClaw workspace 发现，不是云端技能发现 |
| MCP 支持 | 让宿主通过 MCP 使用 MOE | 已实现于本地 connector | 已实现，但不是云端能力 | 本地 `FastMCP` server 已注册 5 个工具 |
| 任务-工具精准匹配 | 非 CSV 任务选择非 CSV 工具 | 未实现 | 未实现 | 任务路由逻辑硬编码，`web_search` 仍会落到 `moe-tool-pandas` |
| Telemetry 上报 | 上报 connector 事件 | 未实现 | 未实现 | 设计稿列出 `/v1/telemetry/connector-events`，当前运行时无此路由 |
| Excel 导出链路 | `openpyxl` / `spreadsheet_generate` | 未实现 | 未实现 | 设计稿有 `moe-tool-openpyxl`，仓库实际工具目录没有 |

## 三、已确认实现的能力

### 1. 任务执行闭环

当前云端公开 REST API 已实现：

- `GET /v1/service/health`
- `POST /v1/files/upload`
- `POST /v1/tasks/execute`
- `GET /v1/runs/{run_id}`
- `GET /v1/runs/{run_id}/artifacts`
- `GET /v1/artifacts/{artifact_id}/download`

这部分实现位于：

- `src/moe_toolkit/cloud/app.py`

### 2. 最小路由能力

当前路由逻辑是固定规则，不是动态 registry：

- 默认：
  - `capabilities = ["csv_parse", "data_analysis"]`
  - `selected_images = ["moe-tool-pandas"]`
- 任务文本里包含 `图/chart/plot/trend/趋势` 时：
  - 追加 `visualization`
  - 追加 `moe-tool-matplotlib`

实现位置：

- `src/moe_toolkit/cloud/services.py`

### 3. 多工具顺序执行

当 `selected_images` 有多个镜像时，worker 会按顺序逐个执行。

实现位置：

- `src/moe_toolkit/cloud/executors.py`

注意：

- 这说明“多工具组合能力”存在
- 但“如何选出这些工具”仍是硬编码，而不是动态搜索工具库

### 4. 本地 MCP connector

本地 connector 已实现 `FastMCP` server，并暴露以下 tools：

- `service.health`
- `service.configure`
- `task.execute`
- `run.get_status`
- `run.get_artifacts`

实现位置：

- `src/moe_toolkit/connector/mcp_server.py`

测试覆盖：

- `tests/test_connector_mcp_server.py`

结论：

- 如果问题是“MOE 有没有 MCP 支持”，答案是有
- 如果问题是“云端是不是通过 MCP / registry 动态暴露工具库”，答案是不是

## 四、已确认未实现的能力

### 1. 云端工具库检索

设计稿列出的接口：

- `GET /v1/registry/tools/search`
- `GET /v1/registry/tools/{tool_id}`
- `GET /v1/registry/manifests/{tool_id}/{version}`

当前状态：

- `src/moe_toolkit/cloud/app.py` 中没有这些路由
- 当前线上实例请求 `/v1/registry/tools/search` 返回 `404`

结论：

- 这不是“未验证”
- 是当前运行时确实没有实现

### 2. Skill / Tool 发现机制

当前仓库里存在的“发现”只有：

- 本地 OpenClaw workspace 自动发现

实现位置：

- `src/moe_toolkit/connector/openclaw.py`

这不是设计中想要的：

- 云端 tool registry
- skill discovery
- manifest 查询

结论：

- 当前没有云端 skill/tool 发现能力

### 3. Telemetry 接口

设计稿列出：

- `POST /v1/telemetry/connector-events`

当前状态：

- 当前代码没有这个路由
- 当前线上实例访问该路径返回 `404`

结论：

- 仅存在于设计稿，尚未落地

### 4. Excel / OpenPyXL 导出能力

设计稿中出现：

- `moe-tool-openpyxl`
- `spreadsheet_generate`

当前仓库工具目录实际只有：

- `tools/curated/pandas`
- `tools/curated/matplotlib`

结论：

- `openpyxl` 工具链尚未加入当前实现

## 五、已确认“说法不准确”的地方

### 1. “MCP 工具支持未实现”

这句话不准确。

更准确的表述应为：

- `本地 MCP connector 已实现`
- `但云端工具注册表 / MCP 动态工具发现未实现`

### 2. “多工具组合已实现”

这句话需要收窄描述。

更准确的表述应为：

- `固定的多工具顺序执行已实现`
- `基于云端工具库的动态多工具编排未实现`

### 3. “能力识别已实现”

这句话也需要收窄描述。

更准确的表述应为：

- `固定规则的能力标签识别已实现`
- `语义级能力识别和精准匹配未实现`

## 六、建议的新功能开发优先级

### P0：先把“动态性”补出来

建议优先实现：

1. `GET /v1/registry/tools/search`
2. `GET /v1/registry/tools/{tool_id}`
3. `GET /v1/registry/manifests/{tool_id}/{version}`

原因：

- 这是“云端工具库”成立的最低前提
- 没有 registry，后面的 skill discovery、动态匹配都无从谈起

### P1：把路由器从硬编码改为 registry 驱动

建议改造：

- 从当前 `_build_route_plan()` 的固定 if/else
- 改成：
  - 任务 -> 能力标签
  - 能力标签 -> 候选工具
  - 候选工具 -> 排序/过滤
  - 输出 `route_plan`

当前硬编码逻辑位置：

- `src/moe_toolkit/cloud/services.py`

### P2：补充更多 curated tools

建议至少补：

- `openpyxl`：Excel 生成/导出
- `web_search`：联网检索
- `http_fetch`：抓取网页内容
- `markdown_report`：结果汇总导出

否则：

- 非 CSV 类任务仍然会被错误路由到 `pandas`

### P3：补 skill / capability 元数据

建议为每个工具引入标准元数据：

- `tool_id`
- `version`
- `capabilities`
- `input_types`
- `output_types`
- `cost`
- `network_required`
- `manifest_url`

这样后续才能做：

- 动态工具发现
- 任务-工具精准匹配
- 工具版本管理

### P4：补 Telemetry 与调试接口

建议补：

- `POST /v1/telemetry/connector-events`
- route_plan 命中日志
- tool selection 决策日志
- failed match / fallback 原因

否则：

- 当用户问“为什么选错工具”时，当前系统缺少可观测性

## 七、建议你在对外说明中改写的表述

### 当前版本可对外说

- 已支持 CSV/TSV 上传、分析、图表生成
- 已支持最小路由计划返回
- 已支持本地 MCP connector 接入宿主
- 已支持 OpenClaw / Codex / Claude Code 安装接入

### 当前版本不要对外说

- 已支持动态云端工具库检索
- 已支持完整 skill discovery
- 已支持语义级任务-工具精准匹配
- 已支持通用多工具智能编排

### 更准确的产品定位

当前版本应定位为：

> 一个面向 CSV 分析与图表生成的云端远程执行原型，已具备最小路由计划与本地 MCP 接入能力，但尚未完成动态工具库、技能发现和精准任务匹配。

## 八、最短开发路线建议

如果目标是尽快把“设计初衷”拉近到可演示状态，建议路线：

1. 补 registry API
2. 给现有 pandas / matplotlib 加 manifest 与 capability 元数据
3. 把 `_build_route_plan()` 改成读取 registry
4. 新增 `web_search` 工具并验证非 CSV 任务不再落到 pandas
5. 新增 `openpyxl` 工具，打通 `spreadsheet_generate`
6. 最后补 telemetry

这样改完后，产品就会从“固定工作流”进入“可扩展工具平台”的下一阶段。
