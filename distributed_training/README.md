# Distributed Training Pipeline for 5 Baselines

Hệ thống huấn luyện phân tán đa máy chủ (Multi-node Distributed Training) được thiết kế để huấn luyện 5 mô hình baseline dựa trên dữ liệu đã được xử lý từ Spark.

---

## 🏗️ Kiến trúc hệ thống
Hệ thống sử dụng **PyTorch Distributed Data Parallel (DDP)** và công cụ điều phối **`torchrun`** (theo kiến trúc từ repo `hkproj`).

*   **Orchestrator**: Điều phối chạy lần lượt 5 model (Sequential Training).
*   **DDP Engine**: Tăng tốc huấn luyện bằng cách phân tán dữ liệu lên nhiều GPU/Nodes.
*   **Data Bridge**: Đọc trực tiếp định dạng Parquet từ Spark output.

---

## 🛠️ Thiết lập trên Google Cloud Platform (GCP)

### 1. Cấu hình mạng (Networking)
*   Đảm bảo các máy (Nodes) nằm trong cùng một **VPC Network** và cùng **Region**.
*   Mở Port `12355` (hoặc Port bạn cấu hình) trong Firewall để các máy có thể giao tiếp với nhau.
*   Lấy **Internal IP** của máy Master (Node 0).

### 2. Cài đặt môi trường (Trên tất cả các Nodes)
```bash
pip install torch torchvision torchaudio
pip install pandas pyarrow fastparquet
pip install transformers  # Phục vụ SBERT
```

---

## ⚙️ Cấu hình trước khi chạy

Mở file `distributed_training/config/cluster_config.py` và cập nhật:
*   `WORLD_SIZE`: Tổng số máy tham gia (Ví dụ: 2 hoặc 4).
*   `MASTER_ADDR`: IP nội bộ của máy Master.
*   `DATA_PATH`: Đường dẫn đến thư mục chứa file Parquet của Spark.

---

## 🚀 Cách vận hành

### Chạy qua Orchestrator (Tự động chạy lần lượt 5 model)
Trên **TẤT CẢ các máy**, thực hiện lệnh sau tại thư mục `distributed_training`:

```bash
python pipeline_orchestrator.py
```

### Chạy thủ công từng mô hình (Ví dụ SBERT)
Nếu bạn muốn debug riêng từng model, sử dụng lệnh `torchrun`:

```bash
# Chạy trên máy Master (Rank 0)
torchrun --nnodes=2 --nproc_per_node=1 --rdzv_id=101 --rdzv_backend=c10d --rdzv_endpoint=MASTER_IP:12355 train_sbert.py

# Chạy trên máy Slave (Rank 1)
torchrun --nnodes=2 --nproc_per_node=1 --rdzv_id=101 --rdzv_backend=c10d --rdzv_endpoint=MASTER_IP:12355 train_sbert.py
```

---

## 📊 Danh sách 5 Baseline Models

1.  **BM25**: Chạy thuật toán xếp hạng dựa trên tần suất từ (Chạy Spark job).
2.  **SBERT**: Huấn luyện mô hình Bi-Encoder để nhúng văn bản vào không gian vector.
3.  **DSSM**: Mô hình tháp đôi (Deep Structured Semantic Model) để khớp Query-Candidate.
4.  **GCN**: Sử dụng đồ thị (Graph Convolutional Network) để học mối quan hệ giữa các sản phẩm.
5.  **HYBRID**: Kết hợp kết quả từ các model trên bằng kỹ thuật Ensemble.

---

## ⚠️ Lưu ý quan trọng
*   **Đồng bộ dữ liệu**: Đảm bảo thư mục dữ liệu đầu ra từ Spark có mặt trên tất cả các máy tại cùng một đường dẫn (Khuyên dùng GCP Filestore hoặc Mount ổ đĩa mạng).
*   **Checkpoint**: Model sau khi train sẽ được lưu tại `output/trained_models/`. Máy Master (Rank 0) sẽ chịu trách nhiệm lưu file này.
