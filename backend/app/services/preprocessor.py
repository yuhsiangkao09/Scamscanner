from __future__ import annotations

import hashlib
import pickle
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import requests
from bs4 import BeautifulSoup, Comment
from gensim.models import Word2Vec


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def resolve_project_resource(path_str: str) -> Path:
    path = Path(path_str)
    candidates = []

    if path.is_absolute():
        candidates.append(path)
    else:
        candidates.extend(
            [
                PROJECT_ROOT / path,
                PROJECT_ROOT / "resources" / path,
                PROJECT_ROOT / "Original" / path,
            ]
        )

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return candidates[0] if candidates else path


def build_element_type_map(feat_vocabulary):
    tags_document = [
        "html", "head", "title", "base", "link", "meta", "style",
        "noscript", "script", "template", "noindex",
    ]
    tags_sectioning = [
        "body", "article", "section", "nav", "aside", "header", "footer",
        "main", "h1", "h2", "h3", "h4", "h5", "h6", "hgroup", "address",
    ]
    tags_text = [
        "p", "pre", "blockquote", "ol", "ul", "li", "dl", "dt", "dd",
        "figure", "figcaption", "div", "center",
    ]
    tags_inline_text = [
        "a", "abbr", "b", "bdi", "bdo", "br", "cite", "code", "data", "dfn",
        "em", "i", "kbd", "mark", "q", "rp", "rt", "ruby", "s", "samp",
        "small", "span", "strong", "sub", "sup", "time", "u", "var", "wbr",
    ]
    tags_embedded = [
        "img", "image", "iframe", "embed", "object", "picture", "video",
        "audio", "track", "source", "map", "area", "canvas",
    ]
    tags_script = ["script", "noscript", "template"]
    tags_forms = [
        "form", "input", "textarea", "button", "select", "option", "optgroup",
        "label", "fieldset", "legend", "datalist", "output", "meter",
        "progress", "param",
    ]
    tags_table = [
        "table", "caption", "thead", "tbody", "tfoot", "tr", "th", "td",
        "col", "colgroup",
    ]
    tags_graphic = [
        "svg", "animate", "animatetransform", "circle", "clippath", "defs",
        "desc", "ellipse", "filter", "g", "glyph", "line", "lineargradient",
        "mask", "path", "polygon", "polyline", "rect", "stop", "symbol",
        "text", "tspan", "use",
    ]
    tags_interactive = ["details", "summary", "dialog"]
    tags_others = [
        "font", "nobr", "cufon", "cufontext", "util-message", "f",
        "description", "del", "ins", "h:header", "h:section", "other",
        "yatag", "comment",
    ]

    elem_type_map = {}
    for elem in feat_vocabulary:
        if elem in ("external_script", "internal_script"):
            elem_type_map[elem] = 5
        elif elem == "unknown_tag":
            elem_type_map[elem] = 10
        elif elem in ("unknown_attr", "title_attr", "label_attr"):
            elem_type_map[elem] = 11
        elif elem in tags_document:
            elem_type_map[elem] = 0
        elif elem in tags_sectioning:
            elem_type_map[elem] = 1
        elif elem in tags_text:
            elem_type_map[elem] = 2
        elif elem in tags_inline_text:
            elem_type_map[elem] = 3
        elif elem in tags_embedded:
            elem_type_map[elem] = 4
        elif elem in tags_script:
            elem_type_map[elem] = 5
        elif elem in tags_forms:
            elem_type_map[elem] = 6
        elif elem in tags_table:
            elem_type_map[elem] = 7
        elif elem in tags_graphic:
            elem_type_map[elem] = 8
        elif elem in tags_interactive:
            elem_type_map[elem] = 9
        elif elem in tags_others:
            elem_type_map[elem] = 10
        else:
            elem_type_map[elem] = 11
    return elem_type_map


