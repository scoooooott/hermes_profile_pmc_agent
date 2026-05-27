# 目标值跨 Skill 依赖关系

## 数据流

```
场景00 (商品画像)
  └→ ods_skus.tier + ods_skus.lifecycle
      │
场景01 (销量需求)
  ├→ 设定 ods_skus.manual_daily_sale_target (均值法/中位数×系数)
  └→ dwd_sku_daily_metrics.weighted_daily
      │
      ├→ 场景02 (库存需求)   — 使用 target_daily × safety_days 做需求膨胀
      ├→ 场景03 (四象限)     — 不使用 target, 独立诊断
      └→ 场景04 (智能备货)   — MAX(weighted_daily, target_daily) × P7
```

## 关键依赖

| 源 | 消费方 | 影响 |
|:---|:---|:---|
| `ods_skus.manual_daily_sale_target` (Scene01) | Scene04 备货 | `MAX(实际, 目标)` 公式，目标值过高会直接膨胀备货建议量 |
| `ods_skus.tier` (Scene00) | 全部场景 | 所有场景按 tier 分组/匹配参数 |

## 实战案例：目标值调整的涟漪效应

**初始（硬编码 3000/1200/500/100）**：
- Scene01 达成率 13%，3,496 个 SKU 有缺口 → 目标不合理

**中位数×2.5 (42/8/2/1)**：
- Scene01 达成率 1,611%，仍有 1,102 个 C 级缺数据分析 → 偏保守

**均值法 (25/4/1/1)**：
- Scene01 零缺口（S/A/B 全部超额） → 目标合理
- Scene04 S 级 Top3 备货 747/741/733 件 → **目标驱动型备货膨胀**
  - 原因：S 级目标 25/日，但 SKU 实际销量仅 2~5/日
  - `MAX(2.6, 25) × 30 = 750`，但实际需求仅 `2.6 × 30 = 78`

## 结论

1. **改变 Scene01 目标值之前**，评估对 Scene04 备货的影响
2. **均值法**对 Scene01 合理（S/A/B 零缺口），但对 Scene04 中低销量 S 级产生过度备货
3. **建议**：如备货要以实际需求为准，将 Scene04 公式中 `MAX(实际, 目标)` 改为纯 `实际`，或设独立备货目标
4. 目标值调整后必须重跑下游相关场景才能看到全貌
