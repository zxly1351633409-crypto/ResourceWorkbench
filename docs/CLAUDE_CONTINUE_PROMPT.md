# 给 Claude / 新 task 的继续提示词

你正在继续开发一个 Windows 本地资源入库工作台，项目路径：

```text
F:\gpt codex huancun\资源管理工具开发\ResourceWorkbench
```

用户的资源库根目录：

```text
Z:\整合——资源管理
```

请先阅读：

```text
docs\PROJECT_STATUS_HANDOFF.md
docs\RESOURCE_WORKBENCH_REQUIREMENTS.md
docs\DEVELOPMENT_LOG.md
```

当前已实现：

- 指定批次只读分析。
- 7-Zip 压缩包目录预览。
- 大合集默认拆成多张资源卡片。
- 参考 Z 盘分类树推荐细分类。
- 预览图缓存。
- 密码候选推断。
- Qt/PySide6 正式视觉验证窗口。
- Qt 正式窗口已经改为 Pinterest 式卡片墙：图片主导、卡片错落、文字极简。
- 左侧导航栏和右侧详情栏可以收起，布局参考 Codex 的左中右结构。
- 左侧新增“路径”浏览器：导入母路径后列出直接子目录，单击子目录会刷新中间卡片墙，初步对应 Eagle 式浏览。
- 左侧已收纳：大标题和大按钮已移除，左侧主要留给路径列表，设置按钮在左下角，常用动作在顶部小图标工具栏。
- 左侧现在代表资源库路径，顶部输入框代表待整理路径；点击左侧资源库不会覆盖顶部待整理路径。
- 左侧预载资源库前两层路径，过滤 `.sync`，只做浅层预载。
- 顶部已有“层级”下拉，支持自动或手动按 1/2/3/4 层文件夹合并资源卡。
- SQLite 快速索引初版已加入：`src\resource_workbench\indexer.py`，数据库在 `workbench_data\resource_index.sqlite`。点击左侧路径先显示占位/缓存卡片，再刷新索引，详细分析由顶部分析按钮触发。
- 资源库快速卡片会按所在 Z 盘分类显示类型，不再全部 unknown/待确认。
- 详细分析按钮运行中会变成取消，扫描循环支持取消。
- 卡片悬浮浮层已有操作入口：打开、翻译、移动、上传、更多。
- 卡片右键菜单保留安全入口：打开所在文件夹、复制来源路径、修改目标分类、标记需确认、解压后深度分析、翻译命名、移动入库、上传115。
- “浏览已存路径”入口已加入，可只读浏览用户手动选择的已有资源路径。
- 右键“解压后深度分析”初版已实现：确认后解压到 `workbench_data\staging`，重新扫描临时目录并生成新卡片，不改动源文件。
- `J 教程` 已修复为自动按两层目录建资源卡，纯视频教程可通过视频抽帧生成预览；CLI 也支持 `--resource-depth 1-4`。
- UI 线性图标已改成多尺寸高清绘制，悬浮按钮不再用单字按钮表达操作。
- 翻译图标已从地球/联网语义改为 “A + 文本线 + 箭头”，上传图标也改为上传箭头。
- 新增只读审阅计划：`src\resource_workbench\planner.py`，窗口侧栏“审阅计划”会生成 `review_plan_*.json` 和 `review_plan_*.md`，不移动、不删除、不上传。
- 新增设置窗口：`src\resource_workbench\settings.py`。DeepSeek API Key 只从环境变量读取，不写入设置文件。
- 新增 DeepSeek 文本审阅客户端：`src\resource_workbench\deepseek.py`，支持 flash/pro 两套模型配置，默认 flash。没有 API Key 时只标记待翻译。
- 新增测试移动模块：`src\resource_workbench\mover.py`。当前只允许从 `F:\gpt codex huancun\资源管理工具开发\测试` 移动到 `F:\gpt codex huancun\资源管理工具开发\测试移动的位置`，非测试路径会被拒绝。
- 详细分析前可自动解压压缩包/文件夹内压缩包到 staging，再扫描解压内容。
- 右侧详情已改成 HTML 分块。
- 新增 Agent 模式方案：`docs\AGENT_MODE_PLAN.md`。

当前正式入口：

```text
启动-正式工作台.bat
启动-正式演示测试目录.bat
```

请不要贸然移动、删除、上传用户文件。

下一步建议：

1. 完善临时解压工作区：
   - 目前已有单张卡片右键触发的初版。
   - 继续补进度条、取消任务、来源关系清单和 staging 清理策略。
   - 输入压缩包或文件夹。
   - 解压到 `workbench_data\staging\<batch_id>`。
   - 支持分卷压缩包。
   - 使用 `resource_workbench.passwords.infer_archive_passwords()` 作为密码候选。
   - 记录解压来源关系。

