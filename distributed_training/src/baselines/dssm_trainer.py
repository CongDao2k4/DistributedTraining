import os
import logging
import torch
import torch.nn as nn
import torch.optim as optim
import pickle
import numpy as np
from torch.nn.parallel import DistributedDataParallel as DDP
from torch.utils.data import Dataset, DataLoader, DistributedSampler
from sentence_transformers import SentenceTransformer
from config.training_config import TrainingConfig
from src.models import DSSM
from tqdm import tqdm

logger = logging.getLogger("dssm_trainer")

class DSSMTrainingDataset(Dataset):
    def __init__(self, interactions_df, embedding_lookup):
        self.df = interactions_df
        self.lookup = embedding_lookup

    def __len__(self): return len(self.df)

    def __getitem__(self, idx):
        row = self.df[int(idx)]
        # Bốc trực tiếp vector đã tính toán trước (Sử dụng Prefix để tránh xung đột)
        q_emb = self.lookup.get_embedding(f"amz_{row['asin']}")
        p_emb = self.lookup.get_embedding(f"vn_{row['product_id']}")
        return torch.from_numpy(q_emb).float(), torch.from_numpy(p_emb).float()

def evaluate_dssm(model, eval_pkl_path, text_encoder, device):
    """Đánh giá model DSSM (Vẫn cần encoder cho tập Eval vì nó nhỏ)"""
    if not os.path.exists(eval_pkl_path):
        return 0.0, 0.0

    with open(eval_pkl_path, 'rb') as f:
        evaluation_dataset = pickle.load(f)

    model.eval()
    base_model = model.module if hasattr(model, 'module') else model
    hits_at_10, ndcg_at_10 = 0, 0.0
    total = len(evaluation_dataset)
    chunk = evaluation_dataset[TrainingConfig.RANK::TrainingConfig.WORLD_SIZE]

    with torch.no_grad():
        for data in tqdm(chunk, desc=f"Eval DSSM Rank {TrainingConfig.RANK}", disable=(TrainingConfig.RANK != 0)):
            q_emb = text_encoder.encode(data['query_text'], convert_to_tensor=True).to(device)
            c_embs = text_encoder.encode(data['candidate_texts'], convert_to_tensor=True).to(device)
            
            q_rep = torch.nn.functional.normalize(base_model.amazon_tower(q_emb.unsqueeze(0)), p=2, dim=1)
            c_reps = torch.nn.functional.normalize(base_model.vn_tower(c_embs), p=2, dim=1)
            
            scores = torch.sum(q_rep * c_reps, dim=1).cpu().numpy()
            ranked_ids = [data['candidate_ids'][i] for i in np.argsort(scores)[::-1]]
            
            try:
                rank = ranked_ids.index(data['true_vn_id']) + 1
                if rank <= 10: hits_at_10 += 1
                ndcg_at_10 += 1.0 / np.log2(rank + 1) if rank <= 10 else 0.0
            except ValueError: pass

    res = torch.tensor([hits_at_10, ndcg_at_10], device=device)
    if TrainingConfig.WORLD_SIZE > 1: torch.distributed.all_reduce(res)
    return res[0].item() / total, res[1].item() / total

def train_dssm(interactions_df, embedding_lookup):
    device = TrainingConfig.DEVICE
    # Chỉ dùng encoder cho phần Evaluation
    text_encoder = SentenceTransformer('paraphrase-multilingual-mpnet-base-v2', device=device)
    
    # 1. Setup Data (Chế độ Precomputed)
    train_set = DSSMTrainingDataset(interactions_df, embedding_lookup)
    sampler = DistributedSampler(train_set, num_replicas=TrainingConfig.WORLD_SIZE, rank=TrainingConfig.RANK)
    loader = DataLoader(train_set, batch_size=TrainingConfig.BATCH_SIZE, sampler=sampler, num_workers=4)
    
    # 2. Setup Model & DDP
    model = DSSM().to(device)
    if TrainingConfig.WORLD_SIZE > 1:
        if not torch.distributed.is_initialized():
            torch.distributed.init_process_group(backend="nccl")
        model = DDP(model, device_ids=[device.index])
    
    optimizer = optim.Adam(model.parameters(), lr=TrainingConfig.LR)
    criterion = nn.MarginRankingLoss(margin=0.2)
    
    best_hr10 = 0.0
    if TrainingConfig.RANK == 0:
        logger.info(">>> BẮT ĐẦU HUẤN LUYỆN DSSM CHẾ ĐỘ THẦN TỐC (PRECOMPUTED)...")
    
    for epoch in range(TrainingConfig.EPOCHS):
        sampler.set_epoch(epoch)
        model.train()
        total_loss = 0
        
        pbar = tqdm(loader, desc=f"Epoch {epoch+1}", disable=(TrainingConfig.RANK != 0))
        for q_embs, p_embs in pbar:
            q_embs, p_embs = q_embs.to(device), p_embs.to(device)
            neg_embs = p_embs[torch.randperm(p_embs.size(0))]
            
            optimizer.zero_grad()
            pos_score = model(q_embs, p_embs)
            neg_score = model(q_embs, neg_embs)
            
            loss = criterion(pos_score, neg_score, torch.ones_like(pos_score).to(device))
            loss.backward()
            optimizer.step()
            
            total_loss += loss.item()
            if TrainingConfig.RANK == 0:
                pbar.set_postfix({"loss": f"{loss.item():.4f}"})
            
        hr10, ndcg10 = evaluate_dssm(model, TrainingConfig.EVAL_PKL_PATH, text_encoder, device)
        if TrainingConfig.RANK == 0:
            logger.info(f"--- EPOCH {epoch+1} DONE | HR@10: {hr10:.4f} ---")
            if hr10 > best_hr10:
                best_hr10 = hr10
                save_model = model.module if hasattr(model, 'module') else model
                torch.save(save_model.state_dict(), os.path.join(TrainingConfig.LOCAL_MODELS_DIR, "dssm_best.pt"))
    return os.path.join(TrainingConfig.LOCAL_MODELS_DIR, "dssm_best.pt")
