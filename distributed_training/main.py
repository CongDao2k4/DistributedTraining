import argparse
import logging
import sys
import os
import torch
import torch.distributed as dist

# Thêm thư mục hiện tại vào sys.path để import được các module nội bộ
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config.training_config import TrainingConfig, setup_logging
from src.gcs_manager import download_training_data, upload_model_checkpoint
from src.data_utils import load_eval_dataset, load_interactions_df, load_precomputed_embeddings

# Import các baseline
from src.baselines.bm25_ranker import run_bm25
from src.baselines.sbert_ranker import run_sbert
from src.baselines.dssm_trainer import train_dssm
from src.baselines.gcn_trainer import train_gcn
from src.baselines.hybrid_ranker import run_hybrid
from src.baselines.llm_chgnn_trainer import run_llm_chgnn
from src.precompute_embeddings import precompute_item_embeddings

logger = logging.getLogger("training_main")

def setup_distributed():
    if not dist.is_initialized():
        backend = "nccl" if torch.cuda.is_available() else "gloo"
        dist.init_process_group(backend=backend, init_method="env://")
        if torch.cuda.is_available():
            torch.cuda.set_device(TrainingConfig.DEVICE)
        dist.barrier()

def cleanup_distributed():
    if dist.is_initialized():
        dist.destroy_process_group()

def run_pipeline(baseline_id):
    ckpt_path = None
    eval_dataset = load_eval_dataset()

    if baseline_id == 1:
        run_bm25(eval_dataset)
    elif baseline_id == 2:
        run_sbert(eval_dataset)
    elif baseline_id in [3, 4]:
        # 1. KIỂM TRA LOCAL VÀ GCS
        emb_path = TrainingConfig.ITEM_EMBEDDINGS_PATH
        if not os.path.exists(emb_path):
            if TrainingConfig.RANK == 0:
                logger.info("!!! KHÔNG TÌM THẤY EMBEDDINGS LOCAL. ĐANG KÍCH HOẠT PRECOMPUTE...")
            
            # Chạy Precompute (Sử dụng 4 GPU)
            precompute_item_embeddings()
            dist.barrier()
            
            # Chỉ Rank 0 thực hiện upload lên GCS để dành cho các Job sau
            if TrainingConfig.RANK == 0:
                from src.gcs_manager import upload_precomputed_data
                upload_precomputed_data()
        
        # 2. Nạp dữ liệu Vector (Memory-Mapped)
        embedding_lookup = load_precomputed_embeddings()
        interactions_df = load_interactions_df()
        
        if baseline_id == 3:
            ckpt_path = train_dssm(interactions_df, embedding_lookup)
        else:
            ckpt_path = train_gcn(interactions_df, embedding_lookup)
            
    elif baseline_id == 5:
        run_hybrid(eval_dataset)
    elif baseline_id == 6:
        run_llm_chgnn(eval_dataset)

    if TrainingConfig.RANK == 0 and ckpt_path and os.path.exists(ckpt_path):
        logger.info(f"Uploading checkpoint {ckpt_path} to GCS...")
        upload_model_checkpoint(ckpt_path)

def main():
    setup_logging()
    parser = argparse.ArgumentParser(description="RecSys Multi-Node Multi-GPU Pipeline")
    parser.add_argument("--baseline", type=str, default="all", help="Chọn Baseline (1-6) hoặc 'all'")
    parser.add_argument("--skip-download", action="store_true", help="Bỏ qua tải dữ liệu từ GCS")
    args = parser.parse_args()

    setup_distributed()

    if TrainingConfig.RANK == 0:
        print("\n" + "="*60)
        print(f"   AMAZON x VN - SUPER-FAST DISTRIBUTED TRAINING (PRECOMPUTED)")
        print(f"   World Size: {TrainingConfig.WORLD_SIZE} | Mode: {args.baseline}")
        print("="*60 + "\n")

    if not args.skip_download and TrainingConfig.RANK == 0:
        try: download_training_data()
        except Exception as e: logger.error(f"Lỗi tải dữ liệu: {e}"); cleanup_distributed(); return
    
    dist.barrier()

    if args.baseline == "all":
        baselines_to_run = [1, 2, 3, 4, 5, 6]
    else:
        baselines_to_run = [int(args.baseline)]

    for b_id in baselines_to_run:
        if TrainingConfig.RANK == 0: logger.info(f">>> BẮT ĐẦU BASELINE {b_id} <<<")
        try: run_pipeline(b_id)
        except Exception as e: 
            logger.error(f"Thất bại tại Baseline {b_id}: {e}")
            import traceback; traceback.print_exc()
        dist.barrier()

    if TrainingConfig.RANK == 0: logger.info("TOÀN BỘ PIPELINE ĐÃ HOÀN TẤT!")
    cleanup_distributed()

if __name__ == "__main__":
    main()
