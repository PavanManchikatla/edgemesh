from dataclasses import dataclass

from models import Node, NodeStatus, RolePreference, TaskType


@dataclass(slots=True)
class EffectiveCapacity:
    effective_cpu_threads: float
    effective_ram_gb: float
    effective_vram_gb: float | None


# Scoring weights for schedule simulation.
# Higher is better: candidates with more headroom and better role/hardware affinity rank first.
_SCORE_WEIGHTS = {
    "cpu_headroom": 45.0,
    "ram_headroom": 35.0,
    "gpu_headroom": 20.0,
    "infer_gpu_bonus": 22.0,
    "cpu_task_cpu_node_bonus": 12.0,
    "role_match_bonus": 14.0,
    "role_mismatch_penalty": 10.0,
    "running_jobs_penalty": 2.0,
}


def _task_requires_gpu(task_type: TaskType) -> bool:
    return task_type == TaskType.INFERENCE


def _task_prefers_cpu(task_type: TaskType) -> bool:
    return task_type in {
        TaskType.EMBEDDINGS,
        TaskType.INDEX,
        TaskType.TOKENIZE,
        TaskType.PREPROCESS,
    }


def _infer_role_match(role: RolePreference) -> bool:
    return role in {RolePreference.AUTO, RolePreference.PREFER_INFERENCE}


def _cpu_role_match(role: RolePreference) -> bool:
    return role in {
        RolePreference.AUTO,
        RolePreference.PREFER_EMBEDDINGS,
        RolePreference.PREFER_PREPROCESS,
    }


def compute_effective_capacity(node: Node) -> EffectiveCapacity:
    cpu_threads = node.capabilities.cpu_threads or node.capabilities.cpu_cores or 0
    ram_total = node.capabilities.ram_total_gb or node.capabilities.ram_gb or 0.0
    vram_total = node.capabilities.vram_total_gb

    effective_cpu_threads = round(
        cpu_threads * (node.policy.cpu_cap_percent / 100.0), 3
    )
    effective_ram_gb = round(ram_total * (node.policy.ram_cap_percent / 100.0), 3)

    effective_vram_gb: float | None = None
    if vram_total is not None:
        gpu_cap = (
            node.policy.gpu_cap_percent
            if node.policy.gpu_cap_percent is not None
            else 100
        )
        effective_vram_gb = round(vram_total * (gpu_cap / 100.0), 3)

    return EffectiveCapacity(
        effective_cpu_threads=effective_cpu_threads,
        effective_ram_gb=effective_ram_gb,
        effective_vram_gb=effective_vram_gb,
    )


def evaluate_node_eligibility(
    node: Node, task_type: TaskType
) -> tuple[bool, list[str]]:
    reasons: list[str] = []

    if not node.policy.enabled:
        reasons.append("policy_disabled")
    if node.status != NodeStatus.ONLINE:
        reasons.append("node_not_online")
    if task_type not in node.policy.task_allowlist:
        reasons.append("task_not_allowed")

    if node.metrics.cpu_percent > node.policy.cpu_cap_percent:
        reasons.append("cpu_over_cap")
    if node.metrics.ram_percent > node.policy.ram_cap_percent:
        reasons.append("ram_over_cap")

    if _task_requires_gpu(task_type):
        if not node.capabilities.has_gpu:
            reasons.append("gpu_required")
        elif node.metrics.gpu_percent is not None:
            gpu_cap = (
                node.policy.gpu_cap_percent
                if node.policy.gpu_cap_percent is not None
                else 100
            )
            if node.metrics.gpu_percent > gpu_cap:
                reasons.append("gpu_over_cap")

    return (len(reasons) == 0, reasons)


def is_node_eligible(node: Node, task_type: TaskType) -> bool:
    eligible, _ = evaluate_node_eligibility(node, task_type)
    return eligible


def _headroom(percent: float, cap_percent: int) -> float:
    cap = max(float(cap_percent), 1.0)
    utilization_ratio = min(percent / cap, 2.0)
    return max(0.0, 1.0 - utilization_ratio)


def score_node(node: Node, task_type: TaskType) -> float:
    score = 0.0

    score += (
        _headroom(node.metrics.cpu_percent, node.policy.cpu_cap_percent)
        * _SCORE_WEIGHTS["cpu_headroom"]
    )
    score += (
        _headroom(node.metrics.ram_percent, node.policy.ram_cap_percent)
        * _SCORE_WEIGHTS["ram_headroom"]
    )

    if _task_requires_gpu(task_type):
        if node.capabilities.has_gpu:
            score += _SCORE_WEIGHTS["infer_gpu_bonus"]

        if node.metrics.gpu_percent is not None:
            gpu_cap = (
                node.policy.gpu_cap_percent
                if node.policy.gpu_cap_percent is not None
                else 100
            )
            score += (
                _headroom(node.metrics.gpu_percent, gpu_cap)
                * _SCORE_WEIGHTS["gpu_headroom"]
            )

        if _infer_role_match(node.policy.role_preference):
            score += _SCORE_WEIGHTS["role_match_bonus"]
        else:
            score -= _SCORE_WEIGHTS["role_mismatch_penalty"]

    if _task_prefers_cpu(task_type):
        if not node.capabilities.has_gpu:
            score += _SCORE_WEIGHTS["cpu_task_cpu_node_bonus"]

        if _cpu_role_match(node.policy.role_preference):
            score += _SCORE_WEIGHTS["role_match_bonus"]
        else:
            score -= _SCORE_WEIGHTS["role_mismatch_penalty"]

    score -= node.metrics.running_jobs * _SCORE_WEIGHTS["running_jobs_penalty"]
    return round(score, 3)
