---
id: time-allocation
name: Time Allocation (computer-usage rhythm)
type: mechanical
input_type: records
output_schema: synthesis-custom
cadence: weekly
cadence_anchor: monday
self_history: longitudinal
status: active
---

# Time Allocation (computer-usage rhythm)

## Намерение

Surface **сдвиги в attention/focus-ритме** owner'а по computer-usage записям
(`_records/activity/{source}/`) и сравнить их с declared work-rhythm целями
(`SOUL.md` → Focus) и с предыдущим окном. Это behavioural-двойник
`energy-pattern`: та слушает affect в словах, эта — внимание в фактах
(switching, deep-work, ночной/утренний сдвиг, meeting-фрагментация).

Цель — **second-derivative сигнал**: не «он много переключается» (абсолют),
а «switching вырос относительно его baseline / прошлой недели», «deep-work
блоки исчезли», «работа сместилась в ночь сильнее обычного», «meeting-нагрузка
скакнула». Метрики уже посчитаны детерминированно (σ-baseline, streaks в самих
записях) — линза **нарративизирует** эти отклонения и связывает с целями и
телом, а не пересчитывает числа.

Калибровка:
- Gloria Mark (attention-fragmentation research) — стоимость переключения, не
  само переключение.
- Newport deep-work — длина непрерывного блока как ресурс, не сумма часов.
- Circadian alignment — сдвиг работы в ночь vs ранние часы как rhythm-сигнал,
  не «дисциплина».

## Чем питается линза (детерминированный субстрат)

Каждая дневная запись `_records/activity/{source}/<date>.md` уже несёт:
- `## Key Numbers` — **scores** `combined_score` / `productivity_score` /
  `focus_score` (0-100, Focus-Engineering headline); **focus** `sustained_focus_h`
  (сумма блоков ≥25м — это НЕ категория `deep_work`, а непрерывный фокус) /
  `longest_focus_block_min` / `focus_blocks_ge_25min`; **switching**
  `human_switches` / `human_switches_per_active_hour` (genuine фрагментация —
  AI-coding churn уже вычтена) + `context_switches` / `switches_per_active_hour`
  (сырой reference) + `ai_assisted_switch_share` / `ai_assisted_h` (контекст);
  **rhythm** `late_night_h` / `late_night_ratio` / `early_morning_h`;
  `meeting_h`; `work_h` / `personal_h` / `unclassified_h`; `top_category`;
  `top_death_loop` (топ attention-leak пара с verdict, уже посчитана коллектором);
  `distracting_loop_count`; `active_h`; `top_app`.
- `## Baseline Deviations` — что сегодня отклонилось от σ-baseline владельца
  (напр. `late_night_ratio 0.59 — +2.0σ strong`). **Это главный hit-субстрат.**
- `## Active Streaks` / `## Streak Transitions` — устойчивые серии
  (`late_night_work_streak`, `focus_drop_streak`, `low_productivity_streak`,
  `context_switch_spike_streak`, `fragmented_focus_streak`,
  `meeting_overload_streak`). Серия ≥3 дней — самый сильный сигнал. Имена
  концептов здесь **иллюстративны** — цитируй то имя, что реально стоит в записи;
  не подставляй имя из этого списка.

**Важно — секции условные.** `## Baseline Deviations` рендерится ТОЛЬКО в дни,
когда метрика отклонилась от σ-baseline; `## Active Streaks` — только когда есть
открытая серия; `## Streak Transitions` — только в день старта/обрыва. На
«спокойный» день этих секций в записи нет — и это **сигнал «в пределах baseline»,
НЕ дыра в данных**. Большинство дней их не имеют; не трактуй отсутствие как
пропуск. `## Key Numbers` есть всегда. Дни-кандидаты на hit — именно те немногие,
где Deviations/Streaks присутствуют.

Линза НЕ считает switching сама и НЕ грузит raw-события — она читает эти
готовые секции по дням окна. (Raw `_sources/.../raw/<date>.json.gz` — escape
hatch только для разбора одного конкретного инцидента, не для bulk-чтения.)

