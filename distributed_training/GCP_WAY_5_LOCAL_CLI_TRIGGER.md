# Cách 5: Kích hoạt Huấn luyện từ Terminal Máy cá nhân (Local CLI)

Phương pháp này cho phép bạn sử dụng công cụ dòng lệnh `gcloud` và `docker` ngay trên máy tính cá nhân để đóng gói mã nguồn và ra lệnh cho Google Cloud thực thi quá trình huấn luyện trên hạ tầng Vertex AI.

## 1. Yêu cầu hệ thống tại máy Local
Để sử dụng phương pháp này, máy tính của bạn cần được cài đặt sẵn các công cụ sau:
- **Google Cloud CLI (gcloud)**: [Hướng dẫn cài đặt](https://cloud.google.com/sdk/docs/install).
- **Docker**: Đã cài đặt và đang chạy (Docker Desktop cho Windows/Mac hoặc Docker Engine cho Linux).
- **Quyền hạn**: Tài khoản Google Cloud của bạn cần có các quyền:
    - `Vertex AI Administrator`
    - `Storage Admin`
    - `Artifact Registry Administrator`

## 2. Quy trình thực hiện chi tiết

### BƯỚC 1: Đăng nhập và Xác thực (Làm 1 lần)
Mở Terminal/PowerShell tại máy local và chạy các lệnh sau:
```bash
# Đăng nhập vào tài khoản Google Cloud
gcloud auth login

# Cấu hình Docker để có quyền đẩy Image lên Google Cloud
gcloud auth configure-docker asia-southeast1-docker.pkg.dev
```

Kết quả:
```bash
PS D:\Hoctap_Code_PrivateProject\MiningMassiveData> gcloud auth configure-docker asia-southeast1-docker.pkg.dev
Adding credentials for: asia-southeast1-docker.pkg.dev
After update, the following will be written to your Docker config file located at [C:\Users\CONG\.docker\config.json]:
 {
  "credHelpers": {
    "asia-southeast1-docker.pkg.dev": "gcloud"
  }
}

Do you want to continue (Y/n)?  Y

Docker configuration file updated.
PS D:\Hoctap_Code_PrivateProject\MiningMassiveData> 
```

### BƯỚC 2: Cấu hình file Script nộp Job
Mở file `submit_job.sh` trong thư mục `distributed_training/` và cập nhật thông tin dự án của bạn:
- `PROJECT_ID`: ID dự án Google Cloud của bạn.
- `REGION`: Vùng bạn muốn chạy (ví dụ: `asia-southeast1`).
- `BUCKET`: Tên GCS Bucket để lưu trữ model checkpoint.

```bash
PROJECT_ID="mining-data-2"   # <--- THAY BẰNG PROJECT ID CỦA BẠN
REGION="asia-southeast1"           # Vùng chạy (us-central1, asia-southeast1, ...)
BUCKET="mining-data-2"         # Tên GCS Bucket của bạn
```

## Chú ý
Cần tạo Repository của mình trên GCP (artifact registry).
    ```bash
    gcloud artifacts repositories create recsys-repo \
        --repository-format=docker \
        --location=asia-southeast1 \
        --description="Kho chua Docker Image"
    ```

### BƯỚC 3: Thực thi nộp Job từ Local
Chạy script `submit_job.sh` kèm theo ID của model bạn muốn huấn luyện:

```bash
# Ví dụ: Huấn luyện Baseline 3 (DSSM)
./submit_job.sh 3

# Ví dụ: Huấn luyện tất cả các model lần lượt
./submit_job.sh all
```
- Cách 1: Sử dụng Git Bash hoặc WSL (Khuyên dùng)

  - Mở Git Bash tại thư mục gốc của dự án và chạy:
```bash

sh distributed_training/submit_job.sh 1
```

- Lúc chạy pull dokcer image về, do quá nhiều luồng download nên dễ lỗi. Lần sau tắt Docker, chạy lại chỉ cần 
```bash
docker pull gcr.io/deeplearning-platform-release/pytorch-gpu.2-4:latest
```
vì dữ liệu lần hỏng trước đó  thì các layer-cache download xong đã đc lưu ròi.

- Cách 2: Sử dụng PowerShell

  - Nếu bạn dùng PowerShell, hãy chạy lệnh này để đảm bảo tham số được truyền đúng vào môi trường Bash:

```powershell
bash distributed_training/submit_job.sh 1
```

- Lưu ý quan trọng khi chạy:
  - Bật API: Khi terminal hỏi `Would you like to enable and retry (y/N)?`, bạn hãy gõ `y` rồi Enter. Quá trình này chỉ mất khoảng 1-2 phút.
  - Docker: Đảm bảo Docker Desktop của bạn đang chạy (trạng thái màu xanh).
  - Thư mục: Nhờ lệnh `cd "$(dirname "$0")"` tôi vừa thêm vào, giờ đây bạn có thể đứng ở bất kỳ đâu chạy script mà không còn lo lỗi "không thấy Dockerfile".


## 3. Luồng vận hành chi tiết của Script
Khi bạn chạy lệnh trên, hệ thống local sẽ thực hiện các bước:
1.  **Build Docker Image**: Docker local sẽ đọc `Dockerfile`, cài đặt môi trường và đóng gói toàn bộ code trong thư mục hiện tại.
2.  **Push Image**: Image được đẩy từ máy bạn lên **Google Artifact Registry**.
3.  **Trigger Vertex AI**: Lệnh `gcloud ai custom-jobs create` gửi yêu cầu kèm cấu hình phần cứng (GPU) lên mây.

## 4. Ưu điểm và Hạn chế

### Ưu điểm:
- **Tiện lợi**: Không cần SSH vào máy ảo trung gian, thao tác trực tiếp trên môi trường code local.
- **Tự động hóa**: Một lệnh duy nhất xử lý từ khâu đóng gói đến khi chạy trên Cloud.

### Hạn chế:
- **Tốc độ Upload**: Nếu mạng internet nhà bạn chậm, việc đẩy Docker Image (thường nặng vài GB) lên Cloud sẽ mất nhiều thời gian.
- **Yêu cầu Docker Local**: Máy cá nhân phải đủ mạnh để build Docker Image.

## 5. Xử lý lỗi thường gặp khi chạy từ Local

### Lỗi 1: Không tìm thấy Dockerfile
- **Nguyên nhân**: Chạy script từ thư mục không đúng.
- **Khắc phục**: Hiện tại script đã có lệnh tự động chuyển vùng `cd "$(dirname "$0")"`. Bạn có thể chạy từ bất kỳ đâu.

### Lỗi 2: Tham số baseline bị bỏ qua (Chạy "all" dù đã nhập số)
- **Nguyên nhân**: Do PowerShell không truyền tham số vào script .sh một cách tự nhiên.
- **Khắc phục**: Trên Windows, hãy dùng lệnh `bash distributed_training/submit_job.sh 1` hoặc sử dụng **Git Bash**.

### Lỗi 3: Lỗi build Docker (failed to solve...)
- **Khắc phục**: Đảm bảo ứng dụng Docker Desktop đã được mở và đang chạy (biểu tượng cá voi màu xanh).

### Lỗi 4: API aiplatform.googleapis.com not enabled
- **Khắc phục**: Gõ **`y`** khi được hỏi trong terminal để gcloud tự động bật API cho bạn.

> [!TIP]
> Nếu mạng upload của bạn chậm, hãy cân nhắc chuyển sang [Cách 4: Quy trình "Vàng"](GCP_WAY_4_GOLDEN_WORKFLOW.md) để sử dụng máy ảo trung gian làm trạm nộp Job.
