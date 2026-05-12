import os
import numpy as np
import pickle
import subprocess
import logging
import sys

# Thêm thư mục gốc vào path để import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.training_config import TrainingConfig

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s]: %(message)s')
logger = logging.getLogger("recheck")

def run_recheck():
    local_dir = TrainingConfig.LOCAL_DATA_DIR
    gcs_chunks_path = f"{TrainingConfig.GCS_PREPARED_DATA}/chunks"
    os.makedirs(local_dir, exist_ok=True)

    logger.info(f">>> ĐANG TẢI DANH SÁCH FILE TỪ GCS: {gcs_chunks_path}")
    result = subprocess.run(["gsutil", "ls", f"{gcs_chunks_path}/*.npy"], capture_output=True, text=True)
    
    if result.returncode != 0:
        logger.error("Không tìm thấy file nào trên GCS hoặc lỗi gsutil.")
        return

    all_npy_gcs = sorted(result.stdout.splitlines())

    stats = {"healthy": 0, "corrupt": 0, "total_items": 0}
    corrupt_files = []

    logger.info(f"Tìm thấy {len(all_npy_gcs)} mảnh. Bắt đầu kiểm tra chi tiết...")

    for npy_gcs in all_npy_gcs:
        f_name = os.path.basename(npy_gcs).replace(".npy", "")
        pkl_gcs = npy_gcs.replace(".npy", ".pkl")
        
        loc_npy = os.path.join(local_dir, f"{f_name}.npy")
        loc_pkl = os.path.join(local_dir, f"{f_name}.pkl")

        try:
            # Tải file về local để check
            subprocess.run(["gsutil", "-q", "cp", npy_gcs, loc_npy], check=True)
            subprocess.run(["gsutil", "-q", "cp", pkl_gcs, loc_pkl], check=True)

            # 1. Kiểm tra số lượng vector
            n_rows = np.load(loc_npy, mmap_mode='r').shape[0]

            # 2. Kiểm tra Index
            with open(loc_pkl, "rb") as f:
                chunk_idx = pickle.load(f)
            n_indices = len(chunk_idx)

            # 3. Kiểm tra Key rỗng/null (Rất quan trọng)
            invalid_keys = [k for k in chunk_idx.keys() if not k or "_None" in k or k.endswith("_")]

            # ĐÁNH GIÁ
            is_healthy = (n_rows == n_indices) and (len(invalid_keys) == 0)

            if is_healthy:
                logger.info(f" [OK] {f_name}: {n_rows:,} items. Sạch 100%.")
                stats["healthy"] += 1
                stats["total_items"] += n_rows
            else:
                reason = []
                if n_rows != n_indices: reason.append(f"Lệch số lượng (NPY={n_rows} vs PKL={n_indices})")
                if invalid_keys: reason.append(f"Có {len(invalid_keys)} key rác (ví dụ: {invalid_keys[0]})")
                
                logger.error(f" [!!] {f_name}: KHÔNG HỢP LỆ. Lý do: {', '.join(reason)}")
                stats["corrupt"] += 1
                corrupt_files.append(f_name)

        except Exception as e:
            logger.error(f" [ERR] {f_name}: Lỗi khi kiểm tra (có thể thiếu file .pkl): {e}")
            stats["corrupt"] += 1
            corrupt_files.append(f_name)
        finally:
            if os.path.exists(loc_npy): os.remove(loc_npy)
            if os.path.exists(loc_pkl): os.remove(loc_pkl)

    logger.info("\n" + "="*60)
    logger.info(f" TỔNG KẾT KIỂM TRA:")
    logger.info(f" - Tổng số mảnh: {len(all_npy_gcs)}")
    logger.info(f" - Mảnh HỢP LỆ: {stats['healthy']}")
    logger.info(f" - Mảnh LỖI (Cần chạy lại): {stats['corrupt']}")
    logger.info(f" - Tổng sản phẩm SẠCH: {stats['total_items']:,}")
    logger.info("="*60)

    if corrupt_files:
        logger.warning("\n>>> HÀNH ĐỘNG CẦN THIẾT:")
        logger.info("Bạn nên chạy các lệnh sau để xóa các mảnh lỗi trên GCS, sau đó chạy lại Pipeline:")
        for f in corrupt_files:
            print(f"gsutil rm {gcs_chunks_path}/{f}.* {gcs_chunks_path}/{f}_done.txt")
    else:
        logger.info("\n>>> TUYỆT VỜI! Tất cả các mảnh đều sạch. Bạn có thể tiến hành MERGE ngay.")

if __name__ == "__main__":
    run_recheck()
