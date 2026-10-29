"""«Добавить субсчёт…» on an account that is not a group: it becomes one first."""

from __future__ import annotations

AZ = {
    "Сделать счёт {code} группой": "{code} hesabını qrup et",
    "Счёт {code} станет группой. Его проводки, остатки и операции не меняются: "
    "они останутся на первом субсчёте. Назовите его — потом добавите следующие.": (
        "{code} hesabı qrup olacaq. Onun yazılışları, qalıqları və əməliyyatları dəyişmir: "
        "onlar birinci subhesabda qalacaq. Ona ad verin — sonra növbətiləri əlavə edərsiniz."
    ),
    "Счёт {code} станет группой, а сам он — её первым субсчётом. "
    "Назовите его — потом добавите следующие.": (
        "{code} hesabı qrup olacaq, özü isə onun birinci subhesabı. "
        "Ona ad verin — sonra növbətiləri əlavə edərsiniz."
    ),
    "Код субсчёта": "Subhesabın kodu",
    "Название субсчёта": "Subhesabın adı",
    "Сделать группой": "Qrup et",
    "Счёт {code} стал группой": "{code} hesabı qrup oldu",
    "счёт {code} уже группа": "{code} hesabı artıq qrupdur",
    "название субсчёта не может быть пустым": "subhesabın adı boş ola bilməz",
    "у субсчёта нужен свой код, не {code}": "subhesabın öz kodu olmalıdır, {code} yox",
    "счёт {code}: по счёту есть проводки, он не может стать группой так. Выберите в плане "
    "счетов «Добавить субсчёт…»: проводки останутся на первом субсчёте": (
        "{code} hesabı: hesab üzrə yazılışlar var, o belə qrup ola bilməz. Hesablar planında "
        "«Subhesab əlavə et…» seçin: yazılışlar birinci subhesabda qalacaq"
    ),
}
