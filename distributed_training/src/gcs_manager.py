import os
import subprocess
import logging
import numpy as np
import pickle
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
    """Upload file vector và index tổng lên GCS."""
    local_dir = TrainingConfig.LOCAL_DATA_DIR
    gcs_path = TrainingConfig.GCS_PREPARED_DATA
    
    emb_file = os.path.join(local_dir, "item_embeddings.npy")
    idx_file = os.path.join(local_dir, "item_index.pkl")
    
    if os.path.exists(emb_file) and os.path.exists(idx_file):
        logger.info("Đang upload bộ nhớ đệm Vector tổng lên GCS...")
        subprocess.run(["gsutil", "-m", "cp", emb_file, gcs_path], check=True)
        subprocess.run(["gsutil", "-m", "cp", idx_file, gcs_path], check=True)

def merge_precomputed_chunks():
    """
    Hợp nhất các file mảnh (chunks) từ GCS thành một file vector 12GB và file index duy nhất.
    Đảm bảo tính nhất quán của index khi gộp.
    """
    local_dir = TrainingConfig.LOCAL_DATA_DIR
    gcs_chunks_path = f"{TrainingConfig.GCS_PREPARED_DATA}/chunks"
    
    final_npy_path = TrainingConfig.ITEM_EMBEDDINGS_PATH
    final_pkl_path = TrainingConfig.ITEM_INDEX_PATH

    logger.info(">>> BẮT ĐẦU QUY TRÌNH HỢP NHẤT CHUNKS...")

    # 1. Tải tất cả chunks về local
    subprocess.run(["gsutil", "-m", "cp", f"{gcs_chunks_path}/*.npy", local_dir], check=True)
    subprocess.run(["gsutil", "-m", "cp", f"{gcs_chunks_path}/*.pkl", local_dir], check=True)

    all_npy_files = sorted([f for f in os.listdir(local_dir) if f.endswith(".npy") and f != "item_embeddings.npy"])
    
    if not all_npy_files:
        logger.warning("Không tìm thấy file chunk nào để gộp!")
        return

    # 2. Khảo sát kích thước để tạo memmap
    total_rows = 0
    file_info = []
    for npy_f in all_npy_files:
        data_path = os.path.join(local_dir, npy_f)
        # Load header-only để lấy shape mà không tốn RAM
        data_shape = np.load(data_path, mmap_mode='r').shape
        file_info.append((npy_f, data_shape[0]))
        total_rows += data_shape[0]

    logger.info(f"Tổng hợp {len(all_npy_files)} mảnh. Tổng số item: {total_rows:,}")

    # 3. Gộp Vector dùng Memmap (RAM Safe)
    fp = np.memmap(final_npy_path, dtype='float32', mode='w+', shape=(total_rows, 768))
    
    final_index = {}
    curr_offset = 0
    
    for npy_f, n_rows in file_info:
        logger.info(f"Đang gộp {npy_f} ({n_rows:,} rows)...")
        # Đọc mảnh
        data_path = os.path.join(local_dir, npy_f)
        data = np.load(data_path)
        
        # Ghi vào vị trí tương ứng trong file tổng
        fp[curr_offset : curr_offset + n_rows] = data
        
        # Đọc và offset lại Index
        pkl_f = npy_f.replace(".npy", ".pkl")
        pkl_path = os.path.join(local_dir, pkl_f)
        with open(pkl_path, "rb") as f_in:
            chunk_idx = pickle.load(f_in)
        
        for key, val in chunk_idx.items():
            # Quan trọng: Cộng dồn offset để index trỏ đúng vào file tổng
            final_index[key] = curr_offset + val
            
        curr_offset += n_rows
        
        # Xóa mảnh local ngay sau khi gộp để giải phóng SSD
        os.remove(data_path)
        os.remove(pkl_path)

    fp.flush()
    del fp # Đóng file
    
    # 4. Lưu file index tổng
    with open(final_pkl_path, "wb") as f_out:
        pickle.dump(final_index, f_out)
    
    logger.info("==> Hợp nhất hoàn tất. Đang upload kết quả cuối cùng...")
    upload_precomputed_data()

def upload_model_checkpoint(local_path):
    gcs_dest = f"{TrainingConfig.GCS_OUTPUT_DIR}/models_checkpoints/"
    subprocess.run(["gsutil", "cp", local_path, gcs_dest], check=True)
