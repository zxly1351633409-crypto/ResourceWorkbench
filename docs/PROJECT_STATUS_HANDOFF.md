# 资源入库工作台：历史进度与交接说明（归档）

> 归档提示（2026-07-11）：本文保留早期实现过程与问题复盘，不再代表当前界面或安全边界。继续开发时先读 `HANDOFF_NEXT.md`、`RESOURCE_WORKBENCH_REQUIREMENTS.md` 和 `USER_GUIDE.md`；若本文与这些文档或 v0.3.x 源码冲突，以后者为准。

原更新时间：2026-06-27

## 当前结论

项目已经从“后台只读脚本”推进到“可视化正式验证版”。

目标对照：

| 目标 | 当前状态 |
| --- | --- |
| 指定路径扫描、识别资源类型、生成报告 | 已实现 |
| Pinterest 式卡片墙浏览资源 | 已实现并持续优化 |
| Eagle 式左侧子路径 / 中间卡片墙 / 右侧详情 | 初版已实现 |
| 已存资源路径浏览 | 初版已实现，仍是只读扫描 |
| SQLite 资源索引/预载 | 初版已实现，用于快速浏览直接子路径 |
| 压缩包目录预览 | 已实现 |
| 完整解压后再分析 | 详细分析前自动解压初版已接入，批量队列未完成 |
| 视频教程预览 | 已实现视频抽帧 |
| 翻译命名 | DeepSeek 文本客户端初版已接入，支持 flash/pro 配置；无 API Key 时只标记 |
| 移动入库 | 测试移动初版已实现；正式 Z 盘移动未开放 |
| 115 上传 | 只有入口，尚未接 API |
| 统一文件夹缩略图显示 | 尚未接入原有工具能力 |
| 审阅者模式 | 审阅计划初版已实现，完整确认/执行队列未完成 |
| DeepSeek 自动整理流程 | 文本审阅请求初版已接入；批量队列未完成 |

本轮已验证：

- `启动-正式工作台.bat` 可以正常拉起空白 Qt 正式窗口。
- `启动-正式演示测试目录.bat` 可以正常拉起 Qt 正式窗口，并自动分析测试目录。
- 命令行只读分析可以生成 38 张资源卡片。
- 最新只读报告示例：`reports/resource_scan_20260627_004026_010246.md`
- 当前仍是安全验证阶段：不会移动、删除、上传任何资源。

现在有三个层级：

1. 后台分析核心  
   负责扫描指定批次、读取压缩包目录、拆分大合集、推荐分类、生成报告。

2. Tkinter 验证窗口  
   早期验证用，入口：
   - `启动-可视化工作台.bat`
   - `启动-演示测试目录.bat`

3. Qt 正式视觉验证窗口  
   当前建议优先体验这个，入口：
   - `启动-正式工作台.bat`
   - `启动-正式演示测试目录.bat`

QRoundedFrame 已经作为外部框架放在：

```text
external/QRoundedFrame
```

但它是 C++/QML 壳，需要 Qt 6、CMake、Ninja、Visual Studio C++ Build Tools。当前电脑暂未检测到这些完整构建工具，因此本阶段先用 PySide6/Qt 做正式视觉验证版。后台 worker 逻辑会继续保持可迁移，后续接 QRoundedFrame 时不需要重写扫描/分类逻辑。

## 已实现功能

### 1. 指定路径分析

软件不会自动扫描整个 `Z:\待整理` 或 `Z:\整合——资源管理`。

用户手动指定：

- 一个资源文件夹
- 一个压缩包
- 一个批次文件夹

### 2. 只读读取压缩包目录

当前会用 7-Zip 读取压缩包目录，但默认不完整解压。

用途：

- 判断资源类型
- 提前识别照片/模型/教程/材质
- 发现大合集
- 尝试抽取单张预览图

### 3. 大合集默认拆分

例如测试目录里的：

```text
科幻29-20230512.scifi
```

之前是一张卡，现在会拆成多个子资源卡片。

当前测试结果：

- 输入文件：9 个
- 外层文件夹：3 个
- 输出卡片：38 张

### 4. 更细目标分类推荐

软件会参考 `Z:\整合——资源管理` 的现有分类树，只读目录结构，不扫描全库文件内容。

示例：

```text
10 MECHANICAL LEG -> M 模型\K 科幻\J 机甲
Basalt Columns Lake -> Z 照片\Z 自然\S 石头
40 Futuristic Sci-fi City -> M 模型\K 科幻\C 场景
GSLV rocket -> M 模型\K 科幻\Z 载具
300 Blackout Ammo -> M 模型\K 科幻\Q 枪支
```

### 5. 内容线索标签

会显示类似：

- 科幻
- 机甲/机器人
- 枪支/弹药
- 建筑/城市
- 载具/飞行器
- 照片包/参考图
- 岩石/玄武岩
- 湖泊/水域

### 6. 预览图缓存

预览图来源：

1. 资源文件夹外层图片
2. 压缩包内部图片，只抽取单张图到工作台缓存

不会完整解压资源，也不会修改源文件。

缓存目录：

```text
workbench_data\previews
```

### 7. 密码推断

已加入自动密码候选规则。

当前会尝试：

- 空密码
- 父文件夹 `_` 后面的字符
- 父文件夹里的明显数字串
- 压缩包名里的明显数字串

例如：

```text
资源包_123456\a.zip -> 自动尝试 123456
科幻29-20230512.scifi\科幻29.part1.rar -> 自动尝试 20230512
```

后续完整解压也应复用同一套密码候选规则。

### 8. 手动纠错安全阀

Qt 正式验证窗口中已有：

- 修改目标分类
- 标记需确认

这两项只改本次工作台建议，不会移动文件。

### 9. Pinterest 式卡片墙

Qt 正式验证窗口已从表格列表改成卡片墙。

当前体验：

- 中间主区域按瀑布流方式显示资源卡片。
- 卡片进一步改成图片主导：保留原始预览比例，形成高低错落。
- 每张卡片默认只显示缩略图、一行标题、类型和必要状态。
- 点击卡片后，右侧显示更细的判断原因、目录样例和分类候选。
- 搜索框可以按名称、标签、分类、类型和判断原因过滤卡片。
- 顶部有“层级”下拉，支持自动或按 1/2/3/4 层文件夹合并资源卡。
- 预览失败时卡片只显示短提示，不会再被失败文字撑大。
- 左侧导航栏和右侧详情栏都可以收起，中间卡片墙会自动重排。

卡片悬浮浮层已接入：

- 打开所在文件夹。
- 翻译命名。
- 移动入库。
- 上传 115。
- 更多操作。

