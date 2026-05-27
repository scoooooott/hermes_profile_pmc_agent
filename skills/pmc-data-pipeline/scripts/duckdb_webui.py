#!/usr/bin/env python3
"""DuckDB Web UI - lightweight SQL browser, bound to Tailscale IP for remote access.

Start: python3 duckdb_webui.py
Access from another Tailscale-connected machine: http://100.93.193.127:8766/

Features:
- Left panel: SQL editor (Cmd+Enter to execute)
- Top buttons: one-click SELECT * FROM <table> LIMIT 50
- Read-only DuckDB connection
- Max 500 rows per query (prevents browser overload)
- Dark theme, mobile-responsive
"""

import http.server
import json
import duckdb
import urllib.parse
import os
import html

DB_PATH = '~/pmc-data/pmc_ods.duckdb'
BIND_HOST = '100.93.193.127'  # Tailscale IP
BIND_PORT = 8766

INDEX_HTML = r"""
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PMC DuckDB Explorer</title>
<style>
:root { --bg: #1a1a2e; --surface: #16213e; --primary: #0f3460; --accent: #e94560; --text: #eee; --muted: #999; --border: #333; --success: #00c853; --warn: #ff9800; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); height: 100vh; display: flex; flex-direction: column; }
#header { background: var(--surface); padding: 12px 20px; display: flex; align-items: center; gap: 16px; border-bottom: 1px solid var(--border); }
#header h1 { font-size: 18px; color: var(--accent); white-space: nowrap; }
#header .db-path { font-size: 12px; color: var(--muted); }
#tables { background: var(--surface); padding: 8px 16px; display: flex; flex-wrap: wrap; gap: 6px; border-bottom: 1px solid var(--border); }
#tables button { background: var(--primary); color: var(--text); border: none; padding: 4px 12px; border-radius: 4px; cursor: pointer; font-size: 12px; }
#tables button:hover { background: var(--accent); }
#main { display: flex; flex: 1; overflow: hidden; }
#query-panel { width: 50%; display: flex; flex-direction: column; border-right: 1px solid var(--border); }
#query-panel textarea { flex: 1; background: #0d1117; color: #c9d1d9; border: none; padding: 16px; font-family: 'SF Mono', Monaco, monospace; font-size: 13px; resize: none; outline: none; }
#query-panel .actions { display: flex; gap: 8px; padding: 8px 16px; background: var(--surface); border-top: 1px solid var(--border); }
#query-panel .actions button { padding: 6px 18px; border: none; border-radius: 4px; cursor: pointer; font-size: 13px; }
#run-btn { background: var(--accent); color: white; }
#clear-btn { background: var(--primary); color: var(--text); }
#result-panel { width: 50%; display: flex; flex-direction: column; overflow: auto; }
#result-header { padding: 8px 16px; background: var(--surface); border-bottom: 1px solid var(--border); font-size: 12px; color: var(--muted); }
#result-body { flex: 1; overflow: auto; padding: 8px; }
#result-body table { width: 100%; border-collapse: collapse; font-size: 12px; }
#result-body th { background: var(--primary); color: var(--text); padding: 6px 8px; text-align: left; position: sticky; top: 0; z-index: 1; }
#result-body td { padding: 4px 8px; border-bottom: 1px solid var(--border); max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
#result-body tr:hover td { background: rgba(233,69,96,0.1); }
#error { color: var(--accent); padding: 12px; font-size: 13px; white-space: pre-wrap; }
#status { font-size: 11px; padding: 4px 12px; }
.status-ok { color: var(--success); }
.status-err { color: var(--accent); }
</style>
</head>
<body>
<div id="header">
  <h1>PMC DuckDB</h1>
  <span class="db-path">pmc_ods.duckdb</span>
  <span id="status" class="status-ok">● ready</span>
</div>
<div id="tables"></div>
<div id="main">
  <div id="query-panel">
    <textarea id="sql" placeholder="Enter SQL query...&#10;&#10;Shortcut: Cmd/Ctrl+Enter to execute" spellcheck="false">SELECT * FROM ods_amazon_msku_agg LIMIT 20;</textarea>
    <div class="actions">
      <button id="run-btn" onclick="execute()">&#9654; Run (&#8984;&#8629;)</button>
      <button id="clear-btn" onclick="clearAll()">Clear</button>
    </div>
  </div>
  <div id="result-panel">
    <div id="result-header">Results</div>
    <div id="result-body"></div>
  </div>
</div>
<script>
const tables = %TABLES_JSON%;
const tableBtns = document.getElementById('tables');
tables.forEach(t => {
  const btn = document.createElement('button');
  btn.textContent = t;
  btn.onclick = () => {
    document.getElementById('sql').value = `SELECT * FROM ${t} LIMIT 50;`;
    execute();
  };
  tableBtns.appendChild(btn);
});

async function execute() {
  const sql = document.getElementById('sql').value.trim();
  if (!sql) return;
  const status = document.getElementById('status');
  status.textContent = '⏳ running...';
  status.className = '';
  try {
    const resp = await fetch('/api/query', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({sql})
    });
    const data = await resp.json();
    const body = document.getElementById('result-body');
    if (data.error) {
      body.innerHTML = `<div id="error">${escapeHtml(data.error)}</div>`;
      document.getElementById('result-header').textContent = 'Error';
      status.textContent = '✕ error';
      status.className = 'status-err';
    } else {
      const cols = data.columns || [];
      const rows = data.rows || [];
      let html = `<table><thead><tr>${cols.map(c => `<th>${escapeHtml(c)}</th>`).join('')}</tr></thead><tbody>`;
      rows.forEach(r => {
        html += '<tr>';
        cols.forEach((c, i) => { html += `<td title="${escapeHtml(String(r[i]??''))}">${escapeHtml(String(r[i]??''))}</td>`; });
        html += '</tr>';
      });
      html += '</tbody></table>';
      body.innerHTML = html;
      document.getElementById('result-header').textContent = `${rows.length} rows × ${cols.length} cols`;
      status.textContent = `● ${rows.length} rows`;
      status.className = 'status-ok';
    }
  } catch(e) {
    document.getElementById('result-body').innerHTML = `<div id="error">${escapeHtml(e.message)}</div>`;
    status.textContent = '✕ error';
    status.className = 'status-err';
  }
}
function clearAll() {
  document.getElementById('result-body').innerHTML = '';
  document.getElementById('result-header').textContent = 'Results';
}
function escapeHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
document.getElementById('sql').addEventListener('keydown', e => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); execute(); }
});
</script>
</body>
</html>
"""

class DuckDBHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == '/' or self.path == '/index.html':
            con = duckdb.connect(DB_PATH, read_only=True)
            tables = [r[0] for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main' ORDER BY table_name").fetchall()]
            con.close()
            html = INDEX_HTML.replace('%TABLES_JSON%', json.dumps(tables))
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(html.encode())
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == '/api/query':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            data = json.loads(body)
            sql = data.get('sql', '')
            try:
                con = duckdb.connect(DB_PATH, read_only=True)
                result = con.execute(sql)
                columns = [desc[0] for desc in result.description] if result.description else []
                rows = result.fetchmany(500)
                con.close()
                response = {'columns': columns, 'rows': [list(r) for r in rows]}
            except Exception as e:
                response = {'error': str(e)}
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response, ensure_ascii=False).encode())
        else:
            self.send_error(404)

if __name__ == '__main__':
    server = http.server.HTTPServer((BIND_HOST, BIND_PORT), DuckDBHandler)
    print(f'DuckDB Web UI → http://{BIND_HOST}:{BIND_PORT}/')
    server.serve_forever()