## Scope (load-bearing)

**Evidence-scope (источник hits):**
- `_records/activity/{source}/` за текущее окно — Key Numbers + Deviations +
  Streaks по дням. `{source}` — любой активный (сейчас `activitywatch`); читай
  все присутствующие.
- Past outputs `_system/agent-lens/time-allocation/` — как age-trail для
  shift-detection (НЕ как evidence для новых claims — см. echo-loop guard).

**Context-scope (baseline и cross-reference, НЕ evidence сам по себе):**
- `_system/SOUL.md` → секция `## Current Focus` (подсекции `### Work` /
  `### Personal`) + `## Working Style` — declared work-rhythm цели владельца
  (что он сам назвал проблемой/целью: switching, deep work, ночные часы,
  meeting-нагрузка — что бы там ни стояло). **Читай эти секции по точным
  заголовкам в рантайме, не предполагай содержание.** Hit относительно declared
  цели сильнее, чем hit без неё.
- `_records/biometric/{source}/` за ту же неделю — телесный ground-truth.
  Cross-ref: совпала ли ночная/switching-тяжёлая неделя с ухудшением
  `readiness` / `sleep_h` / `stress_avg`, или с biometric-streak? (Известное
  направление: высокая meeting-нагрузка → хуже REM той же/следующей ночью —
  проверь его явно.) n=1 caveats обязательны (ниже).
- `_records/observations/` и `_records/meetings/` той же недели — нарратив для
  тяжёлых дней (что было запланировано? что фрагментировало?). Журнальная
  фраза превращает «high switching» из числа в историю.
- `5_meta/mocs/` — хабы про deep work / focus / work-rhythm, если есть (uniqueness
  guard: уже ли паттерн отрефлексирован).

**НЕ scope:**
- Affect в словах — территория `energy-pattern`. Здесь — поведение.
- Содержимое titles/URL как сплетня («что он смотрел») — titles используются
  только чтобы назвать *тип* активности (deep-work-сессия / PR-review / meeting),
  не для пересказа. Записи `is_sensitive: true` — обращайся бережно.
- Абсолютные обвинения продуктивности, морализаторство, «надо меньше сидеть».

## Окно

- **Текущее окно**: 14 дней (последние две недели activity-записей).
- **Сравнение**: с предыдущим 14-дневным окном (через past lens outputs как
  age-trail) и с σ-baseline (он уже зашит в `## Baseline Deviations` записей).
- **Idle-дни исключаются из медиан/трендов.** День с `active_h < ~1ч` (Mac
  выключен / только телефон) — не «спокойный rhythm-день», а отсутствие данных.
  Отметь такие дни как idle, не считай их в медианах switching/late_night и не
  трактуй как сигнал (один 10-минутный день даст `late_night_ratio: 1.0` —
  артефакт, не паттерн). Baseline-движок их уже не кормит (gate `active_h<0.5`).

Полный read-доступ есть; если паттерн просит длиннее арку — расширяй.

## Что считается hit

1. **Deviation/streak в записях окна** — день(дни) с `## Baseline Deviations`
   или активной серией по focus/switching/rhythm-метрике (`focus_score` ↓,
   `productivity_score` ↓, `human_switches_per_active_hour` ↑, `sustained_focus_h` ↓,
   `late_night_ratio` ↑, `meeting_h` ↑). Цитируй запись (path + date) и
   отклонение verbatim (`focus_score 70 — −1.3σ light` / `late_night_ratio 0.59
   — +2.0σ strong`). Серия ≥3 дней — high-кандидат.
2. **Shift vs предыдущее окно** — метрика сместилась относительно прошлой недели
   (switching выше, deep-work-блоки исчезли, ночная доля выросла, meeting-часы
   скакнули). Сравнение через past outputs / baseline.
3. **Divergence (поведение vs журнал)** — журнал говорит «deep-work день / в
   потоке», а запись показывает 400+ switches и 0 deep-work-блоков (или
   наоборот). Surface как гипотезу о расхождении субъективного и измеренного.
