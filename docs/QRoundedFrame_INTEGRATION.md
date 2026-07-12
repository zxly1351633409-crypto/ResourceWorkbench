# QRoundedFrame 接入说明

QRoundedFrame 已导入：

```text
external\QRoundedFrame
```

## 当前状态

已确认 QRoundedFrame 是 C++ Qt Quick + QML 桌面壳。

它推荐的架构是：

```text
C++ / QML：窗口、导航、主题、托盘、卡片列表
Python worker：业务分析、扫描、解压、分类、翻译
SQLite / JSON：数据交换
```

这与本项目当前方向一致。

## 当前未直接编译的原因

当前电脑暂未检测到完整 C++/QML 构建工具：

- Qt 6.6+ / 推荐 Qt 6.11 MSVC 2022 64-bit
- Visual Studio 2022 Build Tools C++ 桌面开发工作负载
- CMake
- Ninja

因此当前先使用 PySide6 做正式视觉验证版。

## 迁移目标

后续 QRoundedFrame 版应包含：

- 左侧导航：入库工作台、正式资源库、上传队列、设置
- 顶部批次状态栏
- 中间虚拟化资源卡片列表
- 右侧预览与确认面板
- 页内弹窗：修改目标分类、翻译确认、移动确认

Python worker 继续保留：

```text
resource_workbench.scanner
resource_workbench.classifier
resource_workbench.taxonomy
resource_workbench.preview
resource_workbench.passwords
```

## 推荐迁移步骤

1. 不要直接改 QRoundedFrame 原仓库代码。
2. 复制或 fork 一个 `ui_qrounded` 工作目录。
3. 先做 QML 静态页面，还不接业务。
4. 将 Python 分析结果输出 JSON。
5. C++/QML 读取 JSON 或 SQLite，显示卡片。
6. 再做 worker IPC。

## 为什么当前 PySide6 版仍然有价值

PySide6 版验证的是：

- 信息布局
- 卡片字段
- 用户确认流程
- 分类候选展示
- 预览图显示
- 错误和需确认状态

这些都可以原样迁移到 QRoundedFrame/QML。

