import pytest

from app.domain.carriers import detect_carrier, tracking_url


@pytest.mark.parametrize("number,carrier", [
    ("1Z999AA10123456784", "UPS"),
    ("1z 999 aa1 0123 456 784", "UPS"),
    ("794644790138", "FedEx"),
    ("9400111899223344556677", "USPS"),
    ("EA123456789US", "USPS"),
    ("1234567890", "DHL"),
    ("ABC", ""),
])
def test_detect_carrier(number, carrier):
    assert detect_carrier(number) == carrier


def test_tracking_url():
    assert tracking_url("UPS", "1Z999AA10123456784") == "https://www.ups.com/track?tracknum=1Z999AA10123456784"
    assert "trknbr=794644790138" in tracking_url("FedEx", "7946 4479 0138")
    assert "tLabels=9400111899223344556677" in tracking_url("USPS", "9400111899223344556677")
    assert "tracking-id=1234567890" in tracking_url("DHL", "1234567890")
    assert tracking_url("", "123") is None
    assert tracking_url("Other", "123") is None
