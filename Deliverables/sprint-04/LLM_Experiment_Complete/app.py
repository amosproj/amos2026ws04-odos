"""ODOS 大模型验证 Demo 的 FastAPI 任务接口。"""

import logging
from pathlib import Path
from threading import Lock, Semaphore
from typing import Literal
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException, Response
from pydantic import BaseModel

# verifier 负责整理 RDF 事实并调用 DeepSeek。这里负责当接待处。
from verifier import InputError, ModelError, VerificationInput, prepare, verify

# FastAPI 根据这里注册的路由生成 API 和 /docs 测试页。
app = FastAPI(title="ODOS DEMO2 — LLM Verification", version="0.1.0")
log = logging.getLogger(__name__)
# 内存里最多留八个任务。服务器一重启，就彻底失忆。
MAX_JOBS = 8
jobs: dict[str, dict] = {}
# lock 保护共享的任务状态。worker 每次只让一个任务调用模型。
lock = Lock()
worker = Semaphore(1)
# 样例名只允许从这份名单里选。服务器硬盘没有开放自助参观。
SAMPLES = Path(__file__).resolve().parent / "samples"
Example = Literal["valid_boundary", "too_narrow", "missing_width", "roof_step_alternative",
                  "setback_boundary", "setback_too_small", "no_target"]


# 这里定义客户端看到的任务状态。完整报告有单独的接口。
class JobStatus(BaseModel):
    id: str
    status: Literal["queued", "processing", "completed", "failed"]
    stage: str | None = None
    message: str | None = None


# 首页是个路标，指向测试页和一个现成样例。
@app.get("/")
def index() -> dict:
    return {"demo": "ODOS LLM verification", "docs": "/docs", "example": "/api/examples/valid_boundary"}


# 这里只检查 FastAPI 能不能应答。DeepSeek 还没被点名。
@app.get("/health")
def health() -> dict:
    return {"status": "ok", "engine": "deepseek"}


# 读取 Turtle 样例，把它包成 POST /api/jobs 需要的 JSON。
@app.get("/api/examples/{name}", response_model=VerificationInput)
def example(name: Example) -> VerificationInput:
    return VerificationInput(
        profile="general_setback" if name.startswith("setback_") else "escape_window",
        rdf=(SAMPLES / f"{name}.ttl").read_text(encoding="utf-8"),
    )


# 接收验证任务并返回 ID。HTTP 202 是收件回执，窗户还没被判合格。
@app.post("/api/jobs", status_code=202, response_model=JobStatus)
def create_job(request: VerificationInput, tasks: BackgroundTasks) -> dict:
    # 先解析 RDF 并找出验证对象。没找到窗户，就不用花钱请模型找空气了。
    try:
        context = prepare(request)
    except InputError as exc:
        raise HTTPException(422, str(exc)) from exc
    job_id = uuid4().hex
    job = {"id": job_id, "status": "queued", "stage": "verification", "message": None}
    # 任务满了就淘汰最早登记的已结束任务。如果全在忙，就请调用方稍后再试。
    with lock:
        if len(jobs) >= MAX_JOBS:
            oldest_finished = next(
                (key for key, value in jobs.items() if value["status"] in {"completed", "failed"}), None
            )
            if oldest_finished is None:
                raise HTTPException(429, "The demo queue is full. Try again after a job completes.")
            jobs.pop(oldest_finished)
        jobs[job_id] = job
        # 把任务状态复制一份返回，后台可以继续更新原记录。
        snapshot = job.copy()
    # FastAPI 发完响应后才运行后台任务。拿返回的 ID 就能查进度。
    tasks.add_task(process, job_id, context)
    return snapshot


# 把任务从排队改为处理中，然后保存报告或错误消息。
def process(job_id: str, context: dict) -> None:
    with worker:
        with lock:
            job = jobs[job_id]
            job["status"] = "processing"
        # 调用模型时不占用状态锁，客户端仍然可以查进度。
        try:
            report = verify(context)
        # 已知的模型调用错误有可直接展示给客户端的提示。
        except ModelError as exc:
            with lock:
                job.update(status="failed", message=str(exc), stage=None)
        # 意外错误的详细信息留在服务器日志，客户端只收简短提示。
        except Exception:
            log.exception("Unexpected error while verifying job %s", job_id)
            with lock:
                job.update(status="failed", message="Verification failed unexpectedly.", stage=None)
        # completed 表示报告已出炉。窗户该不合格，还是不合格。
        else:
            with lock:
                job.update(status="completed", report=report, stage=None)


# 用提交时拿到的 ID 查询状态。404 表示服务端找不到这个任务。
@app.get("/api/jobs/{job_id}", response_model=JobStatus)
def get_job(job_id: str) -> dict:
    with lock:
        if job_id not in jobs:
            raise HTTPException(404, "Unknown job.")
        return jobs[job_id].copy()


# 任务完成后才能读报告。厨房还没出菜，服务员也端不出来。
@app.get("/api/jobs/{job_id}/files/verification_report.json")
def get_report(job_id: str) -> dict:
    with lock:
        if job_id not in jobs:
            raise HTTPException(404, "Unknown job.")
        job = jobs[job_id]
        if job["status"] != "completed":
            raise HTTPException(409, "This job has no verification report.")
        return job["report"]


# 从内存里删除已结束的任务。还在忙的任务先把活干完。
@app.delete("/api/jobs/{job_id}", status_code=204)
def delete_job(job_id: str) -> Response:
    with lock:
        if job_id not in jobs:
            raise HTTPException(404, "Unknown job.")
        if jobs[job_id]["status"] in {"queued", "processing"}:
            raise HTTPException(409, "Wait for the job to finish before deleting it.")
        jobs.pop(job_id)
    return Response(status_code=204)
