from django.core import signing

_SALT = 'phishing-track-v1'


def make_token(campaign_target_id: int) -> str:
    return signing.dumps(campaign_target_id, salt=_SALT)


def resolve_token(token: str) -> int:
    return signing.loads(token, salt=_SALT)
