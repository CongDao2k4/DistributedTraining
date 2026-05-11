# Cách 3: Triển khai chuyên nghiệp trên Vertex AI

Vertex AI cho phép bạn chạy huấn luyện trên các máy chủ GPU mạnh mẽ mà không cần tự quản lý VM. Hệ thống sẽ tự động cấp phát tài nguyên, chạy training và thu hồi tài nguyên sau khi xong (giúp tiết kiệm chi phí tối đa).

> [!IMPORTANT]
> Đảm bảo bạn đã hoàn thành các bước chuẩn bị trong [Tài liệu chung](GCP_0_COMMON_RESOURCES.md).

## 1. Chuẩn bị quyền và Công cụ
Trước khi bắt đầu, hãy đảm bảo máy cá nhân của bạn đã cài đặt và đăng nhập:
1.  **Cài đặt Google Cloud CLI**: [Hướng dẫn cài đặt](https://cloud.google.com/sdk/docs/install).
2.  **Đăng nhập tài khoản**:
    ```bash
    gcloud auth login
    gcloud auth configure-docker gcr.io
    ```
3.  **Bật API cần thiết**:
    ```bash
    gcloud services enable aiplatform.googleapis.com artifactregistry.googleapis.com
    ```

## 2. Cấu hình Script nộp Job
Mở file `submit_job.sh` và cập nhật các thông số sau:
- `PROJECT_ID`: ID dự án Google Cloud của bạn (ví dụ: `my-recsys-project`).
- `REGION`: Vùng có GPU (khuyên dùng `us-central1` hoặc `asia-southeast1`).
- `machine-type`: Loại máy (ví dụ: `n1-standard-8` cho 8 vCPU, 30GB RAM).
- `accelerator-type`: Loại GPU (`NVIDIA_TESLA_T4` hoặc `NVIDIA_L4`).

## 3. Tạo Image và Gửi Job
Script `submit_job.sh` đã được thiết kế để xử lý toàn bộ quy trình:
1. **Đóng gói Code**: Tạo Docker Image chứa toàn bộ mã nguồn và thư viện.
2. **Push Image**: Đẩy Image lên Google Artifact Registry (GCR).
3. **Trigger Vertex AI**: Khởi tạo một Custom Job chạy Image đó với cấu hình GPU bạn chọn.

**Lệnh thực thi:**
```bash
# Chạy Baseline 3 (DSSM) với 1 GPU
./submit_job.sh 3

# Chạy toàn bộ 6 Baselines lần lượt
./submit_job.sh all
```

## 4. Theo dõi và Quản lý
1.  **Vertex AI Dashboard**: Truy cập [Vertex AI Custom Jobs](https://console.cloud.google.com/vertex-ai/training/custom-jobs).
2.  **Xem Logs**: Click vào tên Job -> **View Logs**. Tại đây bạn sẽ thấy tiến độ training từng Epoch, chỉ số Loss, HR@10 và NDCG@10 của từng GPU.
3.  **Output**: Sau khi hoàn tất, kiểm tra thư mục `gs://mining-data-2/models/` để lấy file `best_model.pt`.

## 5. Xử lý lỗi
Xem phần [Troubleshooting trong tài liệu chung](GCP_0_COMMON_RESOURCES.md#6-xử-lý-lỗi-thường-gặp-troubleshooting).
