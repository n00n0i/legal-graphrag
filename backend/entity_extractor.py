"""
Legal GraphRAG — Entity Extractor
==================================
ใช้ LLM สกัด entities + relationships จาก parsed law documents

Supports: OpenAI (gpt-4o), Azure OpenAI, OpenAI-compatible APIs

Example:
  from extractor import LawEntityExtractor
  
  extractor = LawEntityExtractor(provider="openai", api_key="...")
  result = extractor.extract_law_entities(section_text)
  print(result.law.title, result.sections[0].section_number)
"""

import os
import json
from typing import Optional, Literal
from pydantic import BaseModel

from llm_prompts import (
    LawEntities, CleanChunkOutput, ExtractedSection,
    ExtractedPenalty, ExtractedReference,
    EXTRACT_LAW_PROMPT, CLEAN_CHUNK_PROMPT, CROSS_REF_PROMPT,
    SYSTEM_PROMPT
)


# ─── LLM Provider Config ─────────────────────────────────────────────────────

LLM_PROVIDERS = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
        "max_tokens": 4096,
    },
    "azure": {
        "base_url": os.getenv("AZURE_OPENAI_ENDPOINT", ""),
        "model": os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"),
        "api_version": "2024-06-01",
        "api_key": os.getenv("AZURE_OPENAI_API_KEY", ""),
    },
    "ollama": {
        "base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        "model": os.getenv("OLLAMA_MODEL", "llama3"),
        "max_tokens": 2048,
    },
    "lmstudio": {
        "base_url": os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1"),
        "model": os.getenv("LMSTUDIO_MODEL", "local-model"),
        "max_tokens": 2048,
    }
}


# ─── Entity Extractor ─────────────────────────────────────────────────────────

class LawEntityExtractor:
    """
    LLM-based entity extractor สำหรับกฎหมายไทย
    
    Usage:
        extractor = LawEntityExtractor(provider="openai", api_key="sk-...")
        result = extractor.extract_law_entities(section_text)
    """
    
    def __init__(
        self,
        provider: Literal["openai", "azure", "ollama", "lmstudio"] = "openai",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: int = 4096,
    ):
        self.provider = provider
        self.config = LLM_PROVIDERS.get(provider, LLM_PROVIDERS["openai"])
        
        # Override config with provided values
        if api_key:
            self.config["api_key"] = api_key
        if base_url:
            self.config["base_url"] = base_url
        if model:
            self.config["model"] = model
        self.config["max_tokens"] = max_tokens
        
        self._client = None
    
    def _get_client(self):
        """Lazy init OpenAI-compatible client"""
        if self._client is None:
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    api_key=self.config.get("api_key") or os.getenv("OPENAI_API_KEY"),
                    base_url=self.config.get("base_url"),
                )
            except ImportError:
                raise RuntimeError("openai package not installed: pip install openai")
        return self._client
    
    def extract_law_entities(self, law_text: str) -> LawEntities:
        """
        สกัด Law + Sections + Penalties + References จากเอกสารกฎหมาย
        
        Returns: LawEntities (Pydantic model)
        """
        prompt = EXTRACT_LAW_PROMPT.format(doc_text=law_text[:8000])  # limit context
        
        response = self._call_llm(prompt, response_format=LawEntities)
        return response
    
    def clean_chunk(self, chunk_text: str) -> CleanChunkOutput:
        """ทำความสะอาด chunk สำหรับ embedding"""
        prompt = CLEAN_CHUNK_PROMPT.format(chunk_text=chunk_text[:2000])
        return self._call_llm(prompt, response_format=CleanChunkOutput)
    
    def detect_cross_refs(self, section_text: str, section_number: str, law_title: str) -> list[ExtractedReference]:
        """ตรวจหา cross-references ในมาตรา"""
        prompt = CROSS_REF_PROMPT.format(
            section_number=section_number,
            law_title=law_title,
            section_content=section_text[:3000]
        )
        return self._call_llm(prompt, response_format=list[ExtractedReference])
    
    def _call_llm(self, prompt: str, response_format=None):
        """Call LLM via OpenAI-compatible API"""
        client = self._get_client()
        
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ]
        
        kwargs = {
            "model": self.config["model"],
            "messages": messages,
            "temperature": 0.1,  # low temp for extraction
            "max_tokens": self.config.get("max_tokens", 4096),
        }
        
        if response_format:
            kwargs["response_format"] = response_format
        
        if self.provider == "azure":
            kwargs["extra_headers"] = {"api-key": self.config.get("api_key", "")}
            kwargs.pop("api_key", None)
        
        response = client.chat.completions.create(**kwargs)
        return response.choices[0].message.content


