# core/routing/models.py
from pydantic import BaseModel


class ModelTier(BaseModel):
    name: str
    provider: str
    model_id: str
    min_ram_gb: float
    requires_cloud: bool
    cost_per_1k_input_usd: float
    cost_per_1k_output_usd: float
