"""Общая HTTP-сессия с ретраями на транспортном уровне (используется источниками и Telegram-публикацией)."""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ДОБАВЛЕНО (1.5): общая сессия с автоматическими ретраями на транспортном уровне. Раньше
# каждый requests.get/post был "выстрелил и забыл" — один разрыв TCP или один временный
# 502/503 от Reddit/Telegram/RSS-фида сразу считались провалом всего вызова. Теперь urllib3
# сам повторяет запрос с нарастающей паузой на сетевых сбоях и на явно временных HTTP-кодах,
# прежде чем отдать ошибку наверх — вызывающему коду вообще не нужно об этом знать.
#
# Осознанно НЕ используется в SafeImageFetcher (1.4): там свой закрытый бюджет времени на
# файл (IMAGE_TOTAL_TIMEOUT) и свои соображения безопасности (allow_redirects=False и т.п.);
# ретраи на транспорте увеличили бы фактическое время скачивания сверх задокументированного
# и не проверялись интеграционными тестами из 1.4 — трогать не стали.
_HTTP_RETRY = Retry(
    total=3,
    backoff_factor=0.5,               # паузы ~0.5с, 1с, 2с между попытками
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET", "POST"]),  # POST по умолчанию НЕ ретраится urllib3;
                                                   # наш единственный POST (Telegram) собирает
                                                   # тело запроса ЗАРАНЕЕ (см. _post_to_telegram),
                                                   # поэтому повтор той же подготовленной
                                                   # multipart-формы безопасен
    respect_retry_after_header=True,  # Telegram/Reddit при 429 присылают Retry-After — уважаем
    raise_on_status=False,            # пусть resp.raise_for_status() кидает наше привычное исключение
)


def _build_http_session() -> requests.Session:
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=_HTTP_RETRY)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


HTTP_SESSION = _build_http_session()
