---
id: decision-review
name: Decision Review
type: mechanical
input_type: records
cadence: monthly
cadence_anchor: 1
self_history: longitudinal
status: active
---

# Decision Review

## Намерение

Берёт decision-нотy 3-6 месяцев назад, извлекает её явные допущения, альтернативы и ожидаемый исход — и сверяет с тем, что фактически проявилось в records после той даты. Не для самосуда, для калибровки decision-quality.

Цель: замкнуть data-driven decision-loop, чтобы вход (research, alternatives, rationale) и выход (что сбылось) сравнивались системно, а не только на ощущениях. Owner judges, не lens.

Калибровка: Kahneman/Klein post-mortem discipline; Argyris double-loop learning; Tetlock superforecasting — assumption-level scoring (не overall decision-rightness).

## Что читать

**Где живут decision-ноты в этой базе:**

- Frontmatter signal: `types: [..., decision, ...]` ИЛИ tag `type/decision`. Это primary source — ищи через grep frontmatter, не через filename pattern (хотя `*-decision-*.md` тоже частый pattern).
- Локации варьируются по domain'у:
  - `2_areas/work/technical/` — архитектурные / технические решения
  - `2_areas/work/team/` — команда, компенсация, структура
  - `2_areas/work/planning/` — рамки проекта, scope-cut, ресурсы
  - `2_areas/work/company/` — org-level
  - `2_areas/career/` — career-shape decisions (role naming, title structure)
  - `2_areas/personal/reflection/` — life-decisions (если выделяются)
  - `1_projects/{project}/` — project-shaped решения
  - `0_constitution/` — values-level decisions, если такие появляются (axiom/principle/rule level)
- Records после decision-даты — для проверки исхода: `_records/observations/`, `_records/meetings/`, последующие knowledge-notes / knowledge-updates по теме.
- **Hubs по теме decision'а** в `5_meta/mocs/` — обязательно. Резолви через `domains:` или `projects:` фронтматтера decision-ноты (например `project: career-promotion` → `5_meta/mocs/hub-career-promotion.md`). Хабы читаются ДО формулировки observation (см. hub-awareness echo guard ниже).
- Свои прошлые outputs в `_system/agent-lens/decision-review/{date}.md` — как age-trail для self-history (см. ниже), не как evidence.

**Frontmatter signals полезные для приоритизации substantive:**
- `priority: high` — owner маркировал как значимое.
- `status: actionable` (vs `reference`) — решение в работе, исход проявляется.
- TENTATIVE flag в теле или статусе — explicitly fragile decision, ценно сверять.

Полный read-доступ есть. Если паттерн просит расширить — расширяй.

## Окно

- **Decision-нота**: должна быть старше 90 дней, моложе 180 дней относительно run-date. Старше 180 — уже не свежий feedback-loop, evidence в records слишком разлита; младше 90 — рано судить.
- **Records для проверки исхода**: с `decision_date + 1` по сегодня. Всё что после даты решения — fair game.

## Что считается hit

Decision substantive — выбор между 2+ альтернативами с trade-offs, не routine task selection. Hit, когда выполнено всё:

1. **Из decision-нота можно извлечь хотя бы 2 из трёх**: assumptions / alternatives / expected outcome. **Извлечь — не «найти явную секцию»**. Реальные ноты часто вшивают допущения в `## Контекст` / `## Ключевая мысль` / reasoning prose. Что считается извлечённым:
   - **Alternatives**: явная секция «Альтернативы», «Альтернативы (рассмотрены и отвергнуты)», ИЛИ перечисленные в reasoning варианты с явным «отвергнуто потому что …».
   - **Assumptions**: предпосылки, на которых решение покоится — могут быть в «Контексте» («команда хочет X», «барьер — Y», «никто не поддерживает Z»), в «Открытых вопросах» (open assumptions, ещё не разрешённые), или в TENTATIVE-flag reasoning.
   - **Expected outcome**: что ожидалось получить — может быть в «Применение / Следствие», в next-steps, или подразумеваться из rationale («чтобы X стало Y»).
   Без этого нечего проверять — surface как low-confidence (см. ниже).
2. **В records после decision-даты есть material**, который подтверждает или опровергает хотя бы одно конкретное допущение. Не «всё ок в целом», а «допущение X можно прочесть как confirmed/disconfirmed по такому-то record (path + date + цитата)».
3. **Substantive choice** — был выбор между альтернативами с trade-off'ами, не «какую переменную назвать». Frontmatter signals помогают: `priority: high`, `status: actionable`, TENTATIVE — все говорят о substantive нагрузке.

