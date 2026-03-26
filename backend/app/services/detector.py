from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import torch
from torch_geometric.data import Data


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from model import DomTreeAutoencoderWithDomain, DomTreeAutoencoderWithoutDomain  # noqa: E402


class PhishingDetector:
    def __init__(self, model_path, threshold, with_domain=True, device="cuda"):
        self.threshold = float(threshold)
        self.with_domain = with_domain
        self.device = device if torch.cuda.is_available() and device == "cuda" else "cpu"

        model_kwargs = {
            "base_feat_size": 32,
            "hidden_channel": 64,
            "optimizer_para": 1,
            "topk_ratio": 0.2,
            "batch_size": 8,
            "learning_rate": 1e-3,
        }

        if with_domain:
            self.model = DomTreeAutoencoderWithDomain.load_from_checkpoint(
                model_path, **model_kwargs
            ).to(self.device)
        else:
            self.model = DomTreeAutoencoderWithoutDomain.load_from_checkpoint(
                model_path, **model_kwargs
            ).to(self.device)
        self.model.eval()

    def predict(self, graph_data, beta=1.0, debug=False):
        node_feature = torch.from_numpy(graph_data["node_feature"][:, 2:]).float().to(self.device)
        edge_index = torch.from_numpy(graph_data["edge_index"]).long().to(self.device)
        batch = torch.zeros(node_feature.size(0), dtype=torch.long, device=self.device)

        if self.with_domain:
            domain = torch.from_numpy(graph_data["domain"]).float().to(self.device)
            len_domain = torch.as_tensor(
                graph_data["len_domain"], dtype=torch.long, device=self.device
            ).reshape(-1)
            data = Data(
                x=node_feature,
                edge_index=edge_index,
                domain=domain,
                len_domain=len_domain,
                batch=batch,
                y=torch.tensor([0.0], device=self.device),
            )
        else:
            data = Data(
                x=node_feature,
                edge_index=edge_index,
                batch=batch,
                y=torch.tensor([0.0], device=self.device),
            )

        with torch.inference_mode():
            errors, _, y_pred_errors = self.model(data)
            reconstruction_error = float(errors.reshape(-1)[0].item())
            classifier_logit = float(y_pred_errors.reshape(-1)[0].item())
            classifier_benign_score = float(torch.sigmoid(y_pred_errors.reshape(-1)[0]).item())

        threshold_benign_score = 1.0 / (1.0 + np.exp(beta * (reconstruction_error - self.threshold)))
        fused_benign_score = (classifier_benign_score + threshold_benign_score) / 2.0
        phishing_score = 1.0 - fused_benign_score

        prediction = "phishing" if phishing_score >= 0.5 else "benign"
        error_only_prediction = "phishing" if reconstruction_error > self.threshold else "benign"

        if phishing_score >= 0.8:
            risk_level = "HIGH"
        elif phishing_score >= 0.5:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"

        result = {
            "reconstruction_error": reconstruction_error,
            "threshold": self.threshold,
            "threshold_benign_score": float(threshold_benign_score),
            "classifier_benign_score": float(classifier_benign_score),
            "fused_benign_score": float(fused_benign_score),
            "phishing_score": float(phishing_score),
            "prediction": prediction,
            "error_only_prediction": error_only_prediction,
            "risk_level": risk_level,
            "is_phishing": prediction == "phishing",
        }

        if debug:
            model_debug = {
                "threshold_margin": float(reconstruction_error - self.threshold),
                "classifier_logit": classifier_logit,
                "node_feature_tensor_shape": tuple(node_feature.shape),
                "edge_index_tensor_shape": tuple(edge_index.shape),
            }
            if self.with_domain:
                model_debug["domain_tensor_shape"] = tuple(domain.shape)
                model_debug["len_domain_tensor"] = len_domain.tolist()
            result["model_debug"] = model_debug

        return result