右键菜单保留为备用，包含：

- 打开所在文件夹。
- 复制来源路径。
- 修改目标分类。
- 标记需确认。
- 解压后深度分析。
- 翻译命名。
- 移动入库。
- 上传 115。

其中打开位置、复制路径、修改分类、标记需确认已经可用。解压后深度分析也已接入：确认后会把来源压缩包解压到 `workbench_data\staging`，再重新扫描临时目录生成新卡片，不会改动源文件。翻译、移动、上传目前只是安全入口或意图标记，不会真正改名、移动或上传。

### 10. 已存资源浏览入口

新增“浏览已存路径”按钮，用来选择 `Z:\整合——资源管理` 下的某个已有分类或资源文件夹，并用同一卡片墙浏览。

注意：

- 当前仍是只读分析，不建立正式 SQLite 索引。
- 不会自动扫描整个 Z 盘。
- 如果选择资源库根目录，窗口会提示这可能耗时，更推荐先选择具体分类。

后续正式资源库应改为：

```text
用户选定分类范围
  -> 分批建立 SQLite 索引
  -> 生成缩略图缓存
  -> 卡片墙快速浏览
  -> 双击或右键打开真实路径
```

当前 Qt 正式窗口还新增了左侧“路径”浏览器：

- 选择母路径后会列出直接子目录。
- 单击子目录会切换分析路径，并刷新中间瀑布卡片墙。
- 这是 Eagle 式资源浏览布局的初版：左侧子路径，中间卡片墙，右侧详情判断。

### 11. 用户新的分析反馈

用户认为只读取封面或压缩包目录仍然不够，尤其是：

- 照片包：局部风景或人物预览难以判断州、城市、历史文物或地理环境。
- 模型包：物件、配件、建筑的判断涉及相对人的尺度和主观使用语境，仅靠文件名容易误分。
- 大合集：外层封面只能知道大概主题，不能确认每个子资源边界。

因此正式入库阶段应优先：

```text
运输压缩包
  -> 临时解压工作区
  -> 重新扫描真实目录和代表图
  -> 生成卡片
  -> 用户审阅
  -> 再移动、翻译、上传
```

DeepSeek 当前可承担文本翻译、名称摘要、标签和分类候选选择。图片判断可以等 DeepSeek 多模态或其他视觉模型成熟后接入；在此之前，不应让纯文本模型凭图片文件名或单张封面编造地点、年代和实际尺度。

### 12. 审阅者模式方向

用户希望未来从“操作者”变成“审阅者”。

目标流程：

```text
选择批次
  -> 软件解压
  -> 软件分析和拆卡
  -> DeepSeek 翻译和推荐分类
  -> 软件生成移动/上传计划
  -> 用户只审核每张卡是否正确
  -> 确认后执行
```

例如发现 Blender 教程，但 `J 教程` 下没有对应的 `B Blender` 分类时，软件可以提出“新建分类”的建议；默认不直接创建，除非用户确认。

### 13. 临时解压深度分析初版

已新增：

```text
src\resource_workbench\staging.py
```

能力：

- 为单个压缩包创建唯一 staging 目录。
- 调用 7-Zip 完整解压到 `workbench_data\staging`。
- 复用 `resource_workbench.passwords.infer_archive_passwords()` 作为密码候选。
- 检查分卷入口，非 part1/001 入口会拒绝。
- 通过右键“解压后深度分析”接入 Qt 窗口。
- 解压成功后自动扫描 staging 目录，重新生成卡片、预览和报告。

仍需完善：

- 批量深度分析队列。
- 解压进度条。
- 取消任务。
- 解压来源关系清单。
- 运输压缩包/资源内容压缩包判定。
- staging 清理策略。

### 14. 已入库教程目录浏览修复

用户反馈 `Z:\整合——资源管理\J 教程` 分析效果很差：

- 文件夹套文件夹时识别不到真正资源边界。
- 纯视频教程没有预览图。
- 教程内部附带工程文件时，会被误判成 UE、模型或 mixed。

当前已修复：

- 新增 `ScanConfig.resource_root_depth`。
- `J 教程` 自动使用资源库浏览分组：
  - 选择 `J 教程`：按两层目录建卡，例如 `P ps\王克举 网课`。
  - 选择 `J 教程\P ps`：按一层目录建卡，例如 `王克举 网课`。
- 资源库浏览模式不拆教程内部压缩包目录。
- `J 教程` 下卡片优先尊重已有库分类，统一显示为教程。
- 每张卡保存真实 `source_path`，打开所在文件夹不再靠卡名猜路径。
- 扫描记录 `video_candidates`。
- 预览模块支持从视频抽帧：
  - 优先系统 `ffmpeg`。
  - 没有系统 `ffmpeg` 时使用 `imageio-ffmpeg`。
- `pyproject.toml` 已加入 `imageio-ffmpeg>=0.5`。

验证结果：

```text
旧结果：31 张卡，unknown/mixed/model/tutorial/ue 混杂。
新结果：11 张卡，全部 tutorial。
纯视频预览源：4 张。
```

新报告：

```text
reports\resource_scan_20260627_225811_532798.json
reports\resource_scan_20260627_225811_532798.md
```

新截图：

```text
reports\ui_j_tutorial_fixed_preview.png
```

### 15. 层级切换与高清图标

用户继续反馈：

- 需要检验多级文件夹是否还有问题。
- 悬浮/工具图标有点糊，需要高清化。

当前已处理：

- Qt 正式窗口顶部新增“层级”下拉：
  - 默认“自动”仍按路径推断。
  - 选择 `J 教程` 时自动按两层目录建卡。
  - 用户可手动切换 1/2/3/4 层后重扫，用于处理更深或更浅的资源包结构。
- CLI 同步新增：

```text
--resource-depth 1-4
```

- 分析完成摘要会显示当前按几层建卡。
- 线性 UI 图标改为 24/32/48/64 多尺寸绘制，避免高 DPI 屏放大小图导致模糊。

真实路径验证：

```text
Z:\整合——资源管理\J 教程

depth=1 -> 4 张大分类卡，太粗。
depth=2 -> 11 张资源卡，符合当前资源包视角。
depth=3 -> 45 张章节/子目录卡，会把完整课程拆碎。
```

结论：

- `J 教程` 默认继续用两层目录建卡。
- 多级文件夹里的内容不会漏扫；例如资源文件夹下的 `Chapter`、`Assets` 会统计到同一张资源卡。
- 如果个别目录本身比当前资源库结构更深，可在窗口里手动切换层级重扫。

新截图：

