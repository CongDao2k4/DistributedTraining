#!/bin/bash

# submit_job.sh - Script chuẩn gửi huấn luyện phân tán lên Google Vertex AI
#
# CÁCH DÙNG:
#   1. Trên Linux/Mac/Git Bash: ./submit_job.sh [baseline_id]
#   2. Trên Windows PowerShell: bash distributed_training/submit_job.sh [baseline_id]
#
# Tham số: [baseline_id] có thể là 1, 2, 3, 4, 5, 6 hoặc "all" (mặc định)

# --- 0. ĐẢM BẢO CHẠY ĐÚNG THƯ MỤC ---
cd "$(dirname "$0")"

# --- 1. CẤU HÌNH DỰ ÁN (BẮT BUỘC THAY ĐỔI) ---
PROJECT_ID="mining-data-2"   # <--- THAY BẰNG PROJECT ID CỦA BẠN
REGION="asia-southeast1"           # Vùng chạy (us-central1, asia-southeast1, ...)
BUCKET="mining-data-2"         # Tên GCS Bucket của bạn

# --- 2. CẤU HÌNH PHẦN CỨNG ---
MACHINE_TYPE="n1-highmem-8"   # Loại máy (8 vCPU, 52GB RAM)
ACCELERATOR_TYPE="NVIDIA_TESLA_T4" # Loại GPU, tên định danh GPU T4 trên Vertex AI
ACCELERATOR_COUNT=4            # CHẠY 4 GPU PHÂN TÁN trên mỗi node VM
REPLICA_COUNT=1                # Số lượng Node VM (1 cho Single-Node, >1 cho Multi-Node)

# --- 3. XỬ LÝ THAM SỐ VÀ TAG ---
BASELINE_ID="$1"
if [ -z "$BASELINE_ID" ]; then
    BASELINE_ID="all"
fi
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
IMAGE_NAME="distributed-training"
# Sử dụng Artifact Registry cùng Region (asia-southeast1) để tránh lỗi kéo image liên lục địa
REPO_NAME="recsys-repo-2"
IMAGE_URI="asia-southeast1-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/$IMAGE_NAME:v_$TIMESTAMP"

# --- 4. KIỂM TRA PROJECT ID ---
if [ "$PROJECT_ID" == "your-project-id" ]; then
    echo "LỖI: Vui lòng mở file submit_job.sh và thay PROJECT_ID bằng ID dự án của bạn!"
    exit 1
fi

echo "=========================================================="
echo "   RECSYS DISTRIBUTED TRAINING SUBMITTER"
echo "   Baseline: $BASELINE_ID | Region: $REGION"
echo "   Image:    $IMAGE_URI"
echo "=========================================================="

# --- 5. BUILD & PUSH DOCKER ---
echo ">>> Đang đóng gói Code và đẩy lên Cloud..."
gcloud auth configure-docker asia-southeast1-docker.pkg.dev --quiet
docker build -t $IMAGE_URI .
docker push $IMAGE_URI

# --- 6. KHỞI TẠO JOB TRÊN VERTEX AI ---
echo ">>> Đang gửi yêu cầu huấn luyện lên Vertex AI..."
gcloud ai custom-jobs create \
    --region=$REGION \
    --project=$PROJECT_ID \
    --display-name="RecSys_Baseline_${BASELINE_ID}_${TIMESTAMP}" \
    --worker-pool-spec="machine-type=$MACHINE_TYPE,replica-count=$REPLICA_COUNT,container-image-uri=$IMAGE_URI,accelerator-type=$ACCELERATOR_TYPE,accelerator-count=$ACCELERATOR_COUNT" \
    --args="--baseline=$BASELINE_ID"

echo "----------------------------------------------------------"
echo "KẾT QUẢ: Job đã được gửi thành công!"
echo "Bạn có thể theo dõi tại: https://console.cloud.google.com/vertex-ai/training/custom-jobs?project=$PROJECT_ID"
echo "=========================================================="
