import pytorch_lightning as pl
import torch
import torch.nn.functional as F
import torch_scatter
from torch import nn
from torch.nn.utils.rnn import pad_sequence, pack_padded_sequence
from torch_geometric.nn import GCNConv, TopKPooling
from torch_geometric.utils import add_self_loops, to_undirected


class DomainFeatureUpdateModel(torch.nn.Module):
    def __init__(self, hidden_size):
        super().__init__()
        self.lstm_model = nn.LSTM(input_size=32, hidden_size=hidden_size, batch_first=True)

    def forward(self, domain, len_domain):
        sequences = []
        start = 0
        for length in len_domain:
            seq = domain[start : start + length]
            sequences.append(seq)
            start += length
        padded = pad_sequence(sequences, batch_first=True)
        packed_input = pack_padded_sequence(
            padded,
            len_domain.cpu(),
            batch_first=True,
            enforce_sorted=False,
        )
        _, (h_n, _) = self.lstm_model(packed_input)
        return h_n[-1]


class GNNBaseModel(torch.nn.Module):
    def __init__(self, in_channels, hidden_channels):
        super().__init__()
        self.conv1 = GCNConv(in_channels, hidden_channels)
        self.conv2 = GCNConv(hidden_channels, hidden_channels)
        self.conv3 = GCNConv(hidden_channels, in_channels)

    def forward(self, x, edge_index):
        x = self.conv1(x, edge_index)
        x = F.leaky_relu(x)
        x = self.conv2(x, edge_index)
        x = F.leaky_relu(x)
        x = self.conv3(x, edge_index)
        return x


class RootPreservingTopKPooling(TopKPooling):
    def forward(self, x, edge_index, batch):
        x_original, batch_original = x, batch
        x, edge_index, _, batch, perm, _ = super().forward(
            x=x,
            edge_index=edge_index,
            batch=batch,
        )

        root_nodes = []
        batch_size = batch.max().item() + 1
        for idx in range(batch_size):
            root = (batch_original == idx).nonzero(as_tuple=True)[0].max()
            root_nodes.append(root.item())

        missing_roots = [idx for idx, root in enumerate(root_nodes) if root not in perm]
        if missing_roots:
            kept_roots = torch.tensor([root_nodes[idx] for idx in missing_roots], device=x.device)
            x = torch.cat([x, x_original[kept_roots]], dim=0)
            batch = torch.cat([batch, batch_original[kept_roots]], dim=0)
            perm = torch.cat([perm, kept_roots])

        return x, edge_index, batch, perm, root_nodes


class TreeGNNEncoder(nn.Module):
    def __init__(self, n_dim):
        super().__init__()
        self.linear = nn.Linear(n_dim * 2, n_dim)

    def forward(self, x, edge_index, root_nodes):
        del root_nodes
        num_nodes = x.size(0)
        device = x.device
        child, parent = edge_index
        degrees = torch.bincount(parent, minlength=num_nodes).to(device)
        processed = torch.zeros(num_nodes, dtype=torch.bool, device=device)
        level_nodes = (degrees == 0).nonzero(as_tuple=True)[0]

        is_leaf = True
        while level_nodes.numel() > 0:
            processed[level_nodes] = True
            if is_leaf:
                is_leaf = False
                messages = torch.zeros_like(x[level_nodes], device=device)
            else:
                level_node_mask = torch.zeros(num_nodes, dtype=torch.bool, device=device)
                level_node_mask[level_nodes] = True
                edge_mask = level_node_mask[parent]
                active_parents = parent[edge_mask]
                active_children = child[edge_mask]

                if active_parents.numel() == 0:
                    messages = torch.zeros_like(x[level_nodes], device=device)
                else:
                    x_parent = x[active_parents]
                    x_child = x[active_children]
                    attn_scores = (x_child * x_parent).sum(dim=1)
                    parent_indices = torch.searchsorted(level_nodes, active_parents)
                    attn_weights = torch_scatter.scatter_softmax(
                        attn_scores,
                        index=parent_indices,
                    )
                    messages = x_child * attn_weights.unsqueeze(1)
                    messages = torch_scatter.scatter_add(
                        messages,
                        parent_indices,
                        dim=0,
                        dim_size=level_nodes.numel(),
                    )

            x_input = torch.cat([messages, x[level_nodes]], dim=1)
            x[level_nodes] = self.linear(x_input).float()

            child_level_mask = torch.zeros(num_nodes, dtype=torch.bool, device=device)
            child_level_mask[level_nodes] = True
            new_parents = parent[child_level_mask[child]]
            degrees -= torch.bincount(new_parents, minlength=degrees.size(0))
            level_nodes = ((degrees == 0) & (~processed)).nonzero(as_tuple=True)[0]

        return x


