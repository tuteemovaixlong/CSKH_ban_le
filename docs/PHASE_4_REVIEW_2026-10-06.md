# Phase 4 — Snapshot lịch sử review 2026-10-06

> **Superseded**, cập nhật cô đọng ngày 2026-10-07. Nguồn review hiện hành duy nhất: [REVIEW_PHASE_4_PLAN.md](phase4/REVIEW_PHASE_4_PLAN.md).

## Bước sửa nhỏ theo yêu cầu owner

Owner yêu cầu Astra xhigh sửa specification R10–R12 và chốt mitigation R13 trước BUILD. Lượt docs 2026-10-07 đã áp dụng R10–R12 ở mức CLOSED(spec), giữ R13 OPEN cho tới khi guard được Gemini triển khai/test trong PR.

## Prompt trigger Gemini sau lượt sửa nhỏ

~~~text
Gemini Antigravity: BUILD HARNESS offline/local theo docs/phase4/REVIEW_PHASE_4_PLAN.md (review 2026-10-07), đóng R10–R13 trong implementation PR, chạy offline acceptance/clean-checkout replay và CI. Mở PR, báo kết quả và dừng chờ owner review trước merge. Giữ runtime/frozen benchmark; không paid/cloud/deploy/live smoke/full measurement.
~~~

## Lịch sử và kết quả re-review

Review trước tìm thấy bốn mâu thuẫn chính: whole-report schema áp sai lên JSONL; scope cấm code cản BUILD HARNESS; vLLM dùng nhầm custom /agent/*; gate paid-smoke có dependency cycle. Astra đã sửa contract raw riêng, scope evaluation tooling, system/harness/overlay identity, topology provider_id=api, G0–G7, first-attempt primary, cache OFF và phân kỳ 4A/4B.

Review lại trên runtime SHA 49671b928ad6badfaa01331174eb73f0e366752e: specification đủ để BUILD offline/local; R10–R12 đã được chốt ở mức spec, R13 vẫn OPEN implementation/pre-merge. Chưa nghiệm thu harness, merge, live smoke hay measurement.

Local contracts, hai frozen validators/hashes, notebook sync và offline no-model handoff probe đạt. Ba JSONL examples parse/keys đạt; chưa có executable schemas/full-bundle validation. Không coi checks PASS là evidence live quality.

## Recommendation

Lượt tiếp theo: Gemini BUILD HARNESS → mở PR → CI/clean replay → dừng chờ owner review trước merge. Không tự chuyển sang measurement.
