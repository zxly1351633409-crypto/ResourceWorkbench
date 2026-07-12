# ResourceWorkbench 资源入库工作台

把"扫描待整理资源 → 生成 Pinterest 式卡片 → 翻译/审阅 → 推荐分类 → 移动入库"集中在一个桌面工作台中。

**v0.3.5 Hana Edition** — 全新 Electron + Hana 前端，双面板独立架构。

## 架构

```
ResourceWorkbench/
├── src/resource_workbench/
│   ├── electron_server/          ← HTTP API 层（CardStore / TaskManager / ApplicationService）
│   ├── classifier.py             ← 卡片分类器
│   ├── scanner.py                ← 文件扫描器（max 300000 文件）
│   ├── taxonomy.py               ← 目标路径分类规则（4 级深度匹配）
│   ├── deepseek.py               ← AI 翻译接口
│   ├── mover.py                  ← plan_move + execute_formal_move
│   └── ...（33 个核心模块）
├── frontend/                     ← Hana 暖白设计系统
│   └── js/components/
│       ├── card-wall.js          ← Pinterest 瀑布流布局
│       ├── card.js               ← 卡片组件（悬浮按钮 + 右键菜单）
│       ├── sidebar.js            ← 资源库侧栏（预加载 + 右键菜单）
│       ├── target-picker.js      ← 文件夹式目标分类选择器
│       └── settings.js           ← Hana 风格设置面板
└── server_launcher.py            ← 启动入口

ResourceWorkbench-Electron/       ← Electron 壳（frameless 窗口）
```

## v0.3.5 更新

- **双面板独立架构**：资源库和待整理各自独立，切换不丢失状态
- **Pinterest 瀑布流**：卡片高度随图片比例自适应，错落有致
- **完整分析管线**：扫描 → 分类 → 历史推荐 → 目标路径，匹配原版逻辑
- **网页变卡片**：粘贴网址自动识别，生成截图 + 标题 + 域名标签
- **AI 翻译 + 重命名**：DeepSeek 翻译命名并自动重命名本地文件夹
- **文件夹式目标选择器**：含推荐分类、历史匹配、搜索和目录浏览
- **正式移动入库**：plan_move 预演 → execute_formal_move 执行，MoveLog 可撤销
- **Hana 风格设置**：6 色主题自定义 + 翻译/移动按钮颜色 + 字号调节
- **API Key 安全存储**：secret.json 分离存储，永不返回前端
- **侧栏预加载**：一级目录后台拉取子级，展开零等待

## 启动

```bat
cd ResourceWorkbench-Electron
双击 启动-Electron.bat
```

首次需 `npm install`（约 2 分钟）。需要 Python 3.10+ 及依赖（`pip install -r requirements.txt`）。

## 待开发

- [ ] PyInstaller 打包为独立 EXE（无需 Python）
- [ ] 深色主题
- [ ] 审阅队列面板
- [ ] 快捷键支持
