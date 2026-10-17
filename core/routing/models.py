# core/routing/models.py
from pydantic import BaseModel, Field


class ModelTier(BaseModel):
    name: str
    provider: str
    model_id: str
    min_ram_gb: float
    requires_cloud: bool
    # Prices feed the cost ledger: non-finite or negative values would poison every total built on them.
    cost_per_1k_input_usd: float = Field(ge=0, allow_inf_nan=False)
    cost_per_1k_output_usd: float = Field(ge=0, allow_inf_nan=False)