class URLPreprocessor:
    def __init__(
        self,
        word2vec_tree_path="data/Word2Vec_model/word2vec_dom_tree.model",
        word2vec_domain_path="data/Word2Vec_model/word2vec_domain_name.model",
        tags_path="data/utility/tags_html.pickle",
        attrs_path="data/utility/attributes_html.pickle",
        save_raw_html=True,
        raw_html_dir="logs/url_scanner_html",
    ):
        word2vec_tree_path = resolve_project_resource(word2vec_tree_path)
        word2vec_domain_path = resolve_project_resource(word2vec_domain_path)
        tags_path = resolve_project_resource(tags_path)
        attrs_path = resolve_project_resource(attrs_path)

        self.word2vec_tree = Word2Vec.load(str(word2vec_tree_path))
        self.word2vec_domain = Word2Vec.load(str(word2vec_domain_path))
        self.vector_size = 32
        self.save_raw_html = bool(save_raw_html)
        self.raw_html_dir = Path(raw_html_dir) if raw_html_dir else None

        if self.save_raw_html and self.raw_html_dir is not None:
            self.raw_html_dir.mkdir(parents=True, exist_ok=True)

        with open(tags_path, "rb") as file:
            html_tag_all = pickle.load(file)
        with open(attrs_path, "rb") as file:
            html_attr_all = pickle.load(file)

        self.feat_vocabulary = deepcopy(html_tag_all)
        self.feat_vocabulary.extend(
            [
                "external_script",
                "internal_script",
                "unknown_tag",
                "unknown_attr",
                "title_attr",
                "label_attr",
            ] + deepcopy(html_attr_all)
        )
        self.feat_vocabulary.remove("script")
        self.feat_vocabulary.sort()
        self.elem_type_map = build_element_type_map(self.feat_vocabulary)

    def parse_dom_tree(self, soup):
        node_features = []
        edge_index = [[], []]
        node_levels = []
        node_id_counter = [0]

        def add_node(name, level, is_tag=True):
            node_id = node_id_counter[0]
            node_id_counter[0] += 1
            node_features.append([name, is_tag])
            node_levels.append(level)
            return node_id

        def traverse(node, parent_id=None, level=0):
            if isinstance(node, Comment):
                node_id = add_node("comment", level)
                if parent_id is not None:
                    edge_index[0].append(parent_id)
                    edge_index[1].append(node_id)
                return

            if not hasattr(node, "name") or node.name is None or node.name == "style":
                return

            node_tag = "external_script" if node.name == "script" and node.get("src") else node.name
            if node.name == "script" and not node.get("src"):
                node_tag = "internal_script"
            if node_tag not in self.feat_vocabulary:
                node_tag = "unknown_tag"

            node_id = add_node(node_tag, level, True)
            if parent_id is not None:
                edge_index[0].append(parent_id)
                edge_index[1].append(node_id)

            for attr in node.attrs:
                attr_name = deepcopy(attr)
                if attr == "title":
                    attr_name = "title_attr"
                elif attr == "label":
                    attr_name = "label_attr"
                if attr_name not in self.feat_vocabulary:
                    attr_name = "unknown_attr"
                attr_node_id = add_node(attr_name, level + 1, False)
                edge_index[0].append(node_id)
                edge_index[1].append(attr_node_id)

            for child in node.children:
                traverse(child, parent_id=node_id, level=level + 1)

        html_root = soup.find("html")
        if html_root is not None:
            traverse(html_root, None, 0)

        return node_features, edge_index, node_levels

    def extract_domain_features(self, url):
        domain_raw = urlparse(url).netloc
        if not domain_raw:
            return domain_raw, []
        if "_" in domain_raw:
            domain_raw = domain_raw.replace("_", "-")

        domain_vectors = []
        for char in domain_raw:
            try:
                domain_vectors.append(self.word2vec_domain.wv[char])
            except Exception:
                try:
                    domain_vectors.append(self.word2vec_domain.wv[char.lower()])
                except Exception:
                    continue
        return domain_raw, domain_vectors

    def fetch_html(self, url, timeout=15, verify=True):
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0 Safari/537.36"
            )
        }
        return requests.get(url, headers=headers, timeout=timeout, verify=verify)

    def _build_raw_html_path(self, url):
        if self.raw_html_dir is None:
            return None
        host = urlparse(url).netloc.lower() or "scan"
        safe_host = "".join(
            char if char.isalnum() or char in ("-", ".") else "_"
            for char in host
        ).strip("._")
        if not safe_host:
            safe_host = "scan"
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        url_hash = hashlib.sha1(url.encode("utf-8", errors="ignore")).hexdigest()[:12]
        return self.raw_html_dir / f"{timestamp}__{safe_host}__{url_hash}.html"

    def save_response_html(self, url, html_content):
        if not self.save_raw_html or self.raw_html_dir is None:
            return None
        output_path = self._build_raw_html_path(url)
        with open(output_path, "w", encoding="utf-8", errors="ignore") as file:
            file.write(html_content)
        return str(output_path)

    def _process_html_core(
        self,
        html_content,
        source_url,
        with_domain=True,
        debug=False,
        metadata=None,
    ):
        if not html_content or not html_content.strip():
            raise ValueError("HTML input is empty")
        soup = BeautifulSoup(html_content, "html.parser")
        node_features, edge_index, node_levels = self.parse_dom_tree(soup)

        if len(node_features) <= 10:
            raise ValueError("DOM has too few nodes after parsing")
        if len(edge_index[0]) <= 10:
            raise ValueError("DOM has too few edges after parsing")

        sorted_indices = np.argsort(node_levels)[::-1]
        node_features_sorted = [node_features[i] for i in sorted_indices]
        old_to_new = {
            old_idx.item(): len(node_levels) - 1 - new_idx
            for new_idx, old_idx in enumerate(sorted_indices)
        }
        edge_index_sorted = [
            [old_to_new[index] for index in edge_index[0]],
            [old_to_new[index] for index in edge_index[1]],
        ]
        sorted_pairs = sorted(
            zip(edge_index_sorted[0], edge_index_sorted[1]),
            key=lambda pair: pair[1],
            reverse=True,
        )
        parent_nodes, child_nodes = zip(*sorted_pairs)
        edge_index_sorted = [parent_nodes, child_nodes]

        node_features_final = []
        unknown_tag_count = 0
        unknown_attr_count = 0
        for feat_name, is_tag in node_features_sorted:
            node_name = feat_name
            try:
                feat_embedding = self.word2vec_tree.wv[node_name]
            except Exception:
                if is_tag:
                    node_name = "unknown_tag"
                    feat_embedding = self.word2vec_tree.wv[node_name]
                    unknown_tag_count += 1
                else:
                    node_name = "unknown_attr"
                    feat_embedding = self.word2vec_tree.wv[node_name]
                    unknown_attr_count += 1

            if node_name == "unknown_tag" and feat_name == "unknown_tag":
                unknown_tag_count += 1
            if node_name == "unknown_attr" and feat_name == "unknown_attr":
                unknown_attr_count += 1

            category = self.elem_type_map[node_name]
            node_idx = self.feat_vocabulary.index(node_name)
            feat_final = [node_idx, category] + feat_embedding.tolist()
            node_features_final.append(feat_final)

        debug_info = None
        if debug:
            safe_nodes = max(len(node_features_final), 1)
            metadata = metadata or {}
            debug_info = {
                "http_status": metadata.get("http_status"),
                "http_reason": metadata.get("http_reason"),
                "final_url": metadata.get("final_url", source_url),
                "content_type": metadata.get("content_type"),
                "raw_html_path": metadata.get("raw_html_path"),
                "input_mode": metadata.get("input_mode", "url"),
                "html_chars": int(len(html_content)),
                "max_dom_depth": int(max(node_levels) if node_levels else 0),
                "node_count_without_dummy": int(len(node_features_final)),
                "edge_count_before_root": int(len(edge_index_sorted[0])),
                "unknown_tag_count": int(unknown_tag_count),
                "unknown_attr_count": int(unknown_attr_count),
                "unknown_tag_ratio": float(unknown_tag_count / safe_nodes),
                "unknown_attr_ratio": float(unknown_attr_count / safe_nodes),
                "unique_node_types": int(len(set(item[0] for item in node_features_sorted))),
                "tls_verify_enabled": metadata.get("tls_verify_enabled"),
                "used_fallback_source_url": bool(metadata.get("used_fallback_source_url", False)),
            }

        if with_domain:
            node_features_final.append([len(self.feat_vocabulary), 12] + [-1] * self.vector_size)

        node_features_final = np.array(node_features_final)
        edge_index_sorted = np.array(edge_index_sorted)

        if with_domain:
            edge_index_sorted = np.append(edge_index_sorted + 1, [[0], [1]], axis=1)
            edge_index_sorted[[0, 1]] = edge_index_sorted[[1, 0]]
            edge_index_sorted = len(node_features_final) - 1 - edge_index_sorted
        else:
            edge_index_sorted[[0, 1]] = edge_index_sorted[[1, 0]]
            edge_index_sorted = len(node_features_final) - 1 - edge_index_sorted

        result = {
            "node_feature": node_features_final,
            "edge_index": edge_index_sorted,
        }

        if with_domain:
            domain_raw, domain_vectors = self.extract_domain_features(source_url)
            if not domain_vectors:
                raise ValueError("Failed to derive usable domain features from URL")
            result["domain"] = np.array(domain_vectors)
            result["len_domain"] = int(len(domain_vectors))
            if debug_info is not None:
                debug_info["domain_raw"] = domain_raw
                debug_info["domain_token_count"] = int(len(domain_vectors))

        if debug_info is not None:
            debug_info["edge_count"] = int(edge_index_sorted.shape[1])
            debug_info["node_count_with_dummy"] = int(node_features_final.shape[0])
            result["debug"] = debug_info

        return result

    def process_url(self, url, with_domain=True, timeout=15, verify=True, debug=False):
        response = self.fetch_html(url, timeout=timeout, verify=verify)
        html_content = response.text
        content_type = response.headers.get("Content-Type", "")
        html_hint = "<html" in html_content.lower() or "<body" in html_content.lower()
        raw_html_path = self.save_response_html(response.url, html_content)

        if not html_content.strip():
            raise ValueError(
                f"Target returned HTTP {response.status_code} with an empty response body"
            )
        if "html" not in content_type.lower() and not html_hint:
            raise ValueError(
                f"Target returned HTTP {response.status_code} without usable HTML content"
            )

        result = self._process_html_core(
            html_content=html_content,
            source_url=response.url,
            with_domain=with_domain,
            debug=debug,
            metadata={
                "http_status": int(response.status_code),
                "http_reason": response.reason,
                "final_url": response.url,
                "content_type": content_type,
                "raw_html_path": raw_html_path,
                "input_mode": "url",
                "tls_verify_enabled": bool(verify),
            },
        )
        if raw_html_path:
            result["artifacts"] = {"raw_html_path": raw_html_path}
        return result

    def process_html(self, html_content, source_url=None, with_domain=True, debug=False):
        fallback_source_url = False
        if not source_url:
            source_url = "https://uploaded-html.local/"
            fallback_source_url = True
        raw_html_path = self.save_response_html(source_url, html_content)
        return self._process_html_core(
            html_content=html_content,
            source_url=source_url,
            with_domain=with_domain,
            debug=debug,
            metadata={
                "http_status": None,
                "http_reason": None,
                "final_url": source_url,
                "content_type": "text/html (manual)",
                "raw_html_path": raw_html_path,
                "input_mode": "html",
                "tls_verify_enabled": None,
                "used_fallback_source_url": fallback_source_url,
            },
        )
