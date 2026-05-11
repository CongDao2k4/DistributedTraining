# Tài liệu chung cho Huấn luyện trên Google Cloud

Tài liệu này chứa các thông tin nền tảng, cấu hình bắt buộc và kiến thức chuyên sâu áp dụng cho mọi phương pháp huấn luyện trong hệ thống.

## 1. Checklist chuẩn bị trên Google Cloud (Bắt buộc)

Trước khi chạy bất kỳ script nào, bạn cần thực hiện các bước sau trên Console của Google Cloud:

1.  **Bật Billing**: Đảm bảo Project đã được liên kết với thẻ thanh toán.
2.  **Kích hoạt API**:
    ```bash
    gcloud services enable aiplatform.googleapis.com artifactregistry.googleapis.com compute.googleapis.com
    ```
3.  **Tạo Artifact Registry**:
    - Vào Console -> **Artifact Registry** -> **Repositories**.
    - Tạo một Repository mới:
        - Name: `recsys-repo` (Khớp với `submit_job.sh`).
        - Format: `Docker`.
        - Region: `asia-southeast1` (Hoặc vùng bạn chọn).
4.  **Kiểm tra GPU Quota**:
    - Vào **IAM & Admin** -> **Quotas**.
    - Tìm: `Vertex AI Training GPUs` (loại NVIDIA_TESLA_T4 hoặc NVIDIA_L4).
    - Đảm bảo "Limit" lớn hơn hoặc bằng số GPU bạn định dùng. Nếu là 0, hãy bấm **Edit Quotas** để yêu cầu tăng lên.
    - Tại thanh Filter (Bộ lọc), bạn gõ: `Vertex AI Custom Model Training` hoặc `Vertex AI Training GPUs`.
    - hoặc Bạn tìm kiếm đến đúng dòng tên là: `Custom model training Nvidia T4 GPUs per region` (nếu bạn dùng T4) và kiểm tra xem cột `Limit` (Giới hạn) đang là 0 hay 1.

5.  **Cấu hình Docker Local**:
    ```bash
    gcloud auth configure-docker us-central1-docker.pkg.dev
    ```

## 2. Kiến trúc Hệ thống
Hệ thống được thiết kế để xử lý dữ liệu tương tác lớn (55GB) và thực hiện đánh giá trên bộ Evaluation Dataset (.pkl).
- **Phần cứng**: Khuyên dùng 1-4 GPU (L4 hoặc T4) trên mỗi Instance.
- **Phần mềm**: PyTorch DDP (Distributed Data Parallel) + `torchrun`.
- **Dữ liệu**: Lưu trữ trên GCS (`gs://mining-data-2/`).

## 3. Danh sách 6 Mô hình (Baselines)
| ID | Model | File | Thiết bị | Trạng thái |
| :--- | :--- | :--- | :--- | :--- |
| 1 | BM25 + Category | `bm25_ranker.py` | CPU/GPU (Phân tán) | Sẵn sàng |
| 2 | SBERT (mpnet) | `sbert_ranker.py` | Full GPU | Sẵn sàng |
| 3 | DSSM (Two-Tower) | `dssm_trainer.py` | Full GPU (Training) | Sẵn sàng |
| 4 | GCN (Graph) | `gcn_trainer.py` | Full GPU (Training) | Bản nháp |
| 5 | Hybrid (B1+B2+Attr) | `hybrid_ranker.py` | Full GPU | Sẵn sàng |
| 6 | LLM-CHGNN (Proposed) | `llm_chgnn_trainer.py` | Full GPU (Training) | Đang phát triển |

## 4. Quản lý Dữ liệu và Model Checkpoint
- **Dữ liệu đầu vào**: Hệ thống tự động tải `.pkl` từ GCS về thư mục `output/` nội bộ.
- **Dữ liệu lớn (55GB)**: Được đọc theo dạng stream (itertuples) trong `data_utils.py` để không làm tràn RAM.
- **Checkpoint**: Model tốt nhất (`best_model.pt`) sẽ được lưu tại `models/` và tự động upload ngược lên GCS sau khi hoàn tất.

## 5. Lưu ý Quan trọng
- **GPU Quota**: Nếu không đủ quota đa GPU, hãy dùng `--nproc_per_node=1`.
- **Memory**: Nếu gặp lỗi OOM (Out of Memory), hãy giảm `batch_size` trong file `TrainingConfig`.
- **Attribute Matching**: Baseline 5 và 6 yêu cầu cột `parsed_specs`. Hãy đảm bảo đã chạy `prepare_eval_pkl.py` trước đó.

## 6. Xử lý lỗi thường gặp (Troubleshooting)
- **Lỗi 403 (Permission)**: Hãy đảm bảo tài khoản của bạn có quyền `Vertex AI User` và `Storage Admin`.
- **Lỗi Image Not Found**: Đảm bảo lệnh `docker push` thành công và `IMAGE_URI` trong script chính xác.
- **Lỗi Quota (Resource Exhausted)**: 
    - Google Cloud thường giới hạn GPU cho tài khoản mới. Bạn cần vào phần **IAM & Admin > Quotas** để yêu cầu tăng quota cho `Vertex AI Training GPUs`.
    - Nếu không thể tăng quota, hãy thử đổi `REGION` sang các vùng ít bận rộn hơn.
- **Lỗi OOM (Out of Memory)**: Tăng loại máy (`machine-type`) hoặc giảm `BATCH_SIZE` trong `TrainingConfig`.

## 7. Cấu trúc Dự án và Luồng vận hành (Technical Deep Dive)

### 7.1. Cấu trúc thư mục chuẩn
```text
distributed_training/
├── main.py                # File điều phối chính (Coordinater)
├── Dockerfile             # "Bản thiết kế" để đóng gói toàn bộ code
├── requirements.txt       # Danh sách thư viện cần cài đặt
├── submit_job.sh          # Script gửi lệnh lên Cloud
├── config/
│   └── training_config.py # Nơi lưu mọi cấu hình (GCS Path, Batch Size, Epochs)
├── src/
│   ├── baselines/         # Chứa 6 model (BM25, SBERT, DSSM, ...)
│   ├── data_utils.py      # Bộ máy nạp dữ liệu (Xử lý file 55GB)
│   ├── models.py          # Định nghĩa kiến trúc Neural Network (DSSM, CHGNN)
│   └── gcs_manager.py     # Quản lý việc tải/đẩy file với Google Cloud Storage
└── output/                # (Tự động tạo) Nơi lưu dữ liệu .pkl tạm thời
```

### 7.2. Luồng dữ liệu (GCS -> Training)
Đây là cách hệ thống xử lý dữ liệu khổng lồ:
1.  **Khởi động**: `main.py` chạy -> Gọi `download_training_data()`.
2.  **Tải Eval Set**: Chỉ file `.pkl` nhỏ được tải về máy ảo để dùng cho việc đánh giá nhanh.
3.  **Nạp Interaction (55GB)**: Thay vì tải toàn bộ, `src/data_utils.py` sử dụng thư viện `fsspec` và `pyarrow` để **đọc trực tiếp** từ GCS theo từng dòng hoặc từng khối nhỏ (streaming). Điều này giúp máy ảo chỉ có 15-30GB RAM vẫn xử lý được file 55GB mà không bị sập.
