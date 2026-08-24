# YaVolna

**Свой «дневной микс» для Яндекс Музыки.** Утилита собирает один длинный плейлист
(по умолчанию 48 часов) из ваших лайков и свежих рекомендаций, специально чередуя
музыкальные стили, вместо того чтобы час держаться одного жанра.

Провайдер предлагает кандидатов — **порядок выбирает YaVolna.**

Полная документация: [README.md](README.md) (на английском). Ниже — быстрый старт.

## Установка

```bash
git clone https://github.com/demidov-alexander/ya-volna.git
cd ya-volna
python -m venv .venv
source .venv/bin/activate
pip install -e .

cp .env.example .env                # сюда токен
cp config.example.yaml config.yaml  # сюда настройки
```

## Токен

> YaVolna работает через **неофициальный API** Яндекс Музыки. Токен даёт полный доступ к
> музыкальному аккаунту — храните его как пароль. Использование неофициальных клиентов
> может противоречить условиям сервиса; вы делаете это на свой риск.

Откройте в браузере под своим аккаунтом:

```
https://oauth.yandex.ru/authorize?response_type=token&client_id=23cabbbdc6cd418abb4b39c32c41195d
```

После подтверждения в адресной строке будет `#access_token=<ТОКЕН>`. Скопируйте его в `.env`:

```env
YANDEX_MUSIC_TOKEN=y0_ваш_токен
```

Проверка:

```bash
yavolna auth-check
```

## Первый запуск

```bash
yavolna generate --dry-run   # всё посчитать и выгрузить в JSON, ничего не меняя
yavolna inspect-library      # статистика по лайкам
yavolna inspect-clusters     # размеры кластеров и примеры треков
yavolna generate             # создать/обновить плейлист
```

Без аккаунта можно посмотреть работу на синтетической библиотеке:

```bash
yavolna --provider fake generate --dry-run
```

## Один плейлист или новый каждый день

```yaml
playlist:
  mode: "replace"    # один плейлист, содержимое перезаписывается каждый запуск
  # mode: "daily_new"  # новый плейлист на каждый день, с датой в названии
  daily_name_template: "{name} {date}"
  date_format: "%Y-%m-%d"
  keep_daily_playlists: 7   # сколько дневных плейлистов хранить; 0 — не удалять никогда
```

Удаление старых плейлистов по умолчанию выключено и затрагивает только те плейлисты,
которые создала сама YaVolna (они записаны в локальной базе). Плейлисты, созданные
вручную, не трогаются никогда.

Разово можно переопределить режим: `yavolna generate --mode daily_new`.

## Основные настройки

```yaml
playlist:
  target_duration_hours: 48   # целевая длительность
mix:
  familiar_ratio: 0.65        # доля знакомых (залайканных) треков
  discovery_ratio: 0.35       # доля новых; сумма должна быть равна 1.0
repetition:
  track_cooldown_days: 10     # через сколько дней трек может вернуться
  same_artist_gap_tracks: 20  # минимальная дистанция между треками одного артиста
  same_album_gap_tracks: 40
  same_cluster_gap_tracks: 3  # именно это чередует стили
```

Полный справочник по всем параметрам — в [README.md](README.md#configuration-reference),
аннотированный пример — в [`config.example.yaml`](config.example.yaml).

## Расписание

```cron
0 4 * * * cd /opt/ya-volna && .venv/bin/yavolna generate >> /var/log/yavolna.log 2>&1
```

Готовые unit-файлы для systemd — в [`docs/systemd`](docs/systemd).

## Приватность

Данные библиотеки не покидают вашу машину (кроме запросов к самой Яндекс Музыке). Токен
берётся из переменных окружения или `.env` и никогда — из `config.yaml`. Логи проходят
через фильтр, который вырезает токены, cookie и заголовки `Authorization`.

## Лицензия

[MIT](LICENSE). Проект не связан с Яндексом и не поддерживается им.
