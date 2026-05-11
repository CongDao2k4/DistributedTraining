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

# Cấu hình NCCL và Logging
os.environ["TORCH_NCCL_BLOCKING_WAIT"] = "1"
os.environ["TORCH_NCCL_ASYNC_ERROR_HANDLING"] = "1"

def check_gcs_file_exists(gcs_path):
    """Kiểm tra sự tồn tại của file trên GCS bằng gsutil stat."""
    result = subprocess.run(["gsutil", "-q", "stat", gcs_path], capture_output=True)
    return result.returncode == 0

def precompute_item_embeddings():
    """
    Sử dụng đa GPU để mã hóa sản phẩm thành vector.
    Chiến thuật 'Immortal & Efficient':
    - Checkpoint per file: Lưu kết quả từng file Parquet lên GCS ngay khi xong.
    - RAM Efficient: Mỗi GPU chỉ load đúng 1/4 file thông qua Row Group reading.
    - File-based Barrier: Đồng bộ bằng file vật lý để chống NCCL Timeout.
    """
    rank = TrainingConfig.RANK
    world_size = TrainingConfig.WORLD_SIZE
    device = TrainingConfig.DEVICE
    logger = logging.LoggerAdapter(logging.getLogger("precompute"), {'rank': rank})

    # 0. Khởi tạo Distributed
    if world_size > 1 and not dist.is_initialized():
        dist.init_process_group(backend="nccl", timeout=timedelta(minutes=180))

    # 1. Chuẩn bị đường dẫn
    chunks_gcs_dir = f"{TrainingConfig.GCS_PREPARED_DATA}/chunks"
    tmp_sync_dir = "/tmp/embeddings_sync"
    os.makedirs(TrainingConfig.LOCAL_DATA_DIR, exist_ok=True)
    os.makedirs(tmp_sync_dir, exist_ok=True)
    
    # 2. Khảo sát danh sách file
    path = TrainingConfig.GCS_ITEM_NODES if TrainingConfig.IS_CLOUD else "data/item_nodes"
    import gcsfs
    fs = gcsfs.GCSFileSystem() if TrainingConfig.IS_CLOUD else None
    
    if TrainingConfig.IS_CLOUD:
        all_files = sorted([f"gs://{f}" for f in fs.ls(path) if f.endswith(".parquet")])
    else:
        import glob
        all_files = sorted(glob.glob(os.path.join(path, "*.parquet")))

    if rank == 0:
        logger.info(f"==> PHÁT HIỆN {len(all_files)} FILE PARQUET. BẮT ĐẦU CHẾ ĐỘ INCREMENTAL...")
    
    model = SentenceTransformer('paraphrase-multilingual-mpnet-base-v2', device=device)

    # 3. Vòng lặp xử lý từng file Parquet
    for f_idx, f_path in enumerate(all_files):
        f_name = os.path.basename(f_path).replace(".parquet", "")
        done_flag_gcs = f"{chunks_gcs_dir}/{f_name}_done.txt"
        
        # Checkpoint: Bỏ qua nếu file này đã xử lý xong và có trên GCS
        if check_gcs_file_exists(done_flag_gcs):
            if rank == 0: logger.info(f"[{f_idx+1}/{len(all_files)}] SKIP: {f_name} (Đã tồn tại)")
            continue
            
        if rank == 0: logger.info(f"[{f_idx+1}/{len(all_files)}] PROCESSING: {f_name}...")

        try:
            # SỬ DỤNG PARQUETFILE ĐỂ CHỈ ĐỌC PHẦN DỮ LIỆU CẦN THIẾT (TIẾT KIỆM RAM)
            pf = pq.ParquetFile(f_path, filesystem=fs)
            num_row_groups = pf.num_row_groups
            
            # Chia Row Groups cho các Rank (Ví dụ 4 GPU chia đều các block dữ liệu trong file)
            groups_per_rank = (num_row_groups + world_size - 1) // world_size
            my_groups = list(range(rank * groups_per_rank, min((rank + 1) * groups_per_rank, num_row_groups)))
            
            texts, ids, asins = [], [], []
            if my_groups:
                # CHỈ LOAD CÁC ROW GROUPS ĐƯỢC PHÂN CÔNG VÀO RAM
                table = pf.read_row_groups(my_groups, columns=['product_id', 'asin', 'full_text'])
                texts = table['full_text'].to_pylist()
                ids = table['product_id'].to_pylist()
                asins = table['asin'].to_pylist()
                del table
                gc.collect()

            # Encode phần dữ liệu của rank này
            if texts:
                embs = model.encode(texts, batch_size=512, convert_to_numpy=True, show_progress_bar=False)
                
                local_idx_data = []
                for i, (p_id, asin) in enumerate(zip(ids, asins)):
                    local_idx_data.append({"p_id": p_id, "asin": asin})
                
                # Lưu tạm local file cho bước gộp
                np.save(f"{tmp_sync_dir}/emb_{rank}.npy", embs)
                with open(f"{tmp_sync_dir}/idx_{rank}.pkl", "wb") as f: pickle.dump(local_idx_data, f)
                del embs, texts, ids, asins
            else:
                # Rank này không có Row Group nào (do file quá ít dữ liệu)
                # Đảm bảo xóa file cũ nếu có
                for ext in [".npy", ".pkl"]:
                    p = f"{tmp_sync_dir}/" + ("emb_" if ext==".npy" else "idx_") + f"{rank}{ext}"
                    if os.path.exists(p): os.remove(p)

            # ĐỒNG BỘ: Đợi các GPU khác xong file này bằng File-based Barrier
            sync_file = f"{tmp_sync_dir}/sync_{f_name}_{rank}.txt"
            with open(sync_file, "w") as f: f.write("done")
            
            t_wait = time.time()
            while True:
                done_ranks = [x for x in os.listdir(tmp_sync_dir) if x.startswith(f"sync_{f_name}_")]
                if len(done_ranks) >= world_size: break
                if time.time() - t_wait > 1800: raise TimeoutError(f"Timeout chờ đồng bộ file {f_name}")
                time.sleep(5)

            # RANK 0: Gộp kết quả của file Parquet này và đẩy lên GCS
            if rank == 0:
                all_embs = []
                chunk_index = {}
                offset = 0
                
                for r in range(world_size):
                    e_p = f"{tmp_sync_dir}/emb_{r}.npy"
                    i_p = f"{tmp_sync_dir}/idx_{r}.pkl"
                    if os.path.exists(e_p):
                        r_embs = np.load(e_p)
                        with open(i_p, "rb") as f_in:
                            r_idx_list = pickle.load(f_in)
                        
                        all_embs.append(r_embs)
                        for i, meta in enumerate(r_idx_list):
                            g_idx = offset + i
                            if meta['p_id']: chunk_index[meta['p_id']] = g_idx
                            if meta['asin']: chunk_index[meta['asin']] = g_idx
                        offset += len(r_embs)
                
                if all_embs:
                    combined = np.vstack(all_embs)
                    loc_npy = f"{TrainingConfig.LOCAL_DATA_DIR}/{f_name}.npy"
                    loc_pkl = f"{TrainingConfig.LOCAL_DATA_DIR}/{f_name}.pkl"
                    
                    np.save(loc_npy, combined)
                    with open(loc_pkl, "wb") as f_out: pickle.dump(chunk_index, f_out)
                    
                    # Upload lên GCS Chunks
                    subprocess.run(["gsutil", "-m", "cp", loc_npy, f"{chunks_gcs_dir}/{f_name}.npy"], check=True)
                    subprocess.run(["gsutil", "-m", "cp", loc_pkl, f"{chunks_gcs_dir}/{f_name}.pkl"], check=True)
                    subprocess.run(["gsutil", "cp", "/dev/null", done_flag_gcs], check=True)
                    
                    os.remove(loc_npy); os.remove(loc_pkl)
                    logger.info(f"==> DONE & UPLOADED CHUNK: {f_name}")

            # Dọn dẹp rác đồng bộ sau mỗi file để chuẩn bị cho file tiếp theo
            for r in range(world_size):
                for prefix in ["emb_", "idx_", f"sync_{f_name}_"]:
                    for ext in [".npy", ".pkl", ".txt"]:
                        p = f"{tmp_sync_dir}/{prefix}{r}{ext}"
                        if os.path.exists(p): os.remove(p)
            gc.collect()

        except Exception as e:
            logger.error(f"LỖI KHI XỬ LÝ FILE {f_name}: {e}")
            raise e

    # 4. HỢP NHẤT CUỐI CÙNG (CHỈ RANK 0 THỰC HIỆN)
    if rank == 0:
        from src.gcs_manager import merge_precomputed_chunks
        merge_precomputed_chunks()
        logger.info("==> TOÀN BỘ QUY TRÌNH PRECOMPUTE ĐÃ HOÀN TẤT!")

    if world_size > 1:
        dist.barrier() # Đợi Rank 0 hoàn tất merge

if __name__ == "__main__":
    precompute_item_embeddings()
