import pytest
from pydantic import ValidationError

from task1_mcp_server.schemas import GetCustomerRecordInput, TriggerRefundInput


def test_valid_customer_id():
    request = GetCustomerRecordInput(customer_id="CUST-A1001")
    assert request.customer_id == "CUST-A1001"


@pytest.mark.parametrize(
    "customer_id",
    ["CUST-1234", "cust-A1001", "A1001", "CUST-TOOLONG", "CUST-A10_1"],
)
def test_invalid_customer_id(customer_id):
    with pytest.raises(ValidationError):
        GetCustomerRecordInput(customer_id=customer_id)


def test_refund_requires_positive_amount_and_meaningful_reason():
    with pytest.raises(ValidationError):
        TriggerRefundInput(customer_id="CUST-A1001", amount=0.0, reason="Duplicate charge")

    with pytest.raises(ValidationError):
        TriggerRefundInput(customer_id="CUST-A1001", amount=10.0, reason="too short")

    with pytest.raises(ValidationError):
        TriggerRefundInput(customer_id="CUST-A1001", amount=10.0, reason="          ")


def test_extra_fields_are_rejected():
    with pytest.raises(ValidationError):
        GetCustomerRecordInput(customer_id="CUST-A1001", debug=True)