4. **Goal-aligned move** — метрика сдвинулась В сторону declared цели (напр.
   `early_morning_h` вырос за окно, появились deep-work-блоки (`focus_blocks_ge_25min`),
   `late_night_ratio` упал, `focus_score` вырос). Это сдвиг трендов/Key Numbers
   (early_morning_h и sustained-focus НЕ σ-флагуются — слишком разрежены — так что
   читай их как тренд по окну, не как deviation). Прогресс — тоже сигнал.
5. **Biometric co-occurrence** — rhythm-сдвиг совпал с biometric-отклонением той
   же недели (ночная неделя ↔ низкий readiness; meeting-тяжёлый день ↔ хуже REM).
   Только как гипотеза, n=1.

## Что НЕ считается hit (anti-patterns)

1. **Абсолют без тренда** — «526 switches» сам по себе. Switching зависит от
   характера задач; важен сдвиг относительно собственного baseline, не число.
2. **Single-day выброс** без серии/паттерна — один фрагментированный день ≠
   тренд. Surface как «watching only».
3. **Switching внутри meeting'ов** — переключения во время созвона ожидаемы;
   in-scope — фрагментация focus-работы, не митингов.
4. **Inferred без метрики** — «наверное отвлекался» без отклонения в записи —
   гадание. Нужна цитата секции записи.
5. **Causation из co-occurrence** — «ночная работа УХУДШИЛА сон». n=1: только
   «ночная неделя co-occurs с низким readiness», never «вызвала».
6. **Морализаторство / диагноз** — «это выгорание», «надо ложиться раньше»,
   generic поп-продуктивность. Линза surface'ит, owner решает.
7. **Confirming declared без сдвига** — цель уже в SOUL и ничего не сдвинулось →
   «no shift, baseline confirmed», не hit.
8. **Echo-loop: прошлая гипотеза как evidence** — прошлый output назвал паттерн X,
   и тянет засчитать его hit'ом и на этой неделе. Сначала проверь: есть ли свежее
   `## Baseline Deviations` / streak по X в записях ТЕКУЩЕГО окна? Нет свежего
   отклонения — нет hit'а. Surface честно: «recurs in my outputs, но свежего
   deviation в записях этой недели нет — возможно echo, не сдвиг».

## Cross-reference с biometric (n=1 caveats — load-bearing)

Когда `_records/biometric/{source}/` непуст, проверяй co-occurrence rhythm-сдвига
с телом той же/следующей ночи. Per biometric-lens-protocol §n=1:
- Фразируй «activitywatch reports high late-night work, и Oura/Garmin reports
  low readiness ту же неделю», never «ночная работа ухудшила восстановление».
- Эффект-сайзы калиброваны под n=1; одна неделя co-occurrence — гипотеза, не
  вывод. **Counter-evidence И falsifier обязательны** в каждой biometric-гипотезе
  (в секциях `## Counter-evidence` и тексте гипотезы): «это НЕ держалось бы, если
  бы ночная неделя совпала с высоким readiness».
- **Confidence-gate**: гипотезы на biometric co-occurrence — максимум **medium**,
  пока тот же co-паттерн не подтверждён ≥2 consecutive windows.
- Если устройств несколько и метрика расходится — отметь дивергенцию, не
  усредняй.

## AI-assisted работа — switching ≠ фрагментация (уже в метрике)

Коллектор уже разделил переключения: **`human_switches` = настоящая
фрагментация** (продуктивный Browser↔Terminal churn AI-coding-сессий вычтен),
а `ai_assisted_*` — продуктивный deep-work-режим с агентом (Claude Code / Codex /
Aider). Поэтому σ-baseline и deviations стоят на `human_switches_per_active_hour`,
не на сыром счёте. Тебе НЕ нужно угадывать AI-сессии по titles — это сделано.

