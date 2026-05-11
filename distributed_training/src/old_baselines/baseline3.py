import pickle
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
import os
from sentence_transformers import SentenceTransformer
from tqdm.notebook import tqdm
import random

SAVE_DIR = '/content/drive/MyDrive/amazon/prepared_data_improved'
eval_path = os.path.join(SAVE_DIR, 'evaluation_dataset.pkl')

with open(eval_path, 'rb') as f:
    evaluation_dataset = pickle.load(f)

device = 'cuda' if torch.cuda.is_available() else 'cpu'
text_encoder = SentenceTransformer('paraphrase-multilingual-mpnet-base-v2', device=device)

# Pre-compute embeddings
print("1. Pre-compute embeddings...")
unique_vn_texts = {}
amz_data = []

for data in evaluation_dataset:
    for vid, vtext in zip(data['candidate_ids'], data['candidate_texts']):
        if vid not in unique_vn_texts:
            unique_vn_texts[vid] = vtext
    amz_data.append(data)

vn_ids = list(unique_vn_texts.keys())
vn_texts = list(unique_vn_texts.values())
vn_embs_tensor = text_encoder.encode(vn_texts, batch_size=128, show_progress_bar=True, convert_to_tensor=True)
vn_emb_dict = {vid: vn_embs_tensor[i] for i, vid in enumerate(vn_ids)}

amz_queries_text = [d['query_text'] for d in amz_data]
amz_embs_tensor = text_encoder.encode(amz_queries_text, batch_size=128, show_progress_bar=True, convert_to_tensor=True)

# Dataset với Hard Negative Mining
class TripletDatasetHardNeg(Dataset):
    def __init__(self, amz_embs, amz_data, vn_emb_dict):
        self.amz_embs = amz_embs
        self.amz_data = amz_data
        self.vn_emb_dict = vn_emb_dict

    def __len__(self):
        return len(self.amz_data)

    def __getitem__(self, idx):
        anchor_emb = self.amz_embs[idx]
        data = self.amz_data[idx]

        pos_emb = self.vn_emb_dict[data['true_vn_id']]

        # Hard negative: Lấy negative gần anchor nhất (top-k similar nhưng không đúng)
        neg_ids = [vid for vid in data['candidate_ids'] if vid != data['true_vn_id']]
        neg_embs = torch.stack([self.vn_emb_dict[vid] for vid in neg_ids])

        # Tính similarity với anchor
        similarities = torch.nn.functional.cosine_similarity(anchor_emb.unsqueeze(0), neg_embs)

        # Chọn hard negative (có similarity cao nhất)
        hard_neg_idx = torch.argmax(similarities).item()
        neg_emb = neg_embs[hard_neg_idx]

        return anchor_emb, pos_emb, neg_emb

train_dataset = TripletDatasetHardNeg(amz_embs_tensor, amz_data, vn_emb_dict)
train_loader = DataLoader(train_dataset, batch_size=64, shuffle=True)

# DSSM Model
class DSSM(nn.Module):
    def __init__(self, input_dim=768, hidden_dim=256, out_dim=128):
        super(DSSM, self).__init__()
        self.amazon_tower = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(hidden_dim, out_dim)
        )
        self.vn_tower = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(hidden_dim, out_dim)
        )

    def forward(self, amz_emb, vn_emb):
        amz_rep = torch.nn.functional.normalize(self.amazon_tower(amz_emb), p=2, dim=1)
        vn_rep = torch.nn.functional.normalize(self.vn_tower(vn_emb), p=2, dim=1)
        return torch.sum(amz_rep * vn_rep, dim=1)

model = DSSM(input_dim=768).to(device)
optimizer = optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-5)

# SỬA LỖI Ở ĐÂY: Dùng MarginRankingLoss cho điểm số vô hướng (scalar)
criterion = nn.MarginRankingLoss(margin=0.2)

# Training
EPOCHS = 15
print(f"\n2. Huấn luyện DSSM trong {EPOCHS} Epochs với Hard Negatives...")
model.train()

for epoch in range(EPOCHS):
    total_loss = 0
    for anchor, pos, neg in train_loader:
        anchor, pos, neg = anchor.to(device), pos.to(device), neg.to(device)

        optimizer.zero_grad()

        # Positive score và Negative score
        pos_score = model(anchor, pos)
        neg_score = model(anchor, neg)

        # Target = 1 có nghĩa là chúng ta muốn pos_score > neg_score
        target = torch.ones_like(pos_score).to(device)

        loss = criterion(pos_score, neg_score, target)
        loss.backward()
        optimizer.step()
        total_loss += loss.item()

    print(f"Epoch {epoch+1}/{EPOCHS} | Loss: {total_loss/len(train_loader):.4f}")

# Evaluation
print("\n3. Đánh giá...")
model.eval()

def get_ndcg_at_k(rank, k=10):
    return 1.0 / np.log2(rank + 1) if rank <= k else 0.0

hits_at_10 = 0
ndcg_at_10 = 0.0

with torch.no_grad():
    for i, data in tqdm(enumerate(amz_data), total=len(amz_data)):
        q_emb = amz_embs_tensor[i].to(device)
        c_embs = torch.stack([vn_emb_dict[vid].to(device) for vid in data['candidate_ids']])

        # Get DSSM scores
        q_rep = torch.nn.functional.normalize(model.amazon_tower(q_emb), p=2, dim=0)
        c_rep = torch.nn.functional.normalize(model.vn_tower(c_embs), p=2, dim=1)
        dssm_scores = torch.sum(q_rep.unsqueeze(0) * c_rep, dim=1).cpu().numpy()

        ranked_indices = np.argsort(dssm_scores)[::-1]
        ranked_ids = [data['candidate_ids'][j] for j in ranked_indices]

        try:
            rank = ranked_ids.index(data['true_vn_id']) + 1
            if rank <= 10:
                hits_at_10 += 1
            ndcg_at_10 += get_ndcg_at_k(rank, k=10)
        except ValueError:
            pass

print("\n" + "="*50)
print(" KẾT QUẢ BASELINE 3: DSSM + Hard Negatives ")
print("="*50)
print(f"Hit Ratio (HR@10): {hits_at_10 / len(amz_data):.4f}")
print(f"NDCG@10:           {ndcg_at_10 / len(amz_data):.4f}")
print("="*50)

all_baseline_results['DSSM + Hard Negatives'] = {
    'HR@10': hits_at_10 / total_queries,
    'NDCG@10': ndcg_at_10 / total_queries
}