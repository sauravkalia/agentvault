"""AgentVault — Unified memory layer for AI coding agents."""

import os
import warnings

# Suppress ChromaDB telemetry before any chromadb import
os.environ["ANONYMIZED_TELEMETRY"] = "False"
os.environ["CHROMA_TELEMETRY"] = "False"

# Suppress posthog telemetry errors from chromadb
import logging
logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)
logging.getLogger("posthog").setLevel(logging.CRITICAL)

__version__ = "0.1.0"
