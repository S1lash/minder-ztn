#!/usr/bin/env python3
"""Move previous-shape role directories aside and write the owner a hand-off.

Called by `018-roles-previous-shape-handoff.sh`. See that file's header for
why this preserves-and-guides rather than converting.

Deletes nothing. Idempotent. Every path is built with `pathlib`, every read
and write passes `encoding="utf-8"` explicitly — a Cyrillic role body decoded
through a Western Windows locale comes back as mojibake, and this file's whole
job is to hand the owner their own words back intact.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.portable import configure_std_streams  # noqa: E402

from _018_memory import PARKED_DIRNAME, inventory, repo_path, summary_ru  # noqa: E402


HANDOFF_NAME = "HANDOFF.md"
CONFIG_NAME = "config.yml"
ROLE_NAME = "role.md"


def is_previous_shape(d: Path) -> bool:
    """A role directory from the previous shape: has `config.yml`, no `role.md`.

    Both halves matter. Without the `config.yml` test this would sweep up any
    stray directory; without the `role.md` test it would move a CURRENT role
    that happens to sit beside an old config, which would take a working role
    offline.
    """
    return (d / CONFIG_NAME).is_file() and not (d / ROLE_NAME).is_file()


def find_previous(roles_root: Path) -> list:
    if not roles_root.is_dir():
        return []
    return sorted(
        (d for d in roles_root.iterdir()
         if d.is_dir() and not d.name.startswith("_") and is_previous_shape(d)),
        key=lambda p: p.name,
    )


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def scalar(config_text: str, key: str) -> str:
    """One top-level scalar out of the previous config, without needing PyYAML.

    Deliberately dumb: this runs during an update, on a config whose schema is
    gone, and a parse error here must not stop the owner learning where their
    roles went. A key it cannot find yields "" and the hand-off says so.
    """
    for line in config_text.splitlines():
        if line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip().strip("'\"")
    return ""


def git_ok(repo: Path, *args: str) -> bool:
    try:
        return subprocess.run(["git", "-C", str(repo), *args],
                              capture_output=True).returncode == 0
    except OSError:
        return False


def move(repo: Path, src: Path, dst: Path) -> str:
    """Move, preferring `git mv` so history follows. Never overwrites."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        # Never overwrite: something is already parked under this id, from an
        # earlier partial run. Leaving both is recoverable; merging them is not.
        return "LEFT IN PLACE — something is already parked under that name"
    tracked = git_ok(repo, "ls-files", "--error-unmatch", str(src / CONFIG_NAME))
    if tracked and git_ok(repo, "mv", str(src), str(dst)):
        return "moved (git mv — history follows)"
    src.rename(dst)
    return "moved"


def describe(role_dir: Path) -> dict:
    cfg = read_text(role_dir / CONFIG_NAME)
    tick = read_text(role_dir / "hooks" / "tick.md").strip()
    brief = read_text(role_dir / "brief.md").strip()
    return {
        "id": scalar(cfg, "id") or role_dir.name,
        "name": scalar(cfg, "name") or role_dir.name,
        "cadence": " ".join(x for x in (scalar(cfg, "cadence"),
                                        scalar(cfg, "cadence_anchor")) if x),
        "status": scalar(cfg, "status"),
        "tick": tick,
        "brief": brief,
        "memory": inventory(role_dir),
    }


