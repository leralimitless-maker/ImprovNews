"""Общая HTTP-сессия с ретраями на транспортном уровне (используется источниками и Telegram-публикацией)."""
try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    requests = None
    HTTPAdapter = None
    Retry = None

# ДОБАВЛЕНО (1.5): общая сессия с автоматическими ретраями на транспортном уровне.
if Retry:
    _HTTP_RETRY = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"]),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
else:
    _HTTP_RETRY = None


def _build_http_session():
    if requests is None:
        return None
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=_HTTP_RETRY)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


HTTP_SESSION = _build_http_session()
