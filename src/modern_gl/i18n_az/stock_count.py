"""«Инвентаризация»: a warehouse counted, the differences posted."""

AZ: dict[str, str] = {
    "Инвентаризация": "İnventarizasiya",
    "Инвентаризация · {w}": "İnventarizasiya · {w}",
    "Пересчитали склад: учёт подставлен, впишите факт — излишки и недостача проведутся сами": (
        "Anbar sayılıb: uçot yazılıb, faktiki miqdarı daxil edin — artıq və çatışmazlıq "
        "özü keçiriləcək"
    ),
    "«{item}»: на складе нет остатка, чтобы взять среднюю цену — укажите сумму излишков ({q})": (
        "«{item}»: orta qiyməti götürmək üçün anbarda qalıq yoxdur — artığın məbləğini "
        "göstərin ({q})"
    ),
    "не выбран счёт излишков — укажите его в настройках склада (Оприходование)": (
        "artıq üçün hesab seçilməyib — onu anbar ayarlarında göstərin (Mədaxil)"
    ),
    "факт совпадает с учётом — проводить нечего": "fakt uçotla eynidir — keçiriləcək bir şey yoxdur",
    "фактическое количество не может быть меньше нуля": "faktiki miqdar sıfırdan az ola bilməz",
    "укажите счёт, на который списать недостачу": "çatışmazlığın silinəcəyi hesabı göstərin",
    "Остатка нет — впишите, сколько стоят излишки": "Qalıq yoxdur — artığın dəyərini yazın",
    "впишите сумму": "məbləği yazın",
    "Учёт уже подставлен как факт — впишите количество там, где оно другое": (
        "Uçot fakt kimi yazılıb — miqdarı yalnız fərqli olan yerdə dəyişin"
    ),
    "Провести разницу": "Fərqi keçir",
    "Добавить товар…": "Mal əlavə et…",
    "Товар, которого по учёту на складе нет, а нашёлся": "Uçotda anbarda olmayan, amma tapılan mal",
    "Недостачу — на счёт": "Çatışmazlıq — hesaba",
    "Разница инвентаризации проведена": "İnventarizasiya fərqi keçirildi",
    "Факт совпадает с учётом": "Fakt uçotla eynidir",
    "Излишки: {n} на {sum}": "Artıq: {n}, {sum}",
    "Недостача: {n} на {sum}": "Çatışmazlıq: {n}, {sum}",
    "По учёту": "Uçot üzrə",
    "Факт": "Fakt",
    "Сумма разницы": "Fərqin məbləği",
    "Оприходование излишков №{n}": "Artığın mədaxili №{n}",
    "Списание недостачи №{n}": "Çatışmazlığın silinməsi №{n}",
}
