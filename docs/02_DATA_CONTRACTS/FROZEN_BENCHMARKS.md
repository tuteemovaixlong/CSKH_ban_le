# Frozen Benchmarks

> Nguồn: [DATA.digest](../_digest/code/DATA.digest), [CONTRACTS.digest](../_digest/code/CONTRACTS.digest). Snapshot local `8a666fcce464c96b1dd5fc6848a2d4168c6505d1`, ngày 2026-10-08; merged SHA sau G2 [UNVERIFIED] theo [acceptance:104](../phase4/PHASE_4_ACCEPTANCE_CRITERIA.md#L104).

## 1. Hai frozen250files

| File | Cases / dev / held_out | LF SHA-256 | Raw checkout SHA-256 | Digest + nguồn gốc |
|---|---|---|---|---|
| benchmark_250.jsonl |250/150/100|`36fa8c7a52a60323bb4f04d11f1e677106ddfe6a35e0ccac3266784c7c6e4411`|`81f64611eb09eb4d319a29257e9c456fbffff07779182b130832fd7780062105`| [DATA §2](../_digest/code/DATA.digest#2-scenario-inventory--local-computation) + [benchmark:1](../../evals/scenarios/benchmark_250.jsonl#L1), [constants.py:30](../../evals/harness/constants.py#L30) |
| master_250_v1.jsonl |250/150/100|`36fa8c7a52a60323bb4f04d11f1e677106ddfe6a35e0ccac3266784c7c6e4411`|`81f64611eb09eb4d319a29257e9c456fbffff07779182b130832fd7780062105`| [DATA §2](../_digest/code/DATA.digest#2-scenario-inventory--local-computation) + [master:1](../../evals/scenarios/master_250_v1.jsonl#L1), [infra:13](../phase4/PHASE_4_INFRASTRUCTURE_SPEC.md#L13) |

Counts và raw hashes được tính trực tiếp trên checkout local. Hai file có250ID/text/whole-row trùng và được plan gọi là mirror; không cộng thành500ca độc lập. Nguồn: [DATA §2/6](../_digest/code/DATA.digest#6-exact-overlap--local-computation) + [benchmark:1](../../evals/scenarios/benchmark_250.jsonl#L1), [master:1](../../evals/scenarios/master_250_v1.jsonl#L1), [plan:11](../phase4/PLAN_PHASE_4_EVALUATION.md#L11).

## 2. LF normalization đang dùng

Biểu thức dưới đây trích runner, với `read_text` giữ universal newline conversion của Python; không trim nội dung hay thêm final newline: [DATA §1](../_digest/code/DATA.digest#1-phương-pháp-tính-local) + [runner.py:137](../../evals/harness/runner.py#L137).

```python
raw_text = benchmark_path.read_text(encoding="utf-8")
lf_text = raw_text.replace("\r\n", "\n")
dataset_sha256 = hashlib.sha256(lf_text.encode("utf-8")).hexdigest()
```

Raw-byte hashing đọc binary và không chuẩn hóa line endings; dùng cho artifact checksums. Do đó raw checkout hashes trong §1 không thay được frozen LF hash. Nguồn: [DATA §1](../_digest/code/DATA.digest#1-phương-pháp-tính-local) + [writer.py:23](../../evals/harness/writer.py#L23), [runner.py:137](../../evals/harness/runner.py#L137).

## 3. Các pins khác

| Input | Canonical hash | Raw file hash tính local | Digest + code/data gốc |
|---|---|---|---|
| policy_qrels_v1.json |`769a45d682648290a3356dad32aacae3c62f6942b62844dd4cc50f2d83c15161` (text/LF)|`ec2e2b37ffe3ae195a4ea42ad4c45964c00ab8b3eb743dccffdc07c0749fc1ee`| [DATA §3](../_digest/code/DATA.digest#3-sidecarqrels-inventory--local-computation) + [constants.py:31](../../evals/harness/constants.py#L31), [qrels.py:90](../../evals/harness/qrels.py#L90), [qrels:1](../../evals/qrels/policy_qrels_v1.json#L1) |
| Sidecar250 canonical serialization |`69e9835d3f4c63a2466d6ab08749737dcf59de65f2c22713372bd66b19bb3f2d`|`4501df7787e07d198d6a6aeafb3a29af62d45265f67017ea75268034b820aa15` (fixture file)| [DATA §3](../_digest/code/DATA.digest#3-sidecarqrels-inventory--local-computation) + [constants.py:32](../../evals/harness/constants.py#L32), [sidecar.py:102](../../evals/harness/sidecar.py#L102), [fixture:1](../../evals/fixtures/sidecar_250.json#L1) |
| baseline30 |`d41a90b8cf34efa2f938c712f17738417f7ebc36c4bd5045e6b3199e4ea0d14d` (LF local inventory)|`64a4599b83d98436a673aeb372614386f17da71144d50c2cfa4aa41390611b16`| [DATA §2](../_digest/code/DATA.digest#2-scenario-inventory--local-computation) + [baseline:1](../../evals/scenarios/baseline_v1.jsonl#L1) |

Sidecar canonical hash là `json.dumps(...,indent=2,sort_keys=True,ensure_ascii=False)` không final newline; LF fixture-file hash còn khác (`496d29db3b1da8d36f8361dfd1f011d4fa2004d315f3c5d61a89256ea1225d68`). Nguồn: [DATA §1/3](../_digest/code/DATA.digest#3-sidecarqrels-inventory--local-computation) + [sidecar.py:102](../../evals/harness/sidecar.py#L102).

## 4. Enforcement và boundary đã chốt

Runner reject actual LF source mismatch trước emit; manifest schema reject declared dataset hash khác constant. Validator replay rehash nguồn benchmark bị sửa thủ công được defer theo acceptance v1, không ghi là đã fixed: [CONTRACTS §3/5](../_digest/code/CONTRACTS.digest#3-r12--schemajoinsprovenance) + [runner.py:137](../../evals/harness/runner.py#L137), [schema.py:158](../../evals/harness/schema.py#L158), [validator.py:380](../../evals/harness/validator.py#L380), [acceptance:24](../phase4/PHASE_4_ACCEPTANCE_CRITERIA.md#L24).

Không sửa frozen datasets trong lượt re-organize. Hash/counts trên chỉ là identity dữ liệu, không là score model hoặc G5: [DATA §2](../_digest/code/DATA.digest#2-scenario-inventory--local-computation), [CONTRACTS §5](../_digest/code/CONTRACTS.digest#5-k1k8--frozen-acceptance-v1) + [constants.py:30](../../evals/harness/constants.py#L30), [acceptance:62](../phase4/PHASE_4_ACCEPTANCE_CRITERIA.md#L62).

## 5. Unknown / Unverified

- [UNVERIFIED] Creator/creation timestamp/annotation provenance không có trong scanned input metadata. [DATA §7](../_digest/code/DATA.digest#7-unknown--unverified) + [master:1](../../evals/scenarios/master_250_v1.jsonl#L1), [qrels:1](../../evals/qrels/policy_qrels_v1.json#L1).
- [UNVERIFIED] Merged-G2 identity và live DB/KB hash chưa được xác minh. [DATA §7](../_digest/code/DATA.digest#7-unknown--unverified) + [acceptance:104](../phase4/PHASE_4_ACCEPTANCE_CRITERIA.md#L104), [infra:64](../phase4/PHASE_4_INFRASTRUCTURE_SPEC.md#L64).

Đọc tiếp: [data contract](DATA_CONTRACT.md), [contamination](../01_AI_SYSTEM/AI_CONTAMINATION_ANALYSIS.md), [protocol](../03_EVALUATION/EVALUATION_PROTOCOL.md).
