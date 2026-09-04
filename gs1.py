"""GS1 Application Identifier parsing for GS1 DataMatrix content."""

# AI table: ai -> (name, description, length) where length is None for
# variable-length (terminated by FNC1 / GS separator or end of data).
AI_TABLE = {
    "00": ("SSCC", "Серийный код транспортной упаковки", 18),
    "01": ("GTIN", "Глобальный номер т.п.", 14),
    "02": ("CONTENT", "GTIN упаковки", 14),
    "10": ("LOT", "Номер партии", None),
    "11": ("PROD_DATE", "Дата производства", 6),
    "13": ("PACK_DATE", "Дата упаковки", 6),
    "15": ("BEST_BEFORE", "Срок годности", 6),
    "17": ("EXPIRY", "Срок годности", 6),
    "20": ("VARIANT", "Вариант продукта", 2),
    "21": ("SERIAL", "Серийный номер", None),
    "22": ("CPV", "Количество дополнительных продуктов", None),
    "240": ("ADDID", "Дополнительный идентификатор продукта", None),
    "241": ("CUSTNO", "Номер заказчика", None),
    "250": ("SECONDARY", "Вторичный серийный номер", None),
    "251": ("REF", "Ссылка на исходный документ", None),
    "30": ("COUNT", "Количество", None),
    "37": ("COUNT", "Количество", None),
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
    "91": ("KEY", "Ключ проверки", None),
}


class Element:
    def __init__(self, ai, value):
        self.ai = ai
        self.value = value
        info = AI_TABLE.get(ai, (ai, "", None))
        self.name = info[0]
        self.description = info[1]

    def display_name(self):
        if self.name in ("GTIN", "SERIAL", "KEY", "SG", "EXT"):
            return self.name
        return f"AI {self.ai}"


def parse(data):
    """Parse raw DataMatrix bytes into a list of Elements.

    `data` may be the raw bytes (with \\x1d GS separators) or the zxing HRI
    text like '(01)....(21)....'.
    """
    elements = []
    if data is None:
        return elements

    if isinstance(data, bytes):
        s = data.decode("latin-1")
    else:
        s = str(data)

    s = s.replace("\x1d", "").replace("\x1c", "").replace("\x1e", "")
    # Strip HRI parens if present
    if "(" in s and ")" in s:
        out = []
        i = 0
        while i < len(s):
            if s[i] == "(":
                j = s.find(")", i)
                if j == -1:
                    break
                out.append(s[i + 1:j])
                i = j + 1
            else:
                out.append(s[i])
                i += 1
        s = "".join(out)

    i = 0
    n = len(s)
    while i < n:
        ai = None
        for length in (2, 3, 4):
            if i + length <= n and s[i:i + length] in AI_TABLE:
                ai = s[i:i + length]
                i += length
                break
        if ai is None:
            # unknown AI prefix: try 2-digit
            if i + 2 <= n:
                ai = s[i:i + 2]
                i += 2
            else:
                break
        info = AI_TABLE.get(ai)
        fixed = info[2] if info else None
        if fixed is not None:
            value = s[i:i + fixed]
            i += len(value)
        else:
            # variable: read until next known AI or end
            j = i
            while j < n:
                nxt = None
                for length in (4, 3, 2):
                    if j + length <= n and s[j:j + length] in AI_TABLE and s[j:j + length] != ai:
                        nxt = s[j:j + length]
                        break
                if nxt is not None:
                    break
                j += 1
            value = s[i:j]
            i = j
        elements.append(Element(ai, value))
    return elements