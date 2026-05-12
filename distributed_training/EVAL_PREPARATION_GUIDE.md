# Hướng dẫn Chuẩn bị Dữ liệu Đánh giá (.pkl)

Tài liệu này hướng dẫn cách thiết lập và chạy script `src/prepare_eval_pkl.py` để tạo bộ dữ liệu đánh giá chuẩn cho các mô hình training.

## 1. Yêu cầu Hệ thống & VM đề xuất
- **Instance Type**: `e2-standard-4` (4 vCPU, 16GB RAM).
- **Tại sao**: Code V2 đã tối ưu RAM (chỉ dùng ~4-6GB), giúp tiết kiệm chi phí so với máy 32GB trước đây.
- **Boot Disk**: 50GB.
- **Quyền hạn (Scopes)**: Chọn `Allow full access to all Cloud APIs`.

### Nếu chọn VM với GPU:
- **VM type**: `n1-standard-4 4 vCPUs, 15 GB RAM with NVIDIA Tesla T4 GPU`
- **Boot Disk**: 50GB.
- **Quyền hạn (Scopes)**: Chọn `Allow full access to all Cloud APIs`.
- **giảm giá hơn**: kéo xuồng dưới tìm chọn `provision Model` đổi standard thành Spot

## 2. Khởi tạo Môi trường & Cài đặt Thư viện
Sau khi SSH vào máy ảo mới, hãy thực hiện các lệnh sau theo đúng thứ tự:

### Bước 2.1: Cấu hình Google Cloud Project & System Packages
```bash
# 1. Xóa cấu hình cũ để tránh lỗi quyền hạn
rm -rf ~/.config/gcloud

# 2. Thiết lập Project ID
gcloud config set project mining-data-2

# 3. Cập nhật hệ thống và cài đặt các công cụ cần thiết (Git, Venv, Pip)
sudo apt update && sudo apt install -y git python3-venv python3-pip
```

### Bước 2.2: Clone Project & Tạo Virtual Environment
```bash
# 1. Clone repository (thay [LINK_GITHUB_CUA_BAN] bằng link thực tế)
git clone [LINK_GITHUB_CUA_BAN]
cd ~/MiningMassiveData/distributed_training

# 2. Tạo và kích hoạt môi trường ảo
python3 -m venv eval_env  # hoặc fix_venv với chạy file fix_index.py
source eval_env/bin/activate  # source fix_venv/bin/activate với chạy file fix_index.py

# 3. Nâng cấp pip
pip install --upgrade pip
```

### Bước 2.3: Cài đặt Python Dependencies
```bash
# CHỌN MỘT TRONG HAI LỆNH SAU:

# LỰA CHỌN A: Dành cho máy ảo CPU (Tiết kiệm, chỉ dùng đóng gói dữ liệu)
pip install pandas pyarrow datasets gcsfs torch --extra-index-url https://download.pytorch.org/whl/cpu

# LỰA CHỌN B: Dành cho máy ảo GPU (Dùng để Train model trực tiếp)
pip install pandas pyarrow gcsfs torch torchvision torchaudio --extra-index-url https://download.pytorch.org/whl/cu121

# Cài đặt thêm google-cloud-storage và gdown nếu cần
pip install google-cloud-storage gdown
```

- **pyarrow**: Xử lý định dạng Parquet (item_nodes) tốc độ cao.
- **gcsfs**: Cho phép Pandas đọc dữ liệu trực tiếp từ GCS.

## 3. Cấu hình & Chạy Script
Thiết lập biến môi trường và chạy script:

```bash
# 1. Đảm bảo đang ở thư mục distributed_training
cd ~/MiningMassiveData/distributed_training

# 2. Kích hoạt lại môi trường ảo nếu chưa activate
source eval_env/bin/activate

# 3. GCP Authentication (BẮT BUỘC cho GCS access)
gcloud auth application-default login

# 4. Thiết lập biến môi trường (Chấp nhận cả SPARK_ENV hoặc TRAINING_ENV)
export SPARK_ENV=cloud
export TRAINING_ENV=cloud

# 5. Chạy script đóng gói dữ liệu
# Lưu ý: Chạy dưới dạng module (-m) để tránh lỗi import
python3 -m src.prepare_eval_pkl
```

### Kết quả mong đợi:
- Script sẽ đọc `gs://mining-data-2/output/evaluation_dataset` (Parquet) và `gs://mining-data-2/output/item_nodes` (Parquet).
- Tạo file `.pkl` tại: `distributed_training/data/prepared_data_improved/evaluation_dataset.pkl`.
- Tự động upload kết quả lên: `gs://mining-data-2/output/prepared_data_improved/evaluation_dataset.pkl`.

## 4. Kiểm tra
Nếu bảng thống kê hiện ra con số **4,082,820 products** và số lượng Queries tương ứng, bạn đã thành công!

Các đường dẫn GCS quan trọng:
- `gs://mining-data-2/output/evaluation_dataset/` (Dữ liệu ID-Only)
- `gs://mining-data-2/output/item_nodes/` (Metadata sản phẩm)

## 5. Quy trình hoạt động (Logic)
1.  **Bước 1**: Đọc tập ID từ file Eval Parquet để xác định danh sách sản phẩm cần lấy metadata.
2.  **Bước 2**: Đọc file `item_nodes` có lọc (Filter) theo danh sách ID và chọn cột (Column Selection) để tiết kiệm RAM.
3.  **Bước 3**: Xây dựng Lookup Dictionary trong bộ nhớ.
4.  **Bước 4**: Ánh xạ ID sang Text Metadata (Title, Category).
5.  **Bước 5**: Lưu kết quả ra file `.pkl`.
6.  **Bước 6**: (Chỉ Cloud) Upload file lên GCS tại `gs://mining-data-2/output/prepared_data_improved/evaluation_dataset.pkl`.

## 6. Xử lý sự cố
- **Lỗi `NameError: name 'time' is not defined`**: Chưa thêm `import time` vào script. Xem Bước 2.4.
- **Lỗi `ModuleNotFoundError: No module named 'config'`**: Chạy sai thư mục hoặc chưa activate venv. Đảm bảo chạy từ `distributed_training/` với `python3 -m src.prepare_eval_pkl`.
- **Lỗi GCS (`403 Forbidden`, `401 Unauthorized`)**: Chạy `gcloud auth application-default login` và đăng nhập bằng tài khoản có quyền truy cập bucket.
- **Tràn RAM**: Script đã được tối ưu cho dữ liệu 25GB+, nếu vẫn tràn RAM, hãy kiểm tra xem có đang load thừa cột nào không.