```text
reports\ui_j_tutorial_icons_hd.png
reports\ui_j_tutorial_hover_icons_hd.png
```

### 16. 审阅计划与语义图标修正

用户指出不能一直只磨 UI，需要回到总目标，并指出图标语义不匹配，例如“翻译”不该用地球联网图标。

当前已处理：

- 新增 `src\resource_workbench\planner.py`。
- Qt 侧栏新增“审阅计划”按钮。
- 可根据当前卡片生成：

```text
reports\review_plan_*.json
reports\review_plan_*.md
```

审阅计划包含：

- 来源路径。
- 建议目标分类。
- 目标分类是否存在，是否可能需要新建。
- 是否建议深度分析。
- 是否待翻译。
- 移动/上传/删除状态。

安全状态：

- 只生成计划。
- 不移动文件。
- 不删除文件。
- 不上传 115。

UI 修正：

- 翻译图标改为 “A + 文本线 + 箭头” 的翻译语义。
- 上传图标改为上传箭头。
- 悬浮按钮增大到 34x32，图标增大到 22px。
- 左侧路径列表关闭横向滚动条，长路径省略。

新截图：

```text
reports\ui_library_sidebar_plan_icons.png
```

### 17. Codex 式左侧收纳、快速索引、DeepSeek 和测试移动

用户反馈左侧按钮太多，挤占路径窗口，整体应更参考 Codex 交互。

当前已调整：

- 左侧删除大标题和大按钮。
- 左侧只保留路径浏览列表和左下角设置按钮。
- 常用动作移到顶部小图标工具栏：
  - 浏览资源库路径
  - 选择文件夹
  - 选择压缩包
  - 详细分析当前路径
  - 生成审阅计划
  - 打开报告
  - 打开报告文件夹
- 卡片级动作仍放在悬浮层和右键菜单。

新增设置窗口：

```text
src\resource_workbench\settings.py
```

可配置：

- 资源库根路径。
- 测试移动根路径。
- DeepSeek base URL。
- DeepSeek 模型。
- API Key 环境变量名。
- 是否打开资源库路径时刷新快速索引。

新增 SQLite 快速索引：

```text
src\resource_workbench\indexer.py
workbench_data\resource_index.sqlite
```

行为：

- 左侧点击路径后先即时显示占位/缓存卡片。
- 再刷新索引补充文件数和预览源。
- 详细分类分析改为用户点击顶部分析按钮触发。

新增 DeepSeek 文本审阅客户端：

```text
src\resource_workbench\deepseek.py
```

行为：

- 默认模型：`deepseek-v4-flash`。
- API Key 从环境变量读取，不保存明文。
- 卡片“翻译”入口可请求命名/分类审阅建议。
- 没有 API Key 时只标记待翻译，不发请求。

新增测试移动模块：

```text
src\resource_workbench\mover.py
```

安全限制：

- 当前只允许从 `F:\gpt codex huancun\资源管理工具开发\测试` 移动。
- 当前只移动到设置里的测试移动根路径。
- 非测试目录来源会被拒绝，防止误动正式资源库。

验证：

```text
快速索引测试目录：3 张卡。
非测试目录移动：已被安全拦截。
真实移动 smoke：__move_smoke_codex__ -> 测试移动的位置\model\__move_smoke_codex__。
```

新截图：

```text
reports\ui_codex_like_sidebar_quickbrowse.png
```

### 18. 分级预载、取消分析、自动解压和 Agent 方案

本轮根据用户反馈修复：

- 左侧资源库路径不能覆盖待整理路径。
- 分析时如果切到别处打字，回来后不能一直卡住。
- 资源库路径卡片不应全部未知/待确认。
- 设置需要 flash/pro 两套 DeepSeek 配置。
- 右侧详情视觉层级弱。
- 需要自动解压压缩包后再分析。

当前行为：

- 顶部路径框是“待整理路径”，详细分析只分析这里。
- 左侧是“资源库路径”，点击只做资源库快速浏览，不再覆盖顶部路径。
- 左侧预载资源库前两层路径，过滤 `.sync`。
- 快速浏览卡片根据所在 Z 盘分类显示类型，不再全部未知。
- 详细分析按钮运行中会变成取消按钮，扫描循环支持取消。
- 自动解压开关在设置里，默认打开；详细分析前会尝试把压缩包/文件夹内压缩包解到 staging 再扫描。
- DeepSeek 设置包含：
  - Flash 模型
  - Pro 模型
  - 默认模式
- 设置图标改为滑杆图标。
- 右侧详情改为 HTML 分块。

新增方案文档：

```text
docs\AGENT_MODE_PLAN.md
```

用于说明后续 Agent 模式如何持久化规则、审批、移动日志、115 上传日志和错误修正。

验证：

```text
自动解压 smoke test：成功。
非测试路径移动：安全拦截。
Z 盘根路径快速索引：约 3.27 秒。
最新窗口已重启。
```

新截图：

```text
reports\ui_resource_tree_two_level_detail_html.png
```

## 尚未实现

### 1. 完整临时解压工作区

当前已有“单张卡片右键触发”的临时解压深度分析初版，但还不是完整入库级工作区。

正式入库阶段必须新增：

```text
源压缩包/源文件夹
  -> 临时解压工作区
  -> 生成资源卡片
  -> 用户确认
  -> 移动资源文件夹到 Z 盘
```

### 2. 真正移动入库

当前不会移动。

未来移动对象不是“运输压缩包”，而是：

- 解压后的资源文件夹
- 或用户确认应保留为内容包的内部压缩包所在资源文件夹

### 3. 删除运输压缩包

当前不会删除。

未来删除条件必须是：

- 解压成功
- 移动成功
- 本地数量/容量校验通过
- 如果用户设置要求 115 成功后再删，则必须 115 上传成功

默认应移动到回收站，不永久删除。

### 4. 翻译功能

还没有做。

计划：

- 第一阶段：调用 DeepSeek 做文本翻译和中英并存命名建议。
- 第二阶段：允许用户确认翻译结果。
- 第三阶段：批量重命名资源文件夹。

DeepSeek 当前只能处理文本，不处理图片识别。

### 5. 115 上传

还没有做。

计划：

- 本地根目录：`Z:\整合——资源管理`
- 115 根目录：同名目录
- 上传时使用相对路径映射

推荐优先使用 115 官方开放平台 API，而不是模拟客户端 UI。

### 6. QRoundedFrame C++/QML 正式壳

QRoundedFrame 已导入，但未编译接入。

缺少环境：

- Qt 6.6+ / 推荐 Qt 6.11 MSVC 2022 64-bit
- Visual Studio 2022 Build Tools C++ 工作负载
- CMake
- Ninja