def handoff_text(roles: list, base_name: str, tools_md: bool) -> str:
    out = []
    out.append("# Роли, собранные на прежней форме\n")
    out.append(
        "Обновление ничего у тебя не удалило. Эти роли целиком лежат рядом с этим\n"
        "файлом — но текущий движок их **не видит**: он ищет роль по `role.md`, а\n"
        "прежняя форма его не создавала. Поэтому `/ztn:role:list` их не покажет, и\n"
        "ни один ночной прогон их не запустит.\n")
    out.append(
        "**Почему не перенесли автоматически.** Текст ниже написан в словаре, которого\n"
        "больше нет (parts, ledger, staged acts). Перенесённый как есть, он поручил бы\n"
        "роли то, чего никто не реализует — она не упала бы, а начала бы импровизировать,\n"
        "и это хуже. Плюс главное: `writes:` — граница безопасности новой формы, а в\n"
        "прежней ей соответствия не было. Угадывать, куда роли можно писать, — ровно та\n"
        "догадка, которую нельзя делать за тебя.\n")
    out.append(
        "**Что делать — одна команда на роль:**\n\n"
        "```\n/ztn:role:add --from-previous {id}\n```\n\n"
        "Рядом с каждой ролью лежит план переноса. Расписание, имя и статус переезжают\n"
        "как есть. Куда роль может писать и какими секретами пользуется — предложено с\n"
        "обоснованием, тебе остаётся подтвердить или поправить. Твой текст задания\n"
        "консьерж **перепишет** в текущий вид, а не скопирует: он написан в словаре,\n"
        "которого больше нет, и дословный перенос заставил бы роль импровизировать.\n"
        "Спросит он только то, чего не может решить сам.\n"
        "\n"
        "**Память роли переезжает вместе с ней.** То, что роль наработала за месяцы —\n"
        "доска, чтения, вердикты, журнал решений, — лежит рядом и указано в её плане.\n"
        "Пересозданная роль садится на эту память, а не начинает с нуля.\n")
    out.append(
        "**Секреты переносить не надо — они уже перенеслись.** Хранилище то же самое,\n"
        "шифрование то же; переименовалась только переменная с ключом. Перенеси её\n"
        "ЗНАЧЕНИЕ в настройках своей рутины: `ZTN_SECRET_MASTER_KEY` → `ZTN_ROLES_KEY`.\n"
        "Если этого не сделать, роль упадёт в 07:00 с ошибкой доступа, похожей на\n"
        "испорченный токен.\n")
    out.append("---\n")

    for r in roles:
        out.append(f"## {r['name']}\n")
        mem = r["memory"]
        meta = []
        if r["cadence"]:
            meta.append(f"просыпалась: `{r['cadence']}`")
        if r["status"]:
            meta.append(f"статус был: `{r['status']}`")
        meta.append(f"файлы: `{repo_path(mem['directory'], base_name)}`")
        out.append(" · ".join(meta) + "\n")
        if mem["has_memory"]:
            counts = summary_ru(mem)
            out.append(
                "**Эта роль успела наработать память** — не только замысел, но и то, что\n"
                "она за месяцы собрала"
                + (f": {counts}.\n" if counts else ".\n"))
            # Every path below goes through the one converter, so what the owner
            # reads resolves from where they read it — the repository root.
            where = [f"`{repo_path(p['path'], base_name)}`" for p in mem["parts"]]
            if mem["rendered"]:
                out.append(
                    "\nЧитаемый срез — "
                    f"`{repo_path(mem['rendered']['path'], base_name)}`"
                    + (f"; данные под ним — {', '.join(where)}.\n" if where else ".\n"))
            elif where:
                out.append(f"\nДанные — {', '.join(where)}.\n")
            out.append(
                "\nЭто **переносится**: новая форма тоже держит память роли между\n"
                "запусками, и консьерж посадит пересозданную роль на неё, а не на\n"
                "пустое место. Иначе роль проснулась бы, забыв всё, что знала.\n")
        else:
            # Deliberately about the MEMORY, not about whether it ever ran. The
            # previous shape wrote empty part files on a tick that found nothing,
            # so «ни разу не запускалась» would be a false claim in exactly the
            # case that is hardest to check.
            out.append("Накопленной памяти нет — здесь только замысел.\n")
        if r["tick"]:
            out.append("\n**Что ты написал ей делать** (дословно, твоими словами):\n")
            out.append("```\n" + r["tick"] + "\n```\n")
        else:
            out.append("\nТекста задания в `hooks/tick.md` не нашлось.\n")
        if r["brief"]:
            out.append("\n**Стоячая заметка, которую ты к ней приложил:**\n")
            out.append("```\n" + r["brief"] + "\n```\n")
        out.append("")

    if tools_md:
        out.append("---\n")
        out.append("## `_system/registries/TOOLS.md`\n")
        out.append(
            "Твой реестр инструментов из прежней формы — тоже на месте, тоже твой, и\n"
            "тоже больше ничем не читается: текущая форма описывает инструмент словами\n"
            "внутри самой роли, отдельного реестра нет. Ничего делать не нужно; когда\n"
            "будешь пересоздавать роль, он пригодится как напоминание, к каким сервисам\n"
            "она ходила.\n")

    out.append("---\n")
    out.append(
        "Когда пересоздашь всё, что хотел, эту папку можно удалить целиком — руками, "
        "когда сам решишь.\n")
    return "\n".join(out)


