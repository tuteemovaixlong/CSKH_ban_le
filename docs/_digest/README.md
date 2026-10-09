# Digest layer

Digest là cache đọc nhanh, không phải nguồn chạy. Mỗi digest ghi rõ Sources, SHA, ngày sinh và citation file:line. Khi source hoặc SHA thay đổi, regenerate digest liên quan rồi cập nhật public docs.

## Code digests

[MODELS](code/MODELS.digest) · [PROMPTS](code/PROMPTS.digest) · [AGENTS](code/AGENTS.digest) · [TOOLS](code/TOOLS.digest) · [RAG](code/RAG.digest) · [EVAL](code/EVAL.digest) · [DATA](code/DATA.digest) · [INFRA](code/INFRA.digest) · [CONTRACTS](code/CONTRACTS.digest)

## Meta digests

[ACRONYMS](meta/ACRONYMS.digest) · [DECISIONS](meta/DECISIONS.digest) · [RISKS](meta/RISKS.digest)

## Quy tắc dùng

- Dùng digest để định hướng và trỏ về source gốc; không coi digest là runtime contract.
- Không điền giá trị còn thiếu bằng suy luận. Ghi `[UNVERIFIED]` và nêu source chưa có.
- Merged SHA sau G2 chưa được xác minh trong checkout hiện tại; digest dùng SHA local được ghi ở từng file.