后续路线：

1. 保持 Python worker 输出 JSON。
2. QRoundedFrame/QML 负责正式窗口表现。
3. C++/QML 通过 worker 或 SQLite 读取卡片数据。
4. 当前 PySide6 版作为 UI 信息架构参考。

## 当前推荐下一步

1. 完善“临时解压工作区”：进度条、取消任务、来源关系清单和 staging 清理策略。
2. 解压后重新扫描真实目录，继续优化卡片拆分、缩略图和判断原因。
3. 把“运输压缩包”和“资源内容压缩包”区分开。
4. 做入库前确认界面，让用户以审阅者身份核对分类、翻译名和移动对象。
5. 加入 DeepSeek 文本翻译与分类候选选择，API Key 放本地配置，不写入代码。
6. 建立正式资源库 SQLite 索引，用当前卡片墙浏览已入库资源。
7. 最后再接真实移动、删除、115 上传。
## 2026-06-28 最新补充

- UI 框架继续正式化：
  - 左侧资源库路径改为可折叠树，默认预载两层，深层目录按展开懒加载。
  - 中间卡片墙分离为“待整理”和“资源库”两个状态，左侧点击资源库不会再覆盖待整理路径和分析结果。
  - 全局滚动条、设置图标、右侧详情标签间距已优化。
- 多路径整理已接入：
  - 输入框可用分号分隔多个来源。
  - 选择文件夹/压缩包会追加到待整理来源。
  - 后台分析 worker 会合并多个来源，输出同一批审阅卡片和报告。
- 解压链路已修正：
  - 文件夹内多个压缩包解压后，逐个扫描每个压缩包输出目录，不再只扫描 batch 外层。
  - staging 会写 `_extraction_manifest.json`，保留源压缩包和输出目录映射，后续移动/删除/115 同步可以回溯。
  - 已验证旧 staging 批次能拆出 3 张入口卡：`Sci_Fi Robot Leg`、`Fotoref - Basalt Columns Lake`、`科幻29`。
- 预览图选择已优化：
  - 优先 cover/preview/render/screenshot/main。
  - 降低 normal/roughness/mask/logo/icon 等误选概率。
- Agent 方向：
  - 新增“审阅者 Agent”入口，当前作为对话和流程占位。
  - openhanako/HanaAgent 更适合作为外部大脑，通过 CLI/HTTP/插件调用本工具；本工具应继续沉淀可调用工作流、manifest 和审批队列。

下一步建议：

1. 给资源库索引做后台线程/手动刷新按钮，彻底避免目录点击卡顿。
2. 把 manifest 接入真实移动队列，先移动到测试目录并生成可回滚记录。
3. 让 DeepSeek 输出结构化 JSON：翻译名、目标分类、是否新建文件夹、置信度、需人工确认原因。
4. 将审阅者 Agent 面板升级为任务队列：待审批、已通过、需重判、移动失败、上传待同步。
5. 115 上传在用户审批完成后再同步，避免错误分类后还要云端回滚。

## 2026-06-28 最新修正：资源库预加载与取消默认解压

用户明确反馈：

- 打开软件时就要看到资源库有什么，不要每次点击都等很久。
- 资源库不需要深分析，只要浅层知道类型、名称、预览和大概内容。
- 资源库里的内容默认视为已解压成品，不要再自动解压。
- 待整理资源由用户粘贴路径后再分析。

当前实现：

- 默认资源库路径已修为 `Z:\整合——资源管理`。
- 默认测试来源路径已修为 `F:\gpt codex huancun\资源管理工具开发\测试用这里面的文件`。
- 自动解压已强制关闭，设置面板里该选项禁用。
- 启动后会进入资源库浏览，并启动后台浅层索引。
- SQLite 索引改为增量：子目录修改时间没变则复用缓存。
- 左侧树增加 `▸ / ▾` 三角文本提示。
- 路径输入框按 Enter 或失焦后，若路径存在且不是资源库根目录，会自动开始待整理分析。

注意事项：

- 不要再把“资源库浏览”做成完整扫描，否则会重新造成卡顿。
- 不要默认解压用户资源；如后续恢复解压，必须先完成可回滚 manifest + 审批队列。
- 资源库索引应优先走后台线程和 SQLite 缓存，UI 点击只读缓存/占位。
- Hanako 方案应走 MCP/HTTP/CLI 工具调用，不建议直接控制 PySide UI。
## 2026-06-28 最新交接补充

### 已完成修复

- 正式窗口启动速度：
  - 旧问题：窗口显示前同步预读资源库树两层，启动可卡 40 秒左右。
  - 当前：启动只建一级树，首屏资源库浏览延后到窗口显示后执行，实测约 0.5 秒可显示窗口。
- 左侧路径树：
  - 不再把 `▸/▾` 拼在名称里。
  - 使用独立 SVG 分支箭头，视觉上更像 Windows 导航树。
  - 点击箭头展开/折叠，点击名称浏览该路径。
- 资源库预览：
  - SQLite 旧缓存如果没有预览源，会重新采样。
  - 点击深层路径时会优先切换后台索引到当前路径。
  - 资源库浏览仍只做浅层缓存，不做深度分析、不解压、不移动。
- 待整理测试路径：
  - `F:\gpt codex huancun\资源管理工具开发\测试` 已验证。
  - 自动层级推断会识别外层授权包/合集包/编号子目录。
  - 当前可拆出 38 张有效资源卡，过滤掉外层 `file.jpg` 包装卡。
- 分类规则：
  - 科幻配件类关键词优先物件/配件。
  - 明确武器词才走枪支。
  - 资产包里的视频更倾向资产预览，不直接判教程。
- 黑框说明：
  - 黑色 `F:\...\ResourceWorkbench>` 命令行是调试时用 `python.exe` 可见启动造成的，不是 Hanako/MCP。
  - 当前正式运行使用 `pythonw.exe`，不应再出现黑框。

### 当前运行状态

- 已重新启动最新版窗口。
- 进程：`pythonw.exe`
- 窗口标题：`资源入库工作台`
- 状态：响应。
- 最新截图：`reports\ui_current_window_final_20260628.png`

### Hanako / MCP 建议

- 不建议 Hanako 直接操作 PySide 窗口。
- 建议 ResourceWorkbench 提供 MCP/HTTP/CLI 工具：
  - 读资源库索引。
  - 分析待整理路径。
  - 生成/读取审阅队列。
  - 执行测试移动。
  - 查询 manifest、move log、upload log。
