import logging
import torch
import torch.distributed as dist
import numpy as np
from tqdm import tqdm
from sentence_transformers import SentenceTransformer
from config.training_config import TrainingConfig

logger = logging.getLogger("sbert_ranker")

def get_ndcg_at_k(rank, k=10):
    return 1.0 / np.log2(rank + 1) if rank <= k else 0.0

def run_sbert(dataset):
    """
    Baseline 2: SBERT Inference (Pre-trained).
    Evaluates on evaluation_dataset.pkl.
    """
    device = TrainingConfig.DEVICE
    logger.info(f"Loading SBERT model on {device}...")
    model = SentenceTransformer('paraphrase-multilingual-mpnet-base-v2', device=device)
    
    # 1. Khởi tạo Phân tán nếu cần
    if TrainingConfig.WORLD_SIZE > 1 and not dist.is_initialized():
        dist.init_process_group(backend="nccl" if torch.cuda.is_available() else "gloo")

    # 2. Pre-compute VN unique embeddings (Tăng tốc độ bằng cách encode 1 lần)
    unique_vn = {}
    for d in dataset:
        for vid, vtext in zip(d['candidate_ids'], d['candidate_texts']):
            if vid not in unique_vn: unique_vn[vid] = vtext
            
    vn_ids = list(unique_vn.keys())
    vn_texts = list(unique_vn.values())
    
    if TrainingConfig.RANK == 0:
        logger.info(f"Pre-computing embeddings for {len(vn_texts)} items...")
        
    vn_embs = model.encode(vn_texts, batch_size=128, convert_to_tensor=True, device=device)
    vn_emb_dict = {vid: vn_embs[i] for i, vid in enumerate(vn_ids)}
    
    # 3. Chia nhỏ data theo GPU
    chunk = dataset[TrainingConfig.RANK::TrainingConfig.WORLD_SIZE]
    local_hits, local_ndcg = 0, 0.0
    
    with torch.no_grad():
        for data in tqdm(chunk, desc=f"SBERT Rank {TrainingConfig.RANK}", disable=(TrainingConfig.RANK != 0)):
            query_emb = model.encode(data['query_text'], convert_to_tensor=True, device=device)
            candidate_embs = torch.stack([vn_emb_dict[vid] for vid in data['candidate_ids']])
            
            # Tính toán trên GPU
            cos_scores = torch.nn.functional.cosine_similarity(query_emb.unsqueeze(0), candidate_embs)
            
            # Chuyển Category sang Tensor để so khớp trên GPU (tùy chọn, ở đây dùng numpy cho đơn giản vì data nhỏ)
            cos_scores_cpu = cos_scores.cpu().numpy()
            cat_scores = np.array([1.0 if cat == data['query_category'] else 0.0 for cat in data['candidate_categories']])
            
            combined = 0.7 * cos_scores_cpu + 0.3 * cat_scores * np.max(cos_scores_cpu)
            
            ranked_ids = [data['candidate_ids'][i] for i in np.argsort(combined)[::-1]]
            try:
                rank = ranked_ids.index(data['true_vn_id']) + 1
                if rank <= 10: local_hits += 1
                local_ndcg += get_ndcg_at_k(rank)
            except ValueError: pass

    # 4. Sync kết quả
    res = torch.tensor([local_hits, local_ndcg], device=device)
    if dist.is_initialized():
        dist.all_reduce(res, op=dist.ReduceOp.SUM)
    
    if TrainingConfig.RANK == 0:
        logger.info(f"SBERT Result -> HR@10: {res[0].item()/len(dataset):.4f} | NDCG@10: {res[1].item()/len(dataset):.4f}")

if __name__ == "__main__":
    from src.data_utils import load_eval_dataset
    
    # Cấu hình logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    
    try:
        eval_data = load_eval_dataset()
        run_sbert(eval_data)
    except Exception as e:
        logger.error(f"Error: {e}")
