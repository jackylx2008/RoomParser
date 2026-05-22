from __future__ import annotations

from pathlib import Path

from room_extractor.export.review_task_html_exporter import build_review_task_html, export_review_task_html
from room_extractor.models.issue import Issue
from room_extractor.models.review_task import ReviewTask, ReviewTaskSet


def test_build_review_task_html_contains_machine_review_context() -> None:
    tasks = ReviewTaskSet(
        source_file="sample.dxf",
        rooms_source_file="sample.pdf",
        summary={
            "room_count": 2,
            "task_count": 1,
            "auto_pass_count": 1,
            "priority_counts": {"high": 1},
            "ai_needs_review_counts": {"True": 1},
        },
        tasks=[
            ReviewTask(
                task_id="review_task_0001",
                room_uid="sample_r0001",
                floor="L2",
                room_number="201",
                room_name="会议室",
                area_text_value=25.0,
                confidence={"overall": 0.7},
                priority="high",
                reasons=["本地 AI 建议复核：面积不一致"],
                issue_codes=["PDF_AREA_MISMATCH"],
                issues=[
                    Issue(
                        issue_code="PDF_AREA_MISMATCH",
                        severity="medium",
                        field="area",
                        message="面积不一致",
                        need_manual_review=True,
                    )
                ],
                local_ai_check={
                    "status": "ok",
                    "visible": True,
                    "area_match": False,
                    "needs_review": True,
                    "confidence": 0.6,
                    "notes": "面积不一致",
                },
                review_image_path="data/output/review_images/sample.png",
                bbox_cad=(0, 0, 10, 10),
                polygon_cad=[(0, 0), (10, 0), (10, 10), (0, 10)],
                suggested_fields=["area"],
            )
        ],
    )

    html = build_review_task_html(tasks, out_path="data/output/reports/review_tasks.html")

    assert "正式人工审核任务" in html
    assert "PDF/OCR/AI 机器校核后的正式人工审核队列" in html
    assert "总图：全链路识别后进入人工校核的房间分布" in html
    assert "overview-map" in html
    assert "overview-room high" in html
    assert "会议室" in html
    assert "PDF_AREA_MISMATCH" in html
    assert "../review_images/sample.png" in html


def test_export_review_task_html_writes_file(tmp_path: Path) -> None:
    tasks = ReviewTaskSet(source_file="sample.dxf", tasks=[])
    out = export_review_task_html(tasks, tmp_path / "review.html")

    assert out.exists()
    assert "正式人工审核任务" in out.read_text(encoding="utf-8")