2. 解压后重新扫描 staging：
   - 重新生成卡片。
   - 尽量使用真实文件生成预览图。
   - 识别内部资源内容压缩包。

3. 增加翻译配置：
   - DeepSeek API Key 不要写入代码。
   - 放入 `.env` 或本地设置。
   - 只做文本翻译和命名建议，不做图片识别。
   - DeepSeek 可以负责名称翻译、标签、描述和从候选分类里选择；不要让纯文本模型凭封面推测地点、年代或实际尺度。

4. 做入库确认界面：
   - 每张卡片显示名称、预览图、目标分类、移动对象、是否保留压缩包。
   - 用户可批量确认或逐张改。
   - 目标是把用户从操作者变成审阅者：软件跑解压、翻译、分类、移动、上传计划，用户审核是否正确。
   - 当前已有审阅计划文件，下一步应做成窗口内的确认队列，而不是只导出报告。

5. 建立正式资源库 SQLite 索引：
   - 读取用户指定的已存路径。
   - 使用当前卡片墙快速浏览已有资源。
   - 双击或右键打开真实路径。

6. 最后才做真实移动、删除、115 上传。

当前移动注意：

- 只开放测试移动，不要开放正式 Z 盘移动。
- 已做 smoke test：`__move_smoke_codex__` 被移动到 `测试移动的位置\model\__move_smoke_codex__`。
- 正式移动前必须补完整确认队列、容量/数量校验、撤销记录和失败恢复。

注意：

- 用户希望界面不要密密麻麻，字号和层级要清楚。
- 用户明确希望卡片墙像 Pinterest 一样能快速扫视所有资源，详情分析放在点击之后。
- 用户希望操作不要常驻挤占卡片空间，而是鼠标悬浮后浮在当前卡片上。
- 用户希望多级文件夹不要漏识别；当前 `J 教程` 默认两层最合适，3 层会把完整课程拆成章节卡，必要时让用户用层级下拉重扫。
- 用户希望目标分类尽量细，例如 `M 模型\K 科幻\J 机甲`。
- 用户希望 `科幻29` 这类大合集默认拆卡。
- 用户认为正式入库前应先解压再分析；只看压缩包预览图会误判照片包、模型物件/配件/建筑等资源。
- 用户已有 115 网盘同结构镜像，后续上传要按相对路径映射。
- QRoundedFrame 已放在 `external\QRoundedFrame`，但 C++/QML 编译环境还没齐。当前 PySide6 版是正式视觉验证版，后续可迁移到 QRoundedFrame。
## 2026-06-28 新一轮继续提示

用户最新关注点是正式版交互和自动化整理流程，不要只继续磨 UI 小细节。

已完成：

- 左侧资源库改为可折叠树，默认预载两层，深层展开懒加载。
- 中间卡片墙已有“待整理 / 资源库”两套状态。点击资源库树不会覆盖待整理分析结果。
- 输入框支持分号分隔多个待整理来源，后台 worker 支持多路径合并分析。
- 自动解压文件夹内压缩包后，会逐个扫描每个压缩包输出目录，避免 batch 外层把内部资源合并成一个卡片。
- staging 会写 `_extraction_manifest.json`，当前不删除源压缩包。
- 预览图选择加入打分，优先 cover/preview/render/screenshot/main。
- 新增“审阅者 Agent”入口，占位给 DeepSeek/HanaAgent。

下一步最值得做：

1. 资源库索引刷新做成后台线程和显式刷新按钮，避免任何点击阻塞 UI。
2. 把真实移动队列和 manifest 绑定，先只允许测试目录移动，生成可撤销/可审计记录。
3. DeepSeek 请求改为结构化 JSON，字段包括 translated_name、target_path、new_folder_needed、confidence、review_reason。
4. 审阅者 Agent 面板升级为任务队列，而不是只记录对话。
5. 115 上传要等审批完成后再执行；如果用户否决分类，必须先修正本地移动计划，再考虑云端同步。

## 2026-06-28 后续接手重点

用户又明确了一个方向：资源库是已整理好的库，启动时要像 Eagle 一样先读缓存/索引，不能每次点击都重新分析。

当前已改：

- `settings.py` 默认资源库路径为 `Z:\整合——资源管理`。
- 自动解压已强制关闭。
- 新增 `LibraryIndexWorker` 后台浅索引，启动后索引资源库前两层。
- `ResourceIndex.index_children()` 已做 mtime 增量缓存，未变化目录复用 SQLite 行。
- 左侧树文本增加 `▸ / ▾` 提示。
- 路径框粘贴待整理路径后按 Enter/失焦会自动分析。

继续开发时不要做：

- 不要在资源库点击时调用完整 `scan_input()`。
- 不要默认解压压缩包。
- 不要把资源库浏览和待整理分析混在同一套状态里。

