# Hướng dẫn Triển khai RecSys từ A-Z trên Google Cloud (Cho người mới bắt đầu)

Chào mừng bạn đến với thế giới của GCP! Dưới đây là lộ trình để bạn đưa dự án từ Local lên Cloud.

---

## Bước 1: Kích hoạt các dịch vụ cần thiết (API)
Mặc định GCP sẽ khóa các dịch vụ để tránh tốn tiền. Bạn cần mở chúng lên:
1. Mở **Google Cloud Console** (https://console.cloud.google.com).
2. Chọn đúng Project của bạn ở góc trên bên trái.
3. Mở thanh tìm kiếm và gõ "API Library", sau đó tìm và nhấn **Enable** cho các dịch vụ sau:
   - **Compute Engine API** (Để chạy máy ảo)
   - **Cloud Dataproc API** (Để chạy Spark) 
   - **Cloud Storage API** (Để lưu trữ dữ liệu)

---

## Bước 2: Tạo "Trái tim" lưu trữ (GCS Bucket)
Đây là nơi chứa toàn bộ dữ liệu của bạn.
1. Tìm kiếm "Storage" trong Console.
2. Nhấn **Create Bucket**.
3. **Name**: Đặt tên duy nhất (Ví dụ: `recsys-data-xxxx`). Ghi nhớ tên này.
4. **Location**: Chọn `us-central1` (Thường rẻ và nhiều GPU). 
   - Tôi chọn `asia` để ko mất phí liên lục địa -> từ các bước sau phi chọn Location/Region thuộc châu á
5. Nhấn **Create**.

---

## Bước 3: Tạo máy ảo điều phối (Coordinating VM)
Máy này dùng để chạy các script điều khiển.
1. Tìm kiếm "Compute Engine" -> "VM Instances" -> **Create Instance**.
2. **Name**: `coordinator-vm`.
3. **Machine type**: `e2-medium` (Rẻ, đủ dùng cho điều phối).
4. **Boot Disk**: Chọn Ubuntu 22.04 LTS.
5. Nhấn **Create**.
6. Khi máy hiện lên, nhấn nút **SSH** để mở cửa sổ dòng lệnh.

### Giao diện 2026 hơi khác , nhìn thanh sidebar bên trái để ấn vào `OS and Storage` mới chọn được Urbuntu

---

## Bước 4: Thiết lập Môi trường Cloud (Quan trọng)
Trong cửa sổ **SSH**, hãy cài đặt các biến sau để code nhận diện bạn đang chạy trên GCP:

project này có bucket : mining-data-2

```bash
# Thay đổi 'ten-bucket-cua-ban' thành tên Bucket bạn tạo ở Bước 2
export SPARK_ENV="cloud"
export RAW_DATA_DIR="gs://ten-bucket-cua-ban/raw_data/amazon_gpc/"
export OUTPUT_BASE="gs://ten-bucket-cua-ban/output/"
```
```bash
export SPARK_ENV="cloud"
export RAW_DATA_DIR="gs://mining-data-2/raw_data/amazon_gpc/"
export OUTPUT_BASE="gs://mining-data-2/output/"
```

### (Lưu ý: Nếu sau này bạn tắt cửa sổ SSH này đi và mở lại, bạn sẽ phải chạy lại 3 dòng lệnh này nhé).

---

## Bước 5: Đưa code lên VM và Tải dữ liệu từ Drive
Trong cửa sổ **SSH**, thực hiện:

```bash
# 1. Cài đặt Python và Thư viện hệ thống
sudo apt-get update
sudo apt-get install git python3-pip zip -y
pip3 install gdown google-cloud-storage

# 2. Clone code
git clone [LINK_GITHUB_CUA_BAN]
cd [TEN_THU_MUC_PROJECT]

# 3. Cài đặt thư viện gdown
pip3 install gdown

# 4. Sửa file download_data_to_gcs.py (Dùng lệnh 'nano download_data_to_gcs.py')
# - Điền GOOGLE_DRIVE_ID của bạn.
# - Điền GCS_DESTINATION (gs://ten-bucket-vua-tao/raw_data/amazon_gpc/).

```

### Lỗi ngay chạy lệnh `sudo apt-get update`

Vấn đề do VM instance không có External IP nên không thể kết nối ra ngoài để tải update Ubuntu

- Cách 1: Edit cái VM Instance này để chọn : nhìn cột external Ip của VM instance sẽ thấy None 
  - Cuộn xuống tìm mục Network interfaces (Giao diện mạng), nhấn vào mũi tên thả xuống để mở rộng phần này ra. 
  - Tìm dòng External IPv4 address (Địa chỉ IPv4 bên ngoài). Hãy đổi nó từ "None" thành Ephemeral (Tạm thời).
  - Ấn nút Save
- Cách 1 có thể lỗi vì không chọn được (Ephemeral) do Chính sách tổ chức (Organization Policy) (thường gặp nếu bạn dùng tài khoản của công ty, trường học, hoặc được cấp sẵn). Chính sách này 
cấm việc gắn IP công cộng (External IP) vào máy ảo để đảm bảo bảo mật. Fix bằng dùng `Cloud NAT` giúp bên ngoài ko kết nối xâm nhập đc nhưng bên trong kết nối ra được. 
  - Tìm Cloud NAT -> ấn Get Started (hoặc Create a NAT gateway) 
  - Điền thông tin: 
    - Gateway name (Tên cổng): Đặt là my-nat-gateway.
    - Network (Mạng): Chọn default
    - Region (Khu vực): Bắt buộc chọn asia-southeast1 (hoặc đúng khu vực bạn đã tạo máy ảo coordinator-vm lúc nãy).
  - Ở phần Cloud Router, nhấp vào ô thả xuống và chọn Create new router:
    - Name: Đặt là my-router
    - Nhấn Create (Tạo) để hoàn tất việc tạo Router.
  - Quay lại trang tạo NAT (các thông số khác cứ để mặc định), kéo xuống dưới cùng và nhấn Create
  - Chạy lại lệnh trong SSH
    - đợi 1-2 phút: Mở lại SSH ở VM Instance rồi chạy lại 3 lệnh  export
    - Chạy lại lệnh update: sudo apt-get update 

```bash
export SPARK_ENV="cloud"
export RAW_DATA_DIR="gs://mining-data-2/raw_data/amazon_gpc/"
export OUTPUT_BASE="gs://mining-data-2/output/"
```

### Lỗi chạy lệnh: `pip3 install gdown google-cloud-storage`

- Ý nghĩa của lỗi: Hệ điều hành đang khóa không cho bạn dùng lệnh pip để cài thư viện bừa bãi vào hệ thống gốc. 
Lý do là Linux cũng dùng Python để chạy các ứng dụng lõi của nó, nếu bạn cài đè các thư viện mới lên có thể làm "sập" hệ điều hành.
- cách chuyên nghiệp và an toàn nhất hiện nay là tạo một Môi trường ảo (Virtual Environment - venv).
  - Bước 1: Cài đặt gói hỗ trợ môi trường ảo: 
      `sudo apt-get install python3-venv -y`
  - Bước 2: Tạo môi trường ảo riêng cho dự án của bạn. Lệnh này sẽ tạo ra một thư mục tên là recsys_env chứa một bản Python hoàn toàn độc lập.
      `python3 -m venv recsys_env`
  - Bước 3: Kích hoạt môi trường ảo
      `source recsys_env/bin/activate`
      - Sau khi chạy lệnh này, bạn sẽ thấy chữ (recsys_env) hiện lên ở tuốt đầu dòng lệnh, báo hiệu bạn đã vào trong "vùng an toàn"
  - Bước 4: Cài đặt thư viện thoải mái
      `pip install gdown google-cloud-storage`

### Chú ý: Từ giờ trở đi, mỗi lần bạn tắt cửa sổ SSH và mở lại, máy ảo sẽ quay về môi trường gốc (không có thư viện gdown). 
Do đó, trước khi muốn chạy file `.py`, bạn chỉ cần gõ lại lệnh kích hoạt ở Bước 3 (`source recsys_env/bin/activate`) là được nhé!

### Các lệnh chạy sau đó ở Bước 5 này phải chạy với venv hết vì cần python3, gdown, ...

### Vấn đề với lệnh `python3 download_data.py` 
- yêu cầu VM instance có Disk > 10Gb , hoặc vài chục GB để load data từ drive về, sau đó đẩy lên.
- Nhưng nếu tôi muốn giản nén các file `.gz` ra ngay tại VM rồi mới nhét vào GCS, thì VM cần disk > 10GB rất nhiều.
- Giải pháp: dùng Colab + kỹ thuật Streaming + xử lý từng file lần lượt.
- file [streaming_drive_gcs.ipynb](spark_processing_gpc/streaming_drive_gcs.ipynb)

---

## Bước 6: Tạo cụm Spark (Dataproc) để xử lý ETL - 2026: là Managed Apache Spark

### Cách 1: dùng UI GPC để làm (cách này khá nhanh và dễ)
1. Tìm kiếm "Dataproc"(nay là Managed Apache Spark) -> chọn -> giao diện Managed Apache Spark
2. Side Bar bên trái , ấn **Clusters** -> **Create Cluster** -> giao diện **Cluster on Compute Engine**.
2. **Name**: `amazon-cluster`.
3. **Region**: `us-central1` hoặc mặc định đặt `asia-southeast1`. có thể chọn zone luôn cùng zone VM coordinator
4. **Cluster type**: **Standard** (1 master, N workers). Ở dưới thì mặc định OS là Debian nhưng có thể đổi sang Ubuntu 22.
5. **Bật Lighting Engine và Native ...**
5. **Kéo xuống, mở rộng để cấu hình Master & Worker (tránh tốn RAM, CPU, GB tốn nhiều tiền)**: 
  - **Master**: Đưa về N4-Standard-2 (vCPU:4, RAM:16GB)
  - **Worker**: đưa về N4-Standard-2 (vCPU:4, RAM:16GB)
  - **Number of workers**: Đưa về 2, hoặc 3, 4 tùy bạn, ở ví dụ này đưa về 2 cho tiết kiệm 
  - **Disksize**: Data ở GCS tổng 50GB nên chọn mỗi cái node khoảng 50Gb là đủ.

### Cách 2: Làm bằng code qua SSH
Mở cửa sổ SSH của `coordinator-vm`, copy toàn bộ khối này dán vào và Enter:
```bash
gcloud dataproc clusters create amazon-cluster \
    --region=asia-southeast1 \
    --master-machine-type=n4-standard-2 \
    --master-boot-disk-size=50GB \
    --num-workers=2 \
    --worker-machine-type=n4-standard-2 \
    --worker-boot-disk-size=50GB \
    --image-version=2.1-debian11 (hoặc chọn Ubuntu 22)
```

### Chú ý: Cách để giảm chi phí: 

#### 🚀 Hướng dẫn tạo Dataproc Cluster tối ưu (Spark ETL ~50GB)

#### 🎯 Mục tiêu
- Tối ưu **chi phí / hiệu năng / độ ổn định**
- Sử dụng **Spot VM (Secondary workers)**
- Đảm bảo chạy ETL ~50GB ổn định

---

#### 🧱 Tổng quan kiến trúc

| Thành phần | Số lượng | Loại |
|-----------|--------|------|
| Manager (Master) | 1 | On-demand |
| Primary Workers | 2 | On-demand |
| Secondary Workers | 2 | 🔥 Spot (Preemptible) |

---

#### ⚙️ Cấu hình chi tiết

> 1. Cluster basic

- **Cluster name**: `amazon-cluster`
- **Region**: `asia-southeast1`
- **Cluster type**: Standard (1 master, N workers)
- **Image version**: `2.3-ubuntu22`

---

> 2. Manager node (Master)

| Thuộc tính | Giá trị |
|-----------|--------|
| Machine type | `n4-standard-2` (2 vCPU, 8GB RAM) |
| Disk | 30GB |
| Disk type | Hyperdisk Balanced |
| Local SSD | 0 |

---

> 3. Primary Worker nodes

| Thuộc tính | Giá trị |
|-----------|--------|
| Number of workers | 2 |
| Machine type | `n4-standard-2` |
| vCPU | 2 |
| RAM | 8GB |
| Disk | 30GB |
| Disk type | Hyperdisk Balanced |
| Local SSD | 0 |

 ⚠️ Lưu ý: Primary workers bắt buộc ≥ 2

---

> 4. Secondary Worker nodes (Spot VM)

| Thuộc tính | Giá trị |
|-----------|--------|
| Number of workers | 2 |
| Preemptibility | ✅ Preemptible (Spot) |
| Machine type | `n4-standard-2` |
| Disk | 30GB |
| Disk type | Hyperdisk Balanced |
| Local SSD | 0 |

 🔥 Đây là phần giúp giảm ~50–60% chi phí

---

#### ⚙️ Spark cấu hình khuyến nghị

Thêm vào **Cluster properties**:

```bash
spark:spark.sql.shuffle.partitions=16
spark:spark.default.parallelism=16
spark:spark.task.maxFailures=8
spark:spark.speculation=true
```

---

## Hủy ngay khi chạy xong Apache Spark để tránh tốn tiền

- Xóa cluster để giảm tiền
- xóa Compute Engine → VM instances
- xóa Compute Engine → Disks, và External Disk
- xóa storage bucket: Cloud Storage. Tìm bucket dạng: dataproc-staging-* hoặc dataproc-temp-*. Nếu chỉ dùng tạm:❗ DELETE bucket. Nếu dùng lâu dài: giữ lại nhưng clear data
- xóa Compute Engine → Snapshots
- xóa Compute Engine → Images
- có thể xóa Logs (Cloud Logging), nhưng nó ko tốn nhiều tiền

---

## Bước 7: Submit Job từ GCS và xử lý ETL 
### Cách 1: Làm trên Giao diện Web (Phức tạp hơn)
Giao diện Web không thể lấy code từ máy coordinator-vm của bạn. Để submit qua UI, bạn phải:

Mở SSH coordinator-vm, nén code và dùng gsutil đẩy cả file main.py và dependencies.zip lên một Bucket GCS (ví dụ: gs://mining-data-2/code/).

Lên giao diện Dataproc -> Chọn tab Jobs -> Bấm SUBMIT JOB.

Cấu hình Job:

Cluster: Chọn amazon-cluster

Job type: PySpark

Main python file: Gõ đường dẫn GCS (vd: gs://mining-data-2/code/main.py)

Python files (thư mục phụ): Gõ đường dẫn (vd: gs://mining-data-2/code/dependencies.zip)

Bấm SUBMIT.

### Cách 2: Làm bằng code qua SSH (Được khuyên dùng)
Mở cửa sổ SSH của `coordinator-vm`, đứng tại thư mục project `MiningMassiveData`, chạy các bước sau:

```bash
git pull origin main
```

```bash
# Cập nhật danh sách gói phần mềm
sudo apt-get update

# Cài đặt công cụ zip (thêm sudo và -y để tự động đồng ý)
sudo apt-get install zip -y
```

1. **Chuẩn bị file nén chứa code phụ trợ**:
Lệnh này giúp Spark phân phối các thư mục `config` và `src` đến tất cả các máy Workers trong cụm.
```bash
cd ~/MiningMassiveData/spark_processing_gpc
zip -r dependencies.zip config src
```

**Chưa pull origin main** về mà đã zip
thực hiện lại quy trình này là xong. Lệnh zip sẽ tự động ghi đè lên file cũ với code mới nhất.

Bạn hãy chạy các lệnh sau theo thứ tự:
```bash
# 1. Quay về thư mục gốc của project
cd ~/MiningMassiveData

# 2. Cập nhật code mới nhất từ GitHub
git pull origin main

# 3. Vào thư mục xử lý Spark
cd spark_processing_gpc


# Xóa file zip cũ (nếu có)
rm -f dependencies.zip

# 4. Nén lại code mới (Lệnh này sẽ ghi đè dependencies.zip cũ)
zip -r dependencies.zip config src
```

2. **Bắn job sang cụm Dataproc**:
Thay thế `gs://mining-data-2/` bằng tên bucket của bạn nếu khác.

```bash
gcloud dataproc jobs submit pyspark main.py \
    --cluster=amazon-cluster \
    --region=asia-southeast1 \
    --py-files=dependencies.zip \
    --properties="spark.driverEnv.SPARK_ENV=cloud,spark.executorEnv.SPARK_ENV=cloud,spark.driverEnv.RAW_DATA_DIR=gs://mining-data-2/raw_data/amazon_gpc/,spark.executorEnv.RAW_DATA_DIR=gs://mining-data-2/raw_data/amazon_gpc/,spark.driverEnv.OUTPUT_BASE=gs://mining-data-2/output/,spark.executorEnv.OUTPUT_BASE=gs://mining-data-2/output/" \
    -- \
    --validate
```

*Giải thích các tham số:*
- `--py-files`: Gửi kèm các module `src` và `config`.
- `--properties`: 
    - `spark.driverEnv`: Truyền biến vào code Python chạy trên máy Master.
    - `spark.executorEnv`: Truyền biến vào code Python chạy trên các máy Workers.
- `--`: Sau dấu này là các tham số truyền trực tiếp vào hàm `main()` của Python (ví dụ: `--validate`, `--skip-scan`).

**Ta sẽ gặp lỗi**:
```bash
(recsys_env) cong23122004_gmail_com@coordinator-vm:~/MiningMassiveData/spark_processing_gpc$ ....
> -- \
> --validate
ERROR: (gcloud.dataproc.jobs.submit.pyspark) PERMISSION_DENIED: Request had insufficient authentication scopes. This command is authenticated as 832856245299-compute@developer.gserviceaccount.com which is the active account specified by the [core/account] property.
- '@type': type.googleapis.com/google.rpc.ErrorInfo
  domain: googleapis.com
  metadata:
    method: google.cloud.dataproc.v1.ClusterController.GetCluster
    service: dataproc.googleapis.com
  reason: ACCESS_TOKEN_SCOPE_INSUFFICIENT
```

**Lưu ý quan trọng về Quyền hạn (Permissions):**
Nếu bạn gặp lỗi `PERMISSION_DENIED: Request had insufficient authentication scopes`, đó là do máy ảo bị hạn chế quyền truy cập API. 

**Cách 1: Xác thực bằng luồng Remote (Khuyên dùng - Không cần Restart VM)**
1. Tại cửa sổ SSH, nhấn **`Ctrl + C`** để thoát mọi lệnh đang chờ (nếu có).
2. Chạy lệnh:
   ```bash
   gcloud auth login --no-browser
   ```
3. Copy link hiện ra dán vào trình duyệt máy tính cá nhân.
4. Sau khi đăng nhập và Allow, trình duyệt sẽ **không hiện mã code** mà hiện ra một lệnh bắt đầu bằng: `gcloud auth login --remote-bootstrap="..."`.
5. Hãy copy **toàn bộ lệnh đó**, quay lại cửa sổ SSH và dán vào, sau đó nhấn **Enter**.
6. Chạy lại lệnh `gcloud dataproc jobs submit...` ở trên.

*Lưu ý: Nếu bạn gặp lỗi 400 (invalid_request) khi mở link, hãy đảm bảo bạn đã copy đủ toàn bộ link dài của Google, không thiếu ký tự nào ở cuối.*

**Cách 2: Khắc phục triệt để (Cấp quyền thẳng cho máy ảo)**
(Cách này yêu cầu phải STOP máy ảo, nhưng sau đó bạn không bao giờ phải login nữa).
1. Dừng máy ảo `coordinator-vm`.
2. Nhấn nút **Edit**.
3. Tìm mục **Cloud API access scopes hoặc Access scopes**.
4. Chọn **Allow full access to all Cloud APIs**.
5. Lưu lại và Start máy ảo.
6. Khi chjay lại vẫn bị lỗi thì chạy:
```bash
curl -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/scopes
```
* Nếu kết quả hiện ra có dòng: https://www.googleapis.com/auth/cloud-platform -> Nghĩa là máy ảo đã có quyền Full, lỗi nằm ở IAM.
* Nếu kết quả chỉ có dòng: ...logging.write, ...monitoring.write -> Nghĩa là bước chỉnh Scope của bạn chưa được lưu thành công.

**Bước 2: Kiểm tra quyền IAM (Rất quan trọng)**
Dù máy ảo được phép "gọi" đến Dataproc, nhưng nếu cái địa chỉ Email Service Account của bạn không có tên trong danh sách "Quản lý", nó cũng sẽ bị chặn.

* Vào giao diện GCP -> Tìm "IAM & Admin".
* Tìm dòng có email: 832856245299-compute@developer.gserviceaccount.com.
* Nhấn nút Edit (hình cây bút) ở cuối dòng đó.
* Nhấn Add another role.
* Tìm và thêm quyền: Dataproc Editor.
* Nhấn Save.

**Tại sao đã sửa Bước 1 & 2 vẫn bị lỗi?**
Nếu bạn chạy `gcloud auth list` thấy tài khoản máy ảo đã Active (`*`) mà vẫn báo lỗi `ACCESS_TOKEN_SCOPE_INSUFFICIENT`, đó là do các lần `auth login` trước đó đã tạo ra "Token rác" bị cache trong máy. `gcloud` sẽ dùng cái Token lỗi này thay vì dùng quyền mới bạn vừa cấp.

**Bước 3: Phương án "Chốt hạ" - Dùng JSON Key (Khuyên dùng khi bị lỗi quyền lằng nhằng)**
Cách này sẽ tạo ra một "chìa khóa" độc lập, giúp bạn vượt qua mọi giới hạn của máy ảo và Token cũ. Đây là cách chắc chắn thành công 100%.

1. **Tạo Key trên Web**: 
   - Vào **IAM & Admin** -> **Service Accounts**.
   - Nhấn vào email `...-compute@developer...`.
   - Chọn tab **KEYS** -> **ADD KEY** -> **Create new key** -> Chọn **JSON**.
   - File `.json` sẽ tải về máy tính bạn.
2. **Upload lên máy ảo**:
   - Ở cửa sổ SSH, nhấn **UPLOAD FILE** (góc trên bên phải) và chọn file JSON vừa tải.
3. **Kích hoạt quyền Admin**:
   - Chạy lệnh sau (thay `ten-file.json` bằng tên file bạn vừa upload):
   ```bash
   gcloud auth activate-service-account --key-file=ten-file.json
   ```
4. **Chạy Job**: Bây giờ bạn có thể submit job mà không bao giờ gặp lỗi Scope nữa.

**Bước 3 vẫn không được khi tạo Key -> ... _> JSON bị lỗi**
xảy ra vì Google vừa cập nhật chính sách bảo mật mặc định cho các tài khoản mới (Organization Policy), tự động chặn việc tạo file JSON Key để tránh rò rỉ thông tin.

Vì bạn không tạo được Key, chúng ta hãy tập trung vào việc "Quét sạch máy ảo" để nó nhận được quyền "Full Access" mà bạn đã chỉnh ở Bước 1.

Bước 1: Quét sạch cấu hình lỗi trên máy ảo
Bạn hãy chạy lệnh này để xóa bỏ toàn bộ những Token "rác" đang gây lỗi Scope:

```bash
# Xóa sạch cấu hình gcloud cũ
rm -rf ~/.config/gcloud
# Thiết lập lại Project ID cho máy ảo
gcloud config set project mining-data-2
```
Bước 2: Thử chạy lại Job
Bây giờ, máy ảo sẽ bị buộc phải lấy một "Token mới" trực tiếp từ hệ thống (với quyền Full Access mà bạn đã chỉnh). Bạn hãy chạy lệnh submit job:

```bash
source recsys_env/bin/activate
export SPARK_ENV="cloud"
export RAW_DATA_DIR="gs://mining-data-2/raw_data/amazon_gpc/"
export OUTPUT_BASE="gs://mining-data-2/output/"
```

```bash
cd ~/MiningMassiveData/spark_processing_gpc
# Nhớ chạy export 3 biến môi trường trước nếu chưa chạy
gcloud dataproc jobs submit pyspark main_.....py \
    --cluster=amazon-cluster \
    --region=asia-southeast1 \
    --py-files=dependencies.zip \
    --properties="spark.executorEnv.SPARK_ENV=cloud,spark.yarn.appMasterEnv.SPARK_ENV=cloud,spark.executorEnv.RAW_DATA_DIR=gs://mining-data-2/raw_data/amazon_gpc/,spark.executorEnv.OUTPUT_BASE=gs://mining-data-2/output/" \
    -- \
    --validate
```

hoặc code mới nhất thì chỉ chạy

```bash
cd ~/MiningMassiveData/spark_processing_gpc


# Xóa file zip cũ (nếu có) hoặc chả cần vì có xip tự replace file
rm -f dependencies.zip

zip -r dependencies.zip config src

gcloud dataproc jobs submit pyspark main_12.py \
    --cluster=amazon-cluster \
    --region=asia-southeast1 \
    --py-files=dependencies.zip \
    -- \
    --validate
```
```bash
gcloud dataproc jobs submit pyspark main_34.py \
    --cluster=amazon-cluster \
    --region=asia-southeast1 \
    --py-files=dependencies.zip \
    -- \
    --validate
```

**Mẹo nhỏ (Nếu bạn vẫn muốn dùng JSON Key):**
Nếu bạn thực sự muốn bật tính năng tạo Key (dành cho các dự án sau này), bạn có thể tự tắt chính sách bảo mật này của Google:

- Tìm kiếm "Organization Policies" trên thanh tìm kiếm của GCP.
- Tìm chính sách tên là: iam.disableServiceAccountKeyCreation.
- Nhấn nút Manage Policy -> Nhấn Override.
- Ở mục Rule, chọn Off.
- Nhấn Save. (Đợi 1-2 phút là bạn có thể tạo Key như hướng dẫn Bước 3).

Nhưng tôi khuyên bạn nên thử Bước 1 (Xóa cache) trước, vì máy ảo của bạn hiện đã có quyền vạn năng rồi, chỉ là nó đang bị "kẹt" Token cũ thôi!

Bạn có thể dùng bất kỳ cửa sổ SSH nào cũng được (cửa sổ hiện tại hoặc mở cái mới trên giao diện Cloud Console đều được), vì tất cả đều truy cập vào cùng một máy ảo coordinator-vm.

** Quy trình tốt nhất bây giờ:**

- Dùng ngay cửa sổ SSH hiện tại. của VM instance (coordinator-vm).
- Chạy lệnh: rm -rf ~/.config/gcloud (Để xóa hết cái Token đang bị lỗi Scope).
- Chạy lệnh: gcloud config set project mining-data-494820 (Để máy nhận diện lại Project).
- Chạy lệnh Submit Job.
- Việc xóa thư mục .config/gcloud giống như việc bạn "reset factory" cho trình điều khiển của máy ảo. Sau đó, nó sẽ tự động dùng quyền "Full Access" mà bạn đã chỉnh trong phần Edit VM để làm việc.

Bạn thử chạy lệnh rm ngay đi, tôi tin là nó sẽ giải quyết được vấn đề!
---


**Lưu ý quan trọng: Biến môi trường (Environment Variables)**

Sau khi SSH vào `coordinator-vm` (bằng bất kỳ cách nào), bạn **bắt buộc phải** chạy lại 3 lệnh `export` ở đầu cửa sổ Terminal để khởi tạo các biến môi trường. Nếu không có các biến này, code Spark sẽ không tìm thấy đường dẫn GCS và báo lỗi `FileNotFound`.

```bash
export SPARK_ENV="cloud"
export RAW_DATA_DIR="gs://mining-data-2/raw_data/amazon_gpc/"
export OUTPUT_BASE="gs://mining-data-2/output/"
# Dòng này để kích hoạt môi trường ảo Python
source recsys_env/bin/activate
```

3. **Kết quả**
```bash
cong23122004_gmail_com@coordinator-vm:~$ source recsys_env/bin/activate
(recsys_env) cong23122004_gmail_com@coordinator-vm:~$ export SPARK_ENV="cloud"
(recsys_env) cong23122004_gmail_com@coordinator-vm:~$ export RAW_DATA_DIR="gs://mining-data-2/raw_data/amazon_gpc/"
(recsys_env) cong23122004_gmail_com@coordinator-vm:~$ export OUTPUT_BASE="gs://mining-data-2/output/"
(recsys_env) cong23122004_gmail_com@coordinator-vm:~$ cd ~/MiningMassiveData/spark_processing_gpc
(recsys_env) cong23122004_gmail_com@coordinator-vm:~/MiningMassiveData/spark_processing_gpc$ gcloud dataproc jobs submit pyspark main.py \
    --cluster=amazon-cluster \
    --region=asia-southeast1 \
    --py-files=dependencies.zip \
    --properties="spark.executorEnv.SPARK_ENV=cloud,spark.yarn.appMasterEnv.SPARK_ENV=cloud,spark.executorEnv.RAW_DATA_DIR=gs://mining-data-2/raw_data/amazon_gpc/,spark.executorEnv.OUTPUT_BASE=gs://mining-data-2/output/" \
    -- \
    --validate
Job [dc2bad9e2d844914bd38c7aa75d80c7c] submitted.
Waiting for job output...

+----------------------------------------------------------+
|       AMAZON x VN  -  BIG DATA ETL PIPELINE             |
|       PySpark  .  Phan tan song song  .  Parquet         |
+----------------------------------------------------------+
```

3. **Theo dõi tiến trình**:
- Màn hình SSH sẽ hiển thị log trực tiếp.
- Bạn sẽ thấy các dòng log mới dạng `>>> START PHASE 1...` để biết hệ thống đang chạy đến đâu.

### Theo dõi Log qua Cloud Logging (Cách chuyên nghiệp)
Nếu bạn lỡ đóng cửa sổ SSH, bạn vẫn có thể xem log:
1. Vào **Dataproc** -> **Jobs**.
2. Nhấn vào **Job ID** đang chạy.
3. Chọn tab **Monitoring** để xem biểu đồ CPU/RAM.
4. Chọn tab **Output** hoặc nhấn vào link **View logs in Cloud Logging** để xem log chi tiết, lọc theo từng Worker.

### Xóa Hạ tầng để tránh tốn tiền thêm
Ngay khi Job báo "Succeeded" và bạn đã kiểm tra kết quả trên GCS thành công.

1. Qua giao diện UI:
Vào **Dataproc** -> **Clusters** -> Chọn tick vào `amazon-cluster` -> Bấm nút **DELETE**.

2. Qua code SSH:
```bash
gcloud dataproc clusters delete amazon-cluster --region=asia-southeast1 -q
```
### Khi chạy đến Phase 3 thì code dừng do quá tải, vì phải map 4tr item.

## Khi thay đổi cấu hình RAM của VM, phải chỉnh RAM spark trên code

Phải cấu hfinh lại với các worker MẠnh hơn

Nên tôi code main2.py để chạy phase 3, -> hết.

vẫn update lên github code, sau đó pull về rồi mới:

```bash
export SPARK_ENV="cloud"
export RAW_DATA_DIR="gs://mining-data-2/raw_data/amazon_gpc/"
export OUTPUT_BASE="gs://mining-data-2/output/"
# Dòng này để kích hoạt môi trường ảo Python
source recsys_env/bin/activate
```

```bash
cd ~/MiningMassiveData/spark_processing_gpc


# Xóa file zip cũ (nếu có) hoặc chả cần vì có xip tự replace file
rm -f dependencies.zip

zip -r dependencies.zip config src

# Cần thêm lệnh spark.driver.maxResultSize=4g, để driver lấy dữ liệu từ tất cả workers
gcloud dataproc jobs submit pyspark main_34.py \
    --cluster=amazon-cluster \
    --region=asia-southeast1 \
    --py-files=dependencies.zip \
    --properties="spark.executor.memory=7g,spark.executor.memoryOverhead=3g,spark.driver.memory=7g,spark.driver.memoryOverhead=3g,spark.shuffle.compress=true,spark.shuffle.spill.compress=true,spark.driver.maxResultSize=4g" \
    -- \
    --validate
```
```text
1. spark.shuffle.compress=true (Nén dữ liệu khi truyền qua mạng)

Shuffle là gì? Khi bạn thực hiện các lệnh như Join hay GroupBy, Spark phải gom dữ liệu từ máy Worker này chuyển sang máy Worker khác thông qua mạng nội bộ. Việc này gọi là Shuffle.
Tác dụng: Khi bật =true, Spark sẽ nén (compress) dữ liệu lại cho nhỏ gọn trước khi gửi qua mạng.
Lợi ích: Giảm đáng kể tình trạng nghẽn mạng (Network Bottleneck) giữa các máy ảo trên Cloud. Bù lại, CPU sẽ tốn một chút xíu sức lực để nén và giải nén.
2. spark.shuffle.spill.compress=true (Nén dữ liệu khi xả xuống ổ cứng)

Spill là gì? Như tôi vừa giải thích ở tin nhắn trước, khi RAM của Worker bị đầy trong lúc Join/Sort, Spark sẽ xả tạm dữ liệu (Spill) xuống ổ cứng 30GB.
Tác dụng: Khi bật =true, Spark sẽ nén cái đống dữ liệu đó lại trước khi ghi xuống ổ cứng.
Lợi ích: Tốc độ đọc/ghi của ổ cứng (Disk I/O) luôn là thứ chậm chạp nhất trong máy tính. Việc nén dữ liệu giúp dung lượng file xả xuống nhỏ hơn rất nhiều -> Ghi xuống đĩa nhanh hơn -> Đọc lên lại cũng nhanh hơn -> Tránh được lỗi nghẽn ổ cứng.
```

## Lưu ý về SPARK.

**Spark lazy evaluation (Đánh giá lười biếng)**
Trong Spark, tất cả các lệnh trước đó (Join, GroupBy, Filter) đều là Lazy Evaluation (nó chỉ ghi lại kế hoạch chứ chưa chạy).
Lệnh Ghi file (coalesce 16) là lệnh thực thi đầu tiên, kích hoạt toàn bộ chuỗi tính toán.

```bash
window_limit = Window.partitionBy("cand_category").orderBy(F.rand())
    df_vn_sampled = df_vn.withColumn("rn", F.row_number().over(window_limit)) \
                         .filter(F.col("rn") <= 500) # Chỉ lấy tối đa 500 ứng viên mỗi Category để Mining
    
    # Mining: Join Query với tập Candidate đã được thu gọn (Sampled)
    df_neg_candidates = query_ids_df.join(F.broadcast(df_vn_sampled), 
                                          query_ids_df.query_category == df_vn_sampled.cand_category, 
                                          "inner") \
                                    .filter(F.col("query_id") != F.col("cand_asin"))
    
    # Chọn ra 99 Negative cho mỗi Query từ tập ứng viên
    window_neg = Window.partitionBy("query_id").orderBy(F.rand())
    df_negatives = df_neg_candidates.withColumn("rank", F.row_number().over(window_neg)) \
                                    .filter(F.col("rank") <= (num_candidates - 1)) \
                                    .select("query_id", "cand_id") \
                                    .withColumn("label", F.lit(0))

    # 4. Gom tập Positive và Negative
    df_final_ids = df_pos.select("query_id", "cand_id", "label") \
                         .unionByName(df_negatives)

    # Group IDs lại thành List (Format chuẩn cho Training)
    df_grouped = df_final_ids.groupBy("query_id").agg(
        F.collect_list("cand_id").alias("candidate_ids"),
        F.collect_list("label").alias("labels")
    )

    # 5. Join lại với Metadata Amazon (Heavy)
    df_amz_metadata = df_items.filter(F.col("domain") == "amazon").select(
        F.col("asin").alias("query_id"),
        F.col("product_name").alias("query_name"),
        F.col("full_text").alias("query_text"),
        F.col("category").alias("query_category"),
        F.to_json(F.col("parsed_specs")).alias("query_specs")
    )
    
    # df_eval = df_grouped.join(F.broadcast(df_amz_metadata), "query_id", "inner")
    df_eval = df_grouped.join(df_amz_metadata, "query_id", "inner")

    # Trong Spark, tất cả các lệnh trước đó (Join, GroupBy, Filter) đều là Lazy Evaluation (nó chỉ ghi lại kế hoạch chứ chưa chạy).
    # Lệnh Ghi file (coalesce 16) là lệnh thực thi đầu tiên, kích hoạt toàn bộ chuỗi tính toán.
    # Ghi kết quả (TỐI ƯU: Coalesce để giảm phí Class A trên GCS)
    logger.info(f"Ghi ket qua Evaluation (Coalesce 16) xuong: {output_path}")
    df_eval.coalesce(16).write.mode("overwrite").parquet(output_path)
    
    df_items.unpersist()
```
---

## Bước 9: Theo dõi Log
Vì chúng ta đã tắt tính năng ghi log vào file cục bộ (để tránh lỗi GCS), bạn hãy theo dõi log tại:
1. Console Dataproc -> Jobs -> Nhấn vào Job ID đang chạy.
2. Tab **Output**: Xem log thời gian thực.
3. Hoặc vào **Cloud Logging** để xem log chi tiết của toàn bộ hệ thống.

---

## Lời khuyên cực kỳ quan trọng:
- **TẮT MÁY (STOP)**: Khi không làm việc, hãy nhấn nút **Stop** cho VM và **Delete** cụm Dataproc. Nếu để nó chạy qua đêm, bạn sẽ mất rất nhiều tiền (Quota GPU và Dataproc tính phí theo giờ).
- **Quota**: Nếu không tạo được GPU, bạn cần vào "IAM & Admin" -> "Quotas" để yêu cầu Google tăng hạn mức GPU (với tài khoản mới thường là 0).
- **TẮT MÁY (STOP)**: Luôn **Delete** cụm Dataproc sau khi xong việc. GCS sẽ giữ lại toàn bộ kết quả Parquet cho bạn.
- **Quota**: Nếu bị lỗi tạo máy ảo, hãy kiểm tra "Quotas" để đảm bảo tài khoản của bạn được phép dùng máy ảo tại `us-central1`.

Bạn hãy bắt đầu từ **Bước 1 và Bước 2** đi, nếu vướng ở đâu hãy hỏi tôi ngay nhé!
