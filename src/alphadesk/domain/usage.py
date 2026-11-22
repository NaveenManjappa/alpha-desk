"""What one run used: time, tokens and an estimated cost (phase 1 spec, Slice 12).

`RunUsage` travels beside the `Answer` in the `final` event, never inside it. The answer
is research about a company; usage describes the run that produced it. Keeping them apart
means the answer contract stays the same whatever the run cost, and a cached answer in a
later phase can carry the usage of the run that made it, or none.

The TypeScript models in `web/` will mirror `RunUsage`; change both together.
"""

from pydantic import BaseModel, Field


class ModelPrice(BaseModel):
    """What a model costs, in US dollars per million tokens, as the provider lists it.

    Prices change, so they come from settings (see `get_model_price`), never constants.
    """

    input_usd_per_million: float = Field(ge=0)
    output_usd_per_million: float = Field(ge=0)


class RunUsage(BaseModel):
    """The resources one chat turn used, across every model call in it.

    Attributes:
        duration_seconds: Wall-clock time of the whole turn, grounding retry included.
        input_tokens: Tokens sent to the model, summed over every call.
        output_tokens: Tokens the model wrote, summed over every call. Includes any
            reasoning tokens, which the provider bills as output.
        total_tokens: `input_tokens + output_tokens`. Sent ready-made so the UI only
            formats numbers and never calculates.
        estimated_cost_usd: From the token counts and the configured price. An estimate:
            the provider's bill is the real figure (see `services/usage.py`).
    """

    duration_seconds: float = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    estimated_cost_usd: float = Field(ge=0)
