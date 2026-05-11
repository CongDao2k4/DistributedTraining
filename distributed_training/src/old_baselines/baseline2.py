import pickle
import numpy as np
import torch
import os
from sentence_transformers import SentenceTransformer
from tqdm.notebook import tqdm

SAVE_DIR = '/content/drive/MyDrive/amazon/prepared_data_improved'
eval_path = os.path.join(SAVE_DIR, 'evaluation_dataset.pkl')

print("Đang tải dữ liệu...")
with open(eval_path, 'rb') as f:
    evaluation_dataset = pickle.load(f)

# Sử dụng model mạnh hơn: paraphrase-multilingual-mpnet-base-v2
device = 'cuda' if torch.cuda.is_available() else 'cpu'
print(f"Đang tải model paraphrase-multilingual-mpnet-base-v2 trên {device}...")
model = SentenceTransformer('paraphrase-multilingual-mpnet-base-v2', device=device)

# Pre-compute VN embeddings
print("Đang pre-compute embeddings cho VN corpus...")
unique_vn_data = {}
for data in evaluation_dataset:
    for vid, vtext in zip(data['candidate_ids'], data['candidate_texts']):
        if vid not in unique_vn_data:
            unique_vn_data[vid] = vtext

vn_ids = list(unique_vn_data.keys())
vn_texts = list(unique_vn_data.values())
vn_embs_tensor = model.encode(vn_texts, batch_size=128, show_progress_bar=True, convert_to_tensor=True)
vn_emb_dict = {vid: vn_embs_tensor[i] for i, vid in enumerate(vn_ids)}

def get_ndcg_at_k(rank, k=10):
    return 1.0 / np.log2(rank + 1) if rank <= k else 0.0

hits_at_10 = 0
ndcg_at_10 = 0.0
total_queries = len(evaluation_dataset)

print(f"Bắt đầu đánh giá SBERT mpnet trên {total_queries} truy vấn...")

with torch.no_grad():
    for data in tqdm(evaluation_dataset, total=total_queries):
        query_emb = model.encode(data['query_text'], convert_to_tensor=True)
        candidate_embs = torch.stack([vn_emb_dict[vid] for vid in data['candidate_ids']])

        # Cosine similarity
        cos_scores = torch.nn.functional.cosine_similarity(query_emb.unsqueeze(0), candidate_embs).cpu().numpy()

        # Category bonus
        category_scores = np.array([
            1.0 if cat == data['query_category'] else 0.0
            for cat in data['candidate_categories']
        ])

        combined_scores = 0.7 * cos_scores + 0.3 * category_scores * np.max(cos_scores)

        ranked_indices = np.argsort(combined_scores)[::-1]
        ranked_ids = [data['candidate_ids'][i] for i in ranked_indices]

        try:
            rank = ranked_ids.index(data['true_vn_id']) + 1
            if rank <= 10:
                hits_at_10 += 1
            ndcg_at_10 += get_ndcg_at_k(rank, k=10)
        except ValueError:
            pass

print("\n" + "="*50)
print(" KẾT QUẢ BASELINE 2: SBERT mpnet + Category Filter ")
print("="*50)
if total_queries > 0:
    print(f"Hit Ratio (HR@10): {hits_at_10 / total_queries:.4f}")
    print(f"NDCG@10:           {ndcg_at_10 / total_queries:.4f}")
print("="*50)

all_baseline_results['SBERT mpnet + Category Filter'] = {
    'HR@10': hits_at_10 / total_queries,
    'NDCG@10': ndcg_at_10 / total_queries
}