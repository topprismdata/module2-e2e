"""WP17 门禁不变量：未审批不可发布 / 发布不可变 / 分配可追溯 / 兼跑需批准。"""

import pytest
from assignment_service import AssignmentService, InvariantViolation, PolicyViolation, Role
from dq_workbench import Workbench
from dq_workbench.hitl import AdjudicationAction, ReviewConfidence, ReviewerRole
from dq_workbench.models import Finding, IssueStatus, Layer, Severity
from plan_release import IllegalTransition, PlanReleaseService
from service_rules import (
    AdmissionAction,
    GovernanceDisposition,
    Rule,
    RuleSetVersion,
    RuleType,
    Severity,
    evaluate_coverage,
)

PLAN = {"ir": {"clauses": ["街道A", "沿滨江路(限街道A内)"], "pieces": [1, 2, 3]},
        "load_vector": {"stores": 42, "km2": 18.7}}


@pytest.fixture
def env(tmp_path):
    return {
        "plans": PlanReleaseService(":memory:"),
        "assign": AssignmentService(tmp_path / "a.db"),
        "wb": Workbench(tmp_path / "w.db"),
        "rules": RuleSetVersion("v1", (
            Rule("R-COV", RuleType.TERRITORY_COVER, Severity.C2, False),
        )),
    }


def _activate_plan(env, ref_batch="2027Q1"):
    plans = env["plans"]
    pv = plans.new_iteration(ref_batch, PLAN, actor="planner")
    plans.transition(pv.ref, "simulate", actor="analyst")
    plans.transition(pv.ref, "submit", actor="planner")
    plans.transition(pv.ref, "approve", actor="manager")
    return plans.transition(pv.ref, "activate", actor="ops")


def test_g1_未审批不可激活(env):
    plans = env["plans"]
    pv = plans.new_iteration("B", PLAN, actor="planner")
    plans.transition(pv.ref, "simulate", actor="a")
    plans.transition(pv.ref, "submit", actor="planner")
    with pytest.raises(IllegalTransition):  # SUBMITTED 直接 activate 拒绝
        plans.transition(pv.ref, "activate", actor="ops")
    assert plans.active("B") is None


def test_g2_四眼原则贯穿发布(env):
    plans = env["plans"]
    pv = plans.new_iteration("B", PLAN, actor="planner")
    plans.transition(pv.ref, "simulate", actor="a")
    plans.transition(pv.ref, "submit", actor="planner")
    with pytest.raises(IllegalTransition, match="四眼"):
        plans.transition(pv.ref, "approve", actor="planner")


def test_g3_发布后载荷不可变(env):
    pv = _activate_plan(env)
    with pytest.raises(IllegalTransition, match="冻结"):
        env["plans"].edit_payload(pv.ref, {"tampered": 1}, actor="x")
    assert env["plans"].get(pv.ref).payload == PLAN  # 字节不变
    assert env["plans"].verify_audit_chain()


def test_g4_分配可追溯方案版本(env):
    pv = _activate_plan(env)
    svc = env["assign"]
    svc.assign("O1", "repA", Role.PRIMARY_SELLING, "2027-01-01",
               decided_by="ops", source_approved_decision_id=pv.ref)
    # 有主 + 携带 plan_version_ref → 覆盖评估 ALLOW
    e = evaluate_coverage(env["rules"], "O1", has_primary=True,
                          plan_version_ref=pv.ref)[0]
    assert e.verdict is AdmissionAction.ALLOW
    # 缺追溯键 → REVIEW（#48 断链 fail-closed）
    e2 = evaluate_coverage(env["rules"], "O2", has_primary=True)[0]
    assert e2.verdict is AdmissionAction.REVIEW
    assert "missing_plan_version_ref" in e2.evidence


