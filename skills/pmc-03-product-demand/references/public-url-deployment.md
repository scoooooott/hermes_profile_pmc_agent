# 公网部署 HTML 报告（临时隧道）

当用户需要查看本地生成的 HTML 报告但无法直接访问本地文件时，使用 SSH 反向隧道部署到公网。

## 步骤

### 1. 启动本地 HTTP 服务器

```bash
cd /path/to/report/dir && python3 -m http.server 8899 --bind 127.0.0.1
```
- 使用 `terminal(background=true)` 启动，不阻塞会话
- 验证：`curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8899/filename.html` → 应返回 200

### 2. 创建 SSH 反向隧道

```bash
ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=60 -R 80:localhost:8899 nokey@localhost.run
```
- 同样使用 `terminal(background=true)`
- 输出中找 `https://XXXXXXXX.lhr.life` 即为公网 URL
- 轮询 `process(action='poll', session_id=...)` 获取 URL（通常 3-8 秒后出现）
- 完整 URL = `https://{subdomain}.lhr.life/{filename}`（中文文件名需 URL 编码）

### 3. 验证

```bash
curl -s -o /dev/null -w "HTTP %{http_code} | Size: %{size_download}" "https://{subdomain}.lhr.life/{filename}"
```
→ HTTP 200 即成功。

### 4. 清理

- 隧道断开后 URL 即失效
- 如需长期保存，提醒用户下载飞书附件中的 HTML 文件到本地

## 备选方案：Tailscale Serve（推荐，内网稳定）

Mac 上通常已安装 Tailscale。如果用户和你都在同一 tailnet，优先使用：

```bash
# 1. 启动 HTTP 服务（需绑定 0.0.0.0，否则 Tailscale 访问不到）
python3 -m http.server 8899 --bind 0.0.0.0
# 2. 读取 Tailscale IP
tailscale status --json | python3 -c "import sys,json; print(json.load(sys.stdin)['Self']['TailscaleIPs'][0])"
# 3. 将 IP 拼入 URL 发给用户
# http://100.xx.xx.xx:8899/filename.html
```

Tailscale Serve（HTTPS + 好看域名，仍限 tailnet）：
```bash
tailscale serve --bg --set-path /report http://127.0.0.1:8899
# URL: https://{hostname}.{tailnet}.ts.net/report/filename.html
```

## 备选方案：FRP（公网，需已配置）

检查 `~/frp/frpc.toml` 是否有现有配置。如有，添加新 HTTP 代理：
```toml
[[proxies]]
name = "pmc-report"
type = "http"
localIP = "127.0.0.1"
localPort = 8899
subdomain = "pmc-report"
[proxies.transport]
useEncryption = false
useCompression = false
```
然后 `kill` 旧进程 + 重启 `frpc -c frpc.toml`（background=true）。

> **已知问题**：FRP HTTPS 可能因远端证书问题超时。此时回退到 Tailscale。

## 其他备选

- `ssh -R 80:localhost:8899 nokey@localhost.run` → 得 `https://{id}.lhr.life`（有时可用，但已不推荐偏好多跳一层）
- `serveo.net`：实测连接超时，不推荐
- `bore.pub` / `cloudflared`：需额外安装

## 注意事项

- 临时隧道（localhost.run）适合一次性查看；Tailscale 地址持久有效
- 包含 ECharts CDN 的 HTML 在公网 URL 下可正常加载，不受 CORS 影响
- 中文文件名在 URL 中需编码，但 curl 和浏览器通常自动处理
- HTTP 服务用完后应及时 kill，避免端口占用
