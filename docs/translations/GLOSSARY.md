# Translation glossary

Terms used in the Anchorage interface and how each catalogue translates them. New strings follow this table; change a term here first, then in every catalogue.

Never translated: Docker, Docker Engine, Compose, docker-py, Anchorage, API, ID, TTY, CLI, PATH, IPv6, ingress, command lines and file paths. "Engine" in the status bar and sidebar ("Engine 27.1", "Engine: not connected") is the product name and stays as is.

## Docker objects

| English | Russian | German | Spanish | French | Chinese (Simplified) |
|---|---|---|---|---|---|
| container | контейнер | Container | contenedor | conteneur | 容器 |
| image | образ | Image (das) | imagen | image | 镜像 |
| volume | том | Volume (das) | volumen | volume | 卷 |
| network | сеть | Netzwerk | red | réseau | 网络 |
| Compose project | проект Compose | Compose-Projekt | proyecto de Compose | projet Compose | Compose 项目 |
| service (Compose) | сервис | Dienst | servicio | service | 服务 |
| standalone (group of containers outside Compose) | Без проекта | Einzelcontainer | Independientes | Autonomes | 独立容器 |
| repository | репозиторий | Repository | repositorio | dépôt | 仓库 |
| tag (image) | тег | Tag | tag | tag | 版本 |
| label | метка | Label | etiqueta | étiquette | 标签 |
| digest | дайджест | Digest | digest | digest | 摘要 |
| layer | слой | Schicht | capa | couche | 层 |
| mount | монтирование | Einhängepunkt | montaje | montage | 挂载 |
| mountpoint | точка монтирования | Einhängepunkt | punto de montaje | point de montage | 挂载点 |
| driver | драйвер | Treiber | controlador | pilote | 驱动 |
| scope | область | Bereich | ámbito | portée | 范围 |
| subnet | подсеть | Subnetz | subred | sous-réseau | 子网 |
| gateway (gw) | шлюз | Gateway | puerta de enlace | passerelle | 网关 |
| dangling image | образ без тегов | Image ohne Tag | imagen sin tag | image sans tag | 虚悬镜像 |

## Actions

| English | Russian | German | Spanish | French | Chinese (Simplified) |
|---|---|---|---|---|---|
| start | запустить | starten | iniciar | démarrer | 启动 |
| stop | остановить | stoppen | detener | arrêter | 停止 |
| restart | перезапустить | neu starten | reiniciar | redémarrer | 重启 |
| remove | удалить | entfernen | eliminar | supprimer | 删除 |
| force remove | удалить принудительно | Entfernen erzwingen | forzar eliminación | forcer la suppression | 强制删除 |
| prune (button, confirmation) | очистить | bereinigen | limpiar | nettoyer | 清理 |
| prune unused (toolbar, one source per page so adjectives agree) | удалить неиспользуемые | Ungenutzte entfernen | eliminar no usados/as | supprimer les inutilisé(e)s | 清理未使用 |
| pull | загрузить | herunterladen | descargar | télécharger | 拉取 |
| refresh | обновить | aktualisieren | actualizar | actualiser | 刷新 |
| filter | фильтр | filtern | filtrar | filtrer | 筛选 |
| open shell | открыть оболочку | Shell öffnen | abrir shell | ouvrir un shell | 打开 Shell |
| copy | копировать | kopieren | copiar | copier | 复制 |
| dismiss | закрыть | schließen | cerrar | fermer | 关闭 |
| retry | повторить | erneut versuchen | reintentar | réessayer | 重试 |
| clear (log view) | очистить | leeren | borrar | effacer | 清空 |

## Container states

Shown through `anchorage.ui.theme.state_text`; logic keeps the raw Docker state, unknown states are shown raw.

| Docker state | Russian | German | Spanish | French | Chinese (Simplified) |
|---|---|---|---|---|---|
| created | создан | erstellt | creado | créé | 已创建 |
| running | работает | läuft | en ejecución | en cours d'exécution | 运行中 |
| paused | приостановлен | pausiert | en pausa | en pause | 已暂停 |
| restarting | перезапускается | startet neu | reiniciando | en redémarrage | 重启中 |
| removing | удаляется | wird entfernt | eliminando | en suppression | 删除中 |
| exited | завершён | beendet | finalizado | arrêté | 已退出 |
| dead | неисправен | defekt | defectuoso | défaillant | 已失效 |

## Health check states

Shown through `anchorage.ui.containers.details_tree.health_text`; unknown values are shown raw.

| Docker health | Russian | German | Spanish | French | Chinese (Simplified) |
|---|---|---|---|---|---|
| healthy | в норме | gesund | saludable | sain | 健康 |
| unhealthy | не в норме | ungesund | no saludable | non sain | 不健康 |
| starting | запускается | startet | iniciando | en démarrage | 启动中 |
| none | нет | keiner | ninguno | aucun | 无 |

## Interface and system terms

| English | Russian | German | Spanish | French | Chinese (Simplified) |
|---|---|---|---|---|---|
| logs | логи | Logs | registros | journaux | 日志 |
| stats | статистика | Statistik | estadísticas | statistiques | 统计 |
| details | подробности | Details | detalles | détails | 详细信息 |
| settings | настройки | Einstellungen | configuración | paramètres | 设置 |
| socket | сокет | Socket | socket | socket | 套接字 |
| daemon | демон | Daemon | daemon | démon | 守护进程 |
| engine (generic) | Docker Engine | Docker Engine | Docker Engine | Docker Engine | Docker Engine |
| backend | бэкенд | Backend | backend | backend | 后端 |
| native (backend) | встроенный | nativ | nativo | natif | 原生 |
| terminal | терминал | Terminal | terminal (la) | terminal | 终端 |
| command | команда | Befehl | orden (CLI), comando (inspect field) | commande | 命令 |
| environment | окружение | Umgebung | entorno | environnement | 环境变量 |
| health | работоспособность | Health-Status | estado de salud | santé | 健康状态 |
| restart policy | политика перезапуска | Neustartrichtlinie | política de reinicio | politique de redémarrage | 重启策略 |
| exit code | код выхода | Exit-Code | código de salida | code de sortie | 退出码 |
| follow (logs) | следить | folgen | seguir | suivre | 跟踪 |
| timestamps | время | Zeitstempel | marcas de tiempo | horodatage | 时间戳 |
| stream (log) | поток | Stream | flujo | flux | 流 |
| system default (language) | как в системе | Systemstandard | idioma del sistema | langue du système | 跟随系统 |
| language | язык | Sprache | idioma | langue | 语言 |

## Style

- Russian: imperative verbs on buttons («Удалить»), nouns for dialog titles («Удаление образа»), «ё» is written. Counts use three plural forms.
- German: formal «Sie», short forms in buttons and column headers, nouns capitalised, compounds with a hyphen after a product name («Compose-Projekt», «Docker-Socket»).
- Spanish: formal «usted», «¿…?» in questions, «Intro» and «Mayús» for keys.
- French: a non-breaking space (U+00A0) before «?», «:», «;» and «!»; «Entrée» and «Maj» for keys.
- Chinese: full-width punctuation (，：？（）。), a space between Chinese and Latin words or numbers, «个» as the measure word in counts, one plural form.
- Upper-case section headings in the source (USED BY, CPU, MEMORY) stay upper case in alphabets that have case.
