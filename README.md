# module2-e2e

模块② 片区规划集成 E2E（WP17）：六仓 tag 锁定依赖图上的**门禁不变量**测试。

```
plan-release v0.1.0 × assignment-service v0.2.0 × service-rules v0.2.0
× dq-workbench v0.1.1 × sraf v0.1.3 × territory-ir v0.3.2
（传递：coords-core v0.1.0 · market-partition v0.1.1）
```

## 门禁（8 项）

| # | 不变量 | 断言 |
|---|---|---|
| G1 | 未审批不可发布 | SUBMITTED 直接 activate 拒绝；批次无 ACTIVE |
| G2 | 四眼原则贯穿 | approve 人 ≠ submit 人 |
| G3 | 发布不可变 | 冻结后 edit 拒绝；载荷字节不变；审计链可验 |
| G4 | 分配可追溯 | 有主+plan_version_ref=ALLOW；缺追溯键=REVIEW（#48 fail-closed） |
| G5 | 无主门店 fail-closed | REVIEW+REPAIR_REQUIRED → 先 ingest Finding 再开工作台工单 |
| G6 | 兼跑需批准链 | 无批准拒 → dq-workbench HITL 双 SUPPORT 仲裁 → 批准落分配；主访独家不回归 |
| G7 | 词表单源跨链一致 | sraf 与 territory-ir 的 RING_WORDS 是同一对象（WP11 门禁） |
| G8 | 缺口路由 | 诊断→DP01/DP03 映射；未知诊断不臆测路由（primary=None+更多证据） |

## 运行

```bash
uv pip install "module2-e2e[dev] @ git+https://github.com/topprismdata/module2-e2e.git@v0.1.0"
python -m pytest tests -q   # 8 passed，秒级，全 hermetic
```

依赖升级纪律：任何上游仓 bump 需同步本仓 pin 并全绿后才打新 tag（六仓矩阵一致性）。
