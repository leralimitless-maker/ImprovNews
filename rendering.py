"""Рендер PDF: безопасная загрузка картинок и вызов WeasyPrint."""
import ipaddress
import socket
import time
from urllib.parse import urlsplit

import requests
from weasyprint import HTML


# ДОБАВЛЕНО (1.4): с WeasyPrint 68.0 url_fetcher — экземпляр класса URLFetcher, а функция
# default_url_fetcher объявлена deprecated; до 68 fetcher — обычная функция, возвращающая dict.
# Код работает с обеими версиями (см. make_weasyprint_fetcher).
try:
    from weasyprint.urls import URLFetcher as _WPURLFetcher, URLFetcherResponse as _WPURLFetcherResponse
except ImportError:
    _WPURLFetcher = _WPURLFetcherResponse = None

# ДОБАВЛЕНО (1.4, SEC-002): политика для изображений. Раньше WeasyPrint сам ходил по любому
# <img src>/url(...), попавшему в HTML, — без ограничений по хосту, размеру и времени
# (SSRF на localhost/169.254.169.254, гигантские файлы, зависания). Теперь три слоя:
#   1) URL картинок в HTML вообще не приходят от модели — она возвращает только ID фото
#      (P1, P2...), а URL подставляет код из словаря, собранного парсером (см. 1.1–1.3);
#   2) парсер и рендер принимают только https-URL с CDN Telegram (is_allowed_image_url);
#   3) WeasyPrint получает собственный url_fetcher, который не умеет НИЧЕГО, кроме
#      скачивания разрешённых картинок: ни file://, ни data:, ни http, ни редиректов.
# Слой 3 работает и как страховка: даже если в HTML когда-нибудь попадёт чужой URL
# (правка шаблона, испорченный кэш), наружу он не уйдёт.

# cdn*.telesco.pe — актуальный CDN превью t.me/s, cdn*.cdn-telegram.org — прежний.
IMAGE_HOST_SUFFIXES = ("telesco.pe", "cdn-telegram.org")
MAX_IMAGE_URL_LEN = 2048
MAX_IMAGE_BYTES = 8 * 1024 * 1024         # один файл
MAX_TOTAL_IMAGE_BYTES = 40 * 1024 * 1024  # все картинки одного PDF
IMAGE_CONNECT_TIMEOUT = 5
IMAGE_READ_TIMEOUT = 15    # макс. пауза МЕЖДУ порциями данных (см. ограничение ниже)
IMAGE_TOTAL_TIMEOUT = 30   # мягкий общий потолок на один файл, а не жёсткая гарантия — см. fetch()


def is_allowed_image_url(url) -> bool:
    """True только для https-URL на белом списке доменов, без креденшелов и нестандартных портов."""
    if not isinstance(url, str) or not url or len(url) > MAX_IMAGE_URL_LEN:
        return False
    # Пробелы, управляющие символы и обратные слэши разные парсеры URL трактуют по-разному.
    if "\\" in url or any(ch.isspace() or ord(ch) < 32 for ch in url):
        return False
    try:
        parts = urlsplit(url)
        host, port = parts.hostname, parts.port
    except ValueError:
        return False
    if parts.scheme != "https" or not host or port not in (None, 443):
        return False
    host = host.lower()
    # netloc обязан состоять ТОЛЬКО из хоста (и, возможно, :443): так отсекаются user:pass@host
    # и прочие трюки, на которых urlsplit (здесь) и urllib3 (в requests) видят разные хосты.
    if parts.netloc.lower() not in (host, f"{host}:443"):
        return False
    return any(host == s or host.endswith("." + s) for s in IMAGE_HOST_SUFFIXES)


def _sniff_image_type(head: bytes):
    """Тип по «магическим» байтам, а не по заголовку Content-Type: до Pillow/WeasyPrint
    доходят только четыре растровых формата (SVG, EPS, PDF и прочее отсекается здесь)."""
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


_VERIFIED_PUBLIC_HOSTS = set()


