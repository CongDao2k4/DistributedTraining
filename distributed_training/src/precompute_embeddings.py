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
from datetime import timedelta

# Cấu hình NCCL Timeout hệ thống
os.environ["NCCL_BLOCKING_WAIT"] = "1"
os.environ["NCCL_ASYNC_ERROR_HANDLING"] = "1"

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] Rank %(rank)s: %(message)s',
    force=True
)

def precompute_item_embeddings():
    """
    Sử dụng đa GPU để mã hóa sản phẩm thành vector.
    Bản 'Ironclad': Chia shard dữ liệu từ đầu để tiết kiệm RAM và chống NCCL Timeout.
    """
    rank = TrainingConfig.RANK
    world_size = TrainingConfig.WORLD_SIZE
    device = TrainingConfig.DEVICE
    logger = logging.LoggerAdapter(logging.getLogger("precompute"), {'rank': rank})

    # 0. Khởi tạo Distributed với Timeout cực lớn
    timeout = timedelta(minutes=150)
    if world_size > 1 and not dist.is_initialized():
        dist.init_process_group(backend="nccl", timeout=timeout)

    # 1. Chuẩn bị đường dẫn
    output_path = os.path.join(TrainingConfig.LOCAL_DATA_DIR, "item_embeddings.npy")
    index_path = os.path.join(TrainingConfig.LOCAL_DATA_DIR, "item_index.pkl")
    os.makedirs(TrainingConfig.LOCAL_DATA_DIR, exist_ok=True)
    
    # 2. Khảo sát danh sách file (Chỉ Rank 0 làm rồi broadcast hoặc tất cả cùng làm)
    path = TrainingConfig.GCS_ITEM_NODES if TrainingConfig.IS_CLOUD else "data/item_nodes"
    try:
        import gcsfs
        fs = gcsfs.GCSFileSystem() if TrainingConfig.IS_CLOUD else None
        
        if TrainingConfig.IS_CLOUD:
            all_files = sorted([f"gs://{f}" for f in fs.ls(path) if f.endswith(".parquet")])
        else:
            import glob
            all_files = sorted(glob.glob(os.path.join(path, "*.parquet")))
            
        if not all_files:
            raise FileNotFoundError(f"Không tìm thấy dữ liệu tại {path}")

        # TÍNH TOÁN TỔNG SỐ ITEM (Để tạo memmap)
        # Để nhanh, chúng ta đọc metadata của tất cả file
        total_items = 0
        file_metadata = []
        for f in all_files:
            meta = pq.read_metadata(f, filesystem=fs)
            total_items += meta.num_rows
            file_metadata.append((f, meta.num_rows))
            
        # Rank 0 khởi tạo file memmap
        if rank == 0:
            logger.info(f"Khởi tạo file memmap cho {total_items:,} items...")
            shape = (total_items, 768)
            fp = np.memmap(output_path, dtype='float32', mode='w+', shape=shape)
            del fp
            
        if world_size > 1: dist.barrier()
        
        # CHIA SHARD DỮ LIỆU: Mỗi Rank chỉ nạp những file tương ứng với index của nó
        # Đây là bước quan trọng nhất để tránh OOM và Timeout
        items_per_rank = (total_items + world_size - 1) // world_size
        my_start_global = rank * items_per_rank
        my_end_global = min(my_start_global + items_per_rank, total_items)
        
        logger.info(f"Rank {rank} đảm nhiệm dải: {my_start_global:,} -> {my_end_global:,}")
        
        # Tìm các file chứa dải dữ liệu này
        curr_offset = 0
        my_texts, my_ids, my_asins = [], [], []
        
        for f, num_rows in file_metadata:
            f_start = curr_offset
            f_end = curr_offset + num_rows
            
            # Kiểm tra xem file này có giao với dải của Rank không
            overlap_start = max(f_start, my_start_global)
            overlap_end = min(f_end, my_end_global)
            
            if overlap_start < overlap_end:
                # Đọc chỉ phần giao nhau của file này
                local_start = overlap_start - f_start
                local_len = overlap_end - overlap_start
                
                table = pq.read_table(f, columns=['product_id', 'asin', 'full_text'], filesystem=fs)
                table_slice = table.slice(local_start, local_len)
                
                my_ids.extend(table_slice['product_id'].to_pylist())
                my_asins.extend(table_slice['asin'].to_pylist())
                my_texts.extend(table_slice['full_text'].to_pylist())
                del table, table_slice
                gc.collect()
                
            curr_offset += num_rows
            
        my_local_index = {}
        for i, (p_id, asin) in enumerate(zip(my_ids, my_asins)):
            g_idx = my_start_global + i
            if p_id: my_local_index[p_id] = g_idx
            if asin: my_local_index[asin] = g_idx

    except Exception as e:
        logger.error(f"Lỗi nạp Shard dữ liệu: {e}")
        raise e

    # 3. Huấn luyện BERT với cơ chế Flush định kỳ
    logger.info(f"Bắt đầu Encode {len(my_texts):,} items...")
    model = SentenceTransformer('paraphrase-multilingual-mpnet-base-v2', device=device)
    
    sub_batch_size = 100000
    for i in range(0, len(my_texts), sub_batch_size):
        sub_texts = my_texts[i : i + sub_batch_size]
        sub_embs = model.encode(sub_texts, batch_size=512, convert_to_numpy=True, show_progress_bar=False)
        
        s_idx = my_start_global + i
        e_idx = s_idx + len(sub_texts)
        
        # Ghi trực tiếp vào memmap
        fp = np.memmap(output_path, dtype='float32', mode='r+', shape=(total_items, 768))
        fp[s_idx:e_idx] = sub_embs
        fp.flush()
        del fp, sub_embs
        gc.collect()
        logger.info(f"Tiến độ: {e_idx - my_start_global:,}/{len(my_texts):,}")

    # 4. Giao điểm hội quân
    tmp_idx_path = f"/tmp/idx_rank_{rank}.pkl"
    with open(tmp_idx_path, "wb") as f:
        pickle.dump(my_local_index, f)
        
    logger.info("Đã xong phần việc, đang đợi các GPU khác tại Barrier...")
    if world_size > 1:
        # Sử dụng barrier với timeout rõ ràng
        dist.barrier()
    
    # 5. Hợp nhất (Chỉ Rank 0)
    if rank == 0:
        logger.info("Đang hợp nhất Index...")
        final_index = {}
        for r in range(world_size):
            r_path = f"/tmp/idx_rank_{r}.pkl"
            if os.path.exists(r_path):
                with open(r_path, "rb") as f:
                    final_index.update(pickle.load(f))
                os.remove(r_path)
        
        with open(index_path, "wb") as f:
            pickle.dump(final_index, f)
            
        logger.info(f"==> XONG! Toàn bộ dữ liệu đã sẵn sàng tại {output_path}")
        
        try:
            from src.gcs_manager import upload_precomputed_data
            logger.info("Đang upload dữ liệu lên GCS...")
            upload_precomputed_data()
            logger.info("==> TẤT CẢ ĐÃ ĐƯỢC LƯU AN TOÀN TRÊN GCS!")
        except Exception as e:
            logger.error(f"Lỗi upload GCS: {e}")

if __name__ == "__main__":
    precompute_item_embeddings()
