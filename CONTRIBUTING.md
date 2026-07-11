# Contributing

欢迎提交 Issue 和 Pull Request。

## 开发环境

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[fluent,build]"
$env:PYTHONPATH = ".\src"
python -m unittest discover -s tests -v
python -m compileall -q src tests
```

## 提交要求

- 不提交 `workbench_data/`、`.runtime/`、缓存、日志、报告、API Key 或真实用户资源路径。
- 扫描器改动必须覆盖“首层目录不丢卡”和“默认不拆压缩包内部资源”。
- 移动、清理和重命名功能必须保留预检、边界检查和可验证结果。
- UI 改动请附干净示例截图，不得包含真实资源库路径或用户数据。
- 引入第三方源码、图标或素材前先确认许可证，并在 README 或 notices 中署名。
