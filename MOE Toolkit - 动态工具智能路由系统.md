MOE Toolkit - 动态工具智能路由系统
产品定位
一句话定义：LLM 的免疫系统 —— 遇到未知任务，自动识别需求、检索能力、安装执行、积累经验。
核心价值：让任何 MCP 宿主（Claude/Cursor/ChatGPT/Codex 等）获得动态进化能力，无需手动管理工具。

---

架构概览
用户层（任意 MCP 宿主）

- Claude Desktop
- Cursor IDE
- ChatGPT
- Codex CLI
- ...
  MCP 协议适配层
- 标准 MCP Server 实现（FastMCP）
- tools/list
- tools/call
- resources/read
  MOE 核心引擎
- 意图识别器 (Embedding + LLM)
- 工具路由器 (MOE 调度)
- 执行协调器 (沙箱执行)
  工具生命周期管理层
- 本地缓存层 (已安装)
- 仓库索引层 (元数据)
- 网络发现层 (GitHub)
- 动态安装引擎（Docker/Podman + Nix）
  工具市场（GitHub 驱动）
- 自动爬取
- 元数据提取
- 质量评分
- 索引入库

---

技术栈（2026 主流）
层级
技术选型
理由
MCP Server
FastMCP (Python)
官方 SDK，生态成熟
意图识别
OpenAI Embedding + Qwen/bailian 路由
语义理解 + 成本控制
MOE 路由
自研 + 参考 Mixtral 路由逻辑
核心壁垒
沙箱执行
gVisor + Podman
比 Docker 更隔离，rootless
环境管理
Nix / Pixi
可复现、无版本冲突
数据存储
SQLite (本地) + PostgreSQL (云端)
轻量 + 可扩展
向量检索
ChromaDB / Milvus Lite
本地优先
爬虫系统
Crawlee (Node) + GitHub API
专业爬虫框架
配置管理
Pydantic Settings
类型安全

---

核心模块设计

1. 意图识别器 (Intent Recognizer)
   职责：将用户自然语言转换为结构化能力需求
   输入：用户消息 + 上下文
   输出：能力需求列表（带置信度）
   示例：
   用户："分析一下这个销售数据，看看趋势"
   输出：

- csv_parse (confidence: 0.95)
- data_analysis (confidence: 0.92)
- visualization (confidence: 0.88)
- trend_forecast (confidence: 0.75)
  实现要点：
- Embedding 语义匹配（本地模型，无网络依赖）
- LLM 精排（复杂意图拆解）
- 上下文记忆（多轮对话保持连贯）

---

2. 工具路由器 (Tool Router)
   职责：根据能力需求，决策工具组合与执行顺序
   核心算法：MOE (Mixture of Experts) 动态路由
   流程：
   能力需求 → 检索候选工具 → 评分排序 → 组合规划 → 执行图生成
   示例：
   需求：[csv_parse, data_analysis, visualization]
   候选工具：

- pandas-toolkit (score: 0.94)
- polars-toolkit (score: 0.89)
- matplotlib-viz (score: 0.91)
- seaborn-viz (score: 0.87)
  路由决策：

1. csv_parse → pandas-toolkit（高兼容）
2. data_analysis → pandas-toolkit（内置）
3. visualization → matplotlib-viz（标准）
   执行图：
   [csv_parse] → [data_analysis] → [visualization]
   路由策略：

- 单工具足够 → 直接调用
- 多工具组合 → 生成执行 DAG
- 工具缺失 → 触发安装流程

---

3. 工具生命周期管理
   三层发现机制
   层级
   延迟
   来源
   更新频率
   L1 本地缓存
   <10ms
   已安装工具
   实时
   L2 仓库索引
   <100ms
   本地 SQLite
   每日同步
   L3 网络发现
   1-5s
   GitHub API
   按需
   动态安装流程
1. 发现工具缺失
1. 检索仓库索引（关键词 + 语义）
1. 质量评估（评分 > 阈值？）
1. 用户确认（信任等级决定）
1. 下载 + 构建环境（Nix/Pixi）
1. 沙箱测试（自动化验证）
1. 注册到本地缓存
1. 执行用户任务

---

4. 沙箱执行层
   安全模型：零信任 + 最小权限
   gVisor 沙箱容器特性：

- 无 root 权限
- 网络白名单（默认隔离）
- 文件系统只读（除 /tmp/output）
- 资源限制（CPU/内存/时间）
- 系统调用过滤（seccomp）
  执行模式：
- 冷启动：从镜像创建（5-10s）
- 温启动：预创建池（<1s）
- 热启动：常驻进程（<100ms）

---

5. 工具市场爬虫
   目标：自动从 GitHub 发现并索引 MCP/Skills 工具
   爬取策略：
1. 种子列表（awesome-mcp-servers 等）
1. 关联发现（依赖图、作者其他项目）
1. 趋势监控（GitHub Trending、Hacker News）
   元数据提取字段：

- tool_id: github-username-repo-name
- name: 人类可读名称
- description: 功能描述
- capabilities: 能力标签列表
- keywords: 关键词
- install: 安装配置
- runtime: 运行环境
- permissions: 权限声明
- trust: 信任指标（stars/forks/author等）

---

数据模型
工具元数据表

