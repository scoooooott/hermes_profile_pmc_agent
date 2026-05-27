# DuckDB 远程访问（Tailscale + Web UI）

## 背景

DuckDB 是嵌入式数据库，没有 server/client 网络协议。远程可视化需要自己搭 HTTP 层。

## 方案对比

| 方案 | 要求 | 推荐度 |
|---|---|---|
| DBeaver（原生 DuckDB 支持） | 本机安装，不支持远程 | ★★ 本机用可以 |
| DuckDB CLI `-ui` | `brew install duckdb` | ✕ **1.5.2 不能用** |
| Python HTTP Server（本方案） | python3, Tailscale | ★★★ 推荐 |

## DuckDB `-ui` 的坑

DuckDB 1.5.2 的 `-ui` 命令会打印 "UI started at http://localhost:4213/" 然后**立即退出**，进程不复存在，端口不监听。不是权限或端口占用问题——就是启动完就退了。

```bash
# 这条命令在 1.5.2 下不可用
duckdb -ui pmc_ods.duckdb
# → 打印一行后 exit，端口 4213 不可达
```

## Python HTTP Server 方案

脚本路径：`~/pmc-data/duckdb_webui.py`

```bash
# 启动（需在 Tailscale 网络上）
python3 ~/pmc-data/duckdb_webui.py
```

特性：
- 绑定到 Tailscale IP `100.93.193.127:8766`
- 左侧写 SQL，Cmd+Enter 执行
- 顶部按钮自动填 `SELECT * FROM <表名> LIMIT 50`
- 只读连接，每次查询最多返回 500 行
- 深色主题，适配移动端

### 关键代码要点

```python
# 必须用只读连接，防止远程误操作
con = duckdb.connect(DB_PATH, read_only=True)

# 绑定到 Tailscale IP 而非 127.0.0.1
server = http.server.HTTPServer(('100.93.193.127', 8766), DuckDBHandler)
```

## 替代：FRP 暴露

如果不用 Tailscale，也可以用 FRP（本机已有配置 `ifnotnull.xyz:7000`）。在 frpc.toml 中加：

```toml
[[proxies]]
name = "duckdb-ui"
type = "http"
localPort = 8766
customDomains = ["duckdb.frp.ifnotnull.xyz"]
```

然后访问 `https://duckdb.frp.ifnotnull.xyz/`。

## 替代：DBeaver（本机）

```bash
brew install --cask dbeaver-community
```

File → New Connection → DuckDB → 指向 `.duckdb` 文件。免费，GUI 功能全，但不能远程。
