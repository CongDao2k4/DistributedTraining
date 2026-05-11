import pickle
import numpy as np
import torch
import os
from sentence_transformers import SentenceTransformer
from rank_bm25 import BM25Okapi
from tqdm.notebook import tqdm

SAVE_DIR = '/content/drive/MyDrive/amazon/prepared_data_improved'
eval_path = os.path.join(SAVE_DIR, 'evaluation_dataset.pkl')

with open(eval_path, 'rb') as f:
    raw_dataset = pickle.load(f)

# SANITY CHECK: Lọc lại một lần cuối, chỉ giữ các mẫu đủ 100 candidates
evaluation_dataset = [d for d in raw_dataset if len(d['candidate_ids']) == 100]
print(f"Đã tải và xác thực {len(evaluation_dataset)} truy vấn hợp lệ để train GCN.")

device = 'cuda' if torch.cuda.is_available() else 'cpu'
model = SentenceTransformer('paraphrase-multilingual-mpnet-base-v2', device=device)

# Pre-compute embeddings
print("Pre-compute VN embeddings...")
unique_vn_data = {}
for data in evaluation_dataset:
    for vid, vtext in zip(data['candidate_ids'], data['candidate_texts']):
        if vid not in unique_vn_data:
            unique_vn_data[vid] = vtext

vn_ids = list(unique_vn_data.keys())
vn_texts = list(unique_vn_data.values())
vn_embs_tensor = model.encode(vn_texts, batch_size=128, show_progress_bar=True, convert_to_tensor=True)
vn_emb_dict = {vid: vn_embs_tensor[i] for i, vid in enumerate(vn_ids)}

def compute_attribute_match(q_specs, c_specs):
    """Tính điểm match giữa specs của query và candidate"""
    if not q_specs or not c_specs:
        return 0.0

    matches = 0
    total = 0

    # Các key quan trọng cần match
    important_keys = ['công nghệ cpu', 'chip xử lý', 'ram', 'ổ cứng', 'brand', 'thương hiệu']

    for key in important_keys:
        if key in q_specs and key in c_specs:
            total += 1
            if q_specs[key] == c_specs[key]:
                matches += 1

    return matches / max(total, 1)

def get_ndcg_at_k(rank, k=10):
    return 1.0 / np.log2(rank + 1) if rank <= k else 0.0

hits_at_10 = 0
ndcg_at_10 = 0.0
total_queries = len(evaluation_dataset)

print(f"\nChạy Hybrid (BM25 + SBERT + Attribute) trên {total_queries} truy vấn...")

for data in tqdm(evaluation_dataset, total=total_queries):
    # BM25 scores
    query_tokens = data['query_text'].split()
    candidate_tokens = [text.split() for text in data['candidate_texts']]
    bm25 = BM25Okapi(candidate_tokens)
    bm25_scores = bm25.get_scores(query_tokens)
    bm25_scores = np.array(bm25_scores) / (np.max(bm25_scores) + 1e-6)

    # SBERT scores
    query_emb = model.encode(data['query_text'], convert_to_tensor=True)
    candidate_embs = torch.stack([vn_emb_dict[vid] for vid in data['candidate_ids']])
    sbert_scores = torch.nn.functional.cosine_similarity(query_emb.unsqueeze(0), candidate_embs).cpu().numpy()

    # Attribute match scores
    q_specs = data.get('query_specs', {})
    attr_scores = np.array([
        compute_attribute_match(q_specs, c_specs)
        for c_specs in data.get('candidate_specs', [])
    ])

    # Category bonus
    category_scores = np.array([
        1.0 if cat == data['query_category'] else 0.0
        for cat in data['candidate_categories']
    ])

    # Hybrid: BM25*0.2 + SBERT*0.3 + Attr*0.3 + Category*0.2
    combined_scores = (
        0.2 * bm25_scores +
        0.3 * sbert_scores +
        0.3 * attr_scores +
        0.2 * category_scores
    )

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
print(" KẾT QUẢ BASELINE 5: HYBRID (BM25 + SBERT + Attribute) ")
print("="*50)
if total_queries > 0:
    print(f"Hit Ratio (HR@10): {hits_at_10 / total_queries:.4f}")
    print(f"NDCG@10:           {ndcg_at_10 / total_queries:.4f}")
print("="*50)

all_baseline_results['HYBRID (BM25 + SBERT + Attribute)'] = {
    'HR@10': hits_at_10 / total_queries,
    'NDCG@10': ndcg_at_10 / total_queries
}