def _host_is_public(url: str, host: str) -> bool:
    """Все адреса хоста должны быть публичными (не loopback/private/link-local/metadata...).
    ОГРАНИЧЕНИЕ: между этой проверкой и реальным соединением requests резолвит имя заново,
    поэтому от DNS rebinding она не защищает — основной барьер здесь белый список доменов
    Telegram, а проверка IP лишь страхует на случай ошибки в нём."""
    if host in _VERIFIED_PUBLIC_HOSTS:
        return True
    # За прокси имя резолвит сам прокси — локальный getaddrinfo ничего не доказывает
    # и мог бы ложно заблокировать все картинки (в CI без прямого DNS).
    if requests.utils.get_environ_proxies(url):
        return True
    try:
        addrs = {info[4][0] for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    except OSError:
        return False
    if not addrs:
        return False
    for addr in addrs:
        try:
            ip = ipaddress.ip_address(addr.split("%")[0])  # у link-local IPv6 бывает %scope
        except ValueError:
            return False
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global:
            return False
    _VERIFIED_PUBLIC_HOSTS.add(host)  # только успех: временный сбой DNS не «залипает»
    return True


class SafeImageFetcher:
    """Скачивает ОДНУ картинку по проверенному URL: без редиректов, с лимитами размера и времени,
    с проверкой формата по содержимому. Любое нарушение — ValueError (WeasyPrint превратит его
    в предупреждение и просто не нарисует картинку; PDF при этом соберётся)."""

    def __init__(self):
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "Mozilla/5.0 ImprovNewspaperBot/1.0"
        self.total_bytes = 0
        self.fetched = 0
        self.failed = 0
        self.blocked = {}  # причина -> сколько раз

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._session.close()

    def _block(self, reason: str):
        self.blocked[reason] = self.blocked.get(reason, 0) + 1
        raise ValueError(f"изображение заблокировано: {reason}")

    def fetch(self, url: str):
        """Возвращает (байты, mime_type) или бросает исключение."""
        if not is_allowed_image_url(url):
            self._block("URL вне белого списка")
        host = urlsplit(url).hostname.lower()
        if not _host_is_public(url, host):
            self._block("хост указывает на непубличный адрес или не резолвится")
        if self.total_bytes >= MAX_TOTAL_IMAGE_BYTES:
            self._block("исчерпан общий лимит размера картинок")

        # ВАЖНО: это МЯГКИЙ дедлайн. Проверка идёт между чанками, а requests/urllib3 не даёт
        # прервать уже начатый блокирующий recv() снаружи (проверено: закрытие сокета из
        # другого потока либо не будит блокирующее чтение вовсе, либо — при принудительном
        # shutdown() — даёт socket EOF, который для ответа без Content-Length неотличим от
        # штатного конца тела: недокачанные байты тогда прошли бы как «успешно загруженные»,
        # что хуже, чем не пытаться обрывать чтение вовсе). Поэтому реальный потолок на файл —
        # IMAGE_TOTAL_TIMEOUT + IMAGE_READ_TIMEOUT (наш дедлайн может обнаружиться только
        # ПОСЛЕ того, как придёт следующий чанк, а его ожидание само по себе может занять
        # до IMAGE_READ_TIMEOUT). При IMAGE_READ_TIMEOUT << IMAGE_TOTAL_TIMEOUT (как здесь,
        # 15 против 30) перебор небольшой; резать его до нуля — не стоит хрупкости и рисков.
        deadline = time.monotonic() + IMAGE_TOTAL_TIMEOUT
        buf = bytearray()
        try:
            with self._session.get(url, stream=True, allow_redirects=False,
                                   timeout=(IMAGE_CONNECT_TIMEOUT, IMAGE_READ_TIMEOUT)) as resp:
                if 300 <= resp.status_code < 400:
                    self._block("редирект")
                resp.raise_for_status()
                declared = resp.headers.get("Content-Length", "")
                if declared.isdigit() and int(declared) > MAX_IMAGE_BYTES:
                    self._block("файл больше лимита")
                # iter_content отдаёт уже РАСПАКОВАННЫЕ данные, поэтому лимит защищает и от gzip-бомб.
                for chunk in resp.iter_content(chunk_size=65536):
                    buf += chunk
                    if len(buf) > MAX_IMAGE_BYTES:
                        self._block("файл больше лимита")
                    # Кумулятивный лимит проверяем ПО ХОДУ, а не только в начале следующего
                    # fetch(): иначе один файл, попавший в узкое окно "total_bytes ещё меньше
                    # лимита", мог бы докачаться целиком и увести total_bytes далеко за
                    # MAX_TOTAL_IMAGE_BYTES (до +MAX_IMAGE_BYTES перебора). Так перебор — не
                    # больше одного чанка (65536 Б).
                    if self.total_bytes + len(buf) > MAX_TOTAL_IMAGE_BYTES:
                        self._block("исчерпан общий лимит размера картинок")
                    if time.monotonic() > deadline:
                        self._block("превышено общее время загрузки")
        except requests.RequestException:
            self.failed += 1
            raise

        mime = _sniff_image_type(bytes(buf[:16]))
        if mime is None:
            self._block("не JPEG/PNG/GIF/WebP")
        self.total_bytes += len(buf)
        self.fetched += 1
        return bytes(buf), mime

    def summary(self) -> str:
        parts = [f"загружено {self.fetched} ({self.total_bytes // 1024} КБ)"]
        if self.failed:
            parts.append(f"ошибок загрузки {self.failed}")
        parts += [f"заблокировано «{reason}»: {n}" for reason, n in self.blocked.items()]
        return "Изображения для PDF: " + ", ".join(parts)


def make_weasyprint_fetcher(guard: SafeImageFetcher):
    """Адаптер под API WeasyPrint: с 68.0 fetcher — экземпляр URLFetcher (метод fetch),
    до 68 — функция, возвращающая dict. Логика в обоих случаях одна и живёт в guard.fetch;
    к штатному default_url_fetcher/URLFetcher.fetch мы принципиально не делегируем."""
    if _WPURLFetcher is not None:
        class _Fetcher(_WPURLFetcher):
            def fetch(self, url, headers=None):
                body, mime = guard.fetch(url)
                return _WPURLFetcherResponse(url, body, {"Content-Type": mime})
        return _Fetcher()

    def legacy_fetcher(url, *args, **kwargs):
        body, mime = guard.fetch(url)
        return {"string": body, "mime_type": mime, "redirected_url": url}
    return legacy_fetcher


def render_pdf(pdf_html: str, pdf_path: str) -> None:
    with SafeImageFetcher() as guard:
        HTML(string=pdf_html, url_fetcher=make_weasyprint_fetcher(guard)).write_pdf(pdf_path)
    print(guard.summary(), flush=True)
