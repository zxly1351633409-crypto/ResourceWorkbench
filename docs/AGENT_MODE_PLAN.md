# 资源整理 Agent 模式方案

更新时间：2026-06-28

## 目标

用户不再逐个手动解压、翻译、移动、上传，而是：

1. 用户给一个待整理路径。
2. Agent 读取任务规则和资源库分类。
3. Agent 解压到临时工作区。
4. Agent 扫描、翻译、建议分类和移动计划。
5. 用户审批。
6. 通过后才执行测试移动/正式移动。
7. 115 上传在本地移动确认后执行。
8. 用户发现错误时，Agent 根据执行记录反向修正本地和 115。

## 必须持久化的记忆

Agent 不能只靠对话上下文记住规则，必须读写本地状态：

- `settings.json`：资源库根路径、测试移动路径、DeepSeek 模型、API Key 环境变量名。
- `resource_index.sqlite`：资源库路径索引、快速预览、搜索。
- `review_plan_*.json`：每批待审批计划。
- `move_log_*.json`：真实移动记录，用于撤销和修正。
- `upload_log_*.json`：115 上传记录，用于同步修正。
- `docs/RESOURCE_WORKBENCH_REQUIREMENTS.md` 和本文件：长期规则。

## Skill / 规则文件建议

后续可新增一个本地规则文件：

```text
workbench_data/agent_rules.md
```

内容包括：

- 不直接移动到正式 Z 盘，除非用户批准。
- 不删除压缩包，除非解压、移动、上传和校验全部成功。
- 照片包优先解压后分析，不凭封面猜地点、年代、文化属性。
- 模型的物件/配件/建筑判断需要人工审批或视觉模型支持。
- DeepSeek 文本模型只做文本归纳、翻译、分类候选选择。
- 多模态能力未接入前，视觉判断必须标记不确定。

## Agent 分工

### 1. Planner

输入：待整理路径、资源库根路径、用户设置。  
输出：任务计划。

职责：

- 判断是否需要先解压。
- 判断是否需要分批。
- 选择 flash/pro 模型。
- 生成审阅计划。

### 2. Extractor

职责：

- 找到 zip/rar/7z/分卷压缩包入口。
- 解压到 `workbench_data/staging`。
- 记录来源关系。
- 不改源文件。

### 3. Scanner

职责：

- 对 staging 或原目录生成资源卡。
- 抽取图片/视频预览。
- 建立快速索引。

### 4. Classifier

职责：

- 结合规则和 Z 盘分类树推荐目标分类。
- 需要时请求 DeepSeek 文本审阅。
- 标记不确定点。

### 5. Reviewer UI

职责：

- 用户审批每张卡。
- 支持批量通过、逐张改目标、标记错误、重新请求建议。

### 6. Executor

职责：

- 执行移动。
- 写移动日志。
- 校验数量和容量。
- 失败时停止后续步骤。

### 7. Uploader

职责：

- 按本地相对路径上传到 115。
- 写上传日志。
- 支持根据移动日志修正云端位置。

## 当前已落地

- 设置窗口。
- DeepSeek flash/pro 配置字段。
- DeepSeek 文本审阅客户端初版。
- SQLite 快速索引初版。
- 审阅计划文件。
- staging 解压。
- 测试移动护栏。

## 下一步

1. 做窗口内确认队列，不只导出审阅计划。
2. 对接 DeepSeek 批量请求，区分 flash/pro：
   - flash：翻译、摘要、普通分类。
   - pro：低置信度、多候选冲突、移动前最终审阅。
3. 写 `move_log_*.json`，支持撤销测试移动。
4. 做 115 API 可用性验证。
5. 接入统一缩略图工具或重写同等功能。
## 2026-06-28 补充：HanaAgent/openhanako 对接判断

- `openhanako` 更适合作为外部 Agent 大脑，而不是直接替换当前 PySide UI。
- 推荐架构：
  - ResourceWorkbench 负责本地文件系统能力：扫描、解压、缩略图、manifest、审批队列、移动、115 同步。
  - HanaAgent/DeepSeek 负责决策能力：理解用户指令、拆任务、调用工具、解释分类理由、在用户否决后重新规划。
  - 两者之间用 CLI、HTTP 或插件接口连接，不直接互相嵌 UI。
