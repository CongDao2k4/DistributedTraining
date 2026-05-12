# Hướng dẫn Kiểm tra và Cứu hộ Dữ liệu Embedding trên VM

Tài liệu này hướng dẫn cách thiết lập môi trường và chạy các script kiểm tra tính toàn vẹn của dữ liệu Embedding (Chunks) sau khi bạn đã SSH vào máy ảo GCP.

## 1. Chuẩn bị môi trường

```bash
  sudo apt-get update
  sudo apt-get install git python3-pip zip -y
  pip3 install gdown google-cloud-storage
```

Sau khi SSH vào VM, hãy di chuyển vào thư mục gốc của dự án:

```bash
  git clone [LINK_GITHUB_CUA_BAN]
  cd [TEN_THU_MUC_PROJECT]
  pip3 install gdown
```

### Tạo và kích hoạt môi trường ảo (venv)
Việc dùng venv giúp tránh xung đột thư viện hệ thống:

```bash
  # Tạo venv
  python3 -m venv venv_gcp

  # Kích hoạt venv
  source venv_gcp/bin/activate
```

### Cài đặt các thư viện cần thiết
Các script `recheck` và `fix_index` cần một số thư viện cơ bản sau:

```bash
pip install --upgrade pip
pip install numpy gcsfs pyarrow tqdm
```
*Lưu ý: VM cần được cấp quyền truy cập GCS (Service Account có quyền Storage Admin hoặc đã chạy `gcloud auth login`).*

---

## 2. Quy trình Thực hiện

### Bước 1: Kiểm tra tính toàn vẹn (Re-check)
Đây là bước quan trọng nhất để biết mảnh nào lỗi, mảnh nào sạch.

```bash
python3 distributed_training/scripts/recheck_chunks.py
```

**Kết quả:**
- Nếu báo **[OK]**: Mảnh đó hoàn hảo, không cần làm gì thêm.
- Nếu báo **[!!] KHÔNG HỢP LỆ**: Hãy chú ý danh sách lệnh `gsutil rm` ở cuối log.

### Bước 2: Xử lý các mảnh lỗi (Nếu có)
Nếu script `recheck` báo có mảnh lỗi, bạn có 2 lựa chọn:

**Lựa chọn A: Cứu hộ bằng Index (Nếu chỉ lỗi Prefix/ID)**
Nếu bạn nghi ngờ vector vẫn đúng nhưng ID trong file `.pkl` bị sai hoặc thiếu prefix, hãy chạy:
```bash
python3 distributed_training/scripts/fix_index.py
```
*Sau khi chạy xong, hãy chạy lại `recheck_chunks.py` để xác nhận đã hết lỗi chưa.*

**Lựa chọn B: Xóa và chạy lại (Khuyên dùng nếu lệch số lượng)**
Nếu lỗi do thiếu vector, hãy copy các lệnh `gsutil rm` mà script recheck đã in ra và chạy chúng. Sau đó khởi động lại pipeline chính:
```bash
# Sau khi xóa các file lỗi trên GCS
python3 distributed_training/main.py --baseline 3
```
Hệ thống sẽ tự động chỉ tính toán lại các mảnh bạn vừa xóa.

### Bước 3: Gộp file (Merge)
Khi `recheck_chunks.py` báo cáo **100% mảnh đều HỢP LỆ**, bạn có thể tiến hành gộp file tổng:

```bash
# Chạy precompute (lúc này nó sẽ thấy đủ 16 mảnh và tự động chuyển sang bước Merge)
python3 distributed_training/src/precompute_embeddings.py
```

---

## 3. Một số lệnh hữu ích

- **Xem danh sách các mảnh hiện có:**
  ```bash
  gsutil ls gs://recommendation-system-data-mining/prepared_data/chunks/
  ```

- **Theo dõi dung lượng file đang gộp:**
  ```bash
  ls -lh data/item_embeddings.npy
  ```

- **Thoát môi trường ảo:**
  ```bash
  deactivate
  ```