def test_g5_无主门店fail_closed进工作台(env):
    pv = _activate_plan(env)
    e = evaluate_coverage(env["rules"], "O9", has_primary=False)[0]
    assert e.verdict is AdmissionAction.REVIEW
    assert e.disposition is GovernanceDisposition.REPAIR_REQUIRED
    # 落成异常工单（①资产接线：先 ingest Finding 再开单）
    wb = env["wb"]
    fid = f"COVERAGE:O9:{pv.ref}"
    wb.ingest([Finding(finding_id=fid, layer=Layer.IDENTITY, rule_id="R-COV",
                       subject="O9", severity=Severity.C2,
                       message="片区无主门店", evidence=["no_primary_relation"])])
    issue = wb.open_issue([fid], title="片区无主门店 O9")
    assert issue.status is IssueStatus.OPEN


def test_g6_兼跑必须携带HITL批准链(env):
    pv = _activate_plan(env)
    svc = env["assign"]
    svc.assign("O1", "repA", Role.PRIMARY_SELLING, "2027-01-01")
    # 无批准 → 拒
    with pytest.raises(PolicyViolation, match="批准"):
        svc.assign("O1", "repB", Role.CONCURRENT_RUN, "2027-01-01")
    # 走 dq-workbench HITL 双人仲裁拿批准
    wb = env["wb"]
    fid = "CONCURRENT_RUN:O1:repB"
    wb.ingest([Finding(finding_id=fid, layer=Layer.IDENTITY, rule_id="R-COV",
                       subject="O1", severity=Severity.C2,
                       message="兼跑申请待仲裁", evidence=["approval_required"])])
    issue = wb.open_issue([fid], title="兼跑申请")
    wb.transition(issue.issue_id, IssueStatus.ASSIGNED, actor="supervisor")
    wb.transition(issue.issue_id, IssueStatus.IN_REVIEW, actor="supervisor")
    wb.adjudicate(issue.issue_id, "r1", ReviewerRole.DATA_STEWARD,
                  AdjudicationAction.SUPPORT, ReviewConfidence.HIGH)
    verdict = wb.adjudicate(issue.issue_id, "r2", ReviewerRole.DOMAIN_EXPERT,
                            AdjudicationAction.SUPPORT, ReviewConfidence.HIGH)
    assert verdict is AdjudicationAction.SUPPORT
    wb.transition(issue.issue_id, IssueStatus.RESOLVED, actor="supervisor",
                  note="双 SUPPORT 批准兼跑")
    c = svc.assign("O1", "repB", Role.CONCURRENT_RUN, "2027-01-01",
                   source_approved_decision_id=issue.issue_id)
    assert c.role is Role.CONCURRENT_RUN
    # 主访独家不回归
    with pytest.raises(InvariantViolation):
        svc.assign("O1", "repC", Role.PRIMARY_SELLING, "2027-01-01")


def test_g7_词表单源跨链一致(env):
    """②链上所有仓的路名知识来自同一对象（WP11 门禁）。"""
    import intelligence.roadsem as sraf_rs
    import territory_ir.roadsem as tir_rs
    assert sraf_rs.RING_WORDS is tir_rs.RING_WORDS


def test_g8_缺口路由到片区DP(env):
    """sraf_intel 诊断→DP 路由在链上可用（04 §28 映射）。"""
    from sraf_intel.router import ProblemRouter
    router = ProblemRouter()
    assert router.route("TerritoryImbalance").primary_route.startswith("DP03")
    assert router.route("CapacityShortage").primary_route.startswith("DP01")
    unk = router.route("不存在的诊断")
    assert unk.primary_route is None and "更多证据" in unk.reason  # 不臆测路由


def test_g9_载荷契约在链上fail_fast(env):
    """WP16：非法方案（缺负载向量）在 DRAFT 入口即拒——治理只作用于合法文档。"""
    with pytest.raises(IllegalTransition, match="load_vector"):
        env["plans"].new_iteration("BAD", {"ir": {"clauses": ["街道A"]}}, actor="planner")
    pv = _activate_plan(env)  # 合法载荷全生命周期照常
    assert env["plans"].active(pv.batch_id).ref == pv.ref
