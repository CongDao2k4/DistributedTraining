import logging
import torch
import torch.distributed as dist
import numpy as np
from tqdm import tqdm
from sentence_transformers import SentenceTransformer
from rank_bm25 import BM25Okapi
from config.training_config import TrainingConfig

logger = logging.getLogger("hybrid_ranker")

def get_ndcg_at_k(rank, k=10):
    return 1.0 / np.log2(rank + 1) if rank <= k else 0.0

def compute_attribute_match(q_specs, c_specs):
    if not q_specs or not c_specs: return 0.0
    matches, total = 0, 0
    important_keys = ['công nghệ cpu', 'chip xử lý', 'ram', 'ổ cứng', 'brand', 'thương hiệu']
    for key in important_keys:
        if key in q_specs and key in c_specs:
            total += 1
            if q_specs[key] == c_specs[key]: matches += 1
    return matches / max(total, 1)

def run_hybrid(dataset):
    """
    Baseline 5: Hybrid Ranker.
    Combines BM25, SBERT, Attribute and Category scores.
    """
    device = TrainingConfig.DEVICE
    logger.info(f"Initializing Hybrid Ranker on {device}...")
    model_sbert = SentenceTransformer('paraphrase-multilingual-mpnet-base-v2', device=device)
    
    # 1. Khởi tạo Phân tán
    if TrainingConfig.WORLD_SIZE > 1 and not dist.is_initialized():
        dist.init_process_group(backend="nccl" if torch.cuda.is_available() else "gloo")

    # 2. Pre-compute VN unique embeddings
    unique_vn = {}
    for d in dataset:
        for vid, vtext in zip(d['candidate_ids'], d['candidate_texts']):
            if vid not in unique_vn: unique_vn[vid] = vtext
            
    vn_ids = list(unique_vn.keys())
    if TrainingConfig.RANK == 0:
        logger.info(f"Pre-computing embeddings for Hybrid (VN count: {len(vn_ids)})...")
        
    vn_embs = model_sbert.encode(list(unique_vn.values()), batch_size=128, convert_to_tensor=True, device=device)
    vn_emb_dict = {vid: vn_embs[i] for i, vid in enumerate(vn_ids)}
    
    # 3. Chia nhỏ data
    chunk = dataset[TrainingConfig.RANK::TrainingConfig.WORLD_SIZE]
    l_hits, l_ndcg = 0, 0.0
    
    for data in tqdm(chunk, desc=f"Hybrid Rank {TrainingConfig.RANK}", disable=(TrainingConfig.RANK != 0)):
        # -- BM25 (CPU) --
        bm25_scores = np.array(BM25Okapi([t.split() for t in data['candidate_texts']]).get_scores(data['query_text'].split()))
        bm25_scores /= (np.max(bm25_scores) + 1e-6)
        
        # -- SBERT (GPU) --
        with torch.no_grad():
            q_emb = model_sbert.encode(data['query_text'], convert_to_tensor=True, device=device)
            c_embs = torch.stack([vn_emb_dict[vid] for vid in data['candidate_ids']])
            sbert_scores = torch.nn.functional.cosine_similarity(q_emb.unsqueeze(0), c_embs).cpu().numpy()
        
        # -- Attribute Match (CPU Logic) --
        attr_scores = np.array([compute_attribute_match(data.get('query_specs', {}), cs) for cs in data.get('candidate_specs', [])])
        
        # -- Category (CPU Logic) --
        cat_scores = np.array([1.0 if cat == data['query_category'] else 0.0 for cat in data['candidate_categories']])
        
        # -- Combined Ranking --
        combined = 0.2 * bm25_scores + 0.3 * sbert_scores + 0.3 * attr_scores + 0.2 * cat_scores
        ranked_ids = [data['candidate_ids'][i] for i in np.argsort(combined)[::-1]]
        
        try:
            rank = ranked_ids.index(data['true_vn_id']) + 1
            if rank <= 10: l_hits += 1
            l_ndcg += get_ndcg_at_k(rank)
        except ValueError: pass

    # 4. Sync
    res = torch.tensor([l_hits, l_ndcg], device=device)
    if dist.is_initialized():
        dist.all_reduce(res, op=dist.ReduceOp.SUM)
    
    if TrainingConfig.RANK == 0:
        logger.info(f"Hybrid Result -> HR@10: {res[0].item()/len(dataset):.4f} | NDCG@10: {res[1].item()/len(dataset):.4f}")

if __name__ == "__main__":
    from src.data_utils import load_eval_dataset
    # Setup logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    
    try:
        eval_data = load_eval_dataset()
        run_hybrid(eval_data)
    except Exception as e:
        logger.error(f"Error: {e}")