class TreeGNNDecoder(nn.Module):
    def __init__(self, n_dim):
        super().__init__()
        self.linear = nn.Linear(n_dim * 2, n_dim)

    def forward(self, x, edge_index, root_nodes):
        child = edge_index[0]
        parent = edge_index[1]
        parent_child_map = {}
        for child_node, parent_node in zip(child.tolist(), parent.tolist()):
            parent_child_map.setdefault(parent_node, []).append(child_node)

        parent_nodes = root_nodes
        while parent_nodes:
            all_parents = []
            all_children = []
            for parent_node in parent_nodes:
                children = parent_child_map.get(parent_node, [])
                if not children:
                    continue
                all_parents.extend([parent_node] * len(children))
                all_children.extend(children)

            if not all_children:
                break

            all_parents = torch.tensor(all_parents, device=x.device)
            all_children = torch.tensor(all_children, device=x.device)

            parent_feat = x[all_parents]
            child_feat = x[all_children]
            x_input = torch.cat([parent_feat, child_feat], dim=1)
            x[all_children] = self.linear(x_input).float()

            parent_nodes = all_children.tolist()

        return x


class _BaseDomTreeAutoencoder(pl.LightningModule):
    def reconstruct_tree(self, edge_index, perm, batch, batch_old, edge_index_old, root_nodes_old):
        del batch_old
        old_to_new = {old.item(): new for new, old in enumerate(perm)}
        new_to_old = {new: old.item() for new, old in enumerate(perm)}

        parent_map = {}
        for child, parent in zip(edge_index[0], edge_index[1]):
            parent_map[child.item()] = parent.item()

        parent_map_old = {}
        for child, parent in zip(edge_index_old[0], edge_index_old[1]):
            parent_map_old[child.item()] = parent.item()

        root_nodes_new = [old_to_new[idx] for idx in root_nodes_old]

        new_edges = []
        for idx in range(len(batch)):
            if idx in root_nodes_new:
                continue

            if idx in parent_map:
                new_edges.append([idx, parent_map[idx]])
            else:
                idx_old = new_to_old[idx]
                parent_old = parent_map_old[idx_old]
                while True:
                    if (parent_old in root_nodes_old) or (parent_old in old_to_new):
                        new_edges.append([idx, old_to_new[parent_old]])
                        break
                    parent_old = parent_map_old[parent_old]

        new_edge_index = torch.tensor(
            new_edges,
            dtype=torch.long,
            device=batch.device,
        ).t().contiguous()
        return new_edge_index, root_nodes_new

    def configure_optimizers(self):
        optimizer = torch.optim.Adam(self.parameters(), lr=self.learning_rate)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingWarmRestarts(
            optimizer,
            T_0=self.optimizer_para,
        )
        return [optimizer], [scheduler]


