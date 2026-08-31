import torch
import torch.nn.functional as F
from torch_geometric.nn import GCNConv
from torch_geometric.data import Data
from collections import defaultdict
import os

MODEL_PATH = "gnn_model.pt"

class TraderGNN(torch.nn.Module):
    def __init__(self, in_channels=3, hidden_channels=16, out_channels=2):
        super().__init__()
        self.conv1 = GCNConv(in_channels, hidden_channels)
        self.conv2 = GCNConv(hidden_channels, out_channels)

    def forward(self, x, edge_index):
        x = self.conv1(x, edge_index)
        x = F.relu(x)
        x = F.dropout(x, p=0.3, training=self.training)
        x = self.conv2(x, edge_index)
        return x


def build_graph_from_edges(edges):
    if len(edges) < 2:
        return None, None
    trader_ids = set()
    for e in edges:
        trader_ids.add(e["source"])
        trader_ids.add(e["target"])
    trader_ids = list(trader_ids)
    if len(trader_ids) < 3:
        return None, None

    id_to_idx = {tid: i for i, tid in enumerate(trader_ids)}
    edge_index = torch.tensor(
        [[id_to_idx[e["source"]] for e in edges], [id_to_idx[e["target"]] for e in edges]],
        dtype=torch.long
    )

    degree = defaultdict(int)
    weight_sum = defaultdict(float)
    for e in edges:
        degree[e["source"]] += 1; degree[e["target"]] += 1
        weight_sum[e["source"]] += e["weight"]; weight_sum[e["target"]] += e["weight"]

    features = []
    for tid in trader_ids:
        d = degree[tid]
        wsum = weight_sum[tid]
        avg_w = wsum / d if d > 0 else 0.0
        features.append([d, wsum, avg_w])
    x = torch.tensor(features, dtype=torch.float32)
    x = (x - x.mean(0)) / (x.std(0) + 1e-6)

    return Data(x=x, edge_index=edge_index), id_to_idx


def train_gnn(data, epochs=100, lr=0.01):
    model = TraderGNN(in_channels=data.x.shape[1])
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    model.train()
    for epoch in range(epochs):
        optimizer.zero_grad()
        z = model(data.x, data.edge_index)
        src, dst = data.edge_index
        pos_score = (z[src] * z[dst]).sum(dim=1)
        neg_dst = dst[torch.randperm(dst.size(0))]
        neg_score = (z[src] * z[neg_dst]).sum(dim=1)
        loss = F.softplus(neg_score - pos_score).mean()
        loss.backward()
        optimizer.step()
    torch.save(model.state_dict(), MODEL_PATH)
    return model


def load_or_train_gnn(edges):
    data, id_to_idx = build_graph_from_edges(edges)
    if data is None:
        return None, None, None

    model = TraderGNN(in_channels=data.x.shape[1])
    if os.path.exists(MODEL_PATH):
        model.load_state_dict(torch.load(MODEL_PATH))
    else:
        model = train_gnn(data)
    model.eval()
    return model, data, id_to_idx


def gnn_network_score(model, data, id_to_idx, relevant_trader_ids):
    if model is None or data is None:
        return 0.0
    relevant_idx = [id_to_idx[t] for t in relevant_trader_ids if t in id_to_idx]
    if len(relevant_idx) < 2:
        return 0.0
    with torch.no_grad():
        z = model(data.x, data.edge_index)
        idx_tensor = torch.tensor(relevant_idx)
        sub_embeddings = z[idx_tensor]
        sims = []
        for i in range(len(sub_embeddings)):
            for j in range(i + 1, len(sub_embeddings)):
                sim_score = torch.sigmoid((sub_embeddings[i] * sub_embeddings[j]).sum()).item()
                sims.append(sim_score)
        avg_sim = sum(sims) / len(sims) if sims else 0.0
    return round(min(100.0, avg_sim * 100), 2)