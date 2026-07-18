"""Vector store integrations (AnythingLLM, Chroma, Qdrant, etc.).

The pipeline collects records; vector modules push them into a retrieval backend.
Each vector implementation knows its own auth + protocol.
"""
from .anythingllm import AnythingLLMPusher, AnythingLLMConfig

__all__ = ["AnythingLLMPusher", "AnythingLLMConfig"]