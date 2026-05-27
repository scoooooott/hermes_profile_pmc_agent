---
name: pmc-delivery
description: PMC 场景统一交付基础设施 — 共享 Python 模块、输出目录、渠道检测、PDF/Excel 渲染、定时清理。所有 PMC 场景 Skill 在生成报告/导出数据时走此模块，避免各场景自行处理输出逻辑。
---

# PMC 统一交付基础设施

所有 PMC 业务场景的交付输出共享同一套基础设施：

- **共享模块** `pmc_delivery.py` — 渠道检测、PDF 渲染、Excel 格式化、路径管理
- **输出目录** `/tmp/hermes-pmc-output/{pdf,excel,html}/`
- **定时清理** — launchd 每天 3:00 AM 清理旧文件

## 何时使用

- 任何 PMC 场景需要输出报告（PDF、Excel、Markdown 文本）
- 需要在飞书/Telegram/终端之间自适应切换交付方式
- 需要一致的 Excel 格式（深灰表头、冻结首行、条件着色）
- 需要 HTML → Playwright PDF 渲染

## 目录结构

```
/tmp/hermes-pmc-output/
├── pdf/       # PDF 报告（Playwright 生成）
├── excel/     # Excel 明细（openpyxl 生成）
├── html/      # 中间 HTML（1 天后自动清理）
└── cleanup.log
```

## 共享模块

**路径**: `~/workspace/pmc-agents/scripts/pmc_delivery.py`

### 导入

```python
from pmc_delivery import (
    detect_channel, should_use_attachments,
    render_html_to_pdf, render_dataframe_to_excel,
    get_output_path, OUTPUT_BASE,
)
```

或者从任意子目录添加 sys.path：

```python
import sys; sys.path.insert(0, os.path.expanduser("~/workspace/pmc-agents/scripts"))
from pmc_delivery import ...
```

### API 参考

| 函数 | 签名 | 说明 |
|---|---|---|
| `detect_channel()` | → `'feishu'`/`'telegram'`/`'terminal'`/`'unknown'` | 检查 `FEISHU_CHAT_ID`/`LARK_CHAT_ID`/`TELEGRAM_CHAT_ID` 环境变量 + TTY |
| `should_use_attachments(channel)` | → `bool` | 飞书/Telegram 返回 `True`（支持文件附件） |
| `render_html_to_pdf(html_content, output_name)` | → `str` (PDF 路径) | HTML → `/tmp/.../html/{name}.html` → Playwright → `/tmp/.../pdf/{name}.pdf` |
| `render_dataframe_to_excel(df, sheet_name, output_name, danger_column, danger_threshold, warning_threshold, wrap_columns)` | → `str` (xlsx 路径) | B-现代岩灰配色、冻结首行、条件着色、自动列宽、交错行 |
| `get_output_path(category, filename)` | → `Path` | `/tmp/hermes-pmc-output/{category}/{filename}` |
| `now_iso()` | → `str` | UTC ISO-8601 时间戳 |

### render_dataframe_to_excel 参数详解

```python
render_dataframe_to_excel(
    df,                    # pd.DataFrame — 要导出的数据
    sheet_name,            # str — Excel 工作表标签
    output_name,           # str — 文件名（不含扩展名）
    danger_column=None,    # str — 条件着色的目标列名
    danger_threshold=1.0,  # float — 低于此值标红（行背景 + 字体）
    warning_threshold=3.0, # float — 低于此值标橙（仅单元格）
    wrap_columns=None,     # list[str] — 需要自动换行的列（如商品名称）
)
```

自动格式化：
- 深灰表头 `#292524` + 白色加粗文字
- 冻结首行（`A2`）
- 交错行（偶数行 `#FAFAF9`）
- 薄边框（`#E7E5E4`）
- 数值列右对齐
- 列宽自适应（上限 40 字符）
- 条件着色（danger 列低于阈值整行高亮）

## 渠道自适应交付模式

### 标准流程

