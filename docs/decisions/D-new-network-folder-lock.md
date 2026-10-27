# D-new — Сетевая или облачная папка: без WAL, предупреждение и замок файла
Статус: принято
Дата: 2026-10-27

## Контекст
D25: живой `.gl` не открывают с сетевого или облачного диска и вдвоём. Но `db.connect`
всегда включал WAL, которого SQLite на сетевой ФС не держит (`-shm` там не общий), и
ничто не мешало второй копии программы открыть тот же файл.

## Решение
**Место файла узнаёт `company_file.place_of`:** Windows — UNC и сетевой диск
(`GetDriveTypeW`), POSIX — тип ФС точки монтирования из `/proc/mounts` (nfs, cifs/smb,
sshfs…), облако — по имени папки (OneDrive, Dropbox, Google Drive, iCloud, Yandex.Disk).
Там `connect` ставит `journal_mode = DELETE`, а «Bu gün» — янтарную плашку без окна.
**Замок `<файл>.gl.lock`** (`O_CREAT|O_EXCL`; PID, машина, пользователь) берёт
`Workspace.open` и держит до закрытия соединения; живой чужой — `FileInUseError`
«Файл компании уже открыт: машина, пользователь» и совет «только для просмотра» (D80);
умерший процесс этой машины — замок снимается, с другой машины — его удаляют руками
(текст ошибки говорит как). Черновики AI и API (короткая запись рядом) замок не берут.

## Последствия
Код: `infrastructure/company_file.py`, `db.journal_mode`/`when_closed`, `Workspace.open`,
`Session.file_place`, `home_page/page.py`. Тесты: `tests/test_network_folder.py`.
