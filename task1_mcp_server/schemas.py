from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

CUSTOMER_ID_PATTERN = r"^CUST-[A-Z0-9]{5}$"


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class GetCustomerRecordInput(StrictInput):
    customer_id: str = Field(pattern=CUSTOMER_ID_PATTERN)


class TriggerRefundInput(StrictInput):
    customer_id: str = Field(pattern=CUSTOMER_ID_PATTERN)
    amount: float = Field(gt=0)
    reason: str = Field(min_length=10, max_length=500)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("reason must contain at least 10 non-whitespace characters")
        return value
