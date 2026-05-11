import pyarrow.parquet as pq
import random
import logging
import os
import numpy as np
import pandas as pd
from config.training_config import TrainingConfig

logger = logging.getLogger("pretrain_data")

def create_amazon_triplets(n_samples=100000):
    """
    Tạo tập dữ liệu Triplets từ Item Nodes để Pre-train (Anchor, Positive, Negative).
    Đã tối ưu: Dùng PyArrow né lỗi Schema Map và cực tiết kiệm RAM.
    """
    path = TrainingConfig.GCS_ITEM_NODES if TrainingConfig.IS_CLOUD else "data/item_nodes"
    logger.info(f"==> Đang nạp Item Nodes từ {path} để tạo {n_samples:,} triplets...")
    
    # 1. Chỉ đọc 3 cột cần thiết qua PyArrow (Né lỗi Map type)
    import gcsfs
    fs = gcsfs.GCSFileSystem() if TrainingConfig.IS_CLOUD else None
    arrow_path = path.replace("gs://", "") if TrainingConfig.IS_CLOUD else path
    
    table = pq.read_table(arrow_path, columns=['asin', 'product_id', 'category', 'domain'], filesystem=fs)
    
    # Chuyển sang Pandas nhưng chỉ lấy 4 cột (Rất nhẹ RAM ~2GB)
    df = table.to_pandas()
    df_amz = df[df['domain'] == 'amazon'].copy()
    del table # Giải phóng RAM ngay
    
    logger.info(f"Tìm thấy {len(df_amz):,} sản phẩm Amazon. Đang tạo nhóm Category...")
    
    # 2. Gom nhóm theo Category (Tối ưu tốc độ)
    cat_to_asins = df_amz.groupby('category')['asin'].apply(list).to_dict()
    # Chỉ giữ lại các Category có từ 2 sản phẩm trở lên
    valid_cats = [cat for cat, items in cat_to_asins.items() if len(items) > 1]
    
    triplets = []
    logger.info("Đang lấy mẫu Triplets (Vectorized Sampling)...")
    
    # 3. Tạo mẫu Triplets (Vòng lặp tối ưu)
    for _ in range(n_samples):
        # Chọn ngẫu nhiên 1 category hợp lệ
        a_cat = random.choice(valid_cats)
        items = cat_to_asins[a_cat]
        
        # Chọn Anchor và Positive từ cùng category
        a_id, p_id = random.sample(items, 2)
        
        # Chọn Negative từ category khác
        n_cat = random.choice(valid_cats)
        while n_cat == a_cat:
            n_cat = random.choice(valid_cats)
        n_id = random.choice(cat_to_asins[n_cat])
        
        triplets.append({'anchor': a_id, 'positive': p_id, 'negative': n_id})
        
    # 4. Lưu kết quả
    output_df = pd.DataFrame(triplets)
    out_path = os.path.join(TrainingConfig.LOCAL_DATA_DIR, "amazon_triplets.parquet")
    output_df.to_parquet(out_path, index=False)
    
    logger.info(f"==> THÀNH CÔNG! Đã lưu {len(output_df):,} triplets tại: {out_path}")
    return out_path

if __name__ == "__main__":
    create_amazon_triplets()
