#!/usr/bin/env python3
"""
PMC场景03 商品需求四象限 — ECharts交互式网页生成器

用法:
  python3 scene03-echarts-generator.py

输出:
  /tmp/hermes-pmc-output/html/PMC_Scene03_四象限_YYYYMMDD.html

部署:
  cd /tmp/hermes-pmc-output/html && python3 -m http.server 8899 --bind 0.0.0.0
  # FRP 已有 pmc-quadrant 代理，确保 ~/frp/frpc 已在运行（避免重复启动）
  # 公网: https://pmc-quadrant.frp.ifnotnull.xyz/PMC_Scene03_四象限_YYYYMMDD.html
  # Tailscale: http://100.93.193.127:8899/PMC_Scene03_四象限_YYYYMMDD.html
"""
import sys, os, json, duckdb
from datetime import datetime
from pathlib import Path

con = duckdb.connect(os.path.expanduser("os.path.expanduser(os.environ.get("PMC_DB_PATH", "~/pmc-data/pmc_ods.duckdb"))"))

df = con.execute("""
WITH tier_stats AS (
    SELECT tier,
        MEDIAN(weighted_daily) AS ref_x,
        MEDIAN(inventory_days) AS ref_y
    FROM dwd_sku_daily_metrics
    WHERE tier IS NOT NULL AND tier != ''
      AND weighted_daily > 0 AND inventory_days > 0
    GROUP BY tier
)
SELECT d.sku_code, d.tier, d.product_name,
    ROUND(d.weighted_daily, 3) AS weighted_daily,
    ROUND(d.total_inventory, 0) AS total_inventory,
    ROUND(d.inventory_days, 1) AS inventory_days,
    ROUND(ts.ref_x, 3) AS ref_x, ROUND(ts.ref_y, 1) AS ref_y,
    CASE WHEN d.weighted_daily >= ts.ref_x AND d.inventory_days >= ts.ref_y THEN '高销高库存'
         WHEN d.weighted_daily >= ts.ref_x AND d.inventory_days <  ts.ref_y THEN '高销低库存'
         WHEN d.weighted_daily <  ts.ref_x AND d.inventory_days >= ts.ref_y THEN '低销高库存'
         ELSE '低销低库存' END AS quadrant
FROM dwd_sku_daily_metrics d
JOIN tier_stats ts ON d.tier = ts.tier
WHERE d.weighted_daily > 0 AND d.inventory_days IS NOT NULL
ORDER BY d.tier, d.weighted_daily DESC
""").fetchdf()

total_sku = len(df)
quadrant_counts = df['quadrant'].value_counts().to_dict()

# Build chart_data dict
tiers = ['S', 'A', 'B', 'C']
chart_data = {}
for tier in tiers + ['ALL']:
    sub = df if tier == 'ALL' else df[df['tier'] == tier]
    data = [{'name': str(r['product_name']), 'sku': str(r['sku_code']),
             'value': [float(r['weighted_daily']), float(r['inventory_days'])],
             'quadrant': r['quadrant']} for _, r in sub.iterrows()]
    ref = {'ref_x': None, 'ref_y': None} if tier == 'ALL' else \
          {'ref_x': float(sub.iloc[0]['ref_x']), 'ref_y': float(sub.iloc[0]['ref_y'])}
    chart_data[tier] = {'data': data, 'count': len(data), **ref}

# Quadrant counts per tier
tier_q_counts = {t: (df[df['tier'] == t] if t != 'ALL' else df)['quadrant'].value_counts().to_dict()
                 for t in tiers + ['ALL']}

# Colors
q_colors = {'高销高库存': '#2563eb', '高销低库存': '#dc2626', '低销高库存': '#f59e0b', '低销低库存': '#6b7280'}
quad_order = ['高销高库存', '高销低库存', '低销高库存', '低销低库存']

report_date = datetime.now().strftime('%Y-%m-%d %H:%M')
chart_json = json.dumps(chart_data, ensure_ascii=False)
q_counts_json = json.dumps(tier_q_counts, ensure_ascii=False)