Как читать:
- Hit по фрагментации — это deviation/streak по `human_switches_per_active_hour`
  (high) или `focus_score` (low). Сырой `context_switches` высокий, но
  `ai_assisted_switch_share` большой (напр. 0.7) → объясни: «сырых переключений
  много, но 70% — AI-assisted deep work; настоящая фрагментация (`human_switches`)
  низкая — это продуктивный день, не leak». Это и есть anti-false-positive.
- `ai_assisted_h` высокий + высокий `productivity_score`/`focus_score` →
  AI-assisted глубокая работа; surface как сильную сторону, не проблему.

## Death loops (пара уже посчитана)

Коллектор выдаёт `top_death_loop` — топ attention-leak пару (verdict
`mixed`/`distracting`; productive и ai_assisted качели исключены) + `count`, и
`distracting_loop_count`. **Источник — YAML-поле `top_death_loop` в `## Key
Numbers`, НЕ prose-строка «Top death loop» в `## Summary`** — они могут
расходиться (prose = сырой топ-1 по счёту, включая ai_assisted; YAML = топ
именно leak-пары). Цитируй YAML, не prose, и НЕ выводи из titles.
**Narrate verdict as-is: `mixed` ≠ `distracting`.** Не повышай `mixed` до
«distracting leak» — высокий счёт `mixed`-пары это watch-сигнал, не приговор
«потраченное время». Owner мыслит «death loops» и в SOUL называет конкретную
пару-врага (читай её там в рантайме) — сопоставь `top_death_loop` с declared
парой (она может прийти как `mixed`, не апгрейди verdict ради нарратива).
Высокий `distracting_loop_count` или устойчивая та же пара через окна — сильный
сигнал.

## Circadian / boom-bust (owner-context, watch-list)

Owner — выраженный вечерний хронотип (поздние пики, declared цель сдвинуть deep
work в утро). Помимо late_night/early_morning-метрик, держи на радаре (как
longitudinal watch, не как single-week hit):
- **Circadian shift** — пики активности 22:00–03:00 при пустых 05:00–09:00.
- **Boom/bust** — продуктивная серия 3-5 дней (высокий deep_work / низкий
  late_night) с последующим crash-днём (минимум активности или резкий late_night).
  Это longitudinal-паттерн через past outputs, не вывод одной недели.
Surface как наблюдение + три чтения; без диагнозов («это ADHD/DSPD» — запрещено,
это его собственная рамка, не приговор линзы).

## Domain

`time` / `work` обе оси (запись несёт `domains: [time, work]`). Если rhythm-сдвиг
явно пересекается с personal-областью (напр. ночная работа съедает personal-время) —
отметь cross-domain явно, но не выдумывай.

## Вывод (output_schema: synthesis-custom)

Пиши финальный текст сам, без Stage-2 переформатирования. Структура:

```
## Week shape
1-2 предложения: switching-уровень, deep-work-наличие, ночь/утро-баланс,
meeting-нагрузка этой недели — числами из записей, с диапазоном дат.

## Facts
- {метрика}: {значение/отклонение verbatim} — [[_records/activity/{source}/<date>]]
  (по 1 строке на ключевой день/серию; путь + дата обязательны)

## Patterns
- {сдвиг или серия}, framed как vs-baseline / vs-prev-window / vs-SOUL-цель.
  Цитируй declared цель из SOUL если relevant.

## Hypotheses (ranked)
1. {сильнейшая} — с anchor на запись(и) + (если есть) biometric co-occurrence.
   Три чтения где applicable: (a) action gap (сдвиг против всё ещё важной цели),
   (b) baseline shift (норма поменялась — обнови ожидание/SOUL),
   (c) single-week episode (variance, watching only).
2. ...

## Counter-evidence
Что говорит ПРОТИВ каждой гипотезы (день, ломающий паттерн; альтернативное
объяснение; характер задач). Обязательно непусто, если есть ≥1 гипотеза.

## Suggested experiment
Один falsifiable шаг (напр. «две недели deep-work-блок до первого митинга —
вырастет ли longest_focus_block_min, изменится ли readiness»). Не предписание —
проверяемая ставка.

## Memory note (optional)
Только если сигнал силён и устойчив (серия ≥3 дней ИЛИ подтверждено ≥2
consecutive windows). Иначе опусти секцию.
```

