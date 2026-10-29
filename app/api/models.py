from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


class AskResponse(BaseModel):
    answer: str
    route: str
    evidence: list[dict]
    limitations: list[str]
    latency_ms: float
    llm_used: bool
    model_status: str
    node_timings_ms: dict[str, float]
    provider_failures: list[str]