建议下一步：

1. 把后台索引进度做成更明确的 UI 状态，比如右下角小提示/进度条。
2. 给资源库加“手动刷新索引”按钮，并允许刷新当前节点或全库。
3. 建 MCP：`list_library_nodes`、`get_cached_cards`、`analyze_sources`、`create_review_plan`、`execute_test_move`。
4. Hanako 调用 MCP，当任务规划与审阅大脑；ResourceWorkbench 保持本地文件操作和 UI 审批。
## 2026-06-28 最新状态，继续前请先读

本轮已经修复：

- 启动慢：左侧树不再启动前同步预读两层，窗口约 0.5 秒显示。
- 左侧树：使用独立浅色 SVG 箭头，点箭头展开/折叠，点名称浏览路径。
- 资源库浏览：只做浅层缓存/占位，不解压、不深扫、不覆盖待整理视图。
- `测试` 路径嵌套拆卡：自动推断 3 层，生成 38 张有效资源卡，过滤外层包装卡。
- 分类：科幻 parts/kitbash/column/container/hard surface 优先物件/配件，明确 gun/rifle/ammo 才枪支。
- 卡片缩略图：逐张延迟加载，加载后自动重排瀑布流。
- 正式窗口已用 `pythonw.exe` 启动，无黑框。

下一步请不要重新打开自动解压。当前产品决策是：用户先手动解压，ResourceWorkbench 先做好已解压资源的分析、审阅、测试移动、回滚记录和资源库浏览。

Hanako/openhanako 方向：不要让 Hanako 直接控制 PySide UI。应先给 ResourceWorkbench 做 MCP/HTTP/CLI 工具层，让 Hanako 读取 SQLite/task/review queue/manifest 后调用工具。

## 2026-06-28 最新接手提示：继续做卡片优先交互

用户最新反馈：资源库交互体感已经好了很多，但左侧视觉还要更像 Codex，卡片墙要更像 Pinterest，翻译/移动操作要尽量浮在卡片上完成。

当前已改完：
- 左侧资源库树改为深色 Codex 风格侧栏，透明树背景，深灰 hover/选中态。
- 设置图标改为居中的滑杆图标。
- 主窗口扩大到 `1520x900`，左侧栏收窄到 `226px`，卡片宽度调到 `210`。
- 卡片底部新增分类标签，资源库显示 `已入库 / 分类`。
- 已修复 Z 盘映射/NAS UNC 路径导致卡片底部显示 `192.168.31.5 / personal_folder` 的问题。
- 卡片 hover 层新增目标分类胶囊，点击可改目标分类。
- 设置面板新增翻译命名格式：
  - 中文名 + 原英文名
  - 原英文名 + 中文名
  - 只有中文名
  - 保留原英文名
- 设置面板新增 DeepSeek `验证 API` 按钮。
- `deepseek.py` 新增 `test_deepseek_connection()`，并把 Flash/Pro 模型选择抽成统一函数。
- 科幻分类更细：parts/kitbash/hard surface/container/column/accessory -> `W 物件`；building/architecture/facade -> `J 建筑`；明确 gun/rifle/ammo/bullet 才走枪支。
- 如果子目录不存在，也会先给虚拟子分类建议，后续审阅通过后可新建，不再只退回 `K 科幻` 总目录。

已验证：
- `python -m compileall src` 通过。
- 分类 smoke test 通过：
  - `sci fi kitbash hard surface parts` -> `M 模型\K 科幻\W 物件`
  - `sci fi building architecture` -> `M 模型\K 科幻\J 建筑`
  - `sci fi gun rifle` -> `M 模型\K 科幻\Q 枪支`
- 最新窗口已用 `pythonw.exe` 重启，标题 `资源入库工作台`，响应。
- 最新截图：`reports\ui_after_card_settings_20260628.png`

下一步请优先做：
1. 右侧详情改为默认收起或卡片左键弹窗详情，让主视野最大化留给卡片墙。
2. 卡片 hover 移动做成 Pinterest 式完整控件：左上选择/切换推荐路径，右侧保存/测试移动，不要逼用户去右键菜单。
3. 翻译按钮接入 DeepSeek 结构化 JSON，字段至少包括 `translated_name`、`target_path`、`new_folder_needed`、`confidence`、`review_reason`。
4. 翻译/移动都进入审阅队列，用户确认后才执行。
5. 真实移动仍只允许测试目录，直到 move log、撤销、数量/容量校验完成。

注意：
- 不要重新打开自动解压。当前产品决策是用户先手动解压，ResourceWorkbench 先做好已解压资源的分析、审阅、测试移动、回滚记录和资源库浏览。
- 不要让 Hanako 直接操作 PySide UI。应先做 MCP/HTTP/CLI 工具层。