- Hanako/openhanako 作为“大脑”调用这些工具，不依赖长聊天上下文。
- 长期状态必须持久化到 SQLite、manifest、review queue、move/upload log；新对话只需要读取任务 ID 和当前队列。

### 继续开发优先级

1. 完整审阅队列 UI：待确认、通过、退回重判、移动失败、上传待同步。
2. DeepSeek 结构化 JSON 输出：翻译名、目标分类、置信度、是否新建目录、需人工确认原因。
3. 测试移动升级为可回滚 move log。
4. 115 上传在本地审阅通过后执行，避免错误分类后云端也要回滚。
5. MCP/HTTP/CLI 接口，让 Hanako 调用，而不是直接控制 UI。

## 2026-06-28 最新交接补充：卡片优先、翻译设置、分类更细

用户最新确认：资源库交互体感已经明显变好，下一步重点是“正式版卡片优先体验”和“后续让 Claude 继续优化”。

本轮已完成：
- 左侧资源库树视觉更接近 Codex 桌面端：深色低对比侧栏、透明树背景、深灰选中态、设置滑杆图标重新居中绘制。
- 主窗口扩大到 `1520x900`，左侧栏收窄，卡片宽度调到 `210`，中间区域保持 Pinterest 式 4 列左右卡片视野。
- 卡片底部新增精简分类标签：资源库视图显示 `已入库 / 分类`，待整理视图显示推荐目标分类。
- 修复 Z 盘映射到 NAS/UNC 路径时卡片底部出现 `192.168.31.5 / personal_folder` 的问题。
- 卡片 hover 层新增目标分类胶囊入口，点击进入“修改目标分类”，作为 Pinterest 式“卡片上直接选择路径/保存”的前置实现。
- 设置面板新增翻译命名格式：`中文名 + 原英文名`、`原英文名 + 中文名`、`只有中文名`、`保留原英文名`。
- 设置面板新增 `验证 API` 按钮，用当前 DeepSeek base URL、Flash/Pro 模型和 Key 环境变量做最小联网验证。
- DeepSeek prompt 会带上当前翻译命名格式；Key 仍然只读环境变量，不写入设置文件。
- 分类规则继续细化：科幻 parts/kitbash/hard surface/container/column/accessory 优先 `K 科幻\W 物件`；building/architecture/facade 优先 `K 科幻\J 建筑`；gun/rifle/ammo/bullet 才优先枪支。
- 找不到现成子目录时也会给“建议新建/使用子分类”的虚拟目标，不再轻易退回科幻总文件夹。

验证：
- `python -m compileall src` 通过。
- 分类 smoke test 已确认：
  - `sci fi kitbash hard surface parts` -> `M 模型\K 科幻\W 物件`
  - `sci fi building architecture` -> `M 模型\K 科幻\J 建筑`
  - `sci fi gun rifle` -> `M 模型\K 科幻\Q 枪支`
- 最新窗口已用 `pythonw.exe` 重启，标题 `资源入库工作台`，当前响应。
- 最新截图：`reports\ui_after_card_settings_20260628.png`

下一轮/Claude 优先级：
1. 把右侧详情逐步改为默认收起或左键卡片弹窗详情，真正把视野留给卡片墙。
2. 把卡片 hover 移动做成完整 Pinterest 式交互：左上选择推荐路径，右侧保存/测试移动按钮，避免用户去右键菜单里找。
3. DeepSeek 改为结构化 JSON 输出：`translated_name`、`target_path`、`new_folder_needed`、`confidence`、`review_reason`。
4. 翻译结果进入审阅队列，不要直接改名；用户确认后再批量重命名/移动。
5. 真实移动继续只走测试目录，直到有完整 move log、撤销、数量/容量校验和审阅队列。

## 2026-06-28 审阅者工作流后端（结构化建议 + 审阅队列 + 可回滚移动）

本轮聚焦“把用户从操作者变成审阅者”的后端三件套，全部为纯逻辑模块，已用单元测试覆盖（不依赖 GUI、不触碰 Z 盘）。

### 新增/修改模块

