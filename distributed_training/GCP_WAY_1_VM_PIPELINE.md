# Cách 1: Chạy toàn bộ Pipeline trên Cloud VM

Phương pháp này phù hợp khi bạn muốn tự quản lý môi trường trên một máy ảo (Compute Engine) và chạy toàn bộ quy trình huấn luyện cho nhiều model cùng lúc.

> [!IMPORTANT]
> Đảm bảo bạn đã hoàn thành các bước chuẩn bị trong [Tài liệu chung](GCP_0_COMMON_RESOURCES.md).

## 1. Thiết lập Môi trường trên Cloud VM

### BƯỚC 1: Cài đặt Thư viện
```bash
# Cài đặt PyTorch với hỗ trợ CUDA
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# Cài đặt các thư viện bổ trợ
pip install pandas pyarrow gcsfs tqdm rank-bm25 sentence-transformers
```

### BƯỚC 2: Cấu hình Biến môi trường
Cần thiết lập để code biết đang chạy trên Cloud và sử dụng GCS:
```bash
export TRAINING_ENV=cloud
export GCS_BUCKET=mining-data-2
```

## 2. Quy trình Huấn luyện & Đánh giá (Toàn bộ Pipeline)

Sử dụng `main.py` để điều phối toàn bộ các model:

```bash
# Chạy Baseline 3 (DSSM) trên tất cả GPU hiện có
torchrun --nproc_per_node=auto main.py --baseline 3

# Chạy Baseline 3 (DSSM) trên 1 lượng N GPU trong số tổng GPU hiện có
torchrun --nproc_per_node=N main.py --baseline 3

# Chạy tất cả 6 model lần lượt (Toàn bộ Pipeline), thay auto bằng N nếu muốn chỉ dùng N GPU
torchrun --nproc_per_node=auto main.py --baseline all  
```

## 3. Quản lý Kết quả
- Model tốt nhất (`best_model.pt`) sẽ được lưu tại `models/` và tự động upload ngược lên GCS sau khi hoàn tất.
- Xem thêm chi tiết về [Quản lý dữ liệu và Model](GCP_0_COMMON_RESOURCES.md#4-quản-lý-dữ-liệu-và-model-checkpoint).
