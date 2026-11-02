"""GS1 Application Identifier parsing for GS1 DataMatrix content."""
import datetime

# AI table: ai -> (name, description, length) where length is None for
# variable-length (terminated by FNC1 / GS separator or end of data).
AI_TABLE = {
    "00": ("SSCC", "Серийный код транспортной упаковки", 18),
    "01": ("GTIN", "Глобальный номер товара", 14),
    "02": ("CONTENT", "GTIN упаковки", 14),
    "10": ("LOT", "Номер партии", None),
    "11": ("PROD_DATE", "Дата производства", 6),
    "12": ("DUE_DATE", "Срок оплаты", 6),
    "13": ("PACK_DATE", "Дата упаковки", 6),
    "15": ("BEST_BEFORE", "Годен до", 6),
    "16": ("SELL_BY", "Продать до", 6),
    "17": ("EXPIRY", "Срок годности", 6),
    "20": ("VARIANT", "Вариант продукта", 2),
    "21": ("SERIAL", "Серийный номер", None),
    "22": ("CPV", "Количество дополнительных продуктов", None),
    "240": ("ADDID", "Дополнительный идентификатор продукта", None),
    "241": ("CUSTNO", "Номер заказчика", None),
    "250": ("SECONDARY", "Вторичный серийный номер", None),
    "251": ("REF", "Ссылка на исходный документ", None),
    "30": ("COUNT", "Количество", None),
    "37": ("COUNT", "Количество единиц", None),
    "90": ("INTERNAL", "Внутренний идентификатор", None),
    "91": ("KEY", "Ключ проверки", None),
    "92": ("SG", "Электронная подпись", None),
    "93": ("EXT", "Дополнительные данные", None),
    "400": ("ORDERNO", "Номер заказа", None),
    "401": ("GINC", "Идентификатор груза", None),
    "402": ("GDTI", "Идентификатор грузовой единицы", None),
    "403": ("ROUTE", "Маршрут", None),
    "410": ("SHIPTO", "GLN пункта доставки", 13),
    "414": ("LOCNO", "GLN физического расположения", 13),
    "420": ("SHIPTO_POST", "Почтовый индекс доставки", None),
    "7001": ("NSN", "Национальный номер запаса", 13),
    "7002": ("MEAT", "Классификация мяса", None),
    "7003": ("EXPIRY_DT", "Дата и время истечения срока", 10),
    "7004": ("REF_7004", "Ссылка на документ", None),
    "7006": ("FIRST_FREEZE", "Дата заморозки", 6),
    "7030": ("PROCESSOR", "Код процессора", None),
    "8001": ("ROLL", "Параметры рулона", 14),
    "8002": ("CMT", "Идентификатор мобильного устройства", None),
    "8003": ("GRAI", "Глобальный идентификатор возвратной тары", None),
    "8004": ("GIAI", "Глобальный идентификатор актива", None),
    "8005": ("PRICE", "Цена за единицу", 6),
    "8006": ("ITIP", "GTIN и частей", 18),
    "8007": ("IBAN", "Международный номер банковского счёта", None),
    "8008": ("PROD_DT", "Дата и время производства", None),
    "8018": ("SERVICES", "Идентификатор услуги", 18),
    "8020": ("PAYREF", "Ссылка на платёж", None),
    "8100": ("CPID", "Идентификатор купона", None),
    "8110": ("CPN", "Данные купона", None),
    "8200": ("PRODURL", "Ссылка на продукт", None),
}

# 4-digit pattern AIs: 310n..316n measure fixed 6 digits, 390n..395n are
# variable amounts. `n` is the implied decimal position.
_MEASURE_AIS = {
    "310": "Вес нетто", "311": "Длина", "312": "Ширина", "313": "Высота",
    "314": "Площадь", "315": "Объём", "316": "Объём",
}
_AMOUNT_AIS = ("390", "391", "392", "393", "394", "395")

# Fixed dates: AI -> date format (length in digits).
_DATE_FORMATS = {"11": 6, "12": 6, "13": 6, "15": 6, "16": 6, "17": 6,
                 "7006": 6, "7003": 10}


def ai_info(ai):
    """Look up an AI, including pattern AIs (310n..316n, 390n..395n)."""
    info = AI_TABLE.get(ai)
    if info is not None:
        return info
    if len(ai) == 4 and ai.isdigit():
        if ai[:3] in _MEASURE_AIS:
            unit = {"310": "кг", "311": "м", "312": "м", "313": "м",
                    "314": "м²", "315": "л", "316": "м³"}[ai[:3]]
            return (f"{ai[:3]}n", f"{_MEASURE_AIS[ai[:3]]}, {unit}", 6)
        if ai[:3] in _AMOUNT_AIS:
            return (f"{ai[:3]}n", "Сумма", None)
    return None


