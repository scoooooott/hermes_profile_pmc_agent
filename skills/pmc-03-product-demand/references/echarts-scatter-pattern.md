# ECharts 四象限散点图生成模式

## 图表配置要点

### 对数轴
```js
xAxis: { type: 'log', min: 0.01 }   // 避免 log(0)
yAxis: { type: 'log', min: 0.5 }
```

### 象限分色
四个象限用独立 series，每 series 一个散点图：
```js
series: [
  { name: '高销高库存', type: 'scatter', data: [...], itemStyle: { color: '#22c55e' } },
  { name: '高销低库存', type: 'scatter', data: [...], itemStyle: { color: '#ef4444' } },
  { name: '低销高库存', type: 'scatter', data: [...], itemStyle: { color: '#f59e0b' } },
  { name: '低销低库存', type: 'scatter', data: [...], itemStyle: { color: '#6b7280' } },
]
```

### 中位参考线（markLine）
每货盘独立中位线，标注值：
```js
markLine: {
  silent: true,
  symbol: 'none',
  data: [
    { name: '中位日均销', xAxis: ref_x, lineStyle: { color: '#64748b', type: 'dashed' }, label: { formatter: 'x̅={val}' } },
    { name: '中位库存天数', yAxis: ref_y, lineStyle: { color: '#64748b', type: 'dashed' }, label: { formatter: 'ȳ={val}' } },
  ]
}
```

### Tooltip 绑定 SKU 名
data 数组三项 `[x, y, label]`，tooltip formatter 取 `p.data[2]`。

### 缩放控件
```js
dataZoom: [
  { type: 'inside', xAxisIndex: 0, filterMode: 'none' },
  { type: 'inside', yAxisIndex: 0, filterMode: 'none' },
  { type: 'slider', xAxisIndex: 0, bottom: 10, height: 20 },
  { type: 'slider', yAxisIndex: 0, right: 8, width: 20 },
]
```

### 暗色主题
```css
background: '#0f172a'   // 图表背景
#1e293b                 // 网格线 / 滑块轨道
#334155                 // 滑块边框
#94a3b8                 // 轴标签
```

### 多 Tab 切换
每个 Tab 对应一个货盘，切换时 `chart.dispose()` + 重建：
```js
function switchTab(tier) {
  if (chart) chart.dispose();
  chart = echarts.init(dom, null, {renderer: 'svg'});
  chart.setOption(buildOption(tier));
}
```

### SVG 渲染
散点图大数据量时 SVG 优于 Canvas（缩放不模糊）：
```js
echarts.init(dom, null, {renderer: 'svg'})
```

## 数据注入

Python 生成 JSON → `str.replace('%DATA%', json_data)` → 输出 HTML。避免 AJAX fetch（离线打不开）。

## 已知问题

- ECharts log 轴 `min: 0` 会导致 `-Infinity` → 设 `min: 0.01`
- 全量图（2400+ 点）symbolSize 设 3，分货盘图设 5
- 全量图 opacity 设 0.55 避免重叠过密
- `filterMode: 'none'` 在 dataZoom 里必须设，否则 markLine 会被过滤消失
