# Claude Code — Setup Prompt for minder-ztn

Скорми этот документ своему Claude Code вместе с путём до клона
`minder-ztn`. CC выполнит установку одной командой и отчитается.

Установка полностью автоматизирована: `install.sh` рендерит шаблоны,
делает симлинки в `~/.claude/{rules,commands,skills}/` и сам подключает
нужные `@`-импорты в `~/.claude/CLAUDE.md` через managed block (с
бэкапом). Идемпотентно — повторный запуск после `git pull` обновляет
блок на месте.

---

## Вход

`<MINDER_ZTN_PATH>` — абсолютный путь до клона репозитория `minder-ztn`
(содержит `zettelkasten/`, `integrations/claude-code/`, `scripts/`).

Если не передан — спроси и остановись.

---

## Что сделать

1. **Проверить клон.** Убедиться, что `<MINDER_ZTN_PATH>` существует и
   это git-репозиторий с `integrations/claude-code/install.sh` и
   `zettelkasten/_system/`. Если нет — остановиться, сообщить.

2. **Запустить установщик:**
   ```bash
   bash <MINDER_ZTN_PATH>/integrations/claude-code/install.sh
   ```
   Показать вывод пользователю. Если упал — отдать stderr, не чинить
   вслепую.

3. **Smoke test** — кратко выполнить и сообщить:
   - `ls -la ~/.claude/rules/ztn.md ~/.claude/skills/ztn-process` — проверить, что симлинки живые.
   - `git -C <MINDER_ZTN_PATH> pull --rebase --autostash` — убедиться, что pull работает (если remote настроен).
   - Проверить, что в `~/.claude/CLAUDE.md` появился managed block с `<!-- MINDER-ZTN BEGIN ... -->`.

4. **Финальный отчёт:**
   - Что установилось, где бэкап (если был).
   - Подсказать пользователю **перезапустить Claude Code / открыть новую сессию**, чтобы правила подхватились.
   - Если SOUL.md или другие derived views ещё не сгенерены — упомянуть, что после первого batch стоит прогнать `/ztn:regen-constitution`.

---

## Что устанавливается (для информации, не делать руками)

`install.sh` создаёт в `~/.claude/`:

**Rules** (auto-loaded через managed block в `~/.claude/CLAUDE.md`):
- `ztn.md` — search triggers (reactive + narrow proactive) + `/ztn:check-decision` discovery
- `constitution-capture.md` — глобальный capture-hook (4 узких триггера)
- `constitution-core.md` — derived view конституции (аксиомы / принципы / правила)

**Rules** (симлинки, on-demand, не auto-loaded):
- `ztn-engine-doctrine.md` — operating philosophy движка; читается скиллами

**Commands:** `ztn-search`, `ztn-recap`

**Skills:** `ztn:agent-lens-add`, `ztn:agent-lens`, `ztn:bootstrap`,
`ztn:capture-candidate`, `ztn:check-content`, `ztn:check-decision`,
`ztn:lint`, `ztn:maintain`, `ztn:process`, `ztn:regen-constitution`,
`ztn:resolve-clarifications`, `ztn:save`, `ztn:sync-data`, `ztn:update`

---

## Откат

```bash
bash <MINDER_ZTN_PATH>/integrations/claude-code/uninstall.sh
```

Снимает только то, что поставил `install.sh`: симлинки, указывающие в
этот репозиторий, и managed block в `~/.claude/CLAUDE.md`. Бэкапы под
`~/.claude/.minder-ztn-backup-*` сохраняются.

---

## Если что-то идёт не так

- Установка упала → показать stderr, проверить права на `~/.claude/`
  и `<MINDER_ZTN_PATH>`. Не запускать повторно вслепую.
- Симлинки не подхватились → перезапустить CC.
- Скилл `/ztn:*` не находится → проверить `ls ~/.claude/skills/`. Если
  пусто — `install.sh` упал молча, перезапустить через `bash -x`.
- `git pull` ругается на divergent branches → не чинить, отдать
  пользователю.

Никаких деструктивных действий без подтверждения: `rm -rf`, `git reset
--hard`, `--force` push, удаление бэкапов.
