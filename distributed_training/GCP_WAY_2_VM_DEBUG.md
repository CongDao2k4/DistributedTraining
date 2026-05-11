# Cách 2: Chạy lẻ từng Model để Debug trên Cloud VM

Phương pháp này được sử dụng khi bạn đang trong quá trình phát triển, cần kiểm tra lỗi hoặc tinh chỉnh từng model cụ thể một cách nhanh chóng trên máy ảo.

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
```bash
export TRAINING_ENV=cloud
export GCS_BUCKET=mining-data-2
```

## 2. Chạy lẻ từng Model

Bạn có thể chạy trực tiếp các file trong `src/baselines/` bằng cách dùng cờ `-m`:

```bash
# Ví dụ chạy Hybrid Ranker
python3 -m src.baselines.hybrid_ranker

# Hoặc chạy SBERT bằng GPU đơn
python3 -m src.baselines.sbert_ranker
```

## 3. Ưu điểm của phương pháp này
- **Tốc độ**: Khởi động nhanh, không cần thông qua bộ điều phối `main.py`.
- **Dễ dàng Debug**: Các thông báo lỗi (Traceback) hiển thị trực tiếp và rõ ràng.
- **Tiết kiệm tài nguyên**: Phù hợp khi chỉ muốn test logic trên CPU hoặc 1 GPU duy nhất.