```python
from pmc_delivery import detect_channel, should_use_attachments

channel = detect_channel()

if should_use_attachments(channel):
    # 飞书/Telegram：生成 PDF + Excel 附件
    pdf_path = render_html_to_pdf(html_content, "scene01-report")
    xlsx_path = render_dataframe_to_excel(df, "销量缺口", "scene01-detail")

    # 发送时用 MEDIA: 语法
    summary = f"报告已生成：\n📄 MEDIA:{pdf_path}\n📊 MEDIA:{xlsx_path}"
else:
    # 终端/unknown：回退到 Markdown 表格
    summary = "=== 报告摘要 ===\n" + dataframe_to_markdown(df.head(20))
```

### 混合模式（Markdown 摘要 + 附件）

```python
if should_use_attachments(channel):
    xlsx_path = render_dataframe_to_excel(...)
    summary = f"[KPI 总览]\n- 总 SKU: {n}\n- 紧急: {n_crit}\n📊 MEDIA:{xlsx_path}"
```

## 定时清理

macOS 使用 **launchd**（无需 crontab），每天 3:00 AM 执行：

| 目录 | 保留天数 | 说明 |
|------|----------|------|
| `pdf/` | 7 天 | 最终产物，短期保留 |
| `excel/` | 7 天 | 最终产物，短期保留 |
| `html/` | 1 天 | 中间 HTML，快速清理 |

**Plist 路径**: `~/Library/LaunchAgents/com.pmc.output-cleanup.plist`

**脚本路径**: `~/workspace/pmc-agents/scripts/pmc_cleanup.sh`

## 依赖

- `playwright` (Chromium) — PDF 生成
- `openpyxl` — Excel 生成
- `pandas` — DataFrame 输入

```bash
pip install playwright openpyxl pandas
playwright install chromium
```

## 常见陷阱

1. **crontab 在 macOS 上挂死**：macOS `crontab -` 和 `crontab file` 可能因安全授权问题挂起。改用 launchd（`~/Library/LaunchAgents/*.plist`）+ `launchctl load`。
2. **Playwright 字体加载超时**：`waitUntil='networkidle'` 等不到 Google Fonts → 用系统字体 `"PingFang SC", "Hiragino Sans GB", "Microsoft YaHei"` + `waitUntil='domcontentloaded'`。
3. **Playwright `chromium` browser binary 丢失**：`playwright install chromium` 在 `uv run` 下会失败（cmd not found）。修复：`~/.hermes/hermes-agent/venv/bin/python -m playwright install chromium`。若仍报错找不到 binary，检查 `PLAYWRIGHT_BROWSERS_PATH` 是否指向了错误的缓存目录（`~/Library/Caches/ms-playwright`），保持默认即可。
3. **f-string 中的反斜杠**：`f"{'x' if c else 'y'}"` 会报 SyntaxError → 用变量承载条件表达式。
4. **PDF 与截图混用**：不要用 `page.screenshot(full_page=True)` 替代 PDF → 图片模糊、不可复制文本。始终用 Playwright `page.pdf()`。
5. **Excel sheet_name 超长**：Excel 限制 31 字符，`render_dataframe_to_excel` 自动截断但传入时尽量短。
6. **多场景并发写入同一目录**：各场景用独立 `output_name` 前缀（如 `scene01-`, `scene02-`）避免文件冲突。
7. **`dwd_params` 视图因非 JSON 的 `param_default` 崩溃**：`dwd_params` 是通过 `CAST(ods_params.param_default AS JSON)` 解析生成的视图。若 `ods_params` 中某行的 `param_default` 不是合法 JSON（如 P11 的 `sku_override` 缺少引号），所有查询 `dwd_params` 的场景（场景01~09）报错 `Malformed JSON`。修复：`UPDATE ods_params SET param_default = '"sku_override"' WHERE param_no = 'P11'`。遇到这类错误时优先排查 `ods_params.param_default` 中哪些值不是合法的 JSON 对象/数组。
