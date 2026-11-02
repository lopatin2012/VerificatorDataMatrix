"""Opt-in lookup in Chestny Znak (CRPT) public mobile API.

The application NEVER calls this module automatically. A request is made only
from an explicit GUI/Web button or the CLI ``--crpt`` flag. There is no token
and no authentication; the endpoint is undocumented and may be geo-blocked.

    POST https://mobile.api.crpt.ru/mobile/check
    {"code": "<marking code>", "codeType": "datamatrix"}

The mobile app's headers are sent because a bare server User-Agent is often
rejected with HTTP 403.
"""
import datetime
import json
import urllib.error
import urllib.request

ENDPOINT = "https://mobile.api.crpt.ru/mobile/check"
TIMEOUT = 10

_UA = ("Platform: iOS 17.2; AppVersion: 4.47.0; AppVersionCode: 7630; "
       "Device: iPhone 14 Pro;")
_CLIENT = "iOS 17.2; AppVersion: 4.47.0; Device: iPhone 14 Pro;"

STATUS_TEXT = {
    "EMITTED": "Эмитирован",
    "APPLIED": "Нанесён",
    "INTRODUCED": "Введён в оборот",
    "RETIRED": "Выведен из оборота",
    "WRITTEN_OFF": "Списан",
    "DISAGGREGATION": "Расформирован",
    "RESERVED": "Зарезервирован",
    "FREE": "Свободен",
    "WAIT_APPLY": "Ожидает нанесения",
    "not_found": "Не найден",
    "not_found_dm": "Не найден",
    "wrong": "Проверка не пройдена",
    "ok": "OK",
}

WARNING_TEXT = {
    "not_found": "код не найден в ГИС МТ",
    "not_verified": "код не прошёл проверку (криптохвост отсутствует или неверен)",
}

CATEGORY_TEXT = {
    "beer": "Пиво и пивные напитки",
    "milk": "Молочная продукция",
    "tobacco": "Табак",
    "shoes": "Обувь",
    "tires": "Шины",
    "perfume": "Парфюмерия",
    "water": "Вода",
    "softdrinks": "Безалкогольные напитки",
    "pharma": "Лекарства",
    "medical": "Медизделия",
    "wheelchairs": "Кресла-коляски",
    "antiseptic": "Антисептики",
    "bicycle": "Велосипеды",
    "camera": "Фотоаппараты",
    "light": "Светотехника",
    "petfood": "Корма для животных",
    "vegetable": "Растительные масла",
    "grocery": "Бакалея",
    "electronics": "Электроника",
    "toys": "Игрушки",
    "furs": "Меха",
}


class CrptError(RuntimeError):
    """A lookup failed (network, HTTP or malformed response)."""


