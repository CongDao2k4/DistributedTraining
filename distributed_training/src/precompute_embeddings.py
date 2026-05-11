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
    """Kiểm tra sự tồn tại của file trên GCS."""
    result = subprocess.run(["gsutil", "-q", "stat", gcs_path], capture_output=True)
    return result.returncode == 0

def precompute_item_embeddings():
    """
    Chiến thuật 'Độc lập tác chiến' (Independent Workers) - Version: SUPER LOGGING
    - Mỗi GPU xử lý một nhóm file riêng biệt.
    - Cơ chế Resume: Bỏ qua file đã có cờ _done.txt trên GCS (từ bất kỳ phiên bản nào).
    - Hệ thống Log chi tiết để theo dõi tiến độ thời gian thực.
    """
    rank = TrainingConfig.RANK
    world_size = TrainingConfig.WORLD_SIZE
    device = TrainingConfig.DEVICE
    
    # Cấu hình logger hiển thị Rank
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] Rank %(rank)s: %(message)s')
    logger = logging.LoggerAdapter(logging.getLogger("precompute"), {'rank': rank})

    if world_size > 1 and not dist.is_initialized():
        dist.init_process_group(backend="nccl", timeout=timedelta(minutes=180))

    chunks_gcs_dir = f"{TrainingConfig.GCS_PREPARED_DATA}/chunks"
    os.makedirs(TrainingConfig.LOCAL_DATA_DIR, exist_ok=True)
    
    # 1. Khảo sát danh sách file
    path = TrainingConfig.GCS_ITEM_NODES if TrainingConfig.IS_CLOUD else "data/item_nodes"
    import gcsfs
    fs = gcsfs.GCSFileSystem() if TrainingConfig.IS_CLOUD else None
    
    if rank == 0:
        logger.info(f"--- BẮT ĐẦU KHẢO SÁT DỮ LIỆU TẠI: {path} ---")
    
    if TrainingConfig.IS_CLOUD:
        all_files = sorted([f"gs://{f}" for f in fs.ls(path) if f.endswith(".parquet")])
    else:
        import glob
        all_files = sorted(glob.glob(os.path.join(path, "*.parquet")))

    # 2. Chia Shard file
    my_files = all_files[rank::world_size]
    
    if rank == 0:
        logger.info(f"==> TỔNG CỘNG: {len(all_files)} FILE PARQUET.")
        logger.info(f"==> PHÂN CHIA: Mỗi GPU sẽ xử lý khoảng {len(my_files)} file.")
        logger.info("---------------------------------------------------------")
    
    model = SentenceTransformer('paraphrase-multilingual-mpnet-base-v2', device=device)

    # 3. Vòng lặp xử lý độc lập
    for f_idx, f_path in enumerate(my_files):
        f_name = os.path.basename(f_path).replace(".parquet", "")
        done_flag_gcs = f"{chunks_gcs_dir}/{f_name}_done.txt"
        
        # KIỂM TRA RESUME (Kể cả file từ các phiên bản trước)
        if check_gcs_file_exists(done_flag_gcs):
            logger.info(f" [SKIP] >>> File '{f_name}' đã tồn tại trên GCS. Bỏ qua.")
            continue
            
        logger.info(f" [START] >>> Đang xử lý file: {f_name} ({f_idx+1}/{len(my_files)})")

        try:
            # Đọc file
            start_t = time.time()
            logger.info(f"  - Đang nạp dữ liệu từ GCS...")
            table = pq.read_table(f_path, columns=['product_id', 'asin', 'full_text'], filesystem=fs)
            texts = table['full_text'].to_pylist()
            ids = table['product_id'].to_pylist()
            asins = table['asin'].to_pylist()
            num_items = len(texts)
            del table
            logger.info(f"  - Đã nạp {num_items:,} items. Bắt đầu mã hóa (Embedding)...")

            # Encode
            embs = model.encode(texts, batch_size=512, convert_to_numpy=True, show_progress_bar=False)
            logger.info(f"  - Mã hóa xong! Thời gian: {time.time() - start_t:.1f}s. Đang lưu local...")
            
            # Index nội bộ
            chunk_index = {}
            for i, (p_id, asin) in enumerate(zip(ids, asins)):
                if p_id: chunk_index[p_id] = i
                if asin: chunk_index[asin] = i
            
            # Lưu local
            loc_npy = f"{TrainingConfig.LOCAL_DATA_DIR}/{f_name}.npy"
            loc_pkl = f"{TrainingConfig.LOCAL_DATA_DIR}/{f_name}.pkl"
            np.save(loc_npy, embs)
            with open(loc_pkl, "wb") as f: pickle.dump(chunk_index, f)
            
            # Upload GCS
            logger.info(f"  - Đang upload {f_name} lên GCS chunks...")
            subprocess.run(["gsutil", "cp", loc_npy, f"{chunks_gcs_dir}/{f_name}.npy"], check=True)
            subprocess.run(["gsutil", "cp", loc_pkl, f"{chunks_gcs_dir}/{f_name}.pkl"], check=True)
            subprocess.run(["gsutil", "cp", "/dev/null", done_flag_gcs], check=True)
            
            # Cleanup
            os.remove(loc_npy); os.remove(loc_pkl)
            del embs, texts, ids, asins
            gc.collect()
            logger.info(f" [DONE] >>> Hoàn tất file: {f_name}")
            logger.info("---------------------------------------------------------")
            
        except Exception as e:
            logger.error(f" [!!!] LỖI TẠI FILE {f_name}: {e}")
            raise e

    # 4. Hợp nhất cuối cùng (Chỉ Rank 0)
    if rank == 0:
        logger.info(">>> TẤT CẢ GPU ĐÃ XONG PHẦN VIỆC RIÊNG. ĐANG KIỂM TRA TỔNG THỂ...")
        t_start = time.time()
        while True:
            result = subprocess.run(["gsutil", "ls", f"{chunks_gcs_dir}/*_done.txt"], capture_output=True, text=True)
            done_files = result.stdout.splitlines()
            done_count = len(done_files)
            
            if done_count >= len(all_files):
                logger.info(f"==> XÁC NHẬN: {done_count}/{len(all_files)} file đã sẵn sàng!")
                break
            
            # Liệt kê 1 vài file còn thiếu để dễ debug
            if len(all_files) - done_count < 5:
                logger.info(f"Đang đợi {len(all_files) - done_count} file cuối cùng...")
            
            logger.info(f"Tiến độ tổng: {done_count}/{len(all_files)} file hoàn tất. Đang đợi các GPU khác...")
            time.sleep(60)

        logger.info(">>> BẮT ĐẦU QUY TRÌNH HỢP NHẤT FILE TỔNG 12GB (Final Merge)...")
        from src.gcs_manager import merge_precomputed_chunks
        merge_precomputed_chunks()
        logger.info("==> CHÚC MỪNG! TOÀN BỘ QUY TRÌNH PRECOMPUTE ĐÃ THÀNH CÔNG RỰC RỠ!")

    if world_size > 1:
        dist.barrier()

if __name__ == "__main__":
    precompute_item_embeddings()
