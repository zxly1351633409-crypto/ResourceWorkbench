# 资源入库工作台 · 交接与后续任务（2026-07-11）

## 0. 当前接手基线：v0.3.1

v0.3.1 在 v0.3.0 的 UI、扫描、分类和分发隔离基础上，补齐移动安全、慢 NAS 树、SpeedTree 预览与运行数据保留。接手者不要回退：

- v0.2.3 的深层分类增强此前只在源码中，用户运行的仍是 v0.2.2；v0.3.0 首次把该能力和深层资源库修复打入正式包，v0.3.1 继续修复其安全与后台生命周期。
- 真实 19 文件夹批次：19/19 张都有现存深层首选，分别落到 `F 废土\建筑/场景/物件/载具`，车辆继续到 `C 车`。
- 资源库叶目录会索引直系文件：真实 NAS 视频目录 23/23 张均为视频卡且有预览源；图片目录去除 `Thumbs.db` 后为 43/43 张可预览图片卡。
- 图片缩放和 ffmpeg 抽帧移入限并发后台池；缓存键包含 mtime/size，同路径替换不会复用旧图。
- 左侧资源库增加“新建文件夹 / 刷新”，文件监听 + 后台 direct-child signature 轮询同步当前和已展开目录。
- 顶部不再显示版本；左下角仅显示小号 `v0.3.1`。Qt 中文翻译已加载，设置/颜色标准按钮中文；语义配色窗口有分组、预设、单项恢复和实时预览。
- 冻结 EXE 无显式环境变量时使用 `%LOCALAPPDATA%\ResourceWorkbench\Profiles\Public\Stable`；仓库正式启动器保留个人 profile，干净预览每次使用随机临时 profile。
- 分发 ZIP 安全门检查运行数据、本机路径、UNC 和凭证形态，且不在失败输出中回显真实凭证。

- `qt_app.py`：统一路径/URL 输入；移除 editingFinished 自动分析；分析/取消独立；worker progress；卡片区流光文字、进度条、取消；右下角小状态条；顶部移除文件夹/压缩包、层级、搜索；左侧资源库 box；语义主题入口。
- `qt_app.py` 安全补丁：移除卡片“解压后深度分析”的误导入口和 `if False` 死分支；现在明确为“分析压缩包外层（当前不解压）”，普通/重新分析即使收到旧参数也不会自动解压。
- 移动安全补丁：单卡、批量和审阅队列在执行前均显示逐项“来源 → 目标”及文件数/容量；正式移动必须再输入大写 `MOVE`，取消或输错不触碰来源；测试模式只需普通确认。
- 资源树补丁：根/展开/刷新均使用后台 QRunnable；400 项分页、继续加载、失败重试、generation/request/offset 防旧结果覆盖，关闭应用时安全 drain，修复 Qt 退出 fast-fail。
- SpeedTree：优先使用同目录真实 `preview.png` / `<工程名>_preview.png`，排除材质通道图；无图仅生成明确非渲染占位。历史 GUI 批处理脚本不会自动启动。
- `archive.py`：所有 7z/HaoZip subprocess 复用 Windows 无控制台参数。
- `scanner.py` / `classifier.py`：默认 `inspect_archives=False`、默认不拆 archive subresources、贴图/通道/格式目录折叠到所属外层资源。
- `web_resource.py`：ShotDeck/Superhive 先用 Chrome/Edge headless 截图；检测 Cloudflare/blocked DOM 后丢弃并生成风格化封面；不再只用 favicon。
- `settings.py` / `fluent_skin.py`：窗口、侧栏、卡片、输入框、正文/弱文字、边框、图标、hover/selected 等语义颜色可独立设置。
- `move_log.py` / `target_recommender.py`：成功并校验通过的移动记录结构化特征，目标选择器显示“习惯推荐 ×次数”；记录自动按条数/天数修剪。
- `maintenance.py` / `runtime_maintenance.py`：后台预演/清理预览、报告、完整非活动 staging、资源索引及明确终态历史；活动任务、可撤销记录和人工元数据受保护。
- 三个启动器：开发、正式、干净分发预览数据完全隔离。
- `tools/build_windows_app.ps1`：通过 `tools/windows_version_info.txt` 写入 v0.3.1 Windows 文件属性；压缩后重新打开 ZIP 检查本机设置/API/缓存/索引/路径泄漏并生成 v0.3.1 zip。
- `scanner.py` / `classifier.py`：扫描开始固定首层目录快照，建卡后执行目录级硬校验；空目录或暂时不可读目录也生成待确认兜底卡，不再静默少卡。
- `qt_app.py` / `report.py`：版本只在左下角弱显示；分析摘要与报告明确显示“首层资源文件夹 / 卡片覆盖 / 缺失目录”。
- v0.2.2 修正文案歧义：完成状态同时显示“总卡片数 / 需确认数 / 本次入队数”，不再把“18 张需确认”误看成“只生成 18 张”。
- v0.2.3 深层归类：标题、批次语境、普通文件样例、真实目录树和已确认移动历史共同生成二至四级现有分类候选；`.blend1/.blend2` 按 Blender 工程识别。

