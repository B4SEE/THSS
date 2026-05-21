"""
Token generation and verification for campaign tracking URLs.

Tokens are Django-signed values encoding a CampaignTarget pk.
They are embedded in phishing email URLs and validated on every tracking request.
"""
from django.core import signing

_SALT = 'phishing-track-v1'


def make_token(campaign_target_id: int) -> str:
    """Sign and encode a CampaignTarget pk into a URL-safe token string."""
    return signing.dumps(campaign_target_id, salt=_SALT)


def resolve_token(token: str) -> int:
    """Verify and decode a tracking token; raises signing.BadSignature on tampering."""
    return signing.loads(token, salt=_SALT)