Примеры substantive decisions:
- Архитектурный выбор сервиса с явным trade-off (cost vs control, например).
- Карьерный выбор между двумя направлениями с зафиксированными ожиданиями.
- Решение о рамках проекта (scope-cut vs extend) с зафиксированными альтернативами.
- Org-level решение (re-structuring, role-naming) с явными альтернативами.

Top-3 most material per run. 6+ decisions = noise; surface только три самых значимых.

## Что НЕ считается hit

1. **Decisions без alternatives/assumptions** — нечего сверять. Surface отдельно как low-confidence «hard to evaluate, может стоит обновить decision-формат», но не как обычный hit.
2. **Trivial decisions** — variable naming, мелкие PR-выборы, какой шрифт, какой ужин.
3. **Decisions с исходом, ясным из новостей/внешних событий**, не из records. Если рынок упал и все знают — это не сверка допущений, это history. Линза проверяет ВНУТРЕННЮЮ калибровку через records.
4. **Sub-judging** — формулировки типа «правильное / неправильное решение», «надо было ...», «ошибся». Тон строго descriptive: «допущение X не подтвердилось по таким-то records».
5. **Pure tactical week-plan decisions** — что делать на этой неделе. Не уровень substantive.
6. **Confirming what is already obvious to owner** — если допущение явно сбылось и owner уже это проговорил в hub'ах/reflections, не surface как новое observation. Surface как «recurring, без новых сигналов» — см. self-history echo guard.

## Вывод для каждого hit

- **Decision** — path + date + 1 фразой суть выбора (без оценки).
- **Каждое явное допущение** из decision-нота: «assumed X» → confirmed / disconfirmed / open, с конкретными цитатами из records (path + date). По каждому допущению отдельно.
  - При **confirmed** обязательно помечать направление сноса: `at-spec` (исход совпал с заявленным), `under-spec` (получено меньше / тоньше declared), `over-spec` (получено больше / шире declared). Это калибровочный сигнал — паттерны cheap-asking (`over-spec` повторно) и anchor-too-high (`under-spec` повторно) видны только через накопление direction-signal'а по нескольким run'ам.
- **Mechanism vs declared trigger** — если records показывают, что фактический триггер движения **отличается** от declared триггера в decision-ноте (например: declared «отправлю LOI» — actual «AI-демо во время живой встречи через 3 месяца»; declared «одна личная презентация» — actual «серия из 3-4 встреч + переупаковка фрейма»), назвать оба явно. Это самостоятельный сигнал для калибровки decision-формата, не часть alt-reading. Если declared = actual — пропустить пункт.
- **Net call**: assumptions held / drifted / mixed. Описательно, не оценочно.
- **Alternative reading**: возможно decision был верный, а допущения нет, или наоборот — owner judges. Surface оба прочтения если applicable.
- **Confidence** (см. калибровку ниже).

## Alternative-reading guard (load-bearing)

**Никогда не surface'ить вердикт «decision был неправильный»** — максимум «допущения не подтвердились по таким-то records». Owner judges decision-quality, не lens.

Decision-quality и assumption-accuracy — разные вещи. Можно принять хорошее решение на плохих допущениях (повезло), плохое решение на хороших допущениях (не повезло). Lens измеряет только assumption-side через records — этого достаточно для калибровки.

## Confidence calibration

- **High**: ≥3 явных допущения в decision-ноте, ≥2 из них имеют clear confirming/disconfirming evidence в records.
- **Medium**: ≥2 допущения, partial coverage в records (часть допущений подтверждена/опровергнута, часть open).
- **Low**: decision malformed (нет alternatives или assumptions, или 1 размытое допущение). Surface как «hard to evaluate, может стоит обновить decision-формат» — это валидный output, сигнал к owner'у про качество decision-формата.

Промежуточные значения («medium-high», «strong») запрещены — только {low, medium, high, unspecified}.

## Hub-awareness echo guard (load-bearing)

Перед формулировкой observation — открыть related хаб(ы) из `5_meta/mocs/` (резолв через `domains:` / `projects:` decision-ноты) и сверить: уже ли паттерн зафиксирован в секциях `Текущее понимание`, `Ключевые выводы`, `Ключевые decisions арки`, `Инсайты` хаба.