def main(argv: list) -> int:
    # Owner text is not ASCII; std streams must not use the platform default.
    configure_std_streams()
    base = Path(argv[1]).resolve() if len(argv) > 1 else Path("zettelkasten").resolve()
    repo = base.parent
    roles_root = base / "_system" / "roles"
    parked_root = roles_root / PARKED_DIRNAME
    handoff = parked_root / HANDOFF_NAME

    pending = find_previous(roles_root)

    if not pending:
        if not handoff.is_file():
            print("[migration 018] No previous-shape roles — nothing to carry across.")
            return 0
        # Already parked — but possibly by an older copy of this migration, whose
        # hand-off did not mention the memory a role had built up at all. The
        # conversion plans beside it are rebuilt unconditionally on every run, so
        # they self-heal; the hand-off did not, and a generated file left saying
        # something no longer true is the same silence in a quieter form. Rebuild
        # it from the parked roles, which are the source it was written from.
        parked = [d for d in sorted(parked_root.iterdir())
                  if d.is_dir() and not d.name.startswith("_")]
        if parked:
            tools_md = (base / "_system" / "registries" / "TOOLS.md").is_file()
            refreshed = handoff_text([describe(d) for d in parked], base.name, tools_md)
            if refreshed != handoff.read_text(encoding="utf-8", errors="replace"):
                handoff.write_text(refreshed, encoding="utf-8")
                print(f"[migration 018] Already carried across — hand-off refreshed at "
                      f"{handoff.relative_to(repo)}")
                return 0
        print(f"[migration 018] Already carried across — see {handoff.relative_to(repo)}")
        return 0

    described = [describe(d) for d in pending]
    moved = []
    for d, info in zip(pending, described):
        how = move(repo, d, parked_root / info["id"])
        moved.append((info["id"], how))

    tools_md = (base / "_system" / "registries" / "TOOLS.md").is_file()
    parked_root.mkdir(parents=True, exist_ok=True)
    handoff.write_text(handoff_text(described, base.name, tools_md), encoding="utf-8")

    rel = handoff.relative_to(repo)
    lines = [
        "",
        "[migration 018] You had roles built on the previous shape.",
        "",
        f"  {len(moved)} role(s) carried across. NOTHING was deleted:",
    ]
    for rid, how in moved:
        lines.append(f"    - {rid} — {how}")
    lines += [
        "",
        "  The current engine finds a role by its `role.md`, which the previous",
        "  shape never wrote — so those roles were invisible rather than broken.",
        f"  They now sit under `{parked_root.relative_to(repo)}/`, out of the way.",
        "",
        f"  READ THIS: {rel}",
        "",
        "  It quotes back, in your own words, what each role was for — so you can",
        "  re-create it with /ztn:role:add in one conversation. They are NOT",
        "  converted automatically: the old text speaks a vocabulary that no longer",
        "  exists, and the new `writes:` boundary is a decision that is yours.",
        "",
        "  TO THE SESSION RUNNING THIS UPDATE — do not stop at printing this.",
        "  Finish the update first, then, in the same conversation:",
        "",
        f"    1. Read {rel} and say back, in one line per role, what each was for.",
        "    2. Offer to carry them across NOW, one at a time:",
        "",
        "           /ztn:role:add --from-previous {id}",
        "",
        "       Each has a plan beside it — `{id}.plan.json` — with what carries",
        "       over untouched, what is proposed with its reasoning, the old",
        "       assignment as raw material to REWRITE rather than paste, where the",
        "       memory the role built up still sits so it is carried in rather",
        "       than lost, and the",
        "       short list only the owner can settle. The concierge closes what it",
        "       honestly can and asks about the rest. Its three gates still apply:",
        "       a carried-across role earns no shortcut past any of them.",
        "    3. The owner may decline, or take one and leave the rest. That is a",
        "       complete outcome — the parked files are not going anywhere.",
        "    4. After each one, and once at the end, run:",
        "",
        "         python3 scripts/migrations/_018_selfcheck.py",
        "",
        "       It proves the parked data is still whole, that nothing previous-shape",
        "       was left in the live path, and that every re-created role validates.",
        "       Non-zero means stop and tell the owner what failed — do not paper",
        "       over it, and do not re-run the migration to «fix» it.",
        "",
    ]
    sys.stderr.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