def _match_ai(s, i):
    """Longest AI starting at position `i`, or None."""
    for length in (4, 3, 2):
        if i + length <= len(s):
            ai = s[i:i + length]
            if ai_info(ai) is not None:
                return ai
    return None


class Element:
    def __init__(self, ai, value):
        self.ai = ai
        self.value = value
        info = ai_info(ai) or (ai, "", None)
        self.name = info[0]
        self.description = info[1]

    def display_name(self):
        if self.name in ("GTIN", "SERIAL", "KEY", "SG", "EXT"):
            return self.name
        return f"AI {self.ai}"

    def display_value(self):
        """Human-readable value; GS1 dates are rendered as DD.MM.YYYY."""
        length = _DATE_FORMATS.get(self.ai)
        if length:
            formatted = format_gs1_date(self.value, length)
            if formatted:
                return formatted
        return self.value

    def display_label(self):
        """Chip/label text without duplicating 'AI' for generic elements."""
        if self.name in ("GTIN", "SERIAL", "KEY", "SG", "EXT"):
            return f"{self.name} (AI {self.ai})"
        return f"AI {self.ai}"


def parse(data):
    """Parse raw DataMatrix bytes into a list of Elements.

    `data` may be the raw bytes (with \\x1d GS separators) or the zxing HRI
    text like '(01)....(21)....'.
    """
    if data is None:
        return []
    if isinstance(data, bytes):
        s = data.decode("latin-1")
    else:
        s = str(data)
    if s.lstrip().startswith("(") and ")" in s:
        return _parse_hri(s)
    return _parse_raw(s)


def _parse_hri(s):
    """Parse '(01)000...(21)SER' without touching the values themselves."""
    elements = []
    i, n = 0, len(s)
    seps = "\x1c\x1d\x1e"
    while i < n:
        j = s.find("(", i)
        if j < 0:
            break
        k = s.find(")", j + 1)
        if k < 0:
            break
        ai = s[j + 1:k].strip()
        nxt = s.find("(", k + 1)
        value = s[k + 1:nxt if nxt >= 0 else n].rstrip(seps)
        if ai:
            elements.append(Element(ai, value))
        i = nxt if nxt >= 0 else n
    return elements


def _parse_raw(s):
    """Parse raw GS1 data (AIs back to back, GS/FNC1 separated)."""
    elements = []
    i, n = 0, len(s)
    seps = "\x1c\x1d\x1e"
    while i < n:
        while i < n and s[i] in seps:
            i += 1
        if i >= n:
            break
        ai = _match_ai(s, i)
        if ai is None:
            # Unknown AI: assume the usual 2-digit prefix, but only if the
            # data at least starts with digits (otherwise stop parsing).
            if i + 2 <= n and s[i:i + 2].isdigit():
                ai = s[i:i + 2]
            else:
                break
        i += len(ai)
        info = ai_info(ai)
        fixed = info[2] if info else None
        if fixed is not None:
            value = s[i:i + fixed]
            i += len(value)
        else:
            # Variable-length field: a GS/FNC1 separator is authoritative.
            # Without one (typically the last field), look for the next
            # known AI, but never end the value before its first character.
            sep = i
            while sep < n and s[sep] not in seps:
                sep += 1
            if sep < n:
                value = s[i:sep]
                i = sep
            else:
                j = i
                while j < n:
                    if j > i and _match_ai(s, j) is not None:
                        break
                    j += 1
                value = s[i:j]
                i = j
        elements.append(Element(ai, value))
    return elements


def _mod10_check_digit(digits):
    """GS1 mod-10 check digit over the payload digits (excluding the check)."""
    total = 0
    weight = 3
    for ch in reversed(digits):
        total += int(ch) * weight
        weight = 1 if weight == 3 else 3
    return (10 - total % 10) % 10


def _valid_check_digit(digits):
    if not digits.isdigit() or len(digits) < 2:
        return False
    return int(digits[-1]) == _mod10_check_digit(digits[:-1])


def is_gs1(data, elements=None):
    """Best-effort GS1 DataMatrix detection.

    zxing-cpp does not expose the FNC1 position, so we use:
    - a GS/FNC1 separator in the raw bytes or the `<GS>` text marker;
    - otherwise a valid GTIN/SSCC/ITIP at the start (the common case for
      fixed-length-only GS1 symbols).
    A plain DataMatrix that happens to start with a valid GTIN is therefore
    classified as GS1; that is the only ambiguous case without FNC1 info.
    """
    if data is None:
        return False
    if isinstance(data, bytes):
        raw = data
        text = data.decode("latin-1")
    else:
        text = str(data)
        raw = text.encode("latin-1", "ignore")
    if b"\x1d" in raw or "\x1d" in text or "<GS>" in text:
        return True
    if elements is None:
        elements = parse(data)
    if not elements:
        return False
    first = elements[0]
    if first.ai in ("01", "02"):
        return len(first.value) == 14 and _valid_check_digit(first.value)
    if first.ai == "00":
        return len(first.value) == 18 and _valid_check_digit(first.value)
    if first.ai in ("8006", "8018"):
        return len(first.value) == 18 and first.value.isdigit()
    return False