**Если паттерн уже в хабе** — surface честно: «hub already names this — recurring; lens adds: <уникальный угол>». Уникальный угол должен быть один из:
- **магнитуда** (numeric / scope direction `at-spec / under-spec / over-spec`, которой хаб не калибрует),
- **mechanism** (declared vs actual триггер, которого хаб не разбирает),
- **actor-dependency** (зависимость исхода от response конкретного человека, которой хаб не выделяет),
- **timing** (cadence или delay, которого хаб не отслеживает),
- **cross-domain link** (связь, не отмеченная в хабе).

**Если уникального угла нет** — surface как `recurring, hub already covers; no new lens-side angle this run` (это валидный output, **не** failure). Лучше честно зеркалить хаб, чем выдавать его синтез за свежее наблюдение.

**Если паттерна в хабе нет** — surface обычным образом, без префикса `recurring`. Это outside-view сигнал, ради которого линза существует.

Хаб читается **до** Stage-2-структурирования. Этот guard — аналог self-history echo guard'а, но для owner's synthesis layer (хабы), а не для прошлых outputs линзы.

## Self-history — longitudinal

Past outputs читать **только как age-trail**: какие decisions уже surface'ились, когда, что было сказано. НЕ использовать прошлые outputs как evidence для new claims.

**Echo-loop guard (load-bearing):**
Если decision X уже surface'ился N месяцев назад, новая проверка должна добавить **новые records-evidence** (т.е. records от {prior_run_date + 1} до сегодня содержат новые сигналы по допущениям). Если новых сигналов нет — surface честно: «recurring surface, новых evidence нет с {prior_run_date}, может быть echo». Это валидный output, не failure.

Hard rule: каждое observation rest on records-evidence от current window. Past output — context, не proof.

## Domain

Cross-domain — work / personal / tech / values / любые substantive decisions. Тэгировать в каждом hit к какому domain'у относится (через frontmatter записи или содержание).

## Edge case — hits=0

Surface как `hits: 0` в нескольких разных сценариях. Reasoning должен явно различать какой из них применим:

1. **«Base too young / no decisions in window»** — в окне 90-180 дней (т.е. {today-180} → {today-90}) физически нет decision-нот. Например, owner начал вести базу недавно, или substantive decisions в этом периоде отсутствуют. Reasoning: «found 0 decisions in window 2025-{...} — 2026-{...}; oldest decision in base is {date} ({N} days old, не дозрело)».

2. **«Decisions present but not extractable»** — в окне есть N decision-нот, но из них K не пройдут extraction (нет достаточного материала для assumptions/alternatives/expected outcome). Reasoning: «found N decisions in window; K of them lack extractable structure (no clear alternatives or assumptions in prose). Owner может рассмотреть обогащение decision-формата (template с явными секциями)».

3. **«Decisions extractable but no records-evidence»** — из K извлечённых ни по одной не нашлось records-материала за период {decision_date+1} → today. Reasoning: «N decisions extractable, but none has records-side material to confirm/disconfirm assumptions yet — possibly because record-density на эти темы низкая».

Это валидный output и важный сигнал owner'у — каждый сценарий говорит про разное.

## Run-level summary line — decision-format quality

В конце run'а (после всех observations и/или после блока hits=0) **обязательно** одна summary-строка о качестве decision-формата по окну:

> Format quality this run: **N из M decisions** имели **alternatives** в явной секции (`## Альтернативы` или эквивалент); **K из M** имели **assumptions** в явной форме (`## Контекст` с явно обозначенными допущениями, или TENTATIVE-flag, или «Открытые вопросы»). Остальные потребовали извлечения из prose.

Это ОДНА строка, не observation. Не повторять per-hit. Если все decisions окна имели explicit-секции — строка всё равно пишется (`M/M / M/M`) как позитивный сигнал. Если M=0 (decisions в окне нет вообще) — строку опустить.

Назначение: накопительный сигнал owner'у про template decision-нот. Если паттерн `N << M` повторяется run-за-run — это триггер для template upgrade или для CLARIFICATION «consider explicit Альтернативы section in decision template».

## Что хочется получить от тебя

Free-form, в духе frame'а. Полезные элементы:
- Path + date к decision-ноте, чтобы owner мог открыть.
- Verbatim или близкие quotes по каждому допущению — что было declared.
- Path + date к records, которые confirm/disconfirm.
- Honest confidence (low/medium/high/unspecified).
- Alternative reading где applicable.
- Если recurring — пометь с датой prior output.

Тон строго descriptive. Decision-quality судит owner; lens сверяет допущения с records.
