import os
import sys
import logging
import pickle
import gcsfs
import pyarrow.parquet as pq
import numpy as np
import io
import subprocess

# Thêm thư mục gốc vào path để import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.training_config import TrainingConfig
from tqdm import tqdm

# Cấu hình logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("fix_index")

def get_npy_shape_gcs(fs, gcs_path):
    """
    Đọc chuẩn header của file .npy từ GCS để lấy shape mà không tải toàn bộ dữ liệu.
    """
    import numpy.lib.format as npy_format
    try:
        with fs.open(gcs_path, 'rb') as f:
            # Đọc magic string và version
            version = npy_format.read_magic(f)
            # Đọc header dựa trên version
            if version == (1, 0):
                shape, fortan, dtype = npy_format.read_array_header_1_0(f)
            else:
                shape, fortan, dtype = npy_format.read_array_header_2_0(f)
            return shape
    except Exception as e:
        logger.error(f"Không thể đọc header NPY tại {gcs_path}: {e}")
        raise e

def run_index_rescue():
    """
    Script THANH TRA và CỨU HỘ: 
    - Đối soát chéo giữa Parquet, .npy và .pkl con.
    - Sửa và ghi đè các file .pkl con trên GCS để đảm bảo đúng Prefix.
    - Chuẩn bị dữ liệu để có thể Merge ngay lập tức.
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
        f_name = os.path.basename(p_path).replace(".parquet", "")
        npy_path = f"{chunks_path}/{f_name}.npy"
        pkl_con_path = f"{chunks_path}/{f_name}.pkl"

        try:
            # --- 1. Thanh tra dữ liệu ---
            table = pq.read_table(p_path, columns=['product_id', 'asin', 'domain'], filesystem=fs)
            parquet_rows = len(table)
            
            if not fs.exists(npy_path):
                logger.error(f"[!!!] THIẾU VECTOR: {npy_path}. Bỏ qua file này."); continue
            
            npy_rows = get_npy_shape_gcs(fs, npy_path)[0]

            # --- 2. Đối soát ---
            # Lưu ý: Nếu npy_rows != parquet_rows, có nghĩa là file npy đó bị lỗi hoặc đã lọc dữ liệu rác.
            if npy_rows != parquet_rows:
                logger.warning(f"\n[!] CẢNH BÁO: {f_name} có sự sai lệch. Parquet={parquet_rows}, NPY={npy_rows}. Có thể do đã lọc rác.")
                # Nếu bạn muốn fix triệt để, npy_rows phải bằng parquet_rows. 
                # Nếu không, tốt nhất nên xóa file này trên GCS và chạy lại Precompute.

            # --- 3. Tạo Index con MỚI (Dựa trên số lượng NPY thực tế để đảm bảo 1:1) ---
            p_ids = table['product_id'].to_pylist()
            asins = table['asin'].to_pylist()
            domains = table['domain'].to_pylist()
            
            new_chunk_index = {}
            # Chỉ lấy số lượng bằng đúng số vector đang có
            for i in range(min(parquet_rows, npy_rows)):
                p_id, asin, dom = p_ids[i], asins[i], domains[i]
                if dom == 'amazon':
                    if asin: new_chunk_index[f"amz_{asin}"] = i
                else:
                    if p_id: new_chunk_index[f"vn_{p_id}"] = i

            # --- 4. Ghi đè file pkl con lên GCS ---
            local_chunk_pkl = os.path.join(TrainingConfig.LOCAL_DATA_DIR, f"{f_name}.pkl")
            os.makedirs(TrainingConfig.LOCAL_DATA_DIR, exist_ok=True)
            with open(local_chunk_pkl, "wb") as f_out:
                pickle.dump(new_chunk_index, f_out)
            
            subprocess.run(["gsutil", "-q", "cp", local_chunk_pkl, pkl_con_path], check=True)
            os.remove(local_chunk_pkl)
            
            logger.info(f" [FIXED] {f_name}: Đã cập nhật pkl khớp với NPY ({npy_rows} rows).")
            
        except Exception as e:
            logger.error(f"Lỗi tại {f_name}: {e}")

    logger.info("==> CỨU HỘ HOÀN TẤT.")

if __name__ == "__main__":
    run_index_rescue()