### 脱敏验收证据

- 19 文件夹真实回归样本（具体路径仅保留在本机测试记录）：19 个外层目录 → 19 张卡；扫描约 0.407 秒；压缩包内部读取 0；没有提前停止。
- ShotDeck `browse/stills` 和 Superhive 示例产品：真实联网测试均生成非 favicon 封面；Cloudflare/blocked screenshot 会被识别并替换为风格化封面。
- v0.3.1 最终源码与公开暂存区均完成 205 项测试：202 通过、3 跳过、退出码 0；`compileall` 同步通过。
- 最新真实样本回归：Z 盘 19 个首层目录 → 19 张卡、缺失 0、压缩包内部读取 0、约 1.42 秒；NAS 视频叶目录 23/23 张均识别为视频且可抽帧，图片叶目录 43/43 张均有图片预览源；两条 SpeedTree 样本分别命中 `<stem>_preview.png` 与根层 `preview.png`，没有写入源目录或拉起 GUI。
- v0.3.1 正式构建通过 ZIP 安全门、独立复审和随机临时 profile 启动烟测；EXE 7,527,452 bytes，SHA256 `016683747A1DC67207EEA7BAF409D85C35E6C798B4E537FFADB2E477CCA790BF`；ZIP 270,303,183 bytes，SHA256 `CA93A543EA9771D1C6EC041F607222DF1F3801D27584A935392A80C680D495C1`。Windows FileVersion / ProductVersion 均为 `0.3.1`。
- 补 Windows VersionInfo 前的 v0.3.0 构建基线：ZIP 安全审计通过；EXE SHA256 `0BF8955D845230495F6CE853EAAFAC577F949272ED34A00E7E4DE7DFDE5AF152`，ZIP SHA256 `FB5E1AFE16A5675756B72D9087A8F96AE38F8A38D33351641F31761506863666`。这两个旧产物没有 Windows 文件属性版本；重新构建后哈希必然变化，不得作为最终发布哈希。
- 上一个 v0.3.0 构建（含 Windows VersionInfo）已通过 ZIP 安全审计和独立临时 profile 启动：EXE 7,473,128 bytes，SHA256 `48AFDD72E63622079A179A816734870CA04BDD2D98625F6A74C88F8C3E662F3C`；ZIP 270,247,603 bytes，SHA256 `FB0E6FBD7B5279B094C0EF96A94C9DC088C86E21965308F01D1914FB00C9E724`。这只是历史回滚证据，不能作为 v0.3.1 发布哈希。
- v0.2.2 正式 EXE 隔离实跑真实 Z 盘路径：首层 19 / 覆盖 19 / 卡片 19 / 缺失 0；EXE SHA256 `348806C350C7BB9571B3C7611AA23D6B4D279858CE01644F354E07B4E82155A8`，ZIP SHA256 `3449470C2C9B3F52B95819EE4A3D596A5518ECB99508C902257982CBC0A13DE6`。
- Windows Graphics Capture 在本机返回 `0x80004002`，因此自动化视觉验收使用 Qt offscreen；用户仍应在正常 Windows 显示环境目测一轮字体和高 DPI。
- GitHub 已公开发布：`https://github.com/zxly1351633409-crypto/ResourceWorkbench`。v0.3.1 Release 附件摘要与本机构建一致；公开 `main` 在 `d813714bd12b1c920300f7b2223321d43e179c36` 修复 GitHub Windows Runner 的 8.3 短路径测试断言，Actions `tests` 已通过。

### 下一步（不要与已完成项混淆）

1. 请用户在正常桌面运行 `启动-正式工作台.bat`，反馈按钮/字体/高 DPI 的主观视觉；只做细节收口，不恢复已删除顶部控件。
2. 用更多真实“外层多资源 + 内部压缩包”样例继续锁扫描边界。
3. 若要开放“深度读取压缩包”，必须另建独立、默认关闭的高级流程，并单独测试性能/取消；不要把旧的 `auto_extract_archives` 参数或 staging 代码重新接回普通/卡片分析。
4. 继续完善多模态识别和 115 官方上传；不能把文本模型建议当自动移动授权。

## 历史交接记录（2026-06-29，保留供追溯）

这份文档给“接手的新 session / 新 task”用：先读这份，再按需翻 `PROJECT_STATUS_HANDOFF.md`（历史细节）与 `USER_GUIDE.md`（使用说明）。

## 一、当前状态（已验证可用）

核心流程已跑通，用户确认“目前是正确的了”：

