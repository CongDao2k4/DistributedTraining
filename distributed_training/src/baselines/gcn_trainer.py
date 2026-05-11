import os
import logging
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
import pickle
from torch.nn.parallel import DistributedDataParallel as DDP
from torch.utils.data import Dataset, DataLoader, DistributedSampler
from sentence_transformers import SentenceTransformer
from config.training_config import TrainingConfig
from src.models import BatchedGCN
from tqdm import tqdm
import numpy as np

logger = logging.getLogger("gcn_trainer")

class GCNTrainingDataset(Dataset):
    def __init__(self, interactions_df, embedding_lookup):
        self.df = interactions_df
        self.lookup = embedding_lookup

    def __len__(self): return len(self.df)

    def __getitem__(self, idx):
        row = self.df[int(idx)]
        # Tra cứu trực tiếp vector (Thần tốc!)
        q_emb = self.lookup.get_embedding(row['asin'])
        p_emb = self.lookup.get_embedding(row['product_id'])
        return torch.from_numpy(q_emb).float(), torch.from_numpy(p_emb).float()

def evaluate_gcn(model, eval_pkl_path, text_encoder, device):
    """Đánh giá model GCN sử dụng file .pkl"""
    if not os.path.exists(eval_pkl_path):
        return 0.0, 0.0

    with open(eval_pkl_path, 'rb') as f:
        evaluation_dataset = pickle.load(f)

    model.eval()
    hits_at_10, ndcg_at_10 = 0, 0.0
    total = len(evaluation_dataset)
    chunk = evaluation_dataset[TrainingConfig.RANK::TrainingConfig.WORLD_SIZE]

    with torch.no_grad():
        for data in tqdm(chunk, desc=f"Eval GCN Rank {TrainingConfig.RANK}", disable=(TrainingConfig.RANK != 0)):
            q_emb = text_encoder.encode(data['query_text'], convert_to_tensor=True).to(device)
            c_embs = text_encoder.encode(data['candidate_texts'], convert_to_tensor=True).to(device)
            
            X = torch.cat([q_emb.unsqueeze(0), c_embs], dim=0).unsqueeze(0)
            X_out = model(X)
            
            q_gcn = X_out[:, 0:1, :]
            c_gcn = X_out[:, 1:, :]
            
            scores = torch.sum(q_gcn * c_gcn, dim=2).squeeze(0).cpu().numpy()
            ranked_ids = [data['candidate_ids'][i] for i in np.argsort(scores)[::-1]]
            
            try:
                rank = ranked_ids.index(data['true_vn_id']) + 1
                if rank <= 10: hits_at_10 += 1
                ndcg_at_10 += 1.0 / np.log2(rank + 1) if rank <= 10 else 0.0
            except ValueError: pass

    res = torch.tensor([hits_at_10, ndcg_at_10], device=device)
    if TrainingConfig.WORLD_SIZE > 1: torch.distributed.all_reduce(res)
    return res[0].item() / total, res[1].item() / total

def train_gcn(interactions_df, embedding_lookup):
    device = TrainingConfig.DEVICE
    rank = TrainingConfig.RANK
    world_size = TrainingConfig.WORLD_SIZE
    
    # Chỉ dùng encoder cho Evaluation
    text_encoder = SentenceTransformer('paraphrase-multilingual-mpnet-base-v2', device=device)
        
    model = BatchedGCN(in_features=768, hidden_features=256, out_features=128, knn_threshold=0.3).to(device)
    if world_size > 1:
        if not torch.distributed.is_initialized(): torch.distributed.init_process_group(backend="nccl")
        model = DDP(model, device_ids=[device.index])
    
    optimizer = optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-5)
    criterion = nn.TripletMarginLoss(margin=0.5, p=2)

    dataset = GCNTrainingDataset(interactions_df, embedding_lookup)
    sampler = DistributedSampler(dataset, num_replicas=world_size, rank=rank, shuffle=True)
    train_loader = DataLoader(dataset, batch_size=TrainingConfig.BATCH_SIZE, sampler=sampler, num_workers=4)

    best_hr = 0.0
    ckpt_path = os.path.join(TrainingConfig.LOCAL_MODELS_DIR, "gcn_best.pt")
    
    if rank == 0:
        logger.info(">>> BẮT ĐẦU HUẤN LUYỆN GCN CHẾ ĐỘ THẦN TỐC (PRECOMPUTED)...")

    for epoch in range(TrainingConfig.EPOCHS):
        model.train()
        sampler.set_epoch(epoch)
        total_loss = 0
        
        pbar = tqdm(train_loader, desc=f"Epoch {epoch+1}/{TrainingConfig.EPOCHS}", disable=(rank != 0))
        for batch_idx, (q_embs, p_embs) in enumerate(pbar):
            q_embs, p_embs = q_embs.to(device), p_embs.to(device)
            B = q_embs.size(0)
            if B < 2: continue
            
            optimizer.zero_grad()
            # Đưa vector vào đồ thị
            X = torch.stack([q_embs, p_embs], dim=1) 
            X_out = model(X)
            
            anchors, positives = X_out[:, 0, :], X_out[:, 1, :]
            neg_indices = (torch.arange(B, device=device) + 1) % B
            negatives = positives[neg_indices]
            
            loss = criterion(anchors, positives, negatives)
            loss.backward()
            optimizer.step()
            total_loss += loss.item()
            
            if rank == 0 and batch_idx % 100 == 0:
                pbar.set_postfix({"loss": f"{total_loss / (batch_idx + 1):.4f}"})

        hr10, ndcg10 = evaluate_gcn(model, TrainingConfig.EVAL_PKL_PATH, text_encoder, device)
        if rank == 0:
            logger.info(f"GCN EPOCH {epoch+1} DONE | HR@10: {hr10:.4f}")
            if hr10 > best_hr:
                best_hr = hr10
                save_model = model.module if hasattr(model, 'module') else model
                torch.save(save_model.state_dict(), ckpt_path)

    return ckpt_path
