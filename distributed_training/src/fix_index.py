import os
import sys
import logging
import pickle
import gcsfs
import pyarrow.parquet as pq
import numpy as np
import io
import subprocess

from config.training_config import TrainingConfig
from tqdm import tqdm

# Cấu hình logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("fix_index")

def get_npy_shape_gcs(fs, gcs_path):
    """
    Đọc header của file .npy trên GCS để lấy shape mà không cần tải cả file lớn.
    """
    try:
        with fs.open(gcs_path, 'rb') as f:
            # Chỉ đọc 128 bytes đầu tiên (đủ chứa header của numpy)
            header = f.read(128)
            with io.BytesIO(header) as bio:
                # np.load có thể đọc từ stream, ta chỉ cần metadata
                d = np.load(bio)
                return d.shape
    except Exception:
        # Fallback nếu header phức tạp hơn
        with fs.open(gcs_path, 'rb') as f:
            return np.load(f, mmap_mode='r').shape

def run_index_rescue():
    """
    Script THANH TRA và CỨU HỘ: 
    - Đối soát chéo giữa Parquet, .npy và .pkl con.
    - Sửa và ghi đè 16 file .pkl con trên GCS.
    - Tạo file item_index.pkl tổng hợp (Prefix vn_/amz_).
    """
    logger.info(">>> BẮT ĐẦU QUY TRÌNH THANH TRA VÀ CỨU HỘ (CHẾ ĐỘ GHI ĐÈ CHUNKS) <<<")
    
    fs = gcsfs.GCSFileSystem()
    parquet_path = TrainingConfig.GCS_ITEM_NODES
    chunks_path = f"{TrainingConfig.GCS_PREPARED_DATA}/chunks"
    
    # 1. Lấy danh sách Parquet và sắp xếp
    all_parquets = sorted([f"gs://{f}" for f in fs.ls(parquet_path) if f.endswith(".parquet")])
    logger.info(f"Tìm thấy {len(all_parquets)} file Parquet để xử lý.")

    final_index = {}
    curr_offset = 0

    # 2. Duyệt qua từng file để xây dựng lại Mapping
    for idx, p_path in enumerate(tqdm(all_parquets, desc="Sửa file pkl con")):
        # Lấy tên file gốc (ví dụ: part-00000...) để khớp với output của precompute
        f_name = os.path.basename(p_path).replace(".parquet", "")
        npy_path = f"{chunks_path}/{f_name}.npy"
        pkl_con_path = f"{chunks_path}/{f_name}.pkl"

        try:
            # --- 1. Thanh tra dữ liệu ---
            table = pq.read_table(p_path, columns=['product_id', 'asin', 'domain'], filesystem=fs)
            parquet_rows = len(table)
            
            if not fs.exists(npy_path):
                logger.error(f"[!!!] THIẾU VECTOR: {npy_path}"); return
            npy_rows = get_npy_shape_gcs(fs, npy_path)[0]

            # --- C. Kiểm tra file .pkl con (Index cũ) ---
            if not fs.exists(pkl_con_path):
                logger.error(f"[!!!] THIẾU PKL: {pkl_con_path}"); return
            
            with fs.open(pkl_con_path, 'rb') as f:
                old_idx = pickle.load(f)
                pkl_rows = (max(old_idx.values()) + 1) if old_idx else 0

            # --- 2. Đối soát ---
            if not (parquet_rows == npy_rows == pkl_rows):
                logger.error(f"\n[!!!] DỮ LIỆU KHÔNG KHỚP TẠI {f_name}! Parquet={parquet_rows}, NPY={npy_rows}, PKL={pkl_rows}")
                return

            # --- 3. Tạo Index con MỚI (Prefix) ---
            p_ids = table['product_id'].to_pylist()
            asins = table['asin'].to_pylist()
            domains = table['domain'].to_pylist()
            
            new_chunk_index = {}
            for i in range(parquet_rows):
                p_id, asin, dom = p_ids[i], asins[i], domains[i]
                if dom == 'amazon':
                    if asin: 
                        new_chunk_index[f"amz_{asin}"] = i
                        final_index[f"amz_{asin}"] = curr_offset + i
                else:
                    if p_id: 
                        new_chunk_index[f"vn_{p_id}"] = i
                        final_index[f"vn_{p_id}"] = curr_offset + i

            # --- 4. Ghi đè file pkl con lên GCS ---
            local_chunk_pkl = os.path.join(TrainingConfig.LOCAL_DATA_DIR, f"{f_name}.pkl")
            os.makedirs(TrainingConfig.LOCAL_DATA_DIR, exist_ok=True)
            with open(local_chunk_pkl, "wb") as f_out:
                pickle.dump(new_chunk_index, f_out)
            
            # Ghi đè trực tiếp lên GCS
            subprocess.run(["gsutil", "cp", local_chunk_pkl, pkl_con_path], check=True)
            os.remove(local_chunk_pkl)
            
            curr_offset += parquet_rows
            
        except Exception as e:
            logger.error(f"Lỗi tại {f_name}: {e}"); return

    logger.info(f"\n==> ĐÃ GHI ĐÈ 16 FILE PKL CON THÀNH CÔNG.")
    
    # 5. Lưu file Index tổng hợp (Tạm thời comment theo yêu cầu để chỉ sửa chunks)
    # local_pkl = os.path.join(TrainingConfig.LOCAL_DATA_DIR, "item_index.pkl")
    # with open(local_pkl, "wb") as f:
    #     pickle.dump(final_index, f)
    # subprocess.run(["gsutil", "cp", local_pkl, f"{TrainingConfig.GCS_PREPARED_DATA}/item_index.pkl"], check=True)
    
    # Ghi cờ hoàn tất
    done_flag = f"{TrainingConfig.GCS_PREPARED_DATA}/_final_done.txt"
    subprocess.run(["gsutil", "cp", "/dev/null", done_flag], check=True)
    
    logger.info("==> CỨU HỘ HOÀN TẤT. Bạn có thể tiến hành MERGE hoặc TRAINING.")

if __name__ == "__main__":
    run_index_rescue()
