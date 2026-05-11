# Hướng dẫn Huấn luyện Phân tán trên Google Cloud (GCP)

Tài liệu này đã được tách nhỏ thành các hướng dẫn chi tiết cho từng phương pháp tiếp cận. Vui lòng chọn cách làm phù hợp với nhu cầu của bạn.

## 0. Tài nguyên và Cấu hình Chung
**BẮT BUỘC ĐỌC:** Chứa Checklist chuẩn bị, Kiến trúc hệ thống và các lưu ý quan trọng.
- [GCP_0_COMMON_RESOURCES.md](GCP_0_COMMON_RESOURCES.md)

---

## 1. Các phương pháp Huấn luyện

### Cách 1: Chạy toàn bộ Pipeline trên Cloud VM
Phù hợp khi tự quản lý môi trường trên máy ảo và chạy nhiều model cùng lúc.
- [Xem chi tiết Hướng dẫn Cách 1](GCP_WAY_1_VM_PIPELINE.md)

### Cách 2: Chạy lẻ từng Model để Debug trên Cloud VM
Phù hợp khi đang phát triển, cần kiểm tra nhanh logic từng model cụ thể.
- [Xem chi tiết Hướng dẫn Cách 2](GCP_WAY_2_VM_DEBUG.md)

### Cách 3: Triển khai chuyên nghiệp trên Vertex AI (Docker-based)
Phương pháp khuyên dùng cho môi trường Production, tự động cấp phát và thu hồi GPU.
- [Xem chi tiết Hướng dẫn Cách 3](GCP_WAY_3_VERTEX_AI.md)

### Cách 4: Quy trình "Vàng" - Kết hợp GitHub & Coordinator VM
Quy trình tối ưu nhất để quản lý code và nộp job từ xa một cách ổn định.
- [Xem chi tiết Hướng dẫn Cách 4](GCP_WAY_4_GOLDEN_WORKFLOW.md)

### Cách 5: Kích hoạt từ Terminal Máy cá nhân (Local CLI)
Sử dụng công cụ `gcloud` và Docker trực tiếp trên máy của bạn để điều khiển hạ tầng Cloud.
- [Xem chi tiết Hướng dẫn Cách 5](GCP_WAY_5_LOCAL_CLI_TRIGGER.md)

---

## Tóm tắt các thành phần kỹ thuật
- **Data streaming**: Xử lý file 55GB trực tiếp từ GCS.
- **Framework**: PyTorch DDP + `torchrun`.
- **Registry**: Google Artifact Registry.
- **Compute**: Vertex AI Custom Training Jobs.
