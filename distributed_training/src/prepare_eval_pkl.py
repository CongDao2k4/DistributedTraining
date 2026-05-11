import pandas as pd
import pickle
import os
import logging
import gc
import time
import pyarrow.parquet as pq
import gcsfs
from config.training_config import TrainingConfig
from tqdm import tqdm

logger = logging.getLogger("prepare_eval_pkl_v4")

def prepare_evaluation_pickle_optimized():
    """
    PHIÊN BẢN V4 (PYARROW STREAMING): Giải pháp tối ưu nhất cho máy 16GB.
    Đọc từng fragment (file nhỏ) để giữ RAM cực thấp và tránh lỗi Cast Schema.
    """
    t_start = time.time()
    logger.info("============================================================")
    logger.info("   BẮT ĐẦU CHUẨN BỊ EVALUATION PKL (PYARROW STREAMING)")
    logger.info("============================================================")

    # 1. Xác định đường dẫn
    mode = "CLOUD (GCS)" if TrainingConfig.IS_CLOUD else "LOCAL"
    logger.info(f"[BƯỚC 1] Chế độ thực thi: {mode}")

    eval_parquet_path = TrainingConfig.GCS_EVAL_PARQUET
    item_nodes_path = TrainingConfig.GCS_ITEM_NODES
    output_pkl = TrainingConfig.EVAL_PKL_PATH
    
    if not TrainingConfig.IS_CLOUD:
        eval_parquet_path = "data/evaluation_dataset"
        item_nodes_path = "data/item_nodes"

    logger.info(f" -> Path Eval: {eval_parquet_path}")
    logger.info(f" -> Path Item: {item_nodes_path}")

    # --- BƯỚC 2: ĐỌC TẬP ID ---
    logger.info("[BƯỚC 2] Đang đọc danh sách ID từ bộ Evaluation...")
    eval_df = pd.read_parquet(eval_parquet_path)
    
    needed_query_ids = set(eval_df['query_id'].unique())
    needed_cand_ids = set([item for sublist in eval_df['candidate_ids'] for item in sublist])
    all_needed_ids = needed_query_ids.union(needed_cand_ids)
    
    logger.info(f" -> Tìm thấy {len(eval_df):,} queries.")
    logger.info(f" -> Cần truy xuất metadata cho {len(all_needed_ids):,} sản phẩm duy nhất.")

    # --- BƯỚC 3: XỬ LÝ METADATA THEO CHUNK ---
    logger.info("[BƯỚC 3] Đang đọc Metadata theo từng mảnh (Streaming)...")
    lookup = {}
    target_cols = ['product_id', 'asin', 'product_name', 'full_text']
    
    # Kết nối FileSystem
    fs = gcsfs.GCSFileSystem() if TrainingConfig.IS_CLOUD else None
    
    # Mở dataset theo dạng fragments (từng file .parquet lẻ)
    # LƯU Ý: Loại bỏ gs:// nếu dùng filesystem để tránh lỗi ArrowInvalid
    arrow_path = item_nodes_path.replace("gs://", "") if TrainingConfig.IS_CLOUD else item_nodes_path
    dataset = pq.ParquetDataset(arrow_path, filesystem=fs)
    fragments = dataset.fragments
    
    for i, frag in enumerate(fragments):
        logger.info(f" -> Đang xử lý mảnh {i+1}/{len(fragments)}...")
        # Chỉ đọc các cột cần thiết từ mảnh này
        table = frag.to_table(columns=target_cols)
        df_chunk = table.to_pandas()
        
        # Lọc nhanh trong chunk
        mask = df_chunk['product_id'].isin(all_needed_ids) | df_chunk['asin'].isin(all_needed_ids)
        filtered_chunk = df_chunk[mask]
        
        for _, row in filtered_chunk.iterrows():
            final_text = str(row['full_text']) if pd.notnull(row['full_text']) and row['full_text'] != "" else str(row['product_name'])
            meta = {'text': final_text}
            
            p_id = row['product_id']
            asin = row['asin']
            if p_id: lookup[p_id] = meta
            if asin: lookup[asin] = meta
            
        # Giải phóng RAM sau mỗi mảnh
        del table, df_chunk, filtered_chunk
        gc.collect()

    # --- BƯỚC 4: GỘP DỮ LIỆU ---
    logger.info("[BƯỚC 4] Đang đóng gói dữ liệu cuối cùng (Enriching)...")
    enriched_data = []
    for i, (_, row) in enumerate(eval_df.iterrows()):
        if (i+1) % 50 == 0:
            logger.info(f" -> Đã xử lý {i+1}/{len(eval_df)} queries...")
            
        q_id = row['query_id']
        q_meta = lookup.get(q_id, {'text': ""})
        
        cand_texts = [lookup.get(cid, {'text': ""})['text'] for cid in row['candidate_ids']]
        
        labels = row['labels']
        true_vn_id = None
        for idx, lbl in enumerate(labels):
            if lbl == 1:
                true_vn_id = row['candidate_ids'][idx]
                break

        if true_vn_id:
            enriched_data.append({
                'query_id': q_id,
                'query_text': q_meta['text'],
                'candidate_ids': list(row['candidate_ids']),
                'candidate_texts': cand_texts,
                'true_vn_id': true_vn_id
            })

    # --- BƯỚC 5: LƯU & UPLOAD ---
    logger.info(f"[BƯỚC 5] Đang lưu {len(enriched_data)} mẫu vào {output_pkl}...")
    os.makedirs(os.path.dirname(output_pkl), exist_ok=True)
    with open(output_pkl, 'wb') as f:
        pickle.dump(enriched_data, f)

    if TrainingConfig.IS_CLOUD:
        try:
            import subprocess
            subprocess.run(["gsutil", "cp", output_pkl, TrainingConfig.GCS_EVAL_PKL], check=True)
            logger.info(" -> Upload GCS thành công!")
        except:
            logger.error(" -> Lỗi upload GCS.")

    logger.info(f"=== HOÀN TẤT SAU {time.time()-t_start:.1f}s ===")

if __name__ == "__main__":
    prepare_evaluation_pickle_optimized()
