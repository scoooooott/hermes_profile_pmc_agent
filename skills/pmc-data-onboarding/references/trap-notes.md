# 陷阱笔记 — Onboarding 常见错误

## 1. 不要拒绝客户

PMC 是自适应配置，不是筛选淘汰。铺货卖家也有海外库存+采购发货需求。永远不要说"你不适合用 PMC"。

## 2. 不要硬编码参数提问

先查 `ods_params` 表获取当前参数列表和默认值，再逐参数判断是否需要客户确认。不同客户的参数差异巨大，不能用固定列表。

## 3. 参数只写 ods_params

写入参数时只操作 `ods_params` 表，不要直接写 `dwd_params`（那是 VIEW）。`ods_params.param_default` 是原始值，DWD 层展开后下游 Skill 才读 `param_value`。

## 4. 删除敏感文件要用 filter-branch

`git rm` 只是从当前 commit 删除文件，历史 commit 中仍可恢复。如果误推了敏感信息，必须用 `git filter-branch` 彻底清洗历史。
