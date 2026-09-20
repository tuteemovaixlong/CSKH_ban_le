# BÁO CÁO KẾT QUẢ ĐO BENCHMARK EVALUATION — RETAILOPS 2026
> **Thời gian thực hiện**: `2026-09-20T08:05:26.086593+00:00`  
> **Tệp kịch bản kiểm thử**: `benchmark_250.jsonl`  
> **Tổng số ca thử nghiệm**: `250` ca  

---

## 1. TỔNG QUAN CHỈ SỐ ĐỊNH LƯỢNG (DÀNH CHO CHƯƠNG 4 LUẬN VĂN)

| Chỉ số đo lường (Metrics) | Giá trị đạt được | Đánh giá học thuật |
| :--- | :---: | :--- |
| **Tỷ lệ vượt qua (Accuracy)** | **100.0%** (250/250) | Độ chính xác định tuyến & guardrails |
| **Thời gian phản hồi Trung vị (p50)** | **0.1 ms** | Tốc độ phân luồng tức thì (< 5ms) |
| **Đuôi trễ tối đa (p95)** | **0.15 ms** | Đảm bảo không nghẽn luồng |
| **Độ trễ trung bình (Average)** | **0.11 ms** | Hiệu năng ổn định |

---

## 2. KẾT QUẢ CHI TIẾT THEO TỪNG NHÓM NGHIỆP VỤ

| Nhóm nghiệp vụ (`category`) | Số ca kiểm thử | Đạt (Passed) | Độ chính xác (%) |
| :--- | :---: | :---: | :---: |
| `general` | 15 | 15 | **100.0%** |
| `mixed` | 40 | 40 | **100.0%** |
| `order_lookup` | 65 | 65 | **100.0%** |
| `policy` | 35 | 35 | **100.0%** |
| `product` | 35 | 35 | **100.0%** |
| `safety` | 60 | 60 | **100.0%** |

---

## 3. PHÂN TÍCH CÁC CA THẤT BẠI (FAILURE ANALYSIS & ABLATION)

🎉 **Không có ca nào thất bại! Hệ thống đạt độ chính xác 100% trên tập thử nghiệm.**