- 当前已为 Agent 化准备：
  - 多路径输入和批处理。
  - staging `_extraction_manifest.json` 来源追踪。
  - “待整理 / 资源库”视图分离，适合把待整理结果作为审批队列。
  - “审阅者 Agent”入口，后续可承载任务对话。
- 后续 Agent skill 应写清楚：
  - 不直接删除源压缩包。
  - 解压必须写 manifest。
  - 分类和移动必须等用户审批。
  - 用户否决时，先撤销/重建移动计划，再考虑 115 同步修正。
  - 照片地点、历史文物、模型实际尺寸等视觉判断，在没有多模态证据时必须标记为需人工确认。

## MCP 化建议

用户倾向：给 Hanako 和资源入库工作台分别做 MCP，让 Hanako 直接读取/操作本工具。

推荐拆分：

1. ResourceWorkbench MCP
   - `list_library_nodes(root, depth)`：读取资源库树和缓存状态。
   - `get_cached_cards(path)`：读取 SQLite 中的浅层资源卡片。
   - `refresh_library_index(path, depth)`：后台刷新指定路径索引。
   - `analyze_sources(paths)`：分析待整理来源，返回审阅卡片。
   - `create_review_plan(cards)`：生成审阅计划。
   - `execute_test_move(card_ids)`：仅执行测试移动，并返回可回滚记录。
   - `get_operation_manifest(operation_id)`：查询来源、目标、状态和错误。

2. Hanako MCP/插件
   - 作为调度大脑调用 ResourceWorkbench MCP。
   - 负责对话、任务拆解、重新规划、解释原因。
   - 不直接绕过 ResourceWorkbench 做文件移动。

关键安全规则：

- 资源库浏览不解压、不移动、不上传。
- 待整理分析默认也不解压；用户先手动解压。
- 移动前必须经过审批队列。
- 115 上传应在本地审批和移动稳定后执行。
## 2026-06-28 最新补充：Hanako 作为大脑，ResourceWorkbench 作为工具

用户担心 Hanako 每次新对话都丢上下文，长期留在一个对话又浪费 token。解决方向不是把所有规则塞进聊天，而是把任务状态和规则持久化。

### 推荐架构

- ResourceWorkbench 负责本地确定性能力：
  - 资源库 SQLite 索引。
  - 待整理路径扫描。
  - 缩略图/预览采样。
  - 审阅队列。
  - manifest 溯源。
  - 测试移动/正式移动。
  - move log / upload log。
- Hanako/openhanako 负责 Agent 决策：
  - 理解用户自然语言。
  - 读取当前任务状态。
  - 调用 ResourceWorkbench 工具。
  - 解释分类理由。
  - 被用户否决后重新规划。

### MCP 工具草案

ResourceWorkbench MCP 应优先暴露这些工具：

- `list_library_nodes(path, depth)`：读取资源库树和缓存状态。
- `get_cached_cards(path)`：读取 SQLite 缓存卡片。
- `refresh_library_index(path, depth)`：后台刷新指定路径索引。
- `analyze_sources(paths)`：分析一个或多个待整理路径。
- `get_review_queue(task_id)`：读取当前审阅队列。
- `update_review_decision(card_id, decision)`：记录用户通过/退回/改分类。
- `execute_test_move(card_ids)`：只执行测试移动，并写 move log。
- `get_operation_manifest(operation_id)`：查询来源、目标、错误和可回滚信息。

### 关键原则

- Hanako 不直接控制 PySide UI。
- Hanako 每次新对话先读取 task/state，而不是依赖聊天历史。
- 用户审批前不正式移动、不删除、不上传。
- 115 上传应在本地审阅通过并移动稳定后再执行。
- 没有多模态证据时，照片地点、历史文物、模型实际尺度等判断必须标记为需人工确认。