html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>PMC场景03 - 商品需求四象限分析</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<style>
* {{ margin:0;padding:0;box-sizing:border-box; }}
body {{ font-family:'PingFang SC','Microsoft YaHei',sans-serif;background:#f5f5f4;color:#1c1917; }}
.header {{ background:linear-gradient(135deg,#292524,#44403c);color:white;padding:20px 30px; }}
.header h1 {{ font-size:22px; }}
.header .meta {{ font-size:13px;color:#a8a29e;margin-top:4px; }}
.tabs {{ display:flex;gap:0;background:#292524;padding:0 20px; }}
.tab {{ padding:10px 24px;color:#a8a29e;cursor:pointer;border-bottom:3px solid transparent;font-size:14px;transition:all 0.2s; }}
.tab:hover {{ color:#fff;background:#44403c; }}
.tab.active {{ color:#fff;border-bottom-color:#3b82f6;background:#44403c; }}
.content {{ padding:20px; }}
.chart-wrapper {{ background:white;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,0.1);padding:16px; }}
#chart {{ width:100%;height:650px; }}
.stats-bar {{ display:flex;gap:16px;margin-top:12px;flex-wrap:wrap; }}
.stat-item {{ padding:8px 14px;border-radius:6px;font-size:13px; }}
.stat-high {{ background:#eff6ff;color:#1d4ed8; }}
.stat-danger {{ background:#fef2f2;color:#dc2626; }}
.stat-warn {{ background:#fffbeb;color:#b45309; }}
.stat-low {{ background:#f8fafc;color:#64748b; }}
.legend {{ display:flex;gap:16px;margin:12px 0;font-size:13px;align-items:center; }}
.legend-dot {{ display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:4px; }}
.info-card {{ background:white;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,0.1);padding:14px 18px;margin:12px 0;font-size:13px;color:#44403c; }}
.info-card strong {{ color:#1c1917; }}
</style></head><body>
<div class="header">
  <h1>📊 商品需求四象限诊断</h1>
  <div class="meta">{report_date} ｜ 分析SKU: {total_sku}个 ｜ 五套独立坐标系</div></div>
<div class="tabs" id="tabs">
  <div class="tab active" onclick="switchTab('ALL')">📊 全量 ({len(df)})</div>
  <div class="tab" onclick="switchTab('S')">⭐ S ({len(df[df['tier']=='S'])})</div>
  <div class="tab" onclick="switchTab('A')">🔷 A ({len(df[df['tier']=='A'])})</div>
  <div class="tab" onclick="switchTab('B')">🟢 B ({len(df[df['tier']=='B'])})</div>
  <div class="tab" onclick="switchTab('C')">⚪ C ({len(df[df['tier']=='C'])})</div></div>
<div class="content">
  <div class="legend">
    <span><span class="legend-dot" style="background:#2563eb"></span>高销高库存</span>
    <span><span class="legend-dot" style="background:#dc2626"></span>高销低库存 ⚠️</span>
    <span><span class="legend-dot" style="background:#f59e0b"></span>低销高库存</span>
    <span><span class="legend-dot" style="background:#6b7280"></span>低销低库存</span>
    <span style="margin-left:auto;color:#9ca3af;font-size:12px;">X轴: 加权日均销(对数) ｜ Y轴: 库存天数(对数) ｜ 参考线: 货盘中位数</span></div>
  <div class="chart-wrapper"><div id="chart"></div></div>
  <div class="stats-bar" id="stats-bar"></div>
  <div class="info-card"><strong>💡 解读：</strong>高销高库存 → 关注补货节奏 ｜
    <strong style="color:#dc2626">高销低库存 → ⚠️ 断货风险</strong> ｜
    <strong style="color:#f59e0b">低销高库存 → 关注去化</strong> ｜ 低销低库存 → 观察/淘汰</div></div>
<script>
const chartData = {chart_json};
const qCounts = {q_counts_json};
const qColors = {{'高销高库存':'#2563eb','高销低库存':'#dc2626','低销高库存':'#f59e0b','低销低库存':'#6b7280'}};
const quadOrder = ['高销高库存','高销低库存','低销高库存','低销低库存'];
let myChart = null;

function switchTab(tier) {{
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => {{ if(t.textContent.trim().startsWith(tier==='ALL'?'📊':tier)) t.classList.add('active'); }});
  const d = chartData[tier]; if (!d || !d.data || d.data.length === 0) return;
  const groups = {{}}; d.data.forEach(item => {{ const q = item.quadrant; if(!groups[q]) groups[q]=[]; groups[q].push(item); }});
  const series = quadOrder.filter(q => groups[q]).map(q => ({{
    name: q, type: 'scatter',
    data: groups[q].map(x => ({{value: x.value, name: x.name, sku: x.sku}})),
    symbolSize: 10, itemStyle: {{ color: qColors[q] }},
    emphasis: {{ itemStyle: {{ shadowBlur:10,shadowOffsetX:0,shadowColor:'rgba(0,0,0,0.3)' }},
               label: {{ show:true,formatter:p=>p.data.sku,fontSize:12,fontWeight:'bold' }} }}
  }}));
  let maxX = 0, maxY = 0; d.data.forEach(item => {{ maxX = Math.max(maxX,item.value[0]); maxY = Math.max(maxY,item.value[1]); }});
  maxX *= 1.5; maxY *= 1.5; if (maxX < 1) maxX = 10; if (maxY < 1) maxY = 10;
  const markLines = (tier !== 'ALL' && d.ref_x > 0 && d.ref_y > 0) ? [
    {{ xAxis: d.ref_x, label:{{show:true,formatter:'日均销中位: '+d.ref_x.toFixed(2),position:'end'}},
      lineStyle:{{type:'dashed',color:'#292524',width:2}} }},
    {{ yAxis: d.ref_y, label:{{show:true,formatter:'库存天中位: '+d.ref_y.toFixed(1),position:'end'}},
      lineStyle:{{type:'dashed',color:'#292524',width:2}} }}] : [];
  if (series.length > 0) series[0].markLine = markLines.length > 0 ? {{ silent:true, data: markLines }} : undefined;
  const option = {{
    tooltip: {{ trigger:'item', formatter: p => '<strong>'+p.data.sku+'</strong><br/>'+(p.data.name||'')+
      '<br/>日均销: <strong>'+p.data.value[0].toFixed(2)+'</strong> 件/天<br/>库存: <strong>'+p.seriesName+'</strong><br/>库存天数: '+p.data.value[1].toFixed(1)+' 天' }},
    grid: {{ left:'10%',right:'8%',top:'12%',bottom:'15%' }},
    xAxis: {{ type:'log', name:'加权日均销 (件/天)', nameLocation:'center', nameGap:40,
             nameTextStyle:{{fontSize:13,fontWeight:'bold'}}, min:0.01, max:Math.max(maxX,1) }},
    yAxis: {{ type:'log', name:'库存天数', nameLocation:'center', nameGap:55,
             nameTextStyle:{{fontSize:13,fontWeight:'bold'}}, min:0.1, max:Math.max(maxY*2,100) }},
    dataZoom: [{{type:'slider',xAxisIndex:0,bottom:10,height:20,borderColor:'#e5e7eb'}},
               {{type:'inside',xAxisIndex:0}},{{type:'inside',yAxisIndex:0}}],
    series: series,
  }};
  if (!myChart) myChart = echarts.init(document.getElementById('chart'));
  myChart.setOption(option,true); myChart.resize();
  const qc = qCounts[tier]||{{}}; const total = d.count;
  document.getElementById('stats-bar').innerHTML =
    quadOrder.map(q => (qc[q]||0)).reduce((html,c,i) => html + '<div class="stat-item '+
      (['stat-high','stat-danger','stat-warn','stat-low'][i])+'">'+
      (['🟦','🔴','🟠','⚪'][i])+quadOrder[i]+' '+c+' ('+(c/total*100).toFixed(1)+'%)</div>', ''); }}
window.addEventListener('resize',()=>{{ if(myChart) myChart.resize(); }});
switchTab('ALL');
</script></body></html>"""

out_dir = Path(os.path.expanduser('/tmp/hermes-pmc-output/html'))
out_dir.mkdir(parents=True, exist_ok=True)
out_path = out_dir / f'PMC_Scene03_四象限_{datetime.now().strftime("%Y%m%d")}.html'
out_path.write_text(html, encoding='utf-8')

print(f"HTML generated: {out_path}")
print(f"Size: {os.path.getsize(out_path):,} bytes")
print(f"SKUs: {total_sku}")
con.close()
