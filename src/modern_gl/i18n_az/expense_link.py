"""An expense of a batch says which purchase of goods it is for (D220)."""

AZ: dict[str, str] = {
    "К покупке": "Aid olduğu alış",
    "покупка не найдена: {text}": "alış tapılmadı: {text}",
    "строка {line}: к покупке относят расход, а не товар": (
        "sətir {line}: alışa mal yox, xərc aid edilir"
    ),
    "строка {line}: расход относят к другой покупке товара": (
        "sətir {line}: xərc başqa mal alışına aid edilir"
    ),
}