- `src\resource_workbench\deepseek.py`
  - 新增 `request_structured_card_suggestion()`：用 `response_format=json_object` 请求 DeepSeek，输出结构化 JSON。
  - 新增 `parse_structured_suggestion()`：兼容纯 JSON、```json 代码块、前后夹带解释文字三种回复；用括号配平提取 JSON 对象。
  - 字段规范化 `_normalize_suggestion()`：统一为 `translated_name / target_path / new_folder_needed / confidence / review_reason / tags`；兼容中文键名（中文名/目标分类/置信度/新建目录）与数值置信度（0~1 自动映射 high/medium/low）。
  - 原 `request_card_suggestion` / `test_deepseek_connection` 保持不变。

- `src\resource_workbench\review_queue.py`（新）
  - SQLite 持久化审阅队列：`workbench_data\review_queue.sqlite`。
  - 状态机：pending / approved / rejected / needs_recheck / moved / move_failed / upload_pending / done。
  - `card_identity()` 用 source_path 生成稳定 card_id；重复入队只刷新机器建议字段，不覆盖人工已设的 target_path / 状态。
  - `apply_suggestion()` 把 DeepSeek 结构化建议写入队列项（不改状态）。
  - `update_fields()` 白名单字段，禁止从这里改 status（必须走 set_status）。

- `src\resource_workbench\move_log.py`（新）
  - SQLite 移动日志：`workbench_data\move_log.sqlite`。
  - `count_tree()` 统计文件数/字节数做完整性校验。
  - 记录状态：moved / reverted / revert_failed，含来源、目标、数量、容量、verified、时间。
  - `export_records_json()` 可导出审计 JSON。

- `src\resource_workbench\mover.py`
  - `execute_test_move()` 升级：移动前后清点并校验数量/容量，写入 move_log，返回 move_id 与 verified。
  - 新增 `undo_move()`：按 move_id 把目标移回原来源；目标缺失或来源被占用会拒绝并标记 revert_failed；撤销后再次校验。
  - 仍保留“只允许从测试目录移动”的安全限制。

- `src\resource_workbench\cli.py`
  - 新增子命令：`queue list/counts/set-status/set-target`、`move`、`undo`、`moves`（含 `--export`）。
  - `analyze --enqueue` 可把分析结果直接写入审阅队列。
  - 支持环境变量 `RESOURCE_WORKBENCH_HOME` 覆盖数据根目录（便于测试与外部 Agent 指定独立 workbench_data）。

- `tests\test_review_workflow.py`（新）：13 个用例，覆盖 JSON 解析（纯/代码块/中文键/数值置信度/无 JSON）、队列去重与状态流转、非法状态/字段拦截、移动校验、越界来源拦截、撤销恢复、重复撤销拦截。

### 验证

- `python -m compileall src` 通过。
- `python -m unittest discover -s tests` 全部通过（13/13）。
- CLI 端到端冒烟（沙箱临时目录）：analyze --enqueue → queue set-target → move（校验通过）→ undo（恢复并校验）→ moves 显示 reverted，文件成功还原。
- 注意：SQLite 在沙箱的网络挂载盘上会报 disk I/O error，这是沙箱挂载限制；在用户本机本地盘正常（单元测试用本地临时目录已验证）。

### GUI 接入要点（需在 Windows 上运行验证）

`qt_app.py` 尚未接线，建议下一步：
1. 卡片“翻译”按钮改调 `deepseek.request_structured_card_suggestion()`，结果写入 `ReviewQueue.apply_suggestion()`，不直接改名。
2. 侧栏“审阅计划”旁新增“审阅队列”面板：按状态分组（待审阅/已通过/退回重判/移动失败/待上传），逐张确认。
3. 卡片 hover 的“移动入库”改为：确认后调用 `mover.execute_test_move(card, source_root, test_move_root, z_root, move_log=...)`，并在面板显示 move_id 与校验结果；提供“撤销”按钮调 `undo_move()`。
4. 真实 Z 盘移动仍不开放，直到队列确认 + 校验 + 撤销在 GUI 中跑通。

## 2026-06-28 卡片优先交互（目标选择器 + 去右侧面板 + 本地 Key）

针对用户反馈：卡片上的目标地址不好改、移动怕进错位置、右侧窗口浪费空间、不知道 API Key 放哪。

### 新增/修改

- `src\resource_workbench\target_recommender.py`（新，已测试）
  - `recommend_target_folders(card, resource_root)`：按卡片建议分类沿真实资源库目录树向下走，找到最深已存在层，列出该层现有子文件夹并按与卡片名/标签/叶子名的相近度排序；若建议叶子目录不存在，额外给 `suggested_new`（新建建议路径）。叶子是无子目录的死胡同时会自动回退到父级显示兄弟分类。
  - `browse_subfolders(path, resource_root)`：供“点进去”逐层浏览。
  - 只读目录，不创建、不移动。

- `src\resource_workbench\settings.py`
  - 新增本地密钥：`secret_path()`、`save_deepseek_api_key()`、`deepseek_api_key_source()`。
  - `deepseek_api_key()` 改为：环境变量优先，其次本机 `workbench_data\secret.json`。
  - `load_settings()` 注入运行期 `_secret_file`（不写回 settings.json）。secret 不进版本库（workbench_data 已在 .gitignore）。

- `src\resource_workbench\qt_app.py`
  - 新增 `TargetPickerDialog`：Pinterest 式目标分类选择器。顶部推荐近似分类（★），可搜索、双击点进子目录、“返回上一级”、“选择当前这层目录”，选中后底部显示“将移动到…”，确认才返回路径。
  - `修改目标分类` 改为打开该选择器（资源库根不存在时回退系统文件夹对话框）。
  - `移动入库` 若该卡未选目标，会先弹选择器；确认框里显示选定目标分类，避免“移动到不确定的位置”。
  - 移除右侧常驻“预览与判断”面板，主区域全部给卡片墙；预览/详情改为双击卡片弹窗（`detail_dialog` + `show_detail_dialog`）；顶部原“收起右侧”按钮改为“查看/隐藏所选卡片详情”。
  - 设置面板新增「API Key」输入框（密码态）：可直接粘贴 Key，保存写入本机 secret.json；环境变量优先，提示文案显示当前 Key 来源（环境变量/本机保存/未检测到）。

### 验证

- `python -m compileall src` 通过；`python -m unittest discover -s tests` 全过（含新增推荐/密钥共 23 用例）。
- 用 PySide6 桩模块导入 `qt_app` 成功，确认导入期与类定义无缺失符号（方法体仍需 Windows 实跑）。

### 仍需用户在 Windows 上实跑验证

- 目标选择器在真实 `Z:\整合——资源管理` 上的推荐质量与逐层浏览手感。
- 双击卡片弹出详情、隐藏右侧后卡片墙铺满是否如预期。
- 设置里粘贴 DeepSeek Key 后，「验证 API」与卡片翻译是否连通。

### API Key 怎么填（给用户）

打开软件 → 左下角设置 → DeepSeek 区「API Key」框粘贴你的 Key → 保存。保存后写入本机 `ResourceWorkbench\workbench_data\secret.json`，不会上传、不进版本库。若你更想用环境变量，设了同名环境变量会优先生效。

## 2026-06-28 预览修正 + 接入翻译 + 选择器/卡片打磨

- 预览图选择（`classifier._preview_name_score` / `_best_preview_path`）：
  - 扩充正向线索：render/scene/cover/preview/hero/final/showcase/turntable 等。
  - 扩充负向线索：把 normal/roughness/basecolor/albedo/diffuse/ao/orm/height/mask/uv/atlas/lightmap 等贴图通道强力降权，避免把法线/粗糙度等当封面。
  - 名称同分时按文件大小排序（hero 渲染图通常更大），减少“模型场景卡选错预览图”。
  - 已加单测 `tests/test_preview_selection.py`（5 例）。
  - 注意：若真实封面不在每类前 12 张采样内仍可能漏选，后续可在 scanner 提高图片采样上限或优先采样根层图片。
- 翻译接入（`qt_app.translate_card`）：
  - 卡片“翻译”改用 `request_structured_card_suggestion`，解析 translated_name/target_path/new_folder_needed/confidence/review_reason。
  - 译名写入卡片标题（display_name），AI 建议分类并入 target_path_hints 顶部，详情弹窗结构化展示。
  - 仍标记需人工确认，不自动改名、不自动移动。
- 目标选择器打磨（`TargetPickerDialog`）：
  - 顶部“母路径”面包屑改为深色高对比胶囊，清楚显示当前所在父路径。
  - 取消逐子目录 has_children 探测（NAS 上很慢），双击任意文件夹即可进入；空层给提示。
  - 弹窗自带样式表，列表行更大更清晰；推荐项显示完整相对路径，定位不再靠猜。
- 卡片与悬浮按钮：
  - 卡片加宽 210 → 250，预览高度上限放宽（150–380）。
  - 悬浮按钮从 6 个精简为 4 个（翻译/移动、打开/目标分类），尺寸加大到 40×36、图标 24px 白色描边；其余操作仍在右键菜单。

验证：compileall 通过；单测 28 例全过；PySide6 桩导入 qt_app 通过。翻译与移动的真实效果需在 Windows + 已连 DeepSeek + 真实 Z 盘上实测。

## 2026-06-28 一键翻译 + 悬浮配色 + 移动/上传进度 + 115 框架

- 悬浮按钮可视化：改为彩色实心底+白色图标（翻译=蓝、移动=绿、打开=slate、目标=琥珀），加粗图标线条(2.4)，遮罩加深；解决“全是灰白看不清”（此前我误把图标设白色叠加在白底上）。
- 一键翻译：顶部工具栏新增「一键翻译」按钮（translate 图标）→ `translate_all_cards`，带 QProgressDialog 进度+可取消，逐张调 `request_structured_card_suggestion` 并批量写回（译名、建议分类、详情）；只建议不自动改名/移动。
- 移动进度：`execute_selected_test_move` 移动时弹模态进度窗（清点/移动/校验），并改为传入 MoveLog 记录可回滚日志；完成显示是否校验通过。
- 115 上传框架（新 `uploader_115.py`）：
  - `mirror_relative_path` / `remote_target_path`：按本地相对资源库根的路径，镜像到 115 同相对路径（可选 115 根目录名）。已单测。
  - `Uploader115`：is_enabled/is_configured/has_token/status_hint + `upload_folder(progress_cb, cancel_cb)`；`UploadLog` SQLite 记录上传。
  - 真正的 `_upload_file` 为占位：需用户提供 115 开放平台 AppID/AppSecret 并完成授权(token)后，按官方 API 补齐（确保/建目录→取上传凭证→sha1 秒传/分片直传→校验）。未配置/未授权会返回明确提示，不假装成功。
  - 设置面板新增「115 网盘」区：启用、AppID、AppSecret(写本地 secret.json)、115 根目录、移动后自动上传同路径。
  - 移动成功后若开启“自动上传”，自动调用 `upload_card`（带上传进度窗）。
- 测试：compileall 通过；单测 35 例全过（新增 uploader 5 例）；PySide6 桩导入 qt_app 通过（translate_all_cards / upload_card 存在）。

### 115 真实上传待办（需要用户配合）
1. 在 115 开放平台申请应用，拿到 AppID/AppSecret；在设置里填入并启用。
2. 完成授权拿到 token（OAuth/扫码）——授权流程代码尚未写，需要按官方文档补 `uploader_115` 的 token 获取与持久化。
3. 实现 `_upload_file`（建目录+取直传凭证+秒传/分片）。
4. 官方文档此前 web 抓取超时（云端 JS 渲染），需用户提供文档或在能联网环境获取后再接。

## 2026-06-28 自动优化轮（预览v2 + CLI recommend + 队列联动 + 用户指南）

- 预览选择 v2：
  - scanner 新增 `image_sample_limit`(默认40)，不再只采前 12 张图片，降低真正封面没被纳入候选的概率。
  - `_preview_name_score` 改为路径感知：所在文件夹是 textures/maps/source/material 等会降权，是 preview/render/cover 等会加权；`_best_preview_path` 增加“路径越浅越优先”的次级排序（封面常在资源根）。
  - 新增端到端测试 `tests/test_preview_integration.py`：含贴图干扰时仍选中根层 cover/scene_render。
- CLI `recommend`：扫描路径→对每张卡片输出目标分类推荐（母路径/候选/新建建议），`--json` 可机读。端到端测试 `tests/test_cli_recommend.py`。
- 审阅队列联动：窗口启动创建 `ReviewQueue`（与既有 ResourceIndex 同样在启动建 SQLite，已 try/except 保护）；翻译写入建议、移动置 moved、上传成功置 done。全部走 `_queue_card` 守卫，失败静默不影响主流程。队列可用 `cli queue list` 查看（GUI 面板留待后续）。
- 新增 `docs/USER_GUIDE.md`：面向日常使用的中文操作指南。

验证：compileall 通过；单测 37 例全过；PySide6 桩导入 qt_app 通过（_queue_card 存在）。GUI 实际效果仍需 Windows 实跑。

## 2026-06-28 修复：漏读资源 + 翻译不生效排查 + 115 申请入口

- 漏读资源（如 10 MECHANICAL LEG）：根因是分析时间预算太小。科幻29 合集含大量分卷 rar/zip，扫描按 DFS 先处理大合集并逐个 7z 列目录，在旧 `max_seconds=120` 下容易中途超时 break，导致后续顶层资源（DFS 最后处理）被整包漏掉。
  - AnalyzeWorker 预算上调：max_seconds 120→900，max_files 5万→30万，max_depth 8→10，max_archives_to_inspect 16→40。
  - ScanConfig 默认 max_seconds 120→600。
  - 分析若提前停止，现在会弹**显著警告**（之前只在状态栏一行，易忽略）。
  - 回归测试 `tests/test_scan_no_drop.py`：用真实 `测试` 目录验证各 depth 下 MECHANICAL LEG / Basalt / 科幻29 都在（本机有目录才跑）。
- 翻译不生效排查：经核实 `deepseek-v4-flash/pro` 是**当前有效模型名**（deepseek-chat/reasoner 现为 legacy），模型名不是问题。沙箱无法直连 api.deepseek.com（代理 403），故做了防御性加固：
  - `request_structured_card_suggestion` 若带 `response_format` 报错，会自动去掉该参数重试一次（部分部署不支持）。
  - 一键翻译/单张翻译失败时弹**明确错误对话框**（含返回的首条错误），不再只在状态栏一闪而过，便于定位（Key/余额/模型/网络）。
  - 注意：翻译只改卡片显示名与建议，**从不重命名本地文件夹**（用户反馈“本地没中文”属预期）。
- 115：搜索确认开放平台入口 `https://open.115.com/`（需审核入驻），文档 `https://www.yuque.com/115yun/open`。设置面板 115 区已加一行提示。真实上传仍待凭证+授权+按文档实现 `_upload_file`。

