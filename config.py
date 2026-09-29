"""Конфигурация: секреты из окружения, ID документов Google, списки источников, лимиты текста.
Модуль-лист: ничего не импортирует из проекта."""
import os
from datetime import timezone, timedelta

LOCAL_TZ = timezone(timedelta(hours=5))

# ИСПРАВЛЕНО (CFG-001, частично): раньше здесь стояло os.environ["..."] — отсутствующая
# переменная роняла ИМПОРТ модуля трейсбеком с голым KeyError (без списка всего, чего
# не хватает), а сам модуль нельзя было импортировать в тестах без реальных секретов.
# Теперь значения читаются мягко, а проверка обязательных переменных вынесена в
# validate_env() и выполняется первой строкой main(): понятное сообщение сразу со ВСЕМИ
# недостающими именами, до похода в сеть и до трат на Gemini.
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
MY_CHAT_ID = os.environ.get("MY_CHAT_ID", "")

REQUIRED_ENV = ("BOT_TOKEN", "GEMINI_API_KEY", "MY_CHAT_ID")


def validate_env() -> None:
    # Пустая или состоящая из одних пробелов переменная считается отсутствующей.
    missing = [name for name in REQUIRED_ENV if not (os.environ.get(name) or "").strip()]
    if missing:
        raise SystemExit(f"Отсутствуют обязательные переменные окружения: {', '.join(missing)}")


DOC_ID = "13tQCDrY7eW1q0kUggi-1wVXpm8Phh8HxuKwu6GREsd8"
PDF_FOLDER_ID = "1enu9CNlCXxGMojV6lbtjobHWWrhg8q_c"

# ИСПРАВЛЕНО (LOW-3): было CACHE_FILE = "newspaper_cache.json" — относительный путь,
# который резолвится от текущей рабочей директории процесса (CWD). Если скрипт
# когда-нибудь запустят из другого каталога (другой шаг CI, другой cron-юзер),
# файл кэша тихо "потеряется" и появится новый пустой в другом месте.
# Теперь путь абсолютный и всегда указывает на каталог рядом со скриптом,
# независимо от того, откуда его запустили.
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "newspaper_cache.json")

CHANNELS = [
    "zzakatov", "darya_dinosaur_fm", "improv_nv", "dudyukajulia", "improvizekb", 
    "imtakproshche", "sidishkaaa", "svetkakrevetkaaa", "klimchudickyea", "trenazh", 
    "maly6kina", "improvplus", "proseccoshow", "iclairs_improv", "kmp_impro", "paraimprovfraz",
    "shamina_sharit", "improvinsight", "golce06", "improvstudioru", "ImprovBuro", "isk_gus",
    "ImprovLifeblog", "teriviki", "Geksliy", "NastyaNeiro2", "tochkabest", "improvauthors",
    "o_pereverzeva", "improv_paly4", "improvru", "sabrageimprov", "moscowimprovclub", 
    "improvmoscow", "romkaShn", "improv_light", "ada_legna", "improstore", "improculture",
    "improvrostovsidorova", "byvshieshow", "olyaisolyais", "gdscrpt", "moresprava", 
    "ammasters", "lgv_prod", "notscripted", "zigatu1", "drozhizhizhi", "improschoolspb", 
    "manezhclub", "playingtomyself", "domisly", "BRIF_improv", "v40th", "boondockscamp", 
    "improfi_school", "playbackrostov", "improv56", "nikitamenshoff", "Ni_odnogo_D", 
    "a_pligin", "improlab_kzn", "breaking_it", "dreamuchaya_pyatnica", "etoetiteam", 
    "improvlady", "tayaiilyaimprov", "oitheatre", "theatre_13", "sandboxlv", "ostrovimpro",
    "chaoticimprov", "improvteams", "sireneviy_toomuch", "alexmikerov", "zvezdyvlyzhah", 
    "Hoodnews", "improcomunity", "damy_improv", "izbrannye_impro", "akeytou", "carpetstorage",
    "nazhivuyu", "podplie", "showimpro", "impro_Vasa", "poilo_improvband", "improvboris", 
    "improtips", "sevenmetres", "brezglivaya_lubov", "obnyalaimpro", "burnyashnyash", 
    "kicakotli", "netolkoimpro", "Alkaimprov", "azartimprov", "alkomixer", "zhivye_impr", 
    "improvarctic", "impride_spb", "jam_students", "danetnavernoe_improv", "smehotochka", 
    "neujeliatut", "igristyyyee", "improcomfangroup", "rightnow_show", "elina_pro_improv", 
    "razrivnie_Mos_kow", "fouretazhka", "tugezaimprov", "pckcimprov", "neseryosnie", "ligaimprova"
]

RSS_FEEDS = [
    "https://connectedcomedy.com/feed/",
    "https://improveverywhere.com/feed/",
    "https://willhines.substack.com/feed",
    "https://alloutcomedytheater.com/annas-improv-blog?format=rss",
    "https://jimmycarrane.com/feed",
    "https://nationalcomedy.com/feed",
    "https://shinythingscomedy.com/improv-blog?format=rss",
    "https://feeds.libsyn.com/112269/rss",
    "https://ucbcomedy.com/feed",
    "https://improvmoscow.ru/feed"
]

# ДОБАВЛЕНО (1.9–1.10/DAT-003): раньше raw_news обрезался ЕДИНЫМ лимитом в 40000 символов
# уже ПОСЛЕ склейки "Телеграм: ... Reddit: ... Блоги: ..." (см. прежний build_full_newspaper).
# Телеграм-текста почти всегда на порядок больше, чем Reddit/RSS вместе взятых (116 каналов
# против 10 фидов и одного сабреддита), поэтому единая обрезка по хвосту строки на практике
# ВСЕГДА резала Reddit и блоги — иногда целиком, — а не только "лишнее" из Телеграма.
# Теперь у каждого источника свой бюджет символов, применяется ДО склейки (см. main()):
# ни один источник не может вытеснить остальные, даже если один Telegram-канал разродится
# нетипично длинным постом. Суммарно бюджеты дают тот же порядок величины, что и старый
# общий лимit (37000 против 40000), с запасом под теги атрибуции "[Пост Sxx от ...]".
TG_TEXT_BUDGET = 25000
RSS_TEXT_BUDGET = 8000
REDDIT_TEXT_BUDGET = 4000

GEMINI_MODEL = "gemini-3.6-flash"
