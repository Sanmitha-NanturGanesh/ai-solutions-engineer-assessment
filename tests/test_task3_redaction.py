from task3_llm_guardrail.redactor import StreamingRedactor, redact_pii


def test_redacts_supported_pii():
    text = "email jane@example.com ssn 123-45-6789 card 4242 4242 4242 4242"
    safe = redact_pii(text)

    assert "jane@example.com" not in safe
    assert "123-45-6789" not in safe
    assert "4242 4242 4242 4242" not in safe
    assert safe.count("[REDACTED]") == 3


def test_does_not_redact_arbitrary_number_as_card():
    text = "reference 1234 5678 9012 3456"
    assert redact_pii(text) == text


def test_email_split_across_chunks():
    redactor = StreamingRedactor()
    output = "".join(
        [
            redactor.feed("Contact jane.do"),
            redactor.feed("e@example"),
            redactor.feed(".com for help."),
            redactor.flush(),
        ]
    )

    assert "jane.doe@example.com" not in output
    assert "[REDACTED]" in output
    assert "for help." in output


def test_ssn_split_across_chunks():
    redactor = StreamingRedactor()
    output = redactor.feed("SSN 123-45-") + redactor.feed("6789 done") + redactor.flush()
    assert "123-45-6789" not in output
    assert "[REDACTED]" in output
