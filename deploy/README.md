# deploy

Серверный запуск DataMatrix Verifier в Docker за существующим Caddy.

Предполагается, что на сервере уже работает Caddy в отдельном compose-проекте
(например, `deploy_default`) и его адрес задан в `SITE_ADDRESS`.

## Запуск

```bash
cd /opt/datamatrix/deploy
docker compose up -d --build
```

Контейнер `datamatrix` слушает `8501` и подключён к внешней сети
`deploy_default`. Если сеть называется иначе:

```bash
WEB_NETWORK=my_caddy_network docker compose up -d --build
```

## Caddy

Замените конфиг Caddy на `deploy/Caddyfile` (сначала сделайте резервную копию)
и перезагрузите Caddy:

```bash
docker exec deploy-caddy-1 caddy reload --config /etc/caddy/Caddyfile
```

Конфиг проксирует весь сайт на `datamatrix:8501`; старый статический лендинг и
`/api/*` больше не используются.

## Проверка

```bash
curl -fsS https://<домен>/api/version
curl -fsS -o /dev/null -w '%{http_code}\n' https://<домен>/
docker compose ps
docker compose logs --tail=100
```

Если контейнер не стартует, `docker compose logs datamatrix` покажет причину.
