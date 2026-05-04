# Records Layer

Операционная память ZTN. Records — это лёгкие поисковые логи рабочих встреч.

## Характеристики

- 1:1 с источником: одна встреча = один record
- Лёгкий формат: summary, key points, decisions, action items
- Ссылка на исходный транскрипт в `## Source` (оригинал в `_sources/processed/`)
- Не содержат рефлексии или аналитики
- Knowledge notes извлекаются отдельно, когда есть значимый инсайт

## Структура

```
_records/
├── meetings/
│   └── YYYYMMDD-meeting-{participants}-{topic}.md
└── observations/
    └── YYYYMMDD-observation-{topic}.md
```

Два kind'а:
- **meeting** — multi-speaker work meetings (см. `meetings/`)
- **observation** — solo Plaud transcripts: рефлексии, идеи, терапия (см. `observations/README.md`)

Якорь для knowledge notes: всегда wikilink на record-id, никогда на путь транскрипта.

## Отличие от Knowledge Notes

Records отвечают на вопрос: «Что обсуждали на встрече?»
Knowledge Notes отвечают на вопрос: «Что решили / поняли / осознали?»

См. `5_meta/CONCEPT.md` для полной архитектуры.
