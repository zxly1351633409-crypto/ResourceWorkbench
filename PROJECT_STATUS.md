# ResourceWorkbench v0.3.5 — 项目进度

## 架构

```
ResourceWorkbench/                      ← 主项目（后端 + 前端）
├── src/resource_workbench/
│   ├── electron_server/               ← HTTP API 层
│   │   ├── application_service.py     ← 业务编排（对接原版所有模块）
│   │   ├── card_store.py              ← 稳定 card_id 卡片存储
│   │   ├── task_manager.py            ← 后台任务生命周期
│   │   └── server.py                  ← HTTP Server
│   ├── classifier.py                  ← 卡片分类器
│   ├── scanner.py                     ← 文件扫描器
│   ├── taxonomy.py                    ← 目标路径分类规则
│   ├── deepseek.py                    ← AI 翻译接口
│   ├── mover.py                       ← 文件移动（含撤销）
│   ├── move_log.py                    ← 移动日志（SQLite）
│   ├── indexer.py                     ← 资源库索引
│   ├── preview.py                     ← 缩略图生成
│   ├── web_resource.py                ← 网页→卡片
│   ├── settings.py                    ← 设置管理
│   └── ...（33个核心模块）
├── frontend/                          ← DeepSeek Hana 前端
│   ├── index.html
│   ├── css/hana.css                   ← Hana 暖白设计系统
│   └── js/
│       ├── app.js                     ← 主控制器（双面板）
│       ├── api.js                     ← API 客户端
│       └── components/
│           ├── card.js                ← 卡片组件（Pinterest 瀑布流）
│           ├── card-wall.js           ← 瀑布流布局引擎
│           ├── sidebar.js             ← 资源库侧栏（含右键菜单）
│           ├── settings.js            ← 设置面板
│           ├── target-picker.js       ← 目标分类选择器
│           └── detail-panel.js        ← 详情抽屉
├── workbench_data/                    ← 运行时数据
└── server_launcher.py                 ← 启动入口

ResourceWorkbench-Electron/            ← Electron 壳
├── main.js                            ← 启动 Python 后端 → 加载前端
├── preload.js
└── package.json
```

## 已完成功能

### 分析扫描
- 本地目录 / 压缩包扫描（max 300000 文件，深度 10 层）
- 网页链接自动识别 → 生成网页卡片（截图、标题、域名标签）
- AI 翻译命名 + 目标路径推荐（DeepSeek）
- 移动历史注入推荐（apply_history_target_suggestions）
- 扫描进度条 + 分类诊断信息

### 资源库浏览
- 左侧目录树懒加载 + 预加载子级
- SQLite 索引缓存（二次打开秒加载）
- 文件夹类型推断（M 模型 → model，Z 照片 → photo）
- 前 3 层预生成缩略图

### 卡片操作
- Pinterest 瀑布流布局（自适应高度）
- 悬浮按钮：翻译、移动、打开文件夹、修改目标分类
- 右键菜单：打开/复制路径/修改分类/标记确认/重新分析/整理/AI翻译/移动
- 多选模式：全选/清空/翻译选中/整理选中/移动选中
- 目标分类选择器（文件夹浏览器，含推荐和历史）

### 移动入库
- plan_move 预演 → execute_formal_move 执行
- MoveLog 记录（可撤销）
- 移动后卡片自动移除
- 翻译后自动重命名本地文件夹

### 设置
- 资源库路径 / API Key / 模型选择 / 翻译格式
- 主题配色（6 色自定义 + 预设主题）
- 翻译/移动按钮颜色自定义
- 字号调节（12-20px）
- API Key 安全存储（secret.json，不返回前端）

### 历史记录
- 移动记录（含撤销按钮）
- 重命名记录
- 操作历史面板

### 工具
- 查重（按文件名+大小）
- 空目录清理
- 侧栏新建文件夹 / 刷新
- 网页变卡片

## 待优化方向

- [ ] PyInstaller 打包为独立 EXE（不依赖 Python）
- [ ] 侧栏展开状态持久化
- [ ] 批量移动进度优化
- [ ] 右键菜单项补齐（备注/标签编辑）
- [ ] 概览面板（卡片统计、容量统计）
- [ ] 审阅队列面板
- [ ] 撤销后卡片恢复显示
- [ ] 深色主题
- [ ] 快捷键支持
