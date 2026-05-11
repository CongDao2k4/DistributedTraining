import pickle
import pandas as pd
import numpy as np
import logging
import os
import pyarrow.parquet as pq
from config.training_config import TrainingConfig

logger = logging.getLogger("data_utils")

class PrecomputedEmbeddingLookup:
    """Hệ thống tra cứu Vector siêu tốc bằng Memory-Mapping."""
    def __init__(self, embeddings_npy, id_to_idx):
        self.embeddings = embeddings_npy
        self.id_to_idx = id_to_idx
        self.dim = embeddings_npy.shape[1]

    def get_embedding(self, item_id):
        idx = self.id_to_idx.get(item_id)
        if idx is None:
            return np.zeros(self.dim, dtype=np.float32)
        return self.embeddings[idx]

def load_precomputed_embeddings():
    """Nạp dữ liệu vector đã tính toán trước."""
    emb_path = TrainingConfig.ITEM_EMBEDDINGS_PATH
    idx_path = TrainingConfig.ITEM_INDEX_PATH
    
    if not os.path.exists(emb_path) or not os.path.exists(idx_path):
        logger.error("KHÔNG TÌM THẤY DỮ LIỆU PRECOMPUTED!")
        return None
        
    with open(idx_path, "rb") as f:
        id_to_idx = pickle.load(f)
    embeddings = np.load(emb_path, mmap_mode='r')
    return PrecomputedEmbeddingLookup(embeddings, id_to_idx)

def load_eval_dataset():
    """Tải tập Evaluation (Pickle) để đánh giá."""
    path = TrainingConfig.EVAL_PKL_PATH
    if not os.path.exists(path):
        path = "data/prepared_data_improved/evaluation_dataset.pkl"
    with open(path, 'rb') as f:
        return pickle.load(f)

def load_interactions_df():
    """
    Tải lịch sử tương tác sử dụng PyArrow (Thay thế hoàn toàn thư viện datasets).
    Chỉ nạp tỷ lệ phần trăm dữ liệu được chỉ định (mặc định 25%).
    """
    import gcsfs
    path = TrainingConfig.GCS_INTERACTIONS if TrainingConfig.IS_CLOUD else "data/all_interactions"
    fraction = TrainingConfig.DATA_FRACTION
    
    if TrainingConfig.RANK == 0:
        logger.info(f"==> [PyArrow] Đang nạp {int(fraction*100)}% tương tác từ: {path}")
    
    # 1. Kết nối GCS nếu cần
    fs = gcsfs.GCSFileSystem() if TrainingConfig.IS_CLOUD else None
    arrow_path = path.replace("gs://", "") if TrainingConfig.IS_CLOUD else path
    
    # 2. Đọc toàn bộ bảng (Chỉ lấy 2 cột ID để tiết kiệm RAM)
    dataset = pq.ParquetDataset(arrow_path, filesystem=fs)
    table = dataset.read(columns=['asin', 'product_id'])
    
    # 3. Thực hiện Slice (Cắt) lấy 25% đầu tiên
    num_rows = table.num_rows
    target_rows = int(num_rows * fraction)
    table_subset = table.slice(0, target_rows)
    
    if TrainingConfig.RANK == 0:
        logger.info(f"==> Thành công! Đã nạp {table_subset.num_rows:,} dòng tương tác (Tổng file: {num_rows:,})")
    
    # Chuyển sang Pandas để các file Trainer truy cập được bằng index [idx]
    return table_subset.to_pandas()
