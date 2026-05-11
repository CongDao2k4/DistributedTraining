import os
import logging
import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
from tqdm import tqdm
from sentence_transformers import SentenceTransformer
from config.training_config import TrainingConfig
from src.models import LLM_CHGNN

logger = logging.getLogger("llm_chgnn_trainer")

def build_incidence_matrix(data_list, attr_vocab):
    """
    Xây dựng ma trận H (N nodes x E hyperedges).
    N: query + candidates (101 nodes)
    E: số lượng thuộc tính chung trong attr_vocab
    """
    N = len(data_list) # Thường là 101 (1 query + 100 cands)
    E = len(attr_vocab)
    H = torch.zeros((N, E))
    
    attr_to_idx = {attr: i for i, attr in enumerate(attr_vocab)}
    
    for i, item_specs in enumerate(data_list):
        if not item_specs: continue
        for k, v in item_specs.items():
            attr = f"{k}:{v}"
            if attr in attr_to_idx:
                H[i, attr_to_idx[attr]] = 1.0
    return H

def run_llm_chgnn(dataset):
    """
    Proposed Model: LLM-CHGNN.
    Sử dụng Siêu đồ thị Thuộc tính chung để bắt cầu ngôn ngữ.
    """
    device = TrainingConfig.DEVICE
    model_sbert = SentenceTransformer('paraphrase-multilingual-mpnet-base-v2', device=device)
    
    # 1. Khởi tạo model
    model = LLM_CHGNN(in_features=768).to(device)
    model.eval() # Giả định dùng Zero-shot hoặc Pre-trained
    
    # 2. Xây dựng Attribute Vocab từ toàn bộ dataset
    logger.info("Building Global Attribute Vocab...")
    all_attrs = set()
    for data in dataset:
        for specs in [data.get('query_specs', {})] + data.get('candidate_specs', []):
            if specs:
                for k, v in specs.items():
                    all_attrs.add(f"{k}:{v}")
    
    attr_vocab = sorted(list(all_attrs))
    logger.info(f"Global Attribute Vocab Size: {len(attr_vocab)}")
    
    # 3. Đánh giá
    hits_at_10, ndcg_at_10 = 0, 0.0
    chunk = dataset[TrainingConfig.RANK::TrainingConfig.WORLD_SIZE]
    
    with torch.no_grad():
        for data in tqdm(chunk, desc=f"CHGNN Rank {TrainingConfig.RANK}"):
            # Lấy vector SBERT làm input feature (X)
            q_emb = model_sbert.encode(data['query_text'], convert_to_tensor=True)
            c_embs = model_sbert.encode(data['candidate_texts'], convert_to_tensor=True)
            X = torch.cat([q_emb.unsqueeze(0), c_embs], dim=0).unsqueeze(0) # (1, 101, 768)
            
            # Xây dựng ma trận H cho batch này
            item_specs_list = [data.get('query_specs', {})] + data.get('candidate_specs', [])
            H = build_incidence_matrix(item_specs_list, attr_vocab).unsqueeze(0).to(device) # (1, 101, E)
            
            # Forward qua Hypergraph
            X_out = model(X, H).squeeze(0) # (101, 128)
            
            q_vec = X_out[0]
            c_vecs = X_out[1:]
            
            scores = torch.sum(q_vec * c_vecs, dim=1).cpu().numpy()
            ranked_ids = [data['candidate_ids'][i] for i in np.argsort(scores)[::-1]]
            
            try:
                rank = ranked_ids.index(data['true_vn_id']) + 1
                if rank <= 10: hits_at_10 += 1
                # NDCG calculation
                ndcg_at_10 += 1.0 / np.log2(rank + 1) if rank <= 10 else 0.0
            except ValueError: pass

    # Đồng bộ kết quả phân tán
    res = torch.tensor([hits_at_10, ndcg_at_10], device=device)
    torch.distributed.all_reduce(res)
    
    if TrainingConfig.RANK == 0:
        logger.info(f"LLM-CHGNN Result -> HR@10: {res[0].item()/len(dataset):.4f} | NDCG@10: {res[1].item()/len(dataset):.4f}")

if __name__ == "__main__":
    from src.data_utils import load_eval_dataset
    
    # 1. Setup logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    
    # 2. Khởi tạo Phân tán cho GPU
    if TrainingConfig.WORLD_SIZE > 1 and not torch.distributed.is_initialized():
        torch.distributed.init_process_group(backend="nccl" if torch.cuda.is_available() else "gloo")
        if torch.cuda.is_available():
            torch.cuda.set_device(TrainingConfig.DEVICE)

    # 3. Chạy
    try:
        eval_data = load_eval_dataset()
        run_llm_chgnn(eval_data)
    except Exception as e:
        logger.error(f"Error running CHGNN: {e}")