def _post_json(code, code_type="datamatrix", timeout=TIMEOUT):
    body = json.dumps({"code": code, "codeType": code_type},
                      ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT, data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": _UA,
            "client": _CLIENT,
        })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read()
    except urllib.error.HTTPError as exc:
        hint = ""
        if exc.code == 403:
            hint = " (сервис может быть недоступен вне РФ)"
        elif exc.code == 429:
            hint = " (слишком много запросов)"
        raise CrptError(f"Честный знак: HTTP {exc.code}{hint}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CrptError(f"Честный знак: нет связи ({exc})") from exc
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise CrptError("Честный знак: некорректный ответ") from exc


def _pick(*values):
    """First non-empty string-ish value (for names/IDs)."""
    for value in values:
        if isinstance(value, str):
            value = value.strip()
            if value and value.lower() not in ("отсутствует", "null", "none"):
                return value
        elif isinstance(value, (int, float)) and value:
            return str(value)
    return None


def _first(*values):
    """First non-empty value without converting numbers to strings."""
    for value in values:
        if value not in (None, "", 0):
            return value
    return None


def fmt_date(value):
    """Format an ISO date / millisecond timestamp as DD.MM.YYYY."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if value <= 0:
            return None
        seconds = value / 1000.0 if value > 1e11 else float(value)
        try:
            dt = datetime.datetime.fromtimestamp(seconds,
                                                tz=datetime.timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
        return dt.strftime("%d.%m.%Y")
    text = str(value).strip()
    if not text:
        return None
    iso = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        return datetime.datetime.fromisoformat(iso).strftime("%d.%m.%Y")
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.datetime.strptime(text[:19], fmt).strftime(
                "%d.%m.%Y")
        except ValueError:
            continue
    return text


def parse_response(raw, code=None):
    """Normalize the public API response; never raises on missing fields."""
    if not isinstance(raw, dict):
        raise CrptError("Честный знак: некорректный ответ")

    resolved = raw.get("codeResolveData")
    if not isinstance(resolved, dict):
        resolved = {}
    ais = resolved.get("ais")
    if not isinstance(ais, dict):
        ais = {}

    category = _pick(raw.get("category"), resolved.get("codeCategory"))
    detail = None
    if category:
        candidate = raw.get(f"{category}Data")
        if isinstance(candidate, dict):
            detail = candidate
    if detail is None:
        for key, value in raw.items():
            if (key.endswith("Data") and key not in
                    ("codeResolveData", "catalogData")
                    and isinstance(value, dict)):
                detail = value
                category = category or key[:-4]
                break
    if detail is None:
        detail = {}

    catalog = raw.get("catalogData")
    first = (catalog[0] if isinstance(catalog, list) and catalog
             and isinstance(catalog[0], dict) else {})
    props = detail.get("productProperty")
    if not isinstance(props, dict):
        props = {}

    attrs = {}
    country_attr = None
    brand_attr = None
    good_attrs = first.get("good_attrs")
    if isinstance(good_attrs, list):
        wanted = ("Тип упаковки", "Объём продукции в единице упаковки",
                  "Состав", "Срок годности, дней")
        for attr in good_attrs:
            if not isinstance(attr, dict):
                continue
            name = attr.get("attr_name")
            value = _pick(attr.get("attr_value"))
            unit = _pick(attr.get("attr_value_type"))
            if value and unit:
                value = f"{value} {unit}"
            if not value:
                continue
            if name == "Страна производства":
                country_attr = country_attr or value
            elif name == "Товарный знак":
                brand_attr = brand_attr or value
            elif name in wanted and name not in attrs:
                attrs[name] = value

    product_status = _pick(detail.get("status"), raw.get("outerStatus"),
                           raw.get("statusV2"), raw.get("status"))
    check_status = _pick(raw.get("status"), raw.get("statusV2"))
    warning = _pick(raw.get("warning"))

    expiry = fmt_date(_first(detail.get("expirationDate"),
                             detail.get("expireDate"),
                             raw.get("expirationDate"), raw.get("expireDate")))
    produced = fmt_date(_first(detail.get("producedDate"),
                               detail.get("productionDate"),
                               props.get("producedDate")))

    return {
        "ok": True,
        "code": _pick(raw.get("code"), code),
        "found": bool(raw.get("codeFounded")),
        "check": bool(raw.get("checkResult")),
        "verified": bool(resolved.get("verified")),
        "valid": bool(resolved.get("valid")),
        "blocked": bool(resolved.get("isBlocked")),
        "gtin": _pick(resolved.get("gtin"), ais.get("gtin")),
        "serial": _pick(resolved.get("cis"), ais.get("serial")),
        "product_name": _pick(detail.get("productName"),
                              raw.get("productName"),
                              first.get("good_name")),
        "category": category,
        "category_text": CATEGORY_TEXT.get(category, category),
        "producer": _pick(detail.get("producerName"),
                          detail.get("manufacturerName"),
                          raw.get("producerName"),
                          first.get("producer_name")),
        "owner": _pick(raw.get("ownerName"), detail.get("ownerName"),
                       first.get("owner_name")),
        "owner_inn": _pick(raw.get("ownerInn"), detail.get("ownerInn"),
                           first.get("owner_inn")),
        "brand": _pick(brand_attr, detail.get("brand"),
                       first.get("brand_name"), props.get("brand")),
        "country": _pick(country_attr, detail.get("country"),
                         props.get("country")),
        "status": product_status,
        "status_text": STATUS_TEXT.get(product_status, product_status),
        "check_status": check_status,
        "check_status_text": STATUS_TEXT.get(check_status, check_status),
        "warning": warning,
        "warning_text": WARNING_TEXT.get(warning, warning),
        "expiry": expiry,
        "produced": produced,
        "message": _pick(resolved.get("message")),
        "attributes": attrs,
        "raw": raw,
    }


def lookup(code, code_type="datamatrix", timeout=TIMEOUT):
    """Call the public endpoint for one marking code (explicit action only)."""
    code = str(code or "").strip(" \t\r\n")
    if not code:
        raise CrptError("Честный знак: пустой код")
    return parse_response(_post_json(code, code_type, timeout), code=code)
