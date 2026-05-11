import pickle
import numpy as np
import os
from rank_bm25 import BM25Okapi
from tqdm.notebook import tqdm

SAVE_DIR = '/content/drive/MyDrive/amazon/prepared_data_improved'
eval_path = os.path.join(SAVE_DIR, 'evaluation_dataset.pkl')

print("Đang tải dữ liệu...")
with open(eval_path, 'rb') as f:
    raw_dataset = pickle.load(f)

# SANITY CHECK: Lọc lại một lần cuối, chỉ giữ các mẫu đủ 100 candidates
evaluation_dataset = [d for d in raw_dataset if len(d['candidate_ids']) == 100]
print(f"Đã tải và xác thực {len(evaluation_dataset)} truy vấn hợp lệ để train GCN.")

def get_ndcg_at_k(rank, k=10):
    return 1.0 / np.log2(rank + 1) if rank <= k else 0.0

hits_at_10 = 0
ndcg_at_10 = 0.0
total_queries = len(evaluation_dataset)

print(f"Bắt đầu chạy BM25 với Category Filter trên {total_queries} truy vấn...")

for data in tqdm(evaluation_dataset, total=total_queries):
    query_tokens = data['query_text'].split()
    candidate_tokens = [text.split() for text in data['candidate_texts']]

    # BM25 scoring
    bm25 = BM25Okapi(candidate_tokens)
    bm25_scores = bm25.get_scores(query_tokens)

    # Category bonus: ưu tiên cùng category
    category_scores = np.array([
        1.0 if cat == data['query_category'] else 0.0
        for cat in data['candidate_categories']
    ])

    # Hybrid: BM25 * 0.7 + Category * 0.3
    combined_scores = 0.7 * bm25_scores + 0.3 * category_scores * np.max(bm25_scores)

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
print(" KẾT QUẢ BASELINE 1: BM25 + Category Filter ")
print("="*50)
if total_queries > 0:
    print(f"Hit Ratio (HR@10): {hits_at_10 / total_queries:.4f}")
    print(f"NDCG@10:           {ndcg_at_10 / total_queries:.4f}")
print("="*50)

all_baseline_results['BM25 + Category'] = {
    'HR@10': hits_at_10 / total_queries,
    'NDCG@10': ndcg_at_10 / total_queries
}