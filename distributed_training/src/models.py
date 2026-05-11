import torch
import torch.nn as nn
import torch.nn.functional as F

# --- Baseline 3: DSSM (Two-Tower) ---
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
        amz_rep = F.normalize(self.amazon_tower(amz_emb), p=2, dim=1)
        vn_rep = F.normalize(self.vn_tower(vn_emb), p=2, dim=1)
        return torch.sum(amz_rep * vn_rep, dim=1)

# --- Baseline 4: Batched GCN ---
class BatchedGCN(nn.Module):
    def __init__(self, in_features=768, hidden_features=256, out_features=128, knn_threshold=0.3):
        super(BatchedGCN, self).__init__()
        self.knn_threshold = knn_threshold
        self.W1 = nn.Linear(in_features, hidden_features)
        self.W2 = nn.Linear(hidden_features, out_features)
        self.dropout = nn.Dropout(0.3)

    def forward(self, X):
        B, N, _ = X.size()

        # Cosine similarity matrix
        sim_matrix = F.cosine_similarity(X.unsqueeze(2), X.unsqueeze(1), dim=3)

        # Adjacency matrix via KNN threshold
        A = (sim_matrix > self.knn_threshold).float()

        # Self-loop + normalization
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

# --- Proposed Model: LLM-CHGNN (Hypergraph Convolution) ---
class HypergraphConv(nn.Module):
    def __init__(self, in_features, out_features):
        super(HypergraphConv, self).__init__()
        self.W = nn.Linear(in_features, out_features)

    def forward(self, X, H):
        """
        X: (B, N, D) - Node features
        H: (B, N, E) - Incidence matrix (N nodes, E hyperedges)
        """
        # 1. Tính bậc của Node (D_v) và bậc của Hyperedge (D_e)
        D_v = torch.sum(H, dim=2) # (B, N)
        D_e = torch.sum(H, dim=1) # (B, E)
        
        # 2. Chuẩn hóa ma trận H (D_v^-1/2 * H * D_e^-1 * H^T * D_v^-1/2)
        # Placeholder cho công thức chuẩn hóa siêu đồ thị (GCN-style)
        # Ở bản này ta dùng công thức đơn giản: H @ H.T @ X
        
        # Message passing: Node -> Hyperedge -> Node
        out = torch.bmm(H, torch.bmm(H.transpose(1, 2), X))
        return F.relu(self.W(out))

class LLM_CHGNN(nn.Module):
    def __init__(self, in_features=768, hidden_features=256, out_features=128):
        super(LLM_CHGNN, self).__init__()
        self.conv1 = HypergraphConv(in_features, hidden_features)
        self.conv2 = HypergraphConv(hidden_features, out_features)
        self.dropout = nn.Dropout(0.3)

    def forward(self, X, H):
        X = self.dropout(self.conv1(X, H))
        X = self.conv2(X, H)
        return F.normalize(X, p=2, dim=2)
