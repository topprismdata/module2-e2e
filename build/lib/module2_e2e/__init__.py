"""module2-e2e：片区规划全链门禁（WP17）。

链：方案编制(plan-release) → 审批(HITL/dq-workbench) → 发布 → 分配执行
    (assignment-service 兼跑) → 覆盖评估(service-rules TERRITORY_COVER)
    → 缺口路由(sraf_intel DP)。
"""
__version__ = "0.1.0"