class BatchLawExtractor:
    """Process multiple laws in batch with rate limiting"""
    
    def __init__(self, extractor: LawEntityExtractor, max_concurrent: int = 2):
        self.extractor = extractor
        self.max_concurrent = max_concurrent
        self._semaphore = None
    
    def extract_from_pdf(self, pdf_path: str, parser) -> list[LawEntities]:
        """
        1. Parse PDF → sections
        2. For each section group, call LLM extraction
        3. Combine into LawEntities
        """
        from document_parser import PDFLawParser
        
        parsed = parser.parse(pdf_path)
        
        # Group sections by law (normally 1 law per PDF)
        all_entities = []
        
        for section in parsed.sections:
            try:
                entities = self.extractor.extract_law_entities(section.content)
                all_entities.append(entities)
            except Exception as e:
                print(f"Warning: failed to extract section {section.section_number}: {e}")
                continue
        
        return all_entities


# ─── Embedding Helper ────────────────────────────────────────────────────────

class Embedder:
    """
    Text embedder using BAAI/bge-m3 via OpenAI-compatible API
    
    Usage:
        embedder = Embedder(provider="openai", api_key="...")
        vector = embedder.embed("ข้อความที่ต้องการ embed")
    """
    
    def __init__(
        self,
        provider: Literal["openai", "ollama", "lmstudio"] = "openai",
        model: str = "bge-m3",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        dimension: int = 1024,
    ):
        self.provider = provider
        self.model = model
        self.dimension = dimension
        
        # Determine embedding model by provider
        if provider == "openai":
            self.embed_model = "text-embedding-3-small"  # 1536d or use bge-m3 via custom endpoint
        else:
            self.embed_model = model
        
        self._client = None
        self._config = {
            "api_key": api_key or os.getenv("OPENAI_API_KEY"),
            "base_url": base_url or os.getenv("EMBEDDER_BASE_URL", ""),
        }
    
    def _get_client(self):
        if self._client is None:
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    api_key=self._config.get("api_key"),
                    base_url=self._config.get("base_url") or None,
                )
            except ImportError:
                raise RuntimeError("openai package not installed")
        return self._client
    
    def embed(self, text: str) -> list[float]:
        """Embed single text → vector"""
        client = self._get_client()
        
        if self.provider == "openai":
            response = client.embeddings.create(
                model=self.embed_model,
                input=text[:2000],  # max 2000 chars
            )
            return response.data[0].embedding
        
        # OpenAI-compatible (Ollama, LMStudio, etc.)
        response = client.embeddings.create(
            model=self.embed_model,
            input=text[:2000],
        )
        return response.data[0].embedding
    
    def embed_batch(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        """Embed multiple texts in batch"""
        client = self._get_client()
        
        results = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i+batch_size]
            response = client.embeddings.create(
                model=self.embed_model,
                input=[t[:2000] for t in batch],
            )
            results.extend([item.embedding for item in response.data])
        
        return results


if __name__ == "__main__":
    print("=== Entity Extractor ===")
    print(f"Supported LLM providers: {list(LLM_PROVIDERS.keys())}")
    print(f"Supported embedder providers: openai, ollama, lmstudio")
    print()
    print("Example usage:")
    print("  extractor = LawEntityExtractor(provider='openai')")
    print("  result = extractor.extract_law_entities(law_text)")
    print()
    print("  embedder = Embedder(provider='openai')")
    print("  vector = embedder.embed('ข้อความภาษาไทย')")