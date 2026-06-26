# ResourceWorkbench 资源入库工作台

这是“资源整理一体化工具”的第一版开发原型。

当前阶段只做三件事：

1. 扫描你手动指定的一个文件夹或压缩包。
2. 按资源文件夹生成临时卡片建议。
3. 只读预览压缩包目录，用于提前判断资源类型。
4. 输出一份 Markdown/JSON 报告，方便我们判断规则是否靠谱。

当前阶段明确不做：

- 不移动资源。
- 不删除压缩包。
- 不上传 115。
- 不改名、不翻译。
- 不递归扫描整个 `Z:\整合——资源管理`。
- 不解压压缩包；当前只列压缩包目录。

## 推荐用户流程

第一轮测试时，你只需要给一个小批次路径，例如：

```powershell
python -m resource_workbench.cli analyze "Z:\待整理\某个测试文件夹"
```

如果还没有安装为开发包，也可以在项目目录运行：

```powershell
$env:PYTHONPATH="F:\gpt codex huancun\资源管理工具开发\ResourceWorkbench\src"
python -m resource_workbench.cli analyze "Z:\待整理\某个测试文件夹"
```

报告会生成在：

```text
F:\gpt codex huancun\资源管理工具开发\ResourceWorkbench\reports
```

## 设计原则

- 用户指定范围，软件不主动大规模扫描。
- “整理批次”和“资源卡片”分开处理，一个批次可以拆成多张卡片。
- 压缩包先分为运输压缩包、资源内容压缩包、分卷压缩包和未知压缩包。
- 不确定就标记为需要人工确认，不擅自移动。
- 先建立可靠的只读判断，再逐步加入翻译、整理、移动、115 上传。
