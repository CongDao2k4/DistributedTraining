import os
import torch
import numpy as np
import logging
import pyarrow.parquet as pq
from sentence_transformers import SentenceTransformer
from config.training_config import TrainingConfig
import torch.distributed as dist
import time
import pickle
import gc
import subprocess
from datetime import timedelta

def check_gcs_file_exists(gcs_path):
    """Kiểm tra sự tồn tại của file trên GCS bằng gsutil stat."""
    result = subprocess.run(["gsutil", "-q", "stat", gcs_path], capture_output=True)
    return result.returncode == 0

def precompute_item_embeddings():
    """
    Chiến thuật 'Độc lập tác chiến' (Independent Workers):
    - Mỗi GPU xử lý một nhóm file Parquet riêng biệt (Sharding by File).
    - KHÔNG ĐỒNG BỘ giữa chừng -> Loại bỏ 100% rủi ro treo (Deadlock) hoặc NCCL Timeout.
    - Hỗ trợ Resume mạnh mẽ: Tự động bỏ qua các file đã hoàn tất từ phiên chạy trước.
    - RAM Efficient: Phù hợp với file Parquet 150MB.
    """
    rank = TrainingConfig.RANK
    world_size = TrainingConfig.WORLD_SIZE
    device = TrainingConfig.DEVICE
    logger = logging.LoggerAdapter(logging.getLogger("precompute"), {'rank': rank})

    # 0. Khởi tạo Distributed (Cần thiết để Rank 0 gộp file cuối cùng)
    if world_size > 1 and not dist.is_initialized():
        dist.init_process_group(backend="nccl", timeout=timedelta(minutes=180))

    chunks_gcs_dir = f"{TrainingConfig.GCS_PREPARED_DATA}/chunks"
    os.makedirs(TrainingConfig.LOCAL_DATA_DIR, exist_ok=True)
    
    # 1. Lấy danh sách file Parquet
    path = TrainingConfig.GCS_ITEM_NODES if TrainingConfig.IS_CLOUD else "data/item_nodes"
    import gcsfs
    fs = gcsfs.GCSFileSystem() if TrainingConfig.IS_CLOUD else None
    if TrainingConfig.IS_CLOUD:
        all_files = sorted([f"gs://{f}" for f in fs.ls(path) if f.endswith(".parquet")])
    else:
        import glob
        all_files = sorted(glob.glob(os.path.join(path, "*.parquet")))

    # 2. CHIA PHẦN: Mỗi GPU đảm nhận các file tương ứng với Rank của mình (Ví dụ: GPU 0 làm file 0, 4, 8, 12)
    my_files = all_files[rank::world_size]
    
    if rank == 0:
        logger.info(f"==> TỔNG CỘNG: {len(all_files)} FILE. MỖI GPU SẼ XỬ LÝ KHOẢNG {len(my_files)} FILE.")
    
    model = SentenceTransformer('paraphrase-multilingual-mpnet-base-v2', device=device)

    # 3. Vòng lặp xử lý độc lập
    for f_idx, f_path in enumerate(my_files):
        f_name = os.path.basename(f_path).replace(".parquet", "")
        done_flag_gcs = f"{chunks_gcs_dir}/{f_name}_done.txt"
        
        # Checkpoint: Nếu file này đã xong thì bỏ qua ngay
        if check_gcs_file_exists(done_flag_gcs):
            logger.info(f"SKIP: {f_name} (Đã hoàn tất)")
            continue
            
        logger.info(f"PROCESSING: {f_name} ({f_idx+1}/{len(my_files)})")

        try:
            # Đọc nguyên file Parquet (150MB an toàn cho 1 GPU)
            table = pq.read_table(f_path, columns=['product_id', 'asin', 'full_text'], filesystem=fs)
            texts = table['full_text'].to_pylist()
            ids = table['product_id'].to_pylist()
            asins = table['asin'].to_pylist()
            del table
            
            # Encode toàn bộ file
            embs = model.encode(texts, batch_size=512, convert_to_numpy=True, show_progress_bar=False)
            
            # Tạo index nội bộ cho chunk này
            chunk_index = {}
            for i, (p_id, asin) in enumerate(zip(ids, asins)):
                if p_id: chunk_index[p_id] = i
                if asin: chunk_index[asin] = i
            
            # Lưu và upload trực tiếp kết quả
            loc_npy = f"{TrainingConfig.LOCAL_DATA_DIR}/{f_name}.npy"
            loc_pkl = f"{TrainingConfig.LOCAL_DATA_DIR}/{f_name}.pkl"
            np.save(loc_npy, embs)
            with open(loc_pkl, "wb") as f_out: 
                pickle.dump(chunk_index, f_out)
            
            # Upload lên GCS
            subprocess.run(["gsutil", "cp", loc_npy, f"{chunks_gcs_dir}/{f_name}.npy"], check=True)
            subprocess.run(["gsutil", "cp", loc_pkl, f"{chunks_gcs_dir}/{f_name}.pkl"], check=True)
            subprocess.run(["gsutil", "cp", "/dev/null", done_flag_gcs], check=True) # Flag hoàn tất
            
            # Dọn dẹp memory và local file
            os.remove(loc_npy); os.remove(loc_pkl)
            del embs, texts, ids, asins
            gc.collect()
            
        except Exception as e:
            logger.error(f"LỖI TẠI FILE {f_name}: {e}")
            raise e

    # 4. HỢP NHẤT (Chỉ Rank 0 thực hiện sau khi tất cả các mảnh đã xong)
    if rank == 0:
        logger.info("Đang đợi các GPU khác hoàn thành phần việc của mình...")
        t_start = time.time()
        while True:
            # Kiểm tra nhanh bằng cách liệt kê danh sách file trên GCS thay vì gọi stat từng file
            result = subprocess.run(["gsutil", "ls", f"{chunks_gcs_dir}/*_done.txt"], capture_output=True, text=True)
            done_files = result.stdout.splitlines()
            done_count = len(done_files)
            
            if done_count >= len(all_files):
                break
            
            # Timeout 5 tiếng
            if time.time() - t_start > 18000:
                raise TimeoutError("Quá thời gian chờ các GPU khác hoàn thành Precompute.")
            
            logger.info(f"Tiến độ tổng: {done_count}/{len(all_files)} file đã xong...")
            time.sleep(60)

        # Gọi hàm hợp nhất cuối cùng
        from src.gcs_manager import merge_precomputed_chunks
        merge_precomputed_chunks()
        logger.info("==> TẤT CẢ QUY TRÌNH ĐÃ HOÀN TẤT THÀNH CÔNG!")

    if world_size > 1:
        dist.barrier() # Đồng bộ lần cuối để kết thúc job an toàn

if __name__ == "__main__":
    precompute_item_embeddings()