- 扫描：指定路径 → 资源卡片墙（Pinterest 式）。深度自动推断，大合集按真实资源名拆分。
- 预览：路径感知评分，封面/渲染图优先，避开贴图通道（normal/roughness/basecolor…）。
- 翻译：DeepSeek 结构化输出（译名/目标分类/置信度/需确认原因），支持单张与“一键翻译全部”（带进度、失败有明确弹窗）。
- 翻译后可同步重命名本地文件夹（净化+冲突安全+重命名日志，可撤销；设置里可关）。
- 目标分类：Pinterest 式选择器（推荐近似分类、可搜索/点进去、母路径面包屑）。
- 移动：测试移动默认可用；正式 Z 盘移动已接入但默认关闭，需设置允许来源、先预演、二次输入 `MOVE`，并写入可回滚 move log。
- 安全网：扫描根下每个“顶层资源文件夹”保证至少 1 张卡，**整包资源不会再被静默丢掉**（`classifier._ensure_top_level_coverage`，兜底卡标 `recovered_card`）。
- 审阅队列 GUI 面板、历史/撤销面板、查重/空目录清理 GUI、批量整理、卡片标签/备注、概览看板均已接入。
- 115 上传已按用户要求**移除 UI 入口**（`uploader_115.py` 仍在但休眠、不被引用）。

## 二、环境坑（务必先知道，避免重蹈覆辙）

1. **历史上有多个项目副本**：改完务必确认用户实际启动的副本已同步，不要在公开交接文档记录开发机绝对路径。
2. **GUI/压缩包/网络要分层验证**：
   - GUI 改动先用 PySide6 offscreen 测试和 compileall，自然视觉效果仍需用户在 Windows 实跑。
   - 压缩包相关逻辑优先用本机 7-Zip + reports 复盘，再加单测锁住边界。
   - **优先读 `reports/*.json` 复盘用户真实运行**，不要靠本地副本猜（MECHANICAL LEG 漏读就是因为本地副本是解压版、结构不同，盲猜了好几轮）。
3. **写盘偶发截断**：用 Edit/Write 大块写入 src 时多次出现“掉行/截断”。对策：改动后立刻 `python -c "import ast; ast.parse(...)"` 校验；大改用 `cat > 文件 <<'EOF'` 直接写盘并校验行数；必要时 head + 追加重建。
4. 真实 DeepSeek 模型名 `deepseek-v4-flash` / `deepseek-v4-pro` 是**当前有效**的（`deepseek-chat/reasoner` 已是 legacy）。

## 三、最近这轮修复（按时间）

- 预览选择 v2：采样上限 12→40 + 路径感知评分。
- 一键翻译、移动/上传进度弹窗、悬浮按钮彩色化、卡片加大。
- 翻译后同步重命名本地文件夹（renamer.py，可撤销）。
- 扫描过度拆分修复：格式/工程子文件夹（fbx/blend/marmoset/obj&textures/textures/source…）不再各自成卡。
- 扫描“遍历优先、压缩包预览第二阶段”：避免压缩包解析超时拖累遍历。
- **整包漏资源根因定位 + 安全网兜底**（本轮关键）。
- 移除 115 UI。

测试：`tests/` 共 81 例全过（`python -m unittest discover -s tests`）。

## 四、后续任务（建议优先级）

1. **真实端到端验收（Windows）**：逐项确认 Fluent 皮肤、预览、翻译、重命名、测试移动、正式移动 dry-run、撤销。
2. **正式 Z 盘移动小批量实跑**：先只选 1-2 个测试资源，确认落点、move log、撤销、空目录链路清理。
3. **拆分边界继续打磨**：等用户提供错分样本；当前真实测试目录 38 张卡、0 兜底恢复。
4. **115 上传（待用户给 AppID/AppSecret）**：在 `uploader_115.py` 补 OAuth/token 获取 + `_upload_file`（建目录→取直传凭证→sha1 秒传/分片），并加限速/分批/退避以规避绿联 NAS 同步那类风控。
5. **性能**：资源库索引后台线程/手动刷新；超大库分批扫描。

## 五、新 session 快速上手

```
# 跑测试
cd ResourceWorkbench && python -m unittest discover -s tests
# 只读分析 / 推荐 / 队列（CLI）
python -m resource_workbench.cli analyze "路径" --enqueue
python -m resource_workbench.cli recommend "路径" --z-root "D:\ResourceLibrary"
python -m resource_workbench.cli queue list
# 复盘用户真实运行：直接读最新报告
ls -t reports/resource_scan_*.json | head -1
```

启动正式窗口（用户侧 Windows）：`启动-正式工作台.bat` / `启动-正式演示测试目录.bat`。

安全底线（不要打破）：不自动解压；正式 Z 盘移动默认关闭，必须允许来源 + 预演 + `MOVE` 二次确认；翻译/分类是建议需确认；删除只限空目录；115 真实上传仍未开放。
