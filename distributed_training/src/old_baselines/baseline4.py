import pickle
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
import os
from sentence_transformers import SentenceTransformer
from tqdm.notebook import tqdm
import random

SAVE_DIR = '/content/drive/MyDrive/amazon/prepared_data_improved'
eval_path = os.path.join(SAVE_DIR, 'evaluation_dataset.pkl')

with open(eval_path, 'rb') as f:
    raw_dataset = pickle.load(f)

# SANITY CHECK: Lọc lại một lần cuối, chỉ giữ các mẫu đủ 100 candidates
evaluation_dataset = [d for d in raw_dataset if len(d['candidate_ids']) == 100]
print(f"Đã tải và xác thực {len(evaluation_dataset)} truy vấn hợp lệ để train GCN.")

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

# Graph Dataset
class GraphDataset(Dataset):
    def __init__(self, amz_embs, amz_data, vn_emb_dict):
        self.amz_embs = amz_embs
        self.amz_data = amz_data
        self.vn_emb_dict = vn_emb_dict

    def __len__(self):
        return len(self.amz_data)

    def __getitem__(self, idx):
        data = self.amz_data[idx]
        q_emb = self.amz_embs[idx]
        c_embs = torch.stack([self.vn_emb_dict[vid] for vid in data['candidate_ids']])
        pos_idx = data['candidate_ids'].index(data['true_vn_id'])
        return q_emb, c_embs, pos_idx

train_loader = DataLoader(GraphDataset(amz_embs_tensor, amz_data, vn_emb_dict), batch_size=16, shuffle=True)
eval_loader = DataLoader(GraphDataset(amz_embs_tensor, amz_data, vn_emb_dict), batch_size=16, shuffle=False)

# GCN với KNN threshold = 0.3 (thay vì 0.6)
class BatchedGCN(nn.Module):
    def __init__(self, in_features=768, hidden_features=256, out_features=128, k_neighbors=10):
        super(BatchedGCN, self).__init__()
        self.k_neighbors = k_neighbors
        self.W1 = nn.Linear(in_features, hidden_features)
        self.W2 = nn.Linear(hidden_features, out_features)
        self.dropout = nn.Dropout(0.3)

    def forward(self, X):
        B, N, _ = X.size()

        # Cosine similarity
        sim_matrix = F.cosine_similarity(X.unsqueeze(2), X.unsqueeze(1), dim=3)

        # KNN với threshold = 0.3 (giảm từ 0.6)
        A = (sim_matrix > 0.3).float()

        # Self-loop + normalize
        I = torch.eye(N, device=X.device).unsqueeze(0).expand(B, -1, -1)
        A = A + I

        D = torch.sum(A, dim=2)
        D_inv_sqrt = torch.pow(D, -0.5)
        D_inv_sqrt[torch.isinf(D_inv_sqrt)] = 0.0
        D_mat_inv_sqrt = torch.diag_embed(D_inv_sqrt)

        A_norm = torch.bmm(torch.bmm(D_mat_inv_sqrt, A), D_mat_inv_sqrt)

        H1 = F.relu(self.W1(torch.bmm(A_norm, X)))
        H1 = self.dropout(H1)
        H2 = self.W2(torch.bmm(A_norm, H1))

        return F.normalize(H2, p=2, dim=2)

model = BatchedGCN(in_features=768, k_neighbors=10).to(device)
optimizer = optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-5)
criterion = nn.TripletMarginLoss(margin=0.5, p=2)

# Training
EPOCHS = 15
print(f"\n2. Huấn luyện GCN với KNN threshold=0.3 trong {EPOCHS} Epochs...")
model.train()

for epoch in range(EPOCHS):
    total_loss = 0
    for q_emb, c_embs, pos_idx in train_loader:
        q_emb, c_embs, pos_idx = q_emb.to(device), c_embs.to(device), pos_idx.to(device)
        B = q_emb.size(0)
        optimizer.zero_grad()

        X = torch.cat([q_emb.unsqueeze(1), c_embs], dim=1)
        X_out = model(X)

        anchors = X_out[:, 0, :]
        pos_indices = pos_idx + 1
        batch_indices = torch.arange(B, device=device)
        positives = X_out[batch_indices, pos_indices, :]

        # Hard negative
        neg_indices = torch.randint(1, 101, (B,), device=device)
        mask = (neg_indices == pos_indices)
        neg_indices[mask] = (neg_indices[mask] % 100) + 1
        negatives = X_out[batch_indices, neg_indices, :]

        loss = criterion(anchors, positives, negatives)
        loss.backward()
        optimizer.step()
        total_loss += loss.item()

    print(f"Epoch {epoch+1}/{EPOCHS} | Loss: {total_loss/len(train_loader):.4f}")

# Evaluation
print("\n3. Đánh giá GCN...")
model.eval()

def get_ndcg_at_k(rank, k=10):
    return 1.0 / np.log2(rank + 1) if rank <= k else 0.0

hits_at_10 = 0
ndcg_at_10 = 0.0

with torch.no_grad():
    for q_emb, c_embs, pos_idx in tqdm(eval_loader):
        q_emb, c_embs = q_emb.to(device), c_embs.to(device)
        B = q_emb.size(0)

        X = torch.cat([q_emb.unsqueeze(1), c_embs], dim=1)
        X_out = model(X)

        q_gcn = X_out[:, 0:1, :]
        c_gcn = X_out[:, 1:, :]

        scores = torch.sum(q_gcn * c_gcn, dim=2).cpu().numpy()
        pos_idx_np = pos_idx.numpy()

        for i in range(B):
            rank_scores = scores[i]
            true_item_index = pos_idx_np[i]
            ranked_indices = np.argsort(rank_scores)[::-1]
            rank = np.where(ranked_indices == true_item_index)[0][0] + 1
            if rank <= 10:
                hits_at_10 += 1
            ndcg_at_10 += get_ndcg_at_k(rank, k=10)

print("\n" + "="*50)
print(" KẾT QUẢ BASELINE 4: GCN (KNN=0.3) ")
print("="*50)
print(f"Hit Ratio (HR@10): {hits_at_10 / len(amz_data):.4f}")
print(f"NDCG@10:           {ndcg_at_10 / len(amz_data):.4f}")
print("="*50)

all_baseline_results['GCN'] = {
    'HR@10': hits_at_10 / total_queries,
    'NDCG@10': ndcg_at_10 / total_queries
}