验证：compileall 通过；单测 39 例全过；PySide6 桩导入 qt_app 通过。

## 2026-06-28 翻译后同步重命名本地文件夹

- 新增 `src\resource_workbench\renamer.py`：
  - `sanitize_filename`（去 Windows 非法字符、收尾空格/点、压缩空白、限长 150）。
  - `rename_folder` 冲突安全（不覆盖，自动加 (2)(3)）、写 `RenameLog`（SQLite）。
  - `undo_rename` 可撤销；`RenameLog` 记录 old/new/status。
  - 单测 `tests/test_renamer.py`（净化/改名/撤销/冲突/跳过，11 例）。
- GUI 接入：
  - 设置「行为」新增开关：翻译后同步重命名本地文件夹（默认开）。
  - 单张翻译：应用译名后按开关重命名源文件夹，更新 card.source_path / display_name，状态栏提示新名。
  - 一键翻译：开关开启时先确认，再逐张翻译+改名，结尾汇总“已重命名 N 个”。
  - 重命名经 `default_rename_log_path` 记录，可后续做撤销入口。
- 说明：之前“翻译只建议不改名”的设计按用户要求改为“可同步改名”，但保留安全（冲突安全+日志+撤销）。改 Z 盘资源名会触发 NAS 同步，属预期。

