# Windows 打包与分发

更新时间：2026-07-11　适用版本：0.3.1

## 环境

- Python 3.11+（当前验证：Python 3.13）
- `pip install -e .[build]`
- PySide6、Pillow、imageio-ffmpeg 由项目依赖安装

## 构建

在项目根目录运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\build_windows_app.ps1
```

`ExecutionPolicy Bypass` 只作用于本次子进程，不修改系统执行策略。

产物：

```text
dist\ResourceWorkbench\ResourceWorkbench.exe
dist\ResourceWorkbench-0.3.1-win64.zip
```

EXE 使用 `--windowed --onedir`，分析时不会出现 Python 控制台。`tools/windows_version_info.txt` 会写入 Windows 文件属性：FileVersion/ProductVersion 为 `0.3.1`，产品名为 `ResourceWorkbench`，描述为“ResourceWorkbench 资源入库工作台”，贡献者标识为 `ResourceWorkbench Contributors`。复制到其他电脑时应复制整个 `ResourceWorkbench` 文件夹，或直接分发 zip。

## 分发安全门

构建脚本会在压缩后重新打开 ZIP，并检查、拒绝以下内容：

- `workbench_data`
- `reports`
- `settings.json`
- `secret.json`
- `move_log.sqlite`
- `resource_index.sqlite`
- 本机用户目录、UNC 私有路径和已配置的资源库绝对路径
- API Key、Bearer Token 等凭证形态（错误信息不会回显凭证内容）

因此开发机上的资源库路径、DeepSeek/115 凭证、预览缓存、索引、审阅记录和移动历史不会进入分发包。

打包程序第一次在另一台电脑运行时，运行数据默认创建在：

```text
%LOCALAPPDATA%\ResourceWorkbench\Profiles\Public\Stable\workbench_data
```

## 三种运行环境

| 入口 | 程序 | 数据目录 | 用途 |
|---|---|---|---|
| `启动-开发工作台.bat` | 当前源码 | `.runtime\development` | 开发/调试 |
| `启动-正式工作台.bat` | dist EXE，缺失时回退源码 | `%LOCALAPPDATA%\ResourceWorkbench` | 日常正式数据 |
| `启动-干净分发预览.bat` | dist EXE，缺失时回退源码 | `%TEMP%\ResourceWorkbench-CleanPreview-随机值` | 每次模拟首次打开 |

仓库内“正式工作台”继续使用个人正式 profile；直接双击公开分发 EXE 则使用独立 `Public\Stable` profile，所以同一电脑也不会读取开发者旧路径/API/缓存。干净预览每次新建随机临时 profile，不执行递归删除。

## 发布前验证

```powershell
python -m compileall -q src tests
python -m unittest discover -s tests -v
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\build_windows_app.ps1 -AuditArchive .\dist\ResourceWorkbench-0.3.1-win64.zip
(Get-Item .\dist\ResourceWorkbench\ResourceWorkbench.exe).VersionInfo |
    Select-Object FileVersion, ProductVersion, FileDescription, ProductName, CompanyName, OriginalFilename
```

文件属性必须显示 `FileVersion=0.3.1`、`ProductVersion=0.3.1`；每次重建后重新计算并记录 EXE/ZIP SHA256，不得沿用旧哈希。

然后：

1. 双击 `启动-干净分发预览.bat`。
2. 确认资源库、待整理、API Key 都为空。
3. 设置一个临时资源库路径，关闭并改用 `启动-正式工作台.bat`，确认正式环境不读取干净预览的数据。
4. 解压 zip 到另一目录运行 EXE，确认程序目录没有生成设置和缓存；它们应出现在 `%LOCALAPPDATA%`。

## 已知构建提示

PyInstaller 在收集 PySide6 QML 插件时可能输出某个可选 QML DLL 不存在的 warning。只要构建最终显示 `Build complete`、EXE 能启动且完整测试通过，该 warning 不影响本项目当前使用的 Qt Widgets / Qt WebEngine 功能。
