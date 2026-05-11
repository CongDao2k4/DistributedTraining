import os
import subprocess
import logging
from config.training_config import TrainingConfig

logger = logging.getLogger("gcs_manager")

def download_training_data():
    """Tải dữ liệu .pkl và các file vector đã precompute (nếu có) từ GCS."""
    local_dir = TrainingConfig.LOCAL_DATA_DIR
    gcs_path = TrainingConfig.GCS_PREPARED_DATA
    
    logger.info(f"Đang đồng bộ dữ liệu từ {gcs_path} về {local_dir}...")
    
    # Tải các file .pkl cơ bản
    subprocess.run(["gsutil", "-m", "cp", f"{gcs_path}/*.pkl", local_dir], check=False)
    
    # Kiểm tra và tải file vector 12GB nếu đã tồn tại trên GCS (Tiết kiệm 1 tiếng precompute)
    emb_file = "item_embeddings.npy"
    idx_file = "item_index.pkl"
    
    for f in [emb_file, idx_file]:
        remote_f = f"{gcs_path}/{f}"
        local_f = os.path.join(local_dir, f)
        if not os.path.exists(local_f):
            logger.info(f"Đang kiểm tra {f} trên GCS...")
            # Kiểm tra file có tồn tại trên GCS không trước khi tải
            result = subprocess.run(["gsutil", "-q", "stat", remote_f], capture_output=True)
            if result.returncode == 0:
                logger.info(f"Tìm thấy {f} trên GCS. Đang tải về siêu tốc...")
                subprocess.run(["gsutil", "-m", "cp", remote_f, local_f], check=True)

def upload_precomputed_data():
    """Upload file vector 12GB lên GCS để các lần chạy sau không phải tính lại."""
    local_dir = TrainingConfig.LOCAL_DATA_DIR
    gcs_path = TrainingConfig.GCS_PREPARED_DATA
    
    emb_file = os.path.join(local_dir, "item_embeddings.npy")
    idx_file = os.path.join(local_dir, "item_index.pkl")
    
    if os.path.exists(emb_file) and os.path.exists(idx_file):
        logger.info("Đang upload bộ nhớ đệm Vector lên GCS (Chỉ thực hiện 1 lần duy nhất)...")
        subprocess.run(["gsutil", "-m", "cp", emb_file, gcs_path], check=True)
        subprocess.run(["gsutil", "-m", "cp", idx_file, gcs_path], check=True)
        logger.info("==> Đã lưu kho thành công!")

def upload_model_checkpoint(local_path):
    """Upload model sau khi train xong."""
    gcs_dest = f"{TrainingConfig.GCS_OUTPUT_DIR}/models_checkpoints/"
    logger.info(f"Uploading {local_path} to {gcs_dest}")
    subprocess.run(["gsutil", "cp", local_path, gcs_dest], check=True)
