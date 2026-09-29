"""Google Drive: черновик документа и PDF."""
import json
import os

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from config import DOC_ID, PDF_FOLDER_ID

# ИСПРАВЛЕНО (CRT-4): раньше json.loads(), from_service_account_info() и build() стояли
# без try. Битый JSON в секрете GOOGLE_CREDENTIALS (лишний перенос строки, обрезанный
# секрет, не тот формат) или отсутствие обязательных полей роняли процесс необработанным
# трейсбеком — причём вызывалось это ДО сборки газеты/отправки в Telegram, из-за чего
# проблема с Drive блокировала всю доставку. Теперь любая ошибка инициализации превращается
# в None + строчка в логе, а вызывающие функции (update_google_doc, upload_pdf_to_drive)
# уже умеют обработать None и вернуть False (см. 0.2).
# В лог попадает только тип и сообщение исключения — содержимое секрета в них не входит.
def get_drive_service():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    if not creds_json:
        return None
    try:
        creds_dict = json.loads(creds_json)
        credentials = service_account.Credentials.from_service_account_info(
            creds_dict, scopes=['https://www.googleapis.com/auth/drive']
        )
        return build('drive', 'v3', credentials=credentials)
        # build() с локально забандленными discovery-документами (Drive v3 — один из них)
        # не делает сетевых запросов сам по себе, поэтому ретраить здесь нечего: сеть
        # используется только в самих .execute() вызовах ниже (см. _drive_retry).
    except Exception as e:
        print(f"[!] Не удалось инициализировать Google Drive ({type(e).__name__}): {e}", flush=True)
        return None


# ДОБАВЛЕНО (1.7): googleapiclient ходит в сеть через httplib2/google-auth-httplib2, а не
# через requests — HTTP_SESSION с её ретраями (1.5) сюда не дотягивается в принципе.
# tenacity — единственный слой ретраев для Drive. Ретраим только: (а) HttpError с явно
# временным HTTP-кодом (429/5xx) — по коду, а не по тексту сообщения; (б) низкоуровневые
# сетевые сбои без ответа сервера (TimeoutError/ConnectionError). НЕ ретраим прочие
# HttpError (403 доступа, 404 файла и т.п.) — там повтор точно не поможет.
def _is_retryable_drive_error(e: Exception) -> bool:
    if isinstance(e, HttpError):
        return getattr(e.resp, "status", None) in (429, 500, 502, 503, 504)
    return isinstance(e, (TimeoutError, ConnectionError))


def _log_drive_retry(retry_state) -> None:
    exc = retry_state.outcome.exception()
    wait = retry_state.next_action.sleep if retry_state.next_action else 0
    print(f"[!] Google Drive недоступен ({type(exc).__name__}), повтор через {wait:.0f}с "
          f"(попытка {retry_state.attempt_number}/3)...", flush=True)


_drive_retry = retry(
    retry=retry_if_exception(_is_retryable_drive_error),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    stop=stop_after_attempt(3),
    before_sleep=_log_drive_retry,
    reraise=True,
)


# Каждый .execute() — своя маленькая функция под ретраем: если, например, файл уже создан,
# а сбоит только последующая .permissions().create(), повторяется ТОЛЬКО она, а не весь
# upload_pdf_to_drive целиком (иначе рисковали бы создать несколько копий PDF на Диске).
@_drive_retry
def _drive_find_pdf(service, query, fields):
    return service.files().list(q=query, spaces='drive', fields=fields).execute()


@_drive_retry
def _drive_update_file(service, file_id, media):
    return service.files().update(fileId=file_id, media_body=media).execute()


@_drive_retry
def _drive_create_file(service, file_metadata, media):
    return service.files().create(body=file_metadata, media_body=media, fields='id').execute()


@_drive_retry
def _drive_set_public(service, file_id):
    return service.permissions().create(fileId=file_id, body={'role': 'reader', 'type': 'anyone'}).execute()



# ИЗМЕНЕНО (0.2): три функции доставки теперь возвращают bool (True — только при
# реальном успехе), чтобы main() мог записать результат в cache["stages"].
# Раньше они возвращали None и глотали ошибки — из main() нельзя было понять, что было.
def update_google_doc(html_content) -> bool:
    service = get_drive_service()
    if not service:
        print("[!] Google Drive недоступен — черновик в Google Док не обновлён.", flush=True)
        return False

    file_path = "draft.html"
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        media = MediaFileUpload(file_path, mimetype='text/html')
        _drive_update_file(service, DOC_ID, media)
        print("Черновик в Google Док успешно обновлен!", flush=True)
        return True
    except Exception as e:
        print(f"Ошибка при обновлении Google Дока: {e}", flush=True)
        return False

def upload_pdf_to_drive(pdf_path) -> bool:
    service = get_drive_service()
    if not service:
        print("[!] Google Drive недоступен — PDF не загружен.", flush=True)
        return False

    query = f"'{PDF_FOLDER_ID}' in parents and name = 'newspaper.pdf' and trashed = false"
    try:
        # list() внутри try: раньше его сбой ронял весь процесс до отправки в Telegram.
        response = _drive_find_pdf(service, query, 'files(id, name)')
        files = response.get('files', [])
        media = MediaFileUpload(pdf_path, mimetype='application/pdf')
        if files:
            file_id = files[0]['id']
            _drive_update_file(service, file_id, media)
        else:
            file_metadata = {'name': 'newspaper.pdf', 'parents': [PDF_FOLDER_ID]}
            file = _drive_create_file(service, file_metadata, media)
            _drive_set_public(service, file.get('id'))
        print("PDF успешно загружен на Google Диск!", flush=True)
        return True
    except Exception as e:
        print(f"Ошибка при загрузке PDF на Google Диск: {e}", flush=True)
        return False
