# pmc-data-onboarding 陷阱笔记

## 陷阱 1：不要拒绝客户——PMC 自适应，不筛选

**错误做法**：判断铺货/无货源客户「不需要 PMC」并结束 onboarding。

**为什么错**：铺货卖家虽然没有国内仓，但仍有「海外库存 → 预测销量 → 采购/发货缺口」这条链路。PMC 可以通过跳过 `ods_inventory_domestic`、调整安全库存参数来适配，而不是拒绝服务。即便客户做 Temu/SHEIN 全托管（自己没库存数据），也应该说明「该平台 PMC 暂时无法覆盖」而非「你不需要 PMC」。

**正确做法**：了解客户模式后自动调整参数预设和数据板块开关。画像阶段的目标是**自适应配置**，不是**筛选淘汰**。

## 陷阱 2：硬编码参数提问不可维护

**错误做法**：在 onboarding skill 里写死「问客户 SABCN 阈值」「问安全库存天数」「问采购提前期」等固定问题。

**为什么错**：`ods_params` 表里的参数会增删改。硬编码的提问跟真实参数表脱节后，Agent 可能问到已删除的参数，或漏掉新增的参数。

**正确做法**：Agent 先跑 `SELECT * FROM dwd_params` 拿到当前参数表，逐参数判断是否需要客户定制。默认值合理的跳过，依赖客户业务特征的用自然语言解释后提问。

## 陷阱 3：Git 历史里的删除 diff 仍泄露文件内容

**错误做法**：`git rm` 删除文件后提交 → `git push`。认为文件已不在仓库中。

**为什么错**：`git show <commit>` 查看该删除 commit 时，diff 中 `-` 开头的内容就是被删文件的原文。敏感信息通过 delete diff 间接暴露。

**正确做法**：用 `git filter-branch --index-filter 'git rm --cached --ignore-unmatch <file>' --prune-empty --tag-name-filter cat -- --all` 从所有历史 commit 中彻底抹除文件。然后 `git push --force --tags`。最后清理 `refs/original/` 残余引用：`git for-each-ref refs/original/ --format='delete %(refname) %(objectname)' | git update-ref --stdin`。
