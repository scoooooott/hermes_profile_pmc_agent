# PMC 管线维护 — Skill 抽检轮换记录

每次 cron 维护抽检 3 个 scene skill 的核心 SQL。按轮次依次推进，覆盖全部 10 个 scene 后回到 scene00。

| 轮次 | 日期 | 抽检的 scene | 结果 |
|:---|:---|:---|:---|
| 1 | 2026-05-18 | scene01, scene03, scene05 | ✅ 全部通过 |
| 2 | 2026-05-18 | scene07, scene09, scene00 | ✅ 全部通过 |
| 3 | 2026-05-18 | scene02, scene04, scene06 | ✅ 全部通过 |
| 4 | 2026-05-18 | scene08, scene00, scene01 | ✅ 全部通过 |
| 5 | 2026-05-18 | scene02, scene03, scene04 | ✅ 全部通过 |
| 6 | 2026-05-18 | scene05, scene06, scene07 | ✅ 全部通过 |
| 7 | 2026-05-18 | scene08, scene09, scene00 | ✅ 全部通过 |
| 8 | 2026-05-18 | scene00, scene01, scene02 | ✅ 全部通过 |
| 9 | 2026-05-18 | scene03, scene04, scene05 | ✅ 全部通过 |
| 10 | 2026-05-18 | scene06, scene07, scene08 | ✅ 全部通过 |
| 11 | 2026-05-18 | scene09, scene00, scene01 | ✅ 全部通过 |
| 12 | 2026-05-18 | scene02, scene03, scene04 | ✅ 全部通过 |
| 13 | 2026-05-18 | scene05, scene06, scene07 | ✅ 全部通过 |
| 14 | 2026-05-18 | scene08, scene09, scene00 | ✅ 全部通过 |

## 规则

- 每次选 3 个，按 scene 编号轮换
- 运行各 skill 中标注的"核心 SQL"，验证不报错
- 通过/失败记录在上表中
- 10 个全部通过一轮后重置轮次计数