Если 0 hits — пиши `hits: 0` с `## Reasons` и обязательным baseline-snapshot
(см. ниже). «No shift, rhythm baseline holds» — валидный output, не failure.

## Confidence

- **High**: серия ≥3 дней ИЛИ сдвиг подтверждён ≥2 consecutive windows, ≥1
  запись цитирована verbatim, (для biometric-гипотез) gate n≥10 пройден.
- **Medium**: устойчивый паттерн в текущем окне (deviation на ≥2 днях) или
  одно-оконный сдвиг без 2-window подтверждения.
- **Low**: single-day выброс / watching-only / цель уже baseline-confirmed.
- **Biometric co-occurrence**: максимум medium до подтверждения ≥2 consecutive
  windows; counter-evidence + falsifier обязательны (см. cross-reference выше).

Только {low, medium, high, unspecified}. Промежуточных нет.

## First-run protocol (load-bearing)

First-run детектится: нет prior outputs в `_system/agent-lens/time-allocation/`,
ИЛИ нет entries для `lens_id: time-allocation` со `status` ∈ {ok, empty} в
`agent-lens-runs.jsonl`. На first-run shift-detection невозможна by design
(нет prev окна). Hits>0 запрещены. Output — `hits: 0` с `## Reasons`,
содержащим:

```
### Baseline snapshot
(медианы — только по рабочим дням, idle `active_h<~1ч` исключить; ты считаешь
их по числам записей в уме — помечай как **приблизительные** (≈) и округляй, не
выдавай за точные расчёты)
**Scores:** медиана combined / productivity / focus_score — {N}/{N}/{N}; дни с focus_score deviation — {list или none}
**Switching:** медиана `human_switches_per_active_hour` — {N}; медиана `ai_assisted_switch_share` — {N}; дни с human-switch deviation — {list или none}
**Death loops:** топ повторяющаяся attention-leak пара за окно ({top_death_loop}) — {pair или none}; медиана distracting_loop_count — {N}
**Sustained focus:** дней с блоком ≥25м — {N}/{рабочих}; медиана longest_focus_block_min — {N}; дней с sustained_focus_h>0 — {N}
**Rhythm:** медиана late_night_ratio — {N}; дней с early_morning_h>0 — {N}; дни с late-night deviation — {list или none}
**Meetings:** медиана meeting_h — {N}; дней >2ч — {N}
**Active streaks at snapshot:** {none | list с датой старта}
**Biometric co-occurrence at snapshot:** {none | активные streaks/deviation-дни, у которых в тот же/следующий день есть biometric-отклонение — как seed для будущего falsifier, не как finding}
**SOUL-declared rhythm goals present:** {verbatim из `## Current Focus` (`### Work`/`### Personal`) + `## Working Style`, или «none declared»}
**Idle days excluded:** {none | даты с active_h<~1ч}
**Single-day episodes (watching only):** {none | date + 1-line}
```

+ «First run — baseline establishment, shift-detection inactive by design» и
echo-loop preventive note.

## Self-history — longitudinal

Past outputs `_system/agent-lens/time-allocation/{date}.md` — age-trail для
shift-detection (серия крепнет три недели подряд → high; только эта неделя →
episode). **НЕ использовать прошлые outputs как evidence** — только как timeline.

**Echo-loop guard (hard rule):** каждое observation стоит на verbatim секции
записи ИЗ текущего окна. Если в записях окна нет свежего отклонения по метрике —
нет hit'а, даже если прошлые outputs её обсуждали. Ловишь себя на повторе прошлого
вывода без свежей записи — surface честно: «recurs in my outputs, но свежего
deviation в записях этой недели нет — возможно echo, не сдвиг».

## Тон

Descriptive, факт-первый. Без морали, без диагнозов, без поп-продуктивности.
Числа и цитаты записей — да; приговоры — нет. Surface — owner judges.