def validate(elements):
    """Return a list of human-readable warnings for parsed GS1 elements.

    Checks unknown AIs, fixed-length fields, empty values, dates and the
    GTIN/SSCC mod-10 check digit. An empty list means no problems found.
    """
    warnings = []
    for el in elements:
        info = ai_info(el.ai)
        if info is None:
            warnings.append(f"Неизвестный AI {el.ai}")
            continue
        fixed = info[2]
        if not el.value:
            warnings.append(f"AI {el.ai}: пустое значение")
            continue
        if fixed is not None and len(el.value) != fixed:
            warnings.append(
                f"AI {el.ai}: ожидается {fixed} цифр, получено {len(el.value)}")
        if el.ai in _DATE_FORMATS:
            problem = _date_problem(el.value, _DATE_FORMATS[el.ai])
            if problem:
                warnings.append(f"AI {el.ai}: {problem}")
            elif el.ai in ("15", "16", "17"):
                expiry = _expiry_warning(el)
                if expiry:
                    warnings.append(expiry)
    for el in elements:
        if el.ai in ("01", "02") and len(el.value) == 14 and el.value.isdigit():
            if int(el.value[-1]) != _mod10_check_digit(el.value[:13]):
                warnings.append(
                    f"AI {el.ai}: неверная контрольная цифра GTIN")
        elif el.ai == "00" and len(el.value) == 18 and el.value.isdigit():
            if int(el.value[-1]) != _mod10_check_digit(el.value[:17]):
                warnings.append("AI 00: неверная контрольная цифра SSCC")
    return warnings


def _days_in_month(year, month):
    if month == 2:
        return 29 if _is_leap(year) else 28
    return [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]


def _date_parts(value, length):
    """(year, month, day, hour, minute) or None.

    GS1 allows DD=00 to mean "the last day of the month" for date fields.
    """
    if not value.isdigit() or len(value) != length:
        return None
    yy, mm, dd = int(value[0:2]), int(value[2:4]), int(value[4:6])
    if not 1 <= mm <= 12:
        return None
    year = 2000 + yy if yy < 50 else 1900 + yy
    days = _days_in_month(year, mm)
    if not 0 <= dd <= days:
        return None
    hour = minute = 0
    if length == 10:
        hour, minute = int(value[6:8]), int(value[8:10])
        if hour > 23 or minute > 59:
            return None
    return year, mm, dd, hour, minute


def _date_problem(value, length):
    """Return a Russian description if a GS1 date/time value is invalid."""
    if not value.isdigit() or len(value) != length:
        return None  # length is reported separately
    yy, mm, dd = int(value[0:2]), int(value[2:4]), int(value[4:6])
    if not 1 <= mm <= 12:
        return f"некорректный месяц в дате {value}"
    year = 2000 + yy if yy < 50 else 1900 + yy
    if not 0 <= dd <= _days_in_month(year, mm):
        return f"некорректный день в дате {value}"
    if length == 10:
        hh, mi = int(value[6:8]), int(value[8:10])
        if hh > 23 or mi > 59:
            return f"некорректное время в {value}"
    return None


def format_gs1_date(value, length):
    """'251231' -> '31.12.2025'; '2512312359' -> '31.12.2025 23:59'."""
    parts = _date_parts(value, length)
    if parts is None:
        return None
    year, month, day, hour, minute = parts
    if day == 0:
        day = _days_in_month(year, month)
    text = f"{day:02d}.{month:02d}.{year:04d}"
    if length == 10:
        text += f" {hour:02d}:{minute:02d}"
    return text


def _expiry_warning(el):
    """Warn when a best-before/sell-by/expiry date is past or imminent."""
    parts = _date_parts(el.value, 6)
    if parts is None:
        return None
    year, month, day, _hour, _minute = parts
    if day == 0:
        day = _days_in_month(year, month)
    try:
        expiry = datetime.date(year, month, day)
    except ValueError:
        return None
    today = datetime.date.today()
    shown = format_gs1_date(el.value, 6) or el.value
    if expiry < today:
        return f"AI {el.ai}: срок истёк ({shown})"
    if (expiry - today).days <= 30:
        return f"AI {el.ai}: истекает {shown}"
    return None


def _is_leap(year):
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)