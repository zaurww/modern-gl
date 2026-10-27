"""A company file on a network or cloud folder, and the lock that keeps a second copy of
the program out (D-new-network-folder-lock)."""

AZ: dict[str, str] = {
    "Файл открыт с сетевой или облачной папки — работает медленнее, двоим одновременно открывать нельзя": "Fayl şəbəkə və ya bulud qovluğundan açılıb — daha yavaş işləyir, iki nəfər eyni vaxtda aça bilməz",
    "Файл компании уже открыт: {host}, {user}. Двоим одновременно работать в одном файле нельзя — откройте его «только для просмотра» (меню компании → «Открыть для просмотра…»). Если программа там закрыта, удалите файл «{lock}» рядом с «{file}»": "Şirkət faylı artıq açıqdır: {host}, {user}. İki nəfər eyni vaxtda bir faylda işləyə bilməz — onu «yalnız baxış üçün» açın (şirkət menyusu → «Baxış üçün aç…»). Proqram orada bağlıdırsa, «{file}» yanındakı «{lock}» faylını silin",
    "Файл компании открывается другой программой — повторите": "Şirkət faylı başqa proqram tərəfindən açılır — təkrar edin",
}
