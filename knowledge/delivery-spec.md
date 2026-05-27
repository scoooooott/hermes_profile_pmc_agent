# PMC 交付规范

## 输出目录
```
/tmp/hermes-pmc-output/
  pdf/   ← PDF 分析报告
  excel/ ← Excel 明细数据
  html/  ← HTML 中间文件（场景03交互式网页）
```

## 渠道自适应

| 渠道 | PDF | Excel | 文字摘要 |
|:---|:---:|:---:|:---|
| 飞书/Telegram | ✅ 附件 | ✅ 附件 | 3-5句文字 |
| 终端/TUI | 本地路径 | 本地路径 | Markdown 纯文本 |
| 场景03 交互式网页 | 不适用 | 不适用 | FRP 公网 URL |

## 交付流程

1. 场景 Skill 执行 SQL 查询，产出分析结果
2. 结果写入 Excel 明细（`/tmp/hermes-pmc-output/excel/`）
3. 分析报告渲染为 HTML（`/tmp/hermes-pmc-output/html/`）
4. HTML 转 PDF（`/tmp/hermes-pmc-output/pdf/`）
5. 根据渠道自动选择交付方式（附件/路径/URL）

## 清理机制

- macOS launchd 定时任务（`com.pmc.output-cleanup`）每天 03:00 执行
- 清理规则：PDF/Excel 保留 7 天，HTML 保留 1 天
- 清理脚本：`find /tmp/hermes-pmc-output/pdf/ -mtime +7 -delete`

## 共享交付模块

`scripts/pmc_delivery.py` 提供：
- `detect_channel()` — 自动检测当前渠道（飞书/Telegram/终端）
- `make_pdf(html_content, filename)` — HTML→PDF 转换
- `make_excel(data, filename, sheet_name)` — 数据→Excel 生成
- `get_output_path(subdir)` — 获取输出目录路径
- `now_iso()` — ISO 格式时间戳

## 注意事项

- 场景03 的 ECharts 交互式网页保持在线（FRP 公网 URL），不转 PDF
- PDF 渲染使用 Playwright/Chrome headless，需确保浏览器已安装
- Excel 使用 openpyxl 生成，需 `pip install openpyxl`
- 渠道检测依赖环境变量和运行时上下文，非固定值
