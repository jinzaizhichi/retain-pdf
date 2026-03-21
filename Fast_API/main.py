from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query

from .executor import list_jobs
from .executor import load_job
from .executor import status_payload
from .executor import submit_job
from .models import JobStatus
from .models import RunCaseRequest
from .models import RunMinerUCaseRequest
from .models import SubmitJobResponse


app = FastAPI(
    title="OCR Translation API",
    version="1.1.0",
    description="FastAPI wrapper around the stable OCR translation and MinerU pipelines.",
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/run-case", response_model=SubmitJobResponse)
async def run_case(request: RunCaseRequest) -> SubmitJobResponse:
    return submit_job("run-case", request.to_command(), request.model_dump())


@app.post("/v1/run-mineru-case", response_model=SubmitJobResponse)
async def run_mineru_case(request: RunMinerUCaseRequest) -> SubmitJobResponse:
    return submit_job("run-mineru-case", request.to_command(), request.model_dump())


@app.get("/v1/jobs/{job_id}", response_model=JobStatus)
async def get_job(job_id: str) -> JobStatus:
    try:
        return status_payload(load_job(job_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"job not found: {job_id}") from exc


@app.get("/v1/jobs", response_model=list[JobStatus])
async def get_jobs(limit: int = Query(default=20, ge=1, le=200)) -> list[JobStatus]:
    return [status_payload(record) for record in list_jobs(limit=limit)]
