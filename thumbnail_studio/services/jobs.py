from __future__ import annotations

import copy
import logging
import os
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4


TERMINAL_JOB_STATUSES = {"completed", "partial", "failed"}
logger = logging.getLogger(__name__)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def format_failure_log(exc: Exception) -> str:
    details = getattr(exc, "log_details", "").strip()
    trace = traceback.format_exc().strip()
    sections = [
        "Summary",
        str(exc),
    ]
    if details:
        sections.extend(
            [
                "",
                "Context",
                details,
            ]
        )
    if trace:
        sections.extend(
            [
                "",
                "Traceback",
                trace,
            ]
        )
    return "\n".join(sections)


class TransformJobStore:
    def __init__(self, *, max_workers: int | None = None) -> None:
        worker_count = max_workers or max(1, int(os.getenv("TRANSFORM_JOB_WORKERS", "2")))
        self._executor = ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="thumbnail-transform",
        )
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}

    def create_transform_job(
        self,
        *,
        prompt: str,
        videos: list[dict[str, Any]],
        runner: Callable[[dict[str, Any], str], dict[str, Any]],
    ) -> dict[str, Any]:
        job_id = uuid4().hex
        snapshot = {
            "jobId": job_id,
            "status": "queued",
            "message": f"Queued {len(videos)} thumbnail transform(s).",
            "prompt": prompt,
            "videoIds": [str(item.get("id", "")).strip() for item in videos if str(item.get("id", "")).strip()],
            "currentVideoId": None,
            "currentVideoTitle": None,
            "totalCount": len(videos),
            "completedCount": 0,
            "successCount": 0,
            "failureCount": 0,
            "processed": [],
            "failed": [],
            "createdAt": utc_now_iso(),
            "updatedAt": utc_now_iso(),
        }

        with self._lock:
            self._jobs[job_id] = snapshot

        self._executor.submit(self._run_job, job_id, prompt, videos, runner)
        logger.info("Async transform job queued job_id=%s count=%s", job_id, len(videos))
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            snapshot = self._jobs.get(job_id)
            if snapshot is None:
                return None
            return copy.deepcopy(snapshot)

    def _update_job(self, job_id: str, **changes: Any) -> None:
        with self._lock:
            snapshot = self._jobs.get(job_id)
            if snapshot is None:
                return
            snapshot.update(changes)
            snapshot["updatedAt"] = utc_now_iso()

    def _run_job(
        self,
        job_id: str,
        prompt: str,
        videos: list[dict[str, Any]],
        runner: Callable[[dict[str, Any], str], dict[str, Any]],
    ) -> None:
        self._update_job(
            job_id,
            status="running",
            message="Preparing Gemini 4K generation.",
        )
        logger.info("Async transform job running job_id=%s count=%s", job_id, len(videos))

        processed: list[dict[str, Any]] = []
        failed: list[dict[str, str]] = []
        total_count = len(videos)

        for index, item in enumerate(videos, start=1):
            video_id = str(item.get("id", "")).strip()
            video_title = str(item.get("title", "")).strip()

            self._update_job(
                job_id,
                status="running",
                currentVideoId=video_id or None,
                currentVideoTitle=video_title or None,
                message=f"Processing {index} of {total_count}.",
                processed=processed,
                failed=failed,
                completedCount=len(processed) + len(failed),
                successCount=len(processed),
                failureCount=len(failed),
            )

            if not video_id:
                failed.append(
                    {
                        "videoId": "",
                        "message": "A selected video is missing its id.",
                    }
                )
                self._update_job(
                    job_id,
                    processed=processed,
                    failed=failed,
                    completedCount=len(processed) + len(failed),
                    successCount=len(processed),
                    failureCount=len(failed),
                )
                continue

            try:
                result = runner(item, prompt)
                processed.append(result)
                self._update_job(
                    job_id,
                    processed=processed,
                    failed=failed,
                    completedCount=len(processed) + len(failed),
                    successCount=len(processed),
                    failureCount=len(failed),
                    message=f"Uploaded {len(processed)} of {total_count} thumbnail(s).",
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Async transform job failed job_id=%s video_id=%s", job_id, video_id)
                failed.append(
                    {
                        "videoId": video_id,
                        "message": str(exc),
                        "log": format_failure_log(exc),
                    }
                )
                self._update_job(
                    job_id,
                    processed=processed,
                    failed=failed,
                    completedCount=len(processed) + len(failed),
                    successCount=len(processed),
                    failureCount=len(failed),
                    message=f"{len(failed)} thumbnail(s) failed so far.",
                )

        success_count = len(processed)
        failure_count = len(failed)
        if success_count and failure_count:
            status = "partial"
            message = f"{success_count} thumbnails uploaded, {failure_count} failed."
        elif success_count:
            status = "completed"
            message = f"{success_count} thumbnails uploaded to YouTube."
        else:
            status = "failed"
            message = "No selected thumbnail could be updated."

        self._update_job(
            job_id,
            status=status,
            message=message,
            currentVideoId=None,
            currentVideoTitle=None,
            processed=processed,
            failed=failed,
            completedCount=total_count,
            successCount=success_count,
            failureCount=failure_count,
        )
        logger.info(
            "Async transform job finished job_id=%s status=%s success=%s failure=%s",
            job_id,
            status,
            success_count,
            failure_count,
        )
