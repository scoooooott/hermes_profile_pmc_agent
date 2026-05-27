# pmc_delivery.py 已知问题

## 语法错误：`detect_channel()` docstring 未闭合

**文件**：`~/workspace/pmc-agents/scripts/pmc_delivery.py`
**行号**：99-127

### 问题

`detect_channel()` 函数的 docstring（L100 的 `"""`）包含 `Returns` 段落后直接跟了代码，
缺少闭合的 `"""`。Python 解析器将 L113 开始的 `# Check for feishu` 及后续代码均视为
docstring 的一部分，导致 L390 处报 `SyntaxError: unterminated triple-quoted string literal`。

```python
# 当前（错误）：
def detect_channel() -> str:
    """
    ...
    str
        One of ``'feishu'``, ``'telegram'``, ``'terminal'``, ``'unknown'``.
    # Check for feishu          ← 仍在 docstring 内！
    if (os.environ.get('FEISHU_CHAT_ID') or ...
```

### 修复

在 `'unknown'``.` 行之后、`# Check for feishu` 之前插入 `"""` 闭合 docstring：

```python
# 修复后：
def detect_channel() -> str:
    """
    ...
    str
        One of ``'feishu'``, ``'telegram'``, ``'terminal'``, ``'unknown'``.
    """
    # Check for feishu
    if (os.environ.get('FEISHU_CHAT_ID') or os.environ.get('LARK_CHAT_ID') or
        os.environ.get('FEISHU_APP_ID') or os.environ.get('FEISHU_HOME_CHANNEL')):
        return 'feishu'
    # Check HERMES_SESSION_PLATFORM
    platform = os.environ.get('HERMES_SESSION_PLATFORM', '').lower()
    if platform == 'feishu':
        return 'feishu'
    if platform == 'telegram':
        return 'telegram'
    ...
```

### 临时绕过

在 `execute_code` 中无法 import `pmc_delivery` 时，手写路径函数替代：

```python
from pathlib import Path
OUTPUT_BASE = Path("/tmp/hermes-pmc-output")
def get_output_path(cat, fn): return OUTPUT_BASE / cat / fn
def now_iso(): return datetime.now().isoformat()
```
