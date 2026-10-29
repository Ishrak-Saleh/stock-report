"""Tracking number -> carrier and carrier tracking page. Pure functions."""
import re
from urllib.parse import quote

CARRIERS = ["UPS", "FedEx", "USPS", "DHL"]

_URLS = {
    "UPS": "https://www.ups.com/track?tracknum={}",
    "FedEx": "https://www.fedex.com/fedextrack/?trknbr={}",
    "USPS": "https://tools.usps.com/go/TrackConfirmAction?tLabels={}",
    "DHL": "https://www.dhl.com/us-en/home/tracking/tracking-express.html?submit=1&tracking-id={}",
}


def clean(number: str) -> str:
    return re.sub(r"[\s-]", "", number).upper()


def detect_carrier(number: str) -> str:
    """Best guess from the number's shape. Empty string when unsure (the user can pick one)."""
    n = clean(number)
    if re.fullmatch(r"1Z[0-9A-Z]{16}", n):
        return "UPS"
    if re.fullmatch(r"[A-Z]{2}\d{9}US", n) or re.fullmatch(r"9\d{19,21}", n):
        return "USPS"
    if re.fullmatch(r"\d{12}|\d{15}", n):
        return "FedEx"
    if re.fullmatch(r"\d{10,11}|JD\d{18}", n):
        return "DHL"
    return ""


def tracking_url(carrier: str, number: str) -> str | None:
    template = _URLS.get(carrier)
    return template.format(quote(clean(number))) if template else None
