# SpeedTree 预览适配说明

ResourceWorkbench 0.3.x 对 SpeedTree 资源采用“只读、可解释、失败安全”的预览策略。支持 `.spm` 工程文件和经保守二进制判定的 `.srt` 运行时文件；普通 SubRip 字幕 `.srt` 不会被误认为 SpeedTree 资源。

## 实际预览顺序

1. 优先复用工程同目录已有的 `preview.png`、`<工程名>_preview.png`、`render`、`screenshot`、`cover`、`thumbnail` 等明确命名的图片。
2. `normal`、`AO`、`roughness`、`gloss`、`opacity`、`Bark/Clusters` 贴图不会因为尺寸较大就冒充模型预览。
3. 管理员可显式配置一个真正无界面的外部生成器。工作台把输入文件以只读参数传入，并只允许生成器把结果写到工作台缓存目录。
4. 没有真实渲染时生成绿色的 SpeedTree 类型封面，并明确写出 `PLACEHOLDER / NOT A MODEL RENDER`。封面仅表达文件类型，不伪造树模型外观。

所有自动生成内容都位于工作台预览缓存中，源工程目录不会新增或覆盖文件。缓存键包含工程路径、文件大小、修改时间和适配器版本；工程变化后会生成新缓存，旧缓存沿用工作台统一的容量/保留期清理策略。

## 为什么不内嵌 `speedtree_preview_batch.py`

历史批处理脚本没有独立许可声明，且包含以下不适合桌面工作台后台任务的行为：

- 依赖本机已授权的 SpeedTree Modeler、Pillow 和 pywin32；
- 写死本机程序、资源、缓存和日志路径；
- 使用 `subst` 创建/删除临时盘符；
- 启动 SpeedTree 图形界面、最大化并抢占前台；
- 自动向弹窗发送 Enter 键；
- 通过桌面截屏裁切预览，要求可见且无遮挡的交互桌面；
- 默认把 `preview.png` 写回用户资源目录，并在 CSV 中记录真实资源路径。

因此该脚本不会被复制进源码或分发包，工作台也绝不会自动调用它。若以后接入 SpeedTree 官方提供且许可允许分发的无界面渲染接口，应单独完成许可审核并实现新的生成器。

SpeedTree 官方文档说明 `.spm` 是 Modeler 的可编辑模型、`.srt` 是 Compiler 生成的二进制运行时模型：

- <https://docs.speedtree.com/doku.php?id=compiler_testing>
- <https://docs.speedtree.com/doku.php?id=proxies>

## 可选外部无界面生成协议

环境变量 `RESOURCE_WORKBENCH_SPEEDTREE_PREVIEW_COMMAND` 必须是 JSON 字符串数组，而不是 shell 命令文本。首项必须是已存在的绝对可执行文件路径，参数中必须各包含一次或多次 `{input}` 与 `{output}`：

```json
["C:\\Tools\\SpeedTreeHeadlessPreview.exe", "--input", "{input}", "--output", "{output}"]
```

协议约束：

- 必须是无界面、无需键鼠、无需弹窗确认的生成器；
- `{input}` 是 `.spm`/`.srt` 的原始只读路径；
- `{output}` 是工作台控制的临时 PNG 路径；
- 不经过 shell，子进程隐藏控制台窗口，标准输入关闭；
- 默认 45 秒超时，代码层上限 300 秒；
- 仅接受可由 Pillow 校验、边长 32–30000 像素且不超过 100 MB 的输出；
- 失败、超时、输出损坏时直接回退到明确标注的类型封面。

仅设置环境变量不代表第三方生成器安全或具备可分发许可；部署者仍需自行审核该可执行文件。ResourceWorkbench 分发包不携带 SpeedTree、历史批处理脚本或任何 SpeedTree 专有组件。

## 验证范围

自动化测试覆盖：同目录预览复用、同名工程精确匹配、贴图排除、字幕 `.srt` 排除、二进制 `.srt` 识别、占位封面只写缓存、外部命令 JSON 校验/隐藏非 shell 调用/超时参数与结果缓存。