验证：compileall 通过；单测 48 例全过；PySide6 桩导入 qt_app 通过（_maybe_rename_card_folder 存在）。

## 2026-06-28 关键修复：扫描过度拆分 + 移除115

### 扫描过度拆分（严重，已修）
- 现象：分析 `测试` 出现 `fbx and blend / marmoset / obj&textures` 这类无预览的怪卡片，且真资源卡“消失”。
- 根因：这些是**单个模型压缩包内部的格式/工程子文件夹**（磁盘上看不到，在 .rar/.zip 里）。`scanner._candidate_roots_from_parts` 在“第一层目录占主导 + 第二层≥3 个有意义子目录”时会按第二层拆分；单模型按 fbx/marmoset/obj 分目录正好命中，于是被拆成 3 张格式卡，并 `continue` 跳过了真资源卡 → 既冒怪卡又丢真卡。最近把 `max_archives_to_inspect` 16→40、`max_seconds`→900 让更多压缩包被读取，放大了该问题。
- 修复：`scanner._is_meaningful_segment` 现在排除“格式/工程/通道”文件夹（`_is_format_folder`：fbx/blend/blender/obj/max/c4d/maya/marmoset/unreal/unity/textures/maps/source/substance/zbrush/render/lowpoly/usd/... + 连接词，且含中文的名字一律视为真实资源名）。这样单模型不再按格式拆分（候选根只剩模型名→不触发≥3 拆分→保留整张资源卡），而**真合集仍按真实资源名拆**。
- 测试：`tests/test_scan_split.py`（格式文件夹识别、单模型不拆、真合集仍拆）；并保留 `tests/test_scan_no_drop.py` 防漏读回归。
- 局限：沙箱无 7-Zip，无法跑“读压缩包内容”的端到端；已用候选根纯逻辑单测覆盖修复点。Windows 上有 7-Zip，请实测确认怪卡消失、真卡回归。

### 移除 115（按用户要求暂时去除）
- 设置面板 115 区、卡片右键“上传 115”、移动后自动上传触发、upload_card 方法、相关导入全部从 UI 移除；详情/Agent 文案不再提 115。
- `uploader_115.py` 文件保留（休眠、不被引用），以后要恢复很容易。settings 里 115 字段保留但不再使用。

验证：compileall 通过；单测 52 例全过；PySide6 桩导入 qt_app 通过；qt_app 内已无 115 UI 引用。

## 2026-06-28 关键修复（根因）：扫描“遍历优先、压缩包预览第二阶段”

- 现象：用户机上分析 `测试` 仍漏掉 `10 MECHANICAL LEG...`（即使上一轮把时间预算提到 900s）。
- 真正根因：旧逻辑在**目录遍历过程中内联调用 7-Zip 解析压缩包目录**。`科幻29` 含 30+ 个分卷 rar/zip 且体积大，按 DFS 先被处理；逐个 7z 列目录很慢，一旦累计耗时触发遍历层的超时/取消，`while` 直接 break，**栈里还没遍历的资源（如最后处理的 MECHANICAL LEG）整包被丢**。沙箱无 7-Zip，所以本地复现不出来（这也是之前判断为“已在 depth=3 正常”的盲区）。
- 修复（结构性）：`scanner.scan_input` 改为两阶段——
  1. 先完整遍历所有目录/文件，生成全部资源分组（快，不调用 7z）；
  2. 遍历完成后，统一对登记的压缩包做“尽力而为”的目录预览（`_inspect_pending_archives`），超时只停预览、**绝不影响已生成的资源卡**。
  这样任何资源都不会因为“压缩包解析太慢/超时”而被漏。
- 回归测试：`tests/test_scan_no_drop.py` 增加 `test_no_drop_with_archive_inspection`（开启压缩包检查后三大资源仍在）。

验证：compileall 通过；单测 53 例全过。请在 Windows（有 7-Zip、真实大文件）上重扫 `测试` 确认 MECHANICAL LEG 不再漏。若仍异常，请把窗口顶部“发现 X 文件 / 生成 Y 卡片 / 预览压缩包 Z 个”那行、以及是否弹出“分析未完成”警告告诉我，可据此进一步定位。

## 2026-06-28 根因定位（用报告复盘）+ 安全网：杜绝整包漏资源

- 用 `reports/` 里用户真实运行的 JSON 复盘（input_path=F:\gpt codex huancun\...\测试，写入本仓库 reports，证明用户跑的就是本副本）：该次 `stopped_early=False`、3 秒完成、`inspected_archives=40`，共 37 卡、**MECHANICAL LEG 整包为 0 卡**。说明既不是超时也不是层级问题。
- 真实结构（从历史报告 archive_previews 复原）：`10 MECHANICAL LEG.../file.jpg` + `Mechanical-Leg-01.rar`（archive 内含 `Sci_Fi Robot Leg/01..10/`）。我的副本里该资源是“已解压”的 51 个文件，所以本地一直复现不出丢失——这是关键盲区。
- 处理：与其继续盲猜那条把 MECH 拆没的精确边界，新增**结构性安全网** `classifier._ensure_top_level_coverage`：
  - 统计扫描根下每个“顶层资源文件夹”是否至少产出 1 张卡；
  - 任何顶层资源若 0 卡（被包装层跳过/拆分异常/任何边界），自动用其聚合内容兜底生成一张卡（标 `recovered_card`、需人工确认），命名用顶层文件夹名。
  - 正常已出卡的资源不受影响（covered_tops 去重，无重复卡）。
- 这是“整包资源不再被静默丢掉”的硬保证，独立于具体触发原因。
- 测试：`tests/test_safety_net.py`（模拟 MECH 全丢→被恢复为 model 卡；正常组不产生重复）。
- 修复期间文件写盘多次被截断，classifier.py 末尾曾丢失，已用直接写盘重建并校验。

验证：compileall 通过；单测 55 例全过；PySide6 桩导入 qt_app 通过。请在 Windows 重扫 `测试` 确认 MECHANICAL LEG 回归（即使是兜底卡，也会显示该资源、可打开/改目标/移动）。