- id (主键)
- name (名称)
- description (描述)
- capabilities (能力列表，JSON)
- keywords (关键词，JSON)
- install_config (安装配置，JSON)
- runtime_config (运行配置，JSON)
- permission_decl (权限声明，JSON)
- author (作者)
- author_trust_score (作者信任分)
- stars (GitHub stars)
- forks (GitHub forks)
- last_commit (最后提交日期)
- license (许可证)
- install_count (安装次数)
- success_rate (成功率)
- avg_execution_time (平均执行时间)
- user_rating (用户评分)
- status (状态: pending/approved/rejected/deprecated)
- indexed_at (索引时间)
- updated_at (更新时间)
  工具执行记录表
- id (主键)
- tool_id (工具ID)
- session_id (会话ID)
- intent (意图)
- input_hash (输入哈希)
- output_hash (输出哈希)
- status (状态: success/failed/timeout)
- duration_ms (执行时长)
- error_message (错误信息)
- created_at (创建时间)
  会话表
- id (主键)
- host_client (宿主客户端)
- created_at (创建时间)
- last_active (最后活跃)
- context_json (上下文，JSON)

---

场景设计：文件处理
用户旅程示例
用户输入："帮我整理这个文件夹里的所有发票，提取金额和日期"
系统处理：

1. 意图识别 → 提取能力需求

- file_explore (0.98)
- pdf_parse (0.95)
- image_ocr (0.92)
- data_extraction (0.90)
- spreadsheet_generate (0.85)

2. 工具路由 → 发现缺失工具

- 缺失：pdf_parse, image_ocr, data_extraction

3. 自动检索 → 找到候选工具

- pdfplumber-toolkit (score: 0.93)
- tesseract-ocr-toolkit (score: 0.89)
- invoice-parser-toolkit (score: 0.91)

4. 用户确认 → 首次安装确认
5. 并行安装 → 3个工具同时安装
6. 生成执行图

- file_explore → pdf_parse/image_ocr → data_extraction → spreadsheet_generate

7. 执行并返回结果
   用户后续输入："把金额超过1000的发票标红"

- 意图识别 → 已有能力 → 直接执行
  冷启动工具集（文件处理场景）
  工具
  能力
  来源
  file-explorer
  file_explore, file_search
  自研
  pdfplumber-toolkit
  pdf_parse, pdf_extract
  GitHub 爬取
  tesseract-ocr
  image_ocr, text_recognition
  GitHub 爬取
  invoice-parser
  data_extraction, entity_recognition
  GitHub 爬取
  pandas-toolkit
  data_analysis, data_transform
  GitHub 爬取
  openpyxl-toolkit
  spreadsheet_generate, excel_edit
  GitHub 爬取
  file-organizer
  file_move, file_rename, folder_organize
  自研

---

开发路线图
Phase 1：核心引擎（4-6 周）
目标：验证 MOE 路由可行性
任务：

- MCP Server 基础框架
- 意图识别器（Embedding + LLM）
- 工具路由器（MOE 核心）
- 本地工具缓存层
- 3-5 个手动录入的测试工具
  里程碑：在 Claude Desktop 中实现"自动发现工具需求"
  Phase 2：动态安装（4-6 周）
  目标：实现"需要即安装"体验
  任务：
- 工具描述标准定义
- 沙箱执行层（gVisor）
- 动态安装引擎（Nix 集成）
- 基础安全策略（权限声明 + 用户确认）
- 文件处理场景完整闭环
  里程碑：用户说"分析 CSV"，系统自动安装 pandas 并执行
  Phase 3：工具市场（6-8 周）
  目标：工具自动发现与评估
  任务：
- GitHub 爬虫系统
- 元数据自动提取
- 质量评分算法
- 工具索引数据库
- 自动化测试流水线
  里程碑：工具库从 10 个扩展到 100+ 个
  Phase 4：多宿主适配（4-6 周）
  目标：支持 Cursor、ChatGPT 等
  任务：
- Cursor LSP 适配（可选）
- HTTP API 模式
- 宿主特定优化
- 云端同步（可选）
  里程碑：同一工具库，多处可用
  Phase 5：智能进化（持续）
  目标：系统越用越智能
  任务：
- 执行反馈学习
- 用户行为建模
- 预测性预加载
- 社区贡献系统

---

壁垒构建
技术壁垒

1. MOE 路由算法：意图到工具组合的精准匹配
2. 动态安装速度：5 秒内完成环境构建（缓存 + 预构建）
3. 安全沙箱：gVisor + 最小权限，比 Docker 更隔离
   数据壁垒
4. 工具-意图映射数据：用户实际如何使用工具
5. 质量评分数据：工具成功率、用户满意度
6. 执行路径数据：复杂任务的最佳工具组合
   网络效应
7. 开发者：工具被使用 → 获得反馈 → 改进工具
8. 用户：工具越多 → 覆盖场景越全 → 用户越多
9. 数据飞轮：用户越多 → 路由越准 → 体验越好

---

风险与应对
风险
应对策略
MCP 协议变化
紧跟官方，抽象适配层
恶意工具
五层安全 + 信任分级 + 社区审核
安装失败率高
预构建镜像 + 降级策略
冷启动工具质量差
自动化测试 + 渐进开放
宿主不支持 MCP
优先 Claude/Cursor，其他等协议成熟

---

成功指标
指标
Phase 1
Phase 2
Phase 3
工具数量
5
20
100+
意图识别准确率
70%
85%
90%+
安装成功率

- 80%
  95%
  任务完成率
  60%
  80%
  90%+
  用户确认率（安装）
- <50%
  <20%

  ***

  命名建议
  产品名候选：

- Adaptive
- AutoKit
- ToolFlow
- SkillMesh
  核心概念：
- 工具 = Skill
- 安装 = Activate
- 路由 = Match
- 执行 = Run

---

文档版本：v1.0
创建时间：2026-03-08
