"""Version-pinned embedding providers for hybrid retrieval."""

import os

from robot_rag.util import feature_hash_vector, RagError


class FeatureHashEmbedder:
    """Deterministic lexical projection retained as the offline baseline."""

    provider = 'feature_hash_v1'

    def __init__(self, config):
        """Bind the configured output dimensions."""
        self.config = dict(config)
        self.dimensions = config['dimensions']

    def encode(self, texts):
        """Encode text without loading a learned model."""
        return [
            feature_hash_vector(text, self.dimensions)
            for text in texts
        ]


class BgeM3Embedder:
    """Dense BGE-M3 encoder loaded from one immutable model revision."""

    provider = 'bge_m3_transformers_v1'

    def __init__(self, config, allow_download=False, device=None):
        """Load the pinned model with CLS pooling and normalized vectors."""
        try:
            import torch
            from transformers import AutoModel, AutoTokenizer
        except ImportError as error:
            raise RagError(
                'bge_m3_transformers_v1 requires torch and transformers; '
                'run it in the isolated robot_rag embedding environment'
            ) from error
        self.config = dict(config)
        self.dimensions = config['dimensions']
        self._torch = torch
        requested_device = (
            device or os.environ.get('ROBOT_RAG_EMBEDDING_DEVICE', 'auto')
        )
        if requested_device == 'auto':
            requested_device = 'cuda' if torch.cuda.is_available() else 'cpu'
        if requested_device.startswith('cuda') and not torch.cuda.is_available():
            raise RagError('CUDA embedding device requested but unavailable')
        self.device = requested_device
        local_only = not allow_download
        identity = config['model_id']
        revision = config['model_revision']
        try:
            self._tokenizer = AutoTokenizer.from_pretrained(
                identity,
                revision=revision,
                local_files_only=local_only,
                trust_remote_code=False,
            )
            dtype = torch.float16 if self.device.startswith('cuda') else None
            self._model = AutoModel.from_pretrained(
                identity,
                revision=revision,
                local_files_only=local_only,
                trust_remote_code=False,
                torch_dtype=dtype,
            ).to(self.device)
        except (OSError, ValueError, RuntimeError) as error:
            mode = 'local cache' if local_only else 'model registry'
            raise RagError(
                f'cannot load pinned BGE-M3 revision from {mode}: {error}'
            ) from error
        self._model.eval()
        hidden_size = getattr(self._model.config, 'hidden_size', None)
        if hidden_size != self.dimensions:
            raise RagError(
                f'BGE-M3 dimensions mismatch: configured {self.dimensions}, '
                f'model reports {hidden_size}'
            )

    def encode(self, texts):
        """Encode a batch using the model card's CLS + L2 normalization."""
        if not texts:
            return []
        torch = self._torch
        maximum = self.config.get('max_length', 512)
        batch_size = self.config.get('batch_size', 8)
        vectors = []
        with torch.inference_mode():
            for offset in range(0, len(texts), batch_size):
                batch = texts[offset:offset + batch_size]
                tokens = self._tokenizer(
                    batch,
                    max_length=maximum,
                    padding=True,
                    truncation=True,
                    return_tensors='pt',
                )
                tokens = {
                    key: value.to(self.device)
                    for key, value in tokens.items()
                }
                hidden = self._model(**tokens).last_hidden_state[:, 0]
                normalized = torch.nn.functional.normalize(hidden, p=2, dim=1)
                vectors.extend(normalized.float().cpu().tolist())
        precision = self.config.get('vector_precision_decimals', 8)
        return [
            [round(value, precision) for value in vector]
            for vector in vectors
        ]


def create_embedder(config, allow_download=False, device=None):
    """Create only an allowlisted embedding implementation."""
    provider = config['provider']
    if provider == FeatureHashEmbedder.provider:
        return FeatureHashEmbedder(config)
    if provider == BgeM3Embedder.provider:
        return BgeM3Embedder(config, allow_download, device)
    raise RagError(f'unsupported embedding provider: {provider}')
