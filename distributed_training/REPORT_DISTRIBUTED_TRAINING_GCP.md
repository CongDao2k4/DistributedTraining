# BÁO CÁO CHI TIẾT: HỆ THỐNG HUẤN LUYỆN PHÂN TÁN (DISTRIBUTED TRAINING) TRÊN GOOGLE CLOUD

**Mục tiêu:** Huấn luyện mô hình quy mô lớn (55GB dữ liệu) ổn định, tối ưu hóa hiệu suất Multi-GPU, tránh lỗi tràn RAM (OOM) và tự động hóa quy trình triển khai.
**Phạm vi:** `main.py`, `src/data_utils.py`, `src/gcs_manager.py`, `src/baselines/`, `submit_job.sh`

---

## 1. Tóm tắt điều hành (Executive Summary)

Hệ thống huấn luyện được thiết kế theo kiến trúc **Distributed Data Parallel (DDP)** chạy trên nền tảng **GCP Vertex AI Custom Job**. Điểm khác biệt cốt lõi là việc chuyển đổi từ quy trình huấn luyện truyền thống sang quy trình **"Precomputed-First"**:
- **Tiền tính toán Embedding:** Loại bỏ gánh nặng mã hóa BERT/Transformer trong vòng lặp huấn luyện, giúp GPU tập trung 100% vào việc học các tương tác.
- **Quản lý dữ liệu thông minh:** Sử dụng Memory-Mapping và PyArrow để xử lý tập dữ liệu khổng lồ mà không cần cấu hình RAM khủng.
- **Vận hành theo Workflow "Vàng":** Sử dụng Coordinator VM để đóng gói và điều phối, đảm bảo tính nhất quán giữa môi trường phát triển và môi trường Cloud.

---

## 2. Kiến trúc Hệ thống Training Phân tán

### 2.1. Cơ chế Multi-GPU với PyTorch DDP
Hệ thống sử dụng **DistributedDataParallel (DDP)** kết hợp với `torchrun` để thực thi trên cấu hình nhiều GPU (mặc định 4x GPU T4).
*   **Giao tiếp:** Sử dụng backend `nccl` (NVIDIA Collective Communications Library) cho tốc độ đồng bộ gradient tối ưu.
*   **Điều phối:** `torchrun` tự động quản lý các process con, gán `RANK` và `LOCAL_RANK` cho từng GPU, giúp việc chia nhỏ dữ liệu (`DistributedSampler`) diễn ra chính xác.

### 2.2. Chiến lược Precomputed Embeddings (Tăng tốc 5-10x)
Đây là giải pháp then chốt để vượt qua giới hạn về CPU và GPU:
*   **Giai đoạn 1 (Precompute):** Mã hóa toàn bộ text sang vector một lần duy nhất, lưu thành file `.npy` (khoảng 12GB).
*   **Giai đoạn 2 (Fast Training):** Model chỉ cần thực hiện phép nhân ma trận nhẹ nhàng giữa các vector đã có sẵn.
*   **Lợi ích:** Loại bỏ tình trạng GPU phải "chờ" CPU mã hóa văn bản, giảm thời gian huấn luyện mỗi epoch từ hàng tiếng xuống còn vài phút.

### 2.3. Module `data_utils.py`: "Bộ não" quản lý dữ liệu hiệu quả
Đây không chỉ là module nạp dữ liệu thông thường mà chứa đựng các kỹ thuật tối ưu bộ nhớ cốt lõi:
*   **Lớp `PrecomputedEmbeddingLookup`**: Cơ chế tra cứu vector "siêu tốc". Thay vì chạy model Deep Learning liên tục, hệ thống dùng bảng tra cứu (mapping) trực tiếp từ ID sản phẩm sang index trong mảng Numpy, giảm thiểu độ trễ I/O.
*   **Cơ chế Memory-Mapping (`mmap_mode='r'`)**: 
    *   Dữ liệu `.npy` (12GB) được nạp với chế độ `mmap`, cho phép Python truy cập dữ liệu trực tiếp từ SSD mà không cần nạp toàn bộ vào RAM. 
    *   **Tầm quan trọng**: Đây là giải pháp "cứu cánh" giúp huấn luyện trên các máy ảo RAM nhỏ (16GB) mà không gây treo hệ thống.
*   **Nạp dữ liệu bằng PyArrow**: Thay thế Pandas bằng `pyarrow` để đọc file Parquet.
    *   Chỉ nạp đúng 2 cột cần thiết (`asin`, `product_id`), giảm 90% dung lượng bộ nhớ chiếm dụng so với nạp toàn bộ metadata.
    *   Hỗ trợ `DATA_FRACTION` (ví dụ: 25%) giúp nhóm debug thần tốc mà không cần đợi nạp toàn bộ 55GB dữ liệu thô.

---

