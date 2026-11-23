# Задачи по доработке garmin-mcp

Размер: **S** — до часа, **M** — несколько часов, **L** — день и больше.
Контекст: `garminconnect` обновлён до 0.3.20, добавлены инструменты для событий и заметок календаря (164 инструмента).

## Этап 1. Технический долг

- [x] **S** Перенести `tool.uv.dev-dependencies` в `dependency-groups.dev` в `pyproject.toml` (предупреждение при каждом запуске `uv`)
- [ ] **S** Обновить `CLAUDE.md`: число инструментов (122 → актуальное), число модулей, `mcp>=1.23.0` → реальный диапазон из `pyproject.toml`
- [ ] **S** Решить судьбу `.claude/skills/babysit-prs/project.md`: закоммитить или откатить, чтобы рабочая копия была чистой
- [ ] **S** Решить, что делать с повторами GET в `garminconnect` 0.3.20 (до 3 попыток с паузами): оставить как есть, ограничить `retry_attempts` или описать в README, потому что `get_calendar_events` делает по запросу на событие

## Этап 2. Перевод сырых запросов на методы библиотеки

Сверено на живом аккаунте: ответы совпадают. Замена по одному месту с тестами.

- [ ] **M** `activity_management.py:561` → `get_activity_event_types`
- [ ] **M** `training.py:342` (поиск активностей) → `search_activities`
- [ ] **M** `training.py:277` (диапазон max metrics) → `get_max_metrics_range`
- [ ] **M** `gear_management.py:115` → `get_gear_list`
- [ ] **M** `courses.py` (чтение) → `get_courses`, `get_course`
- [ ] **S** `calendar_events.py:99` → `get_calendar_event`
- [ ] **S** `devices.py` (чтение сообщений) → `get_device_messages`
- [ ] **M** `health_wellness.py:371,613` → `get_daily_stats` с явным `current_date` (иначе отличаются средние в `aggregations`)
- Не менять: `challenges.py` на `get_user_goals`. Это другой эндпоинт, формат ответа другой.

Записывающие вызовы переводить по одному и с живой проверкой на тестовых данных:

- [ ] **M** `schedule_workout` (`workouts.py`, `workout_builders.py`)
- [ ] **M** `reschedule_workout` (`workouts.py`)
- [ ] **M** `import_course`, `delete_course` (`courses.py`)
- [ ] **M** `update_activity`, `set_activity_exercise_sets` (`activity_management.py`)
- [ ] **M** `update_heart_rate_zones` (`user_profile.py`), сверить формат с `heartRateZones/v2`

В библиотеке нет аналога, сырые вызовы остаются: весь `nutrition.py`, `food/logs/range` в `health_wellness.py`, `workouts.py:906` (`fbt-adaptive`), POST в `devicemessage`.

## Этап 3. Новые инструменты

### 3a. Календарь и тренировки

- [ ] **M** `move_calendar_item`: перенос тренировки или заметки на другую дату
- [ ] **S** `get_upcoming_events`, `get_primary_event`: ближайшие гонки и целевая гонка плана
- [ ] **M** `copy_workout`, `update_workout`
- [ ] **S** `get_next_scheduled_workout`
- [ ] **S** `send_scheduled_workouts_to_devices`

### 3b. Тренировочные планы

- [ ] **M** `search_training_plans`, `get_training_plan_by_id`
- [ ] **M** `get_active_training_plans`, `get_training_plan_tasks`
- [ ] **M** `schedule_training_plan`, `delete_training_plan` (с предпросмотром и `confirm`)

### 3c. Аналитика активностей

- [ ] **M** `get_activity_laps`, `get_fastest_splits`
- [ ] **M** `get_activity_polyline`, `get_activity_map_details`
- [ ] **M** `get_activity_swim_details`
- [ ] **M** Фильтры в поиске активностей: тип, даты, дистанция, текст

### 3d. Метрики формы

- [ ] **M** `get_running_economy` (+ `_range`), `get_stamina_curve`, `get_pace_bands`
- [ ] **S** `get_max_metrics_latest`
- [ ] **M** `get_daily_training_status`, `get_weekly_training_status`, `get_training_readiness_range`

### 3e. Снаряжение и курсы

- [ ] **M** `create_gear`, `update_gear`, `set_gear_status` (например, списать кроссовки)
- [ ] **M** `create_course`, `update_course`, `convert_activity_to_course`

### 3f. Здоровье (по необходимости)

- [ ] **S** `get_naps`
- [ ] **M** `get_ecg_list`, `get_health_snapshots`
- [ ] **M** Недельные и месячные сводки (`get_weekly_*_stats`, `get_monthly_wellness_stats`)

Для каждого нового инструмента:
валидация входа, `WriteTracker` для записи, аннотации в `tool_annotations.py`, профили в `tool_profiles.py`, пересборка dxt (`scripts/generate_dxt_tools.py` + zip), правка счётчика в `tests/unit/test_tool_annotations.py`, unit-тесты, живая проверка с самоочищающимися тестовыми данными.

## Этап 4. Качество

- [ ] **M** E2E-тесты записи в календарь (события и заметки) в `tests/e2e` за тем же гейтом, что у остальных; создают и сразу удаляют тестовые данные
- [ ] **M** Живая проверка изменения и удаления подписанных (Garmin-курируемых) гонок
- [ ] **S** Проверить, принимает ли Garmin `null` для очистки дистанции, времени старта и целевого времени; если да, добавить очистку в `update_calendar_event`
- [ ] **M** Описать в `CLAUDE.md` чек-лист добавления инструмента (аннотации, профили, dxt, счётчик в тесте)

## Этап 5. Апстрим (по желанию)

- [ ] **S** Решить, предлагать ли календарные инструменты в Taxuspt/garmin_mcp
- [ ] **M** Если да, разделить на два PR: обновление `garminconnect` (поднимает минимальный Python до 3.12) и инструменты календаря отдельно

## Порядок

Сначала этап 1 целиком, затем 3a. Этап 2 делать попутно, когда трогаете соответствующий модуль.
