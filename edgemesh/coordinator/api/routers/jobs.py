import uuid

from fastapi import APIRouter, Body, HTTPException, Query, status

from api.schemas import DemoJobBurstResponse, JobCreateRequest, JobStatusUpdateRequest
from db import create_job, get_job, get_nodes, list_jobs, transition_job_status
from models import Job, JobStatus, TaskType
from scheduler import evaluate_node_eligibility, score_node

router = APIRouter(prefix="/v1", tags=["jobs"])


def _parse_task_type(raw: str) -> TaskType:
    normalized = raw.strip().upper()
    mapping = {
        "INFER": TaskType.INFERENCE,
        "INFERENCE": TaskType.INFERENCE,
        "EMBED": TaskType.EMBEDDINGS,
        "EMBEDDING": TaskType.EMBEDDINGS,
        "EMBEDDINGS": TaskType.EMBEDDINGS,
        "INDEX": TaskType.INDEX,
        "TOKENIZE": TaskType.TOKENIZE,
        "PREPROCESS": TaskType.PREPROCESS,
        "PREPROCESSING": TaskType.PREPROCESS,
    }

    task_type = mapping.get(normalized)
    if task_type is None:
        raise HTTPException(status_code=422, detail=f"Unsupported task_type '{raw}'")
    return task_type


def _parse_job_status(raw: str) -> JobStatus:
    normalized = raw.strip().upper()
    mapping = {
        "QUEUED": JobStatus.QUEUED,
        "RUNNING": JobStatus.RUNNING,
        "COMPLETED": JobStatus.COMPLETED,
        "FAILED": JobStatus.FAILED,
        "CANCELLED": JobStatus.CANCELLED,
    }

    parsed = mapping.get(normalized)
    if parsed is None:
        raise HTTPException(status_code=422, detail=f"Unsupported status '{raw}'")
    return parsed


def _pick_node_for_task(task_type: TaskType) -> str | None:
    candidates: list[tuple[str, bool, float]] = []

    for node in get_nodes():
        eligible, _ = evaluate_node_eligibility(node, task_type)
        score = score_node(node, task_type)
        candidates.append((node.identity.node_id, eligible, score))

    candidates.sort(key=lambda item: (item[1], item[2]), reverse=True)
    chosen = next((candidate for candidate in candidates if candidate[1]), None)
    return chosen[0] if chosen is not None else None


@router.post("/jobs", response_model=Job, status_code=status.HTTP_201_CREATED)
async def create_job_route(
    payload: JobCreateRequest = Body(
        ...,
        examples={
            "embed": {
                "summary": "Create embedding job",
                "value": {
                    "task_type": "EMBED",
                    "payload_ref": "s3://bucket/chunk-001.json",
                },
            }
        },
    ),
) -> Job:
    """Create a job in QUEUED state.

    For Phase 1 this will also attempt a best-fit assignment using scheduler simulation.
    """

    task_type = _parse_task_type(payload.task_type)
    assigned_node_id = _pick_node_for_task(task_type)

    job = Job(
        id=f"job-{uuid.uuid4().hex[:12]}",
        type=task_type,
        status=JobStatus.QUEUED,
        payload_ref=payload.payload_ref,
        assigned_node_id=assigned_node_id,
    )
    return create_job(job)


@router.get("/jobs", response_model=list[Job])
async def list_jobs_route(
    status_filter: str | None = Query(default=None, alias="status"),
    task_type_filter: str | None = Query(default=None, alias="task_type"),
    node_id: str | None = Query(default=None),
) -> list[Job]:
    """List jobs with optional filters by status, task_type, and node_id."""

    status_value = (
        _parse_job_status(status_filter) if status_filter is not None else None
    )
    task_type_value = (
        _parse_task_type(task_type_filter) if task_type_filter is not None else None
    )
    return list_jobs(status=status_value, task_type=task_type_value, node_id=node_id)


@router.get("/jobs/{job_id}", response_model=Job)
async def get_job_route(job_id: str) -> Job:
    """Get a single job by id."""

    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return job


@router.post("/jobs/{job_id}/status", response_model=Job)
async def transition_job_status_route(
    job_id: str,
    payload: JobStatusUpdateRequest = Body(
        ...,
        examples={
            "running": {"summary": "Start job", "value": {"status": "RUNNING"}},
            "failed": {
                "summary": "Fail job",
                "value": {"status": "FAILED", "error": "GPU memory exhausted"},
            },
        },
    ),
) -> Job:
    """Update job status using enforced transition path QUEUED -> RUNNING -> COMPLETED/FAILED."""

    try:
        return transition_job_status(
            job_id=job_id, new_status=payload.status, error=payload.error
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail=f"Job '{job_id}' not found"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/demo/jobs/create-embed-burst", response_model=DemoJobBurstResponse)
async def create_embed_burst(
    count: int = Query(default=20, ge=1, le=200),
) -> DemoJobBurstResponse:
    """Create a demo burst of EMBED jobs and assign using scheduler simulation.

    This populates the jobs table with mixed statuses for dashboard demonstration.
    """

    jobs: list[Job] = []
    assigned_count = 0

    for index in range(count):
        assigned_node_id = _pick_node_for_task(TaskType.EMBEDDINGS)
        if assigned_node_id is not None:
            assigned_count += 1

        job = create_job(
            Job(
                id=f"job-{uuid.uuid4().hex[:12]}",
                type=TaskType.EMBEDDINGS,
                status=JobStatus.QUEUED,
                payload_ref=f"demo://embed/{index:04d}",
                assigned_node_id=assigned_node_id,
            )
        )

        if assigned_node_id is not None and index % 5 == 0:
            job = transition_job_status(job.id, JobStatus.RUNNING)
            job = transition_job_status(job.id, JobStatus.COMPLETED)
        elif assigned_node_id is not None and index % 7 == 0:
            job = transition_job_status(job.id, JobStatus.RUNNING)
            job = transition_job_status(
                job.id, JobStatus.FAILED, error="Synthetic demo failure"
            )
        elif assigned_node_id is not None and index % 2 == 0:
            job = transition_job_status(job.id, JobStatus.RUNNING)

        jobs.append(job)

    queued_count = sum(1 for item in jobs if item.status == JobStatus.QUEUED)
    running_count = sum(1 for item in jobs if item.status == JobStatus.RUNNING)
    completed_count = sum(1 for item in jobs if item.status == JobStatus.COMPLETED)
    failed_count = sum(1 for item in jobs if item.status == JobStatus.FAILED)

    return DemoJobBurstResponse(
        created_count=count,
        assigned_count=assigned_count,
        queued_count=queued_count,
        running_count=running_count,
        completed_count=completed_count,
        failed_count=failed_count,
        jobs=jobs,
    )
