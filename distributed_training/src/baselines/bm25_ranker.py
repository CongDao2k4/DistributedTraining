import logging
import numpy as np
import torch
import torch.distributed as dist
from tqdm import tqdm
from rank_bm25 import BM25Okapi
from config.training_config import TrainingConfig

logger = logging.getLogger("bm25_ranker")

def get_ndcg_at_k(rank, k=10):
    return 1.0 / np.log2(rank + 1) if rank <= k else 0.0

def run_bm25(dataset):
    """
    Baseline 1: BM25 + Category Filter.
    Parallelized across all available ranks.
    """
    device = TrainingConfig.DEVICE
    
    # 1. Khởi tạo Phân tán nếu chạy qua torchrun
    if TrainingConfig.WORLD_SIZE > 1 and not dist.is_initialized():
        dist.init_process_group(backend="gloo") 

    # 2. Chia nhỏ data theo Rank
    chunk = dataset[TrainingConfig.RANK::TrainingConfig.WORLD_SIZE]
    local_hits, local_ndcg = 0, 0.0
    
    if TrainingConfig.RANK == 0:
        logger.info(f">>> Starting BM25 Evaluation (World Size: {TrainingConfig.WORLD_SIZE})...")
    
    for data in tqdm(chunk, desc=f"BM25 Rank {TrainingConfig.RANK}", disable=(TrainingConfig.RANK != 0)):
        query_tokens = data['query_text'].split()
        candidate_tokens = [text.split() for text in data['candidate_texts']]
        
        bm25 = BM25Okapi(candidate_tokens)
        bm25_scores = bm25.get_scores(query_tokens)
        
        # Category bonus
        cat_scores = np.array([1.0 if cat == data['query_category'] else 0.0 for cat in data['candidate_categories']])
        combined = 0.7 * bm25_scores + 0.3 * cat_scores * (np.max(bm25_scores) if np.max(bm25_scores) > 0 else 1.0)
        
        ranked_ids = [data['candidate_ids'][i] for i in np.argsort(combined)[::-1]]
        
        try:
            rank = ranked_ids.index(data['true_vn_id']) + 1
            if rank <= 10: local_hits += 1
            local_ndcg += get_ndcg_at_k(rank)
        except ValueError: pass
        
    # 3. Sync kết quả về Rank 0
    res = torch.tensor([local_hits, local_ndcg], device=device)
    if dist.is_initialized():
        dist.all_reduce(res, op=dist.ReduceOp.SUM)
        
    if TrainingConfig.RANK == 0:
        logger.info(f"BM25 Result -> HR@10: {res[0].item()/len(dataset):.4f} | NDCG@10: {res[1].item()/len(dataset):.4f}")

if __name__ == "__main__":
    from src.data_utils import load_eval_dataset
    
    # Cấu hình logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    
    try:
        dataset = load_eval_dataset()
        run_bm25(dataset)
    except Exception as e:
        logger.error(f"Lỗi khi tải dữ liệu: {e}")
        logger.info("Hay dam bao ban da chay prepare_eval_pkl.py truoc!")
