# Cách 4: Quy trình "Vàng" - Kết hợp GitHub & Coordinator VM

Đây là quy trình tối ưu nhất để tránh việc upload dữ liệu chậm từ máy nhà, giữ cho môi trường huấn luyện luôn sạch sẽ và dễ dàng quản lý phiên bản code.

## 1. Tổng quan Luồng vận hành
Quy trình này sử dụng một máy ảo nhỏ (không cần GPU) làm "Coordinator" để điều phối việc nộp job lên Vertex AI.

1. **Local**: Viết code, đẩy lên GitHub.
2. **Coordinator VM**: Pull code từ GitHub, chạy script nộp Job.
3. **Vertex AI**: Tiếp nhận Job, tự động cấp phát tài nguyên mạnh (Nhiều GPU), chạy huấn luyện và lưu kết quả vào GCS.

- **Quyền hạn**: Tài khoản Google Cloud của bạn cần có các quyền:
    - `Vertex AI Administrator`
    - `Storage Admin`
    - `Artifact Registry Administrator`

## 2. Thiết lập máy ảo Coordinator (Làm 1 lần)
Trên máy ảo Google Cloud của bạn, hãy chạy các lệnh sau:

Cài máy VM 150GB và 16GB RAM, dùng dòng e2-standard-4 để ổn định.

Có thể dùng lệnh ở Cloud Shell:
```bash
gcloud compute instances create coordinator-vm \
    --project=mining-data-2 \
    --zone=asia-southeast1-c \
    --machine-type=e2-standard-4 \
    --network-interface=network-tier=PREMIUM,subnet=default \
    --create-disk=auto-delete=yes,boot=yes,device-name=coordinator-vm,image-project=ubuntu-os-cloud,image-family=ubuntu-2204-lts,mode=rw,size=200,type=pd-balanced \
    --scopes=https://www.googleapis.com/auth/cloud-platform
```    

## Chú ý
Cần tạo Repository của mình trên GCP (artifact registry).

```bash
    gcloud artifacts repositories create recsys-repo-2 \
        --repository-format=docker \
        --location=asia-southeast1 \
        --description="Kho chua Docker Image"
```

1.  **Cài đặt Docker**:
    ```bash
    sudo apt-get update && sudo apt-get install docker.io -y
    sudo usermod -aG docker $USER
    # Logout và Login lại VM để cập nhật quyền Docker
    ```

2.  **Cấu hình Quyền Cloud**:
    ```bash
    gcloud auth login
    gcloud config set project [PROJECT_ID]
    gcloud auth configure-docker --quiet
    ```
- Trên VM cũng cần cài git, python nữa.
    ```bash
    sudo apt-get install git python3-pip zip -y
    ```

3.  **Clone mã nguồn**:
    ```bash
    git clone <URL_REPO_GITHUB_CUA_BAN>
    cd MiningMassiveData/distributed_training
    chmod +x submit_job.sh
    ```
4. **Mỗi lần chạy pull code github mới**
    ```bash
        # Xóa bỏ các thay đổi lặt vặt (hoặc lỗi kẹt) trên máy ảo, ép nó giống hệt trên mạng
        git reset --hard origin/main
        # Kéo code mới nhất về
        git pull origin main

        cd distributed_training
        
        # chmod +x submit_job.sh nếu gán nó thành hàm hệ thống chạy được
        
        # ./submit_job.sh
        hoặc 
        # sh submit_job.sh 1  # ko cần chmod nữa
        # ./submit_job.sh 1 # Ví dụ chạy Baseline 1
    ```
Để bạn có thể tắt laptop mà script vẫn chạy, hãy dùng nohup kết hợp với chạy nền. Cách này đơn giản và không cần cài thêm tmux:
```bash
    nohup bash submit_job.sh all > training_log.txt 2>&1 &
```
Giải thích lệnh này:nohup: Viết tắt của "no hang up" – giúp script lờ đi tín hiệu ngắt kết nối khi bạn tắt SSH/laptop.> training_log.txt: Ghi toàn bộ kết quả (log) vào file để bạn xem lại sau.

2>&1: Gom cả thông báo lỗi vào chung file log đó.

&: Cho script chạy dưới nền (background).

Cách kiểm tra sau khi bật lại laptop:Khi bạn mở máy lại và SSH vào VM, hãy dùng lệnh sau để xem script đã chạy xong chưa hoặc đang chạy đến đâu:

```bash
    tail -f training_log.txt
```
Kiểm tra xem tiến trình còn sống không:

```bash   
    ps aux | grep submit_job.sh
```

Kiểm tra trên Console: Truy cập link Vertex AI ở cuối script của bạn để xem Job đã xuất hiện chưa.


Gõ lệnh kiểm tra dung lượng ổ cứng:
   ```bash
   df -h
   ```

## 3. Luồng làm việc hàng ngày (Daily Workflow)

### Bước 1: Tại máy cá nhân (Local)
- Viết code, chỉnh sửa tham số.
- Đẩy code lên GitHub:
    ```bash
    git add .
    git commit -m "Cập nhật model CHGNN"
    git push origin main
    ```

### Bước 2: Tại máy ảo Coordinator (SSH)
- Kéo code mới nhất và nộp Job:
    ```bash
    git pull origin main
    ./submit_job.sh 6  # Ví dụ chạy CHGNN
    ```

## 4. Tại sao gọi là Quy trình "Vàng"?
- **Tốc độ mạng**: VM Coordinator nằm trong Google Network nên việc `docker push` image lên Artifact Registry cực nhanh.
- **Tính ổn định**: Không phụ thuộc vào kết nối internet chập chờn của máy cá nhân.
- **Môi trường sạch**: Mỗi Job trên Vertex AI là một container mới hoàn toàn, tránh xung đột thư viện.