class DomTreeAutoencoderWithDomain(_BaseDomTreeAutoencoder):
    def __init__(
        self,
        base_feat_size,
        hidden_channel,
        optimizer_para,
        topk_ratio=0.2,
        batch_size=8,
        learning_rate=1e-3,
    ):
        super().__init__()
        self.base_feat_size = base_feat_size
        self.norm = nn.LayerNorm(base_feat_size)
        self.domain_model = DomainFeatureUpdateModel(base_feat_size)
        self.gnn_base = GNNBaseModel(self.base_feat_size, hidden_channel)
        self.topk_pool = RootPreservingTopKPooling(self.base_feat_size, ratio=topk_ratio)
        self.tree_model_encoder = TreeGNNEncoder(self.base_feat_size)
        self.tree_model_decoder = TreeGNNDecoder(self.base_feat_size)
        self.bottleneck_layer = nn.Linear(self.base_feat_size, self.base_feat_size)
        self.error_mapping_layer = nn.Sequential(
            nn.Linear(self.base_feat_size, self.base_feat_size // 2),
            nn.LeakyReLU(),
            nn.Linear(self.base_feat_size // 2, 1),
        )
        self.batch_size = batch_size
        self.learning_rate = learning_rate
        self.optimizer_para = optimizer_para
        self.criterion_1 = nn.MSELoss(reduction="none")
        self.task_weights = nn.Parameter(torch.zeros((3)))

    def forward(self, data):
        x_domain = self.domain_model(data.domain, data.len_domain)
        x_original, edge_index = data.x, data.edge_index
        mask = (x_original == -1).all(dim=1)
        x_original[mask] = x_domain.float()
        x_original = self.norm(x_original)

        x = self.gnn_base(x_original, add_self_loops(to_undirected(edge_index))[0])
        x, edge_index_new, batch, perm, root_nodes_old = self.topk_pool(
            x=x,
            edge_index=edge_index,
            batch=data.batch,
        )
        edge_index, root_nodes = self.reconstruct_tree(
            edge_index_new,
            perm,
            batch,
            data.batch,
            edge_index,
            root_nodes_old,
        )
        x = self.tree_model_encoder(x, edge_index, root_nodes)

        x_hat = x_original[perm]
        x_hat[root_nodes] = self.bottleneck_layer(x[root_nodes])
        y = 1 - data.y
        x_hat = self.tree_model_decoder(x_hat, edge_index, root_nodes)

        errors = []
        x_errors = []
        for idx in range(batch.max().item() + 1):
            mask = batch == idx
            x_i = x[mask]
            x_hat_i = x_hat[mask]
            error = self.criterion_1(x_hat_i, x_i)
            errors.append(error.mean())
            x_errors.append(error.mean(dim=0))
        errors = torch.stack(errors, dim=0)
        x_errors = torch.stack(x_errors, dim=0)

        y_pred_errors = self.error_mapping_layer(x_errors)
        return errors, y, y_pred_errors


class DomTreeAutoencoderWithoutDomain(_BaseDomTreeAutoencoder):
    def __init__(
        self,
        base_feat_size,
        hidden_channel,
        optimizer_para,
        topk_ratio=0.2,
        batch_size=8,
        learning_rate=1e-3,
    ):
        super().__init__()
        self.base_feat_size = base_feat_size
        self.norm = nn.LayerNorm(base_feat_size)
        self.gnn_base = GNNBaseModel(self.base_feat_size, hidden_channel)
        self.topk_pool = RootPreservingTopKPooling(self.base_feat_size, ratio=topk_ratio)
        self.tree_model_encoder = TreeGNNEncoder(self.base_feat_size)
        self.tree_model_decoder = TreeGNNDecoder(self.base_feat_size)
        self.error_mapping_layer = nn.Sequential(
            nn.Linear(self.base_feat_size, self.base_feat_size // 2),
            nn.LeakyReLU(),
            nn.Linear(self.base_feat_size // 2, 1),
        )
        self.batch_size = batch_size
        self.learning_rate = learning_rate
        self.optimizer_para = optimizer_para
        self.criterion_1 = nn.MSELoss(reduction="none")
        self.task_weights = nn.Parameter(torch.zeros((3)))

    def forward(self, data):
        x_original, edge_index = data.x, data.edge_index
        x_original = self.norm(x_original)

        x = self.gnn_base(x_original, add_self_loops(to_undirected(edge_index))[0])
        x, edge_index_new, batch, perm, root_nodes_old = self.topk_pool(
            x=x,
            edge_index=edge_index,
            batch=data.batch,
        )
        edge_index, root_nodes = self.reconstruct_tree(
            edge_index_new,
            perm,
            batch,
            data.batch,
            edge_index,
            root_nodes_old,
        )
        x = self.tree_model_encoder(x, edge_index, root_nodes)

        x_hat = x_original[perm]
        x_hat[root_nodes] = x[root_nodes]
        y = 1 - data.y
        x_hat = self.tree_model_decoder(x_hat, edge_index, root_nodes)

        errors = []
        x_errors = []
        for idx in range(batch.max().item() + 1):
            mask = batch == idx
            x_i = x[mask]
            x_hat_i = x_hat[mask]
            error = self.criterion_1(x_hat_i, x_i)
            errors.append(error.mean())
            x_errors.append(error.mean(dim=0))
        errors = torch.stack(errors, dim=0)
        x_errors = torch.stack(x_errors, dim=0)

        y_pred_errors = self.error_mapping_layer(x_errors)
        return errors, y, y_pred_errors