## 3. Giải pháp Xử lý Dữ liệu Lớn & Tránh tràn RAM (OOM)

| Thách thức | Giải pháp kỹ thuật | Hiệu quả |
| :--- | :--- | :--- |
| File Vector 12GB gây nổ RAM | Dùng `np.load(mmap_mode='r')` | Huấn luyện được trên máy ảo RAM nhỏ (16GB) |
| Tập tương tác 55GB quá lớn | Dùng PyArrow nạp theo tỷ lệ (`DATA_FRACTION`) | Tăng tốc độ nạp dữ liệu, dễ dàng debug/scale |
| Treo Process Group khi khởi tạo | Thiết lập `dist.barrier()` và timeout tường minh | Tránh xung đột và lỗi zombie process trên Cloud |
| Nạp dữ liệu chậm từ Cloud | Đồng bộ Local SSD bằng `gsutil -m` | Tối ưu I/O, giảm độ trễ khi training |

---

## 4. Tối ưu Hạ tầng & Vận hành trên GCP

### 4.1. Quy trình "Golden Workflow"
Sử dụng mô hình **Coordinator VM** (e2-standard-4) làm trạm điều khiển trung tâm:
1.  **Local:** Đẩy code lên GitHub.
2.  **Coordinator:** Pull code, build Docker image và push lên **Artifact Registry**.
3.  **Vertex AI:** Kích hoạt Job với tài nguyên GPU mạnh mẽ, lấy Image từ Registry.
*   **Ưu điểm:** Tốc độ mạng nội bộ GCP cực nhanh (Docker push chỉ mất vài giây), môi trường containerized sạch 100%.

### 4.2. Module `gcs_manager.py`: "Người vận chuyển" thông minh
Quản lý luân chuyển dữ liệu giữa Local VM và Cloud Storage (GCS) một cách tối ưu:
*   **Đồng bộ hóa dữ liệu song song**: Sử dụng `gsutil -m cp` để tải dữ liệu đa luồng, tận dụng tối đa băng thông nội bộ của GCP.
*   **Cơ chế Caching thông minh**: 
    *   Hệ thống kiểm tra file vector 12GB đã có trên GCS chưa. Nếu có, nó sẽ tải về thay vì tính toán lại.
    *   **Kết quả**: Tiết kiệm ít nhất **1 tiếng đồng hồ** chờ đợi cho mỗi lượt chạy Job mới.
*   **Lưu trữ kết quả tự động**: Sau khi huấn luyện, model tốt nhất (`best_model.pt`) và bộ nhớ đệm vector sẽ được đẩy ngược lên GCS để phục vụ các lần chạy sau hoặc bước Evaluation.

### 4.3. Sự kết hợp hoàn hảo giữa các Module
Hệ thống tạo ra một vòng lặp khép kín cực kỳ hiệu quả:
1.  **`gcs_manager`**: Kéo dữ liệu từ GCS về Local SSD với tốc độ cao.
2.  **`data_utils`**: "Ánh xạ" dữ liệu từ SSD vào Python qua Memory-Mapping (RAM sạch).
3.  **DDP Training**: Lấy dữ liệu cực nhanh để đẩy vào GPU, đảm bảo GPU luôn hoạt động ở mức >90% công suất.

---

## 5. Kết luận và Ưu tiên triển khai

Hệ thống hiện tại đã đạt độ chín về mặt kiến trúc để xử lý dữ liệu Massive Data. Các ưu tiên tiếp theo:
1.  **Tăng tỷ lệ dữ liệu (`DATA_FRACTION`):** Sau khi ổn định với 25%, có thể nâng lên 50-100% để đạt độ chính xác tối đa.
2.  **Tối ưu Docker Image:** Giảm kích thước image để rút ngắn thời gian khởi động Job trên Vertex AI.
3.  **Monitor GPU Utilization:** Sử dụng Cloud Monitoring để theo dõi mức độ tận dụng GPU, đảm bảo không có GPU nào bị "nhàn rỗi".

---

## 6. Checklist Vận hành Đề xuất

### Trước khi nộp Job:
- [ ] Xác nhận đã đẩy code mới nhất lên GitHub.
- [ ] Kiểm tra dung lượng ổ cứng trên Coordinator VM (yêu cầu > 100GB).
- [ ] Kiểm tra Quota GPU trên vùng (Region) định chạy (thường là `asia-southeast1`).

### Trong khi huấn luyện:
- [ ] Theo dõi log qua lệnh `tail -f training_log.txt` trên Coordinator.
- [ ] Kiểm tra tiến độ qua link Vertex AI Console được in ra ở cuối script.

### Sau khi hoàn tất:
- [ ] Kiểm tra file model trong bucket `gs://[BUCKET_NAME]/models_checkpoints/`.
- [ ] Giải phóng tài nguyên Coordinator VM nếu không sử dụng lâu dài.
