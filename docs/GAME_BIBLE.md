# BAR OF EXILE — GAME BIBLE

> **Единственный справочник проекта.** Самодостаточный: механика, данные, лор, история, грабли.
> Дневник «что делаем сейчас» — в `ROADMAP.md` (корень проекта).
> **Источник правды — всегда КОД НА ДИСКЕ.** Этот файл может отставать; при конфликте верь коду и правь этот файл.
> Последняя полная сверка с кодом: **18.07.2026** (70 тестов passed, `_test_integration.py` ALL OK).

---

# 0. TL;DR ДЛЯ СТАРТА СЕССИИ

- **Что это:** idle hack-and-slash ARPG в полоске ~64px над таскбаром Windows. TBH-формат + глубина PoE/D2.
- **Стек:** Python 3.11+, PyQt6, Windows. Логика 20 TPS (TICK_DT=0.05), рендер ~30 FPS.
- **Запуск:** `python main.py` из корня. Главный смоук: `python _test_integration.py` → должен быть **ALL OK**.
- **Язык игры:** английский (UI/контент). Общение о разработке: русский.
- **Корень:** `C:\Users\cubi7\Desktop\Claude\bar-of-exile`.
- **Где что:** `game/` = логика, `ui/` = PyQt6, `data/*.json` = данные (только грузить), `assets/` = нарезанные спрайты (не резать), `saves/` = сейвы, `tests/` = юнит-тесты, `новый приколы/` = склад паков от Fable/Opus (беречь).
- **SAVE_VERSION = 5** (skills_v2 блок). Миграция v4→v5 = сброс скиллов на дефолт (очки/уровень/шмот целы).

---

# 1. ЖЕЛЕЗНЫЕ ПРАВИЛА / БИНДИНГИ (не менять)

1. **Формула урона:** `(base + Σflat) × (1 + Σinc/100) × Π(1 + more/100)`. more-бакет через `StatMod.more`.
2. **Pity гэмбла:** 0.006 база / soft@73 / +12%/ролл до 79 / hard 100% на 80. Не менять.
3. **Никакого** energy shield и str/dex/int (констрейнт пака Opus).
4. **Атлас** влияет только на мир/лут/экономику, не на статы героя.
5. **id статов и id скиллов не менять** — на них завязаны иконки, сейвы, coverage-тест.
6. **Ассеты уже нарезаны** — не резать заново, смотреть только `manifest.json`.
7. **Данные `data/*.json`** — только грузить, не генерить заново (кроме как через существующие детерминированные генераторы в `tools/`).
8. **Лор-канон** (§9) — имена не менять.
9. **Один шаг = одна сессия → `_test_integration.py` зелёный → юзер тестит → следующий шаг.** (Юзер иногда снимает это правило ради скорости — см. ROADMAP.)
10. **`game/*` не импортирует `ui/*`.** Смоук-ассерты размеров арта — через `>=`, не `==`.
11. **main.py и window.py — только main-сессия.** Агентам не трогать.

---

# 2. АРХИТЕКТУРА

## game/ (чистая логика, без Qt)
| Файл | Что внутри |
|---|---|
| `core.py` | Общие типы: `Stats`, `StatMod`, `Item`, `Affix`, `Hero`, `Monster`, `Rarity`, `CombatEvent`. Все импортируют ТОЛЬКО отсюда + stdlib. Поля `hero.skills_v2:dict`, `hero.skill_runes:dict`, `hero.flags`, `hero.passives`, `hero.stash`. |
| `combat.py` | Тиковый бой: сближение, атаки по КД, крит, броня/резисты, cleave для melee, проджектайлы дальников, ailment-тики. `_hero_strike`, `_strike_damage()`. Автоатака = primary-скилл (единственный источник урона primary). |
| `skills_v2.py` | **АКТУАЛЬНЫЙ движок скиллов** (data-driven, 80 скиллов). API §5.8. Урон через `game.combat_math._deal`. |
| `combat_math.py` | Общие боевые примитивы (`_deal`/`_heal`/крит/leech/kill-hooks), реюзаются авто-атакой (combat.py) И skills_v2. Импортит только core+ailments (без циклов). |
| `tomes.py` | S.5 Skill Tomes — логика дропа/чтения. НЕ подключён к main. |
| `rifts.py` | 6.6 бесконечные рифты — строит Zone-объекты. НЕ подключён к main/UI. |
| `tree.py` | Дерево пассивок (passives_v2.json, 1002 ноды). allocate/deallocate/path_to/rebuild. Кейстоун-флаги дерева. |
| `classes.py` | 5 классов: базовые статы + рост/уровень. |
| `world.py` | Зоны (19 зон, 4 акта), MonsterTemplate, Spawner, `kills_to_boss(act,pos)`, `mob_life_mult/mob_dmg_mult`, интеграция zone_mods. |
| `progression.py` | XP-кривая Stage 6.1 (`xp_to_level`, `zone_xp_mult`), `grant_xp` (single-source xp_gain_inc), сложности, анлок зон. Uncapped leveling. |
| `save.py` | JSON сейв/лоад, SAVE_VERSION=5, `offline_progress` (OFFLINE_TIERS), миграция аффиксов, `ensure_skills_v2` при load. |
| `loot.py` | Дроп-таблицы, `make_item`→ItemRoller, DROP_CHANCE=0.10 (Stage 6.2), overflow-логика. |
| `item_roller.py` | ItemRoller (пайплайн spec 1.2), RARITY_WEIGHTS {N100/M55/R8}, tier bias, smart loot 25%. |
| `affixes.py` | Пул аффиксов (легаси; вытеснен affixes_v2.json). |
| `statmap.py` | Маппинг v2/v3-статов (id из data) → StatMod. coverage-тест держит ноль инертных. |
| `ailments.py` | ignite/bleed/poison/freeze/shock/stun. Интегрирован в combat. |
| `items.py` | 36 баз предметов (оружие/броня/jewelry), имплиситы, class_req. |
| `uniques.py` | 29 UniqueDef (16 старых + 13 opus). `special`-эффекты частью инертны. |
| `cube.py` | Куб-крафт, 5 рецептов. |
| `vendor.py` | Вендор (STOCK_SIZE=8, рестоки, цена=item_value×4, buyback). |
| `gamble.py` | Ferek's Game of Certainties, pity. |
| `economy.py` | item_value, gamble_cost, bulk_sell_threshold. |
| `atlas.py` | Атлас (из opus_pack, НЕ интегрирован). |
| `zone_mods.py` | Stage 6.5 авто-моды зон (data/zone_mods.json, 12 модов danger→reward). Интегрирован в world+main. |
| `stats_track.py` | StatsTracker (kill/boss/death счётчики). |

## ui/ (PyQt6)
| Файл | Что внутри |
|---|---|
| `window.py` | Полоска над таскбаром. GRID_COLS=6 (сетка 6+6), BTN_ZONE=292, шеврон сворачивания, flash_notify (очередь до 4), set_button_alert. **main-сессия только.** |
| `render.py` | SpriteStore (walk/attack/dead + atlas-формат), процедурный фолбэк, параллакс-фон, HP-бары, циферки, VFX-плеер, проджектайлы, болванки-визуал скиллов v2. |
| `panels.py` | PanelFrame (X+Esc+клампинг, сигнал closed), PanelManager (эксклюзивность/пары), Inventory, Character (Equipped Skills из skills_v2), тултипы, RMB-продажа, Shift-сравнение. |
| `skills_panel.py` | **Панель скиллов V2** (S.6). `SkillsPanel(hero,on_change)`+`refresh()`. 3 колонки: грид 16 / loadout-бар / карточка (ранги+таланты). |
| `tree_panel.py` | Дерево: пан/зум, drawArc минорных дуг, ✕+Esc, иконки нод. |
| `launcher.py` | Лаунчер: QStackedWidget 1376×768, экраны MainMenu/NewCharacter/LoadGame/Settings. |
| `zones_panel.py`, `cube_panel.py`, `vendor_panel.py`, `gamble_panel.py`, `stash_panel.py` | Соответствующие панели (все на PanelFrame). |
| `main.py` | (корень) game loop, интеграция всего. **main-сессия только.** |

## data/ (только грузить)
`skills_v2.json` (80 скиллов), `skill_talents_v2.json` (пулы талантов), `passives_v2.json` (1002 ноды, планарное, edge_arcs 768), `affixes_v2.json` (195 аффиксов v3, 39 семей, version 3), `skill_socket_passives.json` (5 пассивок), `skills_map.json` (80 иконок), `zone_mods.json` (12 модов), `atlas_tree.json`, `skill_talents.json`/`skills_full.json`/`skills_new.json`/`passives.json` (легаси/задел).

## Проверка (важно!)
- `python _test_integration.py` — главный.
- Юнит-тесты гонять **`python tests/<x>.py`** (НЕ `python -m tests.<x>` — сломан чужим site-packages «tests»). Или `python -m pytest -q` (83 passed).
- Смоуки: `python -m game.<m>` / `python -m ui.<m>`.
- Есть: test_skills_v2, test_balance_stage6, test_tomes, test_keystones, test_class_keystones, test_ailments, test_atlas, test_economy, test_gamble, test_item_roller, test_stat_coverage, test_wave1.

---

# 3. БОЙ, СТАТЫ, ПРЕДМЕТЫ

## 3.1 Статы и урон
- **Статы:** life, mana, damage_min/max, attack_speed, crit_chance, crit_multi, armor, evasion, move_speed, резисты (fire/cold/lightning/chaos, кап 75%), + inc-статы (damage_inc, aoe_damage_inc, boss_damage_inc, life_leech, cast_speed_inc, …).
- **StatMod(stat, flat, inc, more)** → `(base + Σflat) × (1 + Σinc/100) × Π(1 + more/100)`.
- **5 типов урона:** physical (режется бронёй), fire/cold/lightning (резисты), chaos.
- **Дальности атаки:** warrior 42, barbarian 44, cleric 46, archer 160, mage 180. (Skills V2 ranges: melee 48 / medium 140 / ranged 260.)
- Смерть героя → респавн 2.5с.
- **Cleave для melee** (combat.py): warrior/barbarian/cleric бьют до 4 мобов в R=60px за 50% урона (`MELEE_CLEAVE_CLASSES`, `CLEAVE_RANGE=60`, `CLEAVE_MULT=0.5`, `CLEAVE_MAX_TARGETS=4`).
- **Проджектайлы дальников:** archer/mage авто-атака пускает летящий VFX hero→target (визуал; урон мгновенный в `_hero_strike`). `RANGED_PROJECTILE={archer:proj_arrow, mage:proj_mage}`.

## 3.2 Ailments (game/ailments.py, интегрированы в combat)
Накладываются ТОЛЬКО скиллами (не базовой автоатакой — by design v3.1).
- **ignite** 40%/3с (сильнейший выигрывает) · **bleed** 50%/4с · **poison** 60%/5с (стак×3) · **freeze** стоп 0.8с + слоу 30%/2с · **shock** +15% входящего/3с · **stun** 0.6с.
- DoT снапшот финального хита, тики 4/с; боссы: контрол-длительности ×0.5.
- Кейстоуны: pyromaniac / winters_grasp / plaguebearer (DIRECT_PENALTY=0.15) / storm_herald (SHOCK_SPREAD_RADIUS=60).
- Рендер: точки 3×3px над HP-баром (6 цветов).
- API: get_state/try_apply_on_hit/tick_ailments/damage_taken_mult/move_speed_mult/is_stunned/apply_stun/spread_shock/active_icons.

## 3.3 Предметы, лут, аффиксы
- **Редкости:** Normal (белый) → Magic (синий, 1-2 аффикса) → Rare (жёлтый, 4-6, генерируемое имя) → Unique (оранжевый, фикс. моды).
- **36 баз:** оружие (dps/aps), броня по слотам, jewelry, имплиситы, req уровня. **Привязка к классам:** sword→warrior, axe→barbarian, bow→archer, staff→mage, mace→cleric; плейт-броня только warrior/barbarian/cleric. `class_req` в Item+save.
- **Аффиксы v3:** 195 аффиксов, 39 семей, тиры T5→T1, гейт по ilvl. Файл `data/affixes_v2.json` (version 3). Выкинуты статы: stun/block/armor_pen/shock_effect/ailment-chance/low_life/burning/projectile (айлменты теперь только у скиллов).
- **ItemRoller** (item_roller.py): ilvl→base→rarity (Stage 6.2: {N100/M55/R8}, IR-шифт)→affix counts→pick loop с tier bias (ilvl≥45 T5×0.6; ≥60 T5×0.35 T4×0.6)→value roll→naming→smart loot 25%. Детерминизм от rng.
- Инвентарь 32 слота (INV_CAP). Overflow: rare/unique → стеш, normal/magic → авто-продажа с флешем; кнопка инвентаря красная при полном.
- Тултипы PoE-стиля, Shift = сравнение с одетым.

## 3.4 Уники (29)
16 оригинальных + 13 из opus_pack. `UniqueDef.special = tuple[(id,text)]`. Special-эффекты **оживлены** через `game/unique_specials.py` (single source): STAT-спецы (boss_damage, kael_tax) вливаются в recalc как обычные StatMod; FLAG-спецы (low_life_fire, phys_to_fire, knockback, stagger, corrosion_immune, double_pity, gamble_cost_up, unique_drop_penalty, rare_mod_steal) — булевы флаги в `hero.flags`, читаются в call-site (combat/gamble/loot). Числа-тюнинги живут в `unique_specials.py`. Спец-эффект хранится на display-Affix `<uid>_special` → переживает save/load без новых raw-ключей.

### Corrosion (slime-дебафф, combat.py) — Tier C
Slime-семейство (`monster_id` `slime*` / `mother_of_slimes`) при каждом ударе вешает стек коррозии на героя: −6%/стек **эффективной** брони на этот удар (cap 5 стеков = −30%), стеки сбрасываются разом через 4с после последнего. **Не трогает `hero.stats`** (recalc-safe) — только митигейт в `_monster_strike`. Не-slime (Orc Warlord death-wall) не затронут. `corrosion_immune` (The Quarantine Rolls) гасит полностью. Decay-тик: `_tick_corrosion`.

### Rare mod steal (covenant_of_the_hunt, combat.py) — Tier C
С флагом `rare_mod_steal` убийство **Rare**-моба крадёт 1 его «аффикс» на 20с (cap 3, старейший вылетает при переполнении). Мобы не носят item-аффиксы → крадётся производное от силы моба (`unique_specials.steal_mod_from`): доля hp как flat life / доля удара как added-урон его типа / +10% attack speed / доля брони. Живёт на `hero._stolen_mods` (вливается в recalc), expiry — `_tick_stolen`. Транзиентно, НЕ сериализуется.

## 3.5 Куб / Вендор / Гэмбл / Стеш / Экономика
- **Куб** (cube.py): 3 Normal→Magic; 3 Magic→Rare; 3 Magic+Rare→reroll Rare; 2 кольца→Magic-амулет; 3 предмета→+5 ilvl первому. Кнопка «3x same base».
- **Вендор** (vendor.py): STOCK_SIZE=8, REFRESH_SEC=3600, веса N50/M35/R14/U1, цена=item_value×4, sell/buyback (cap 5, gold-neutral), «Sell junk (ilvl<X)». Кнопка V.
- **Гэмбл Ferek** (gamble.py): pity 0.6%/soft@73/hard@80, ~62.3 ролла до уника. Кнопка G.
- **Стеш** (stash_panel.py): безлимит, «Stash all», клик=вернуть. Кнопка S.
- **Экономика** (economy.py): item_value (base=6+2·ilvl, jewelry ×1.4; rarity ×1/2.2/5/12; affix_quality), gamble_cost, bulk_sell_threshold.

## 3.6 Оффлайн-прогресс (Stage 6.1.4)
- `OFFLINE_TIERS = [(8ч, 0.60), (24ч, 0.35), (72ч, 0.15)]`, дальше 72ч = 0. OFFLINE_LEVEL_CAP снят.
- Источник рейта: снапшоты `xp/kill/gold_rate` в сейве, обновляются каждые 60с онлайн (main.py `_update_rate_snapshot`, RATE_SNAPSHOT_SEC=60). Оффлайн = снапшот × tier × время. **Больше НЕ пересчитывается из zone math** (там жил баг ×600 gold).
- Оффлайн-лут: золото (полное) + до 20 сгущённых дропов (magic+) на возврате + продвижение pity.
- `xp_gain_inc` применяется РОВНО раз в `grant_xp` (фикс двойного XP).

---

# 4. КЛАССЫ

| Класс | Стиль | Описание |
|---|---|---|
| **Warrior** | меч+щит, phys/bleed | Сбалансированный мили-танк: жизнь и броня |
| **Barbarian** | двуручник/топор, fury/phys | Огромный урон и жизнь, броня почти нулевая |
| **Archer** | лук, proj/poison | Дальний бой: скорость атак, криты, уклонение |
| **Mage** | посох, elemental | Стеклянная пушка-кастер (референс-«стекло», не бафать) |
| **Cleric** | булава+святой огонь, holy | Живучий боец с самолечением, medium range |

Баланс-пасс §5: warrior/barbarian/cleric подняты (life/armor/leech/dmg); mage/archer НЕ трогать. Разброс по уровню сведён к 1.57× (4ч normal).

---

# 5. SKILLS V2 («Gem Souls») — АКТУАЛЬНАЯ СИСТЕМА СКИЛЛОВ

> Полная дизайн-спека была в `новый приколы/SKILLS_MECHANICS_V2.md`. Здесь — весь канон.
> Заменяет старую систему talent-по-уровням-героя. Таланты теперь на РАНГАХ скиллов, уровни героя дают КЛАССОВЫЕ КЕЙСТОУНЫ.

## 5.1 Три слоя прогрессии
| Слой | Драйвер | Каденс | Выбор |
|---|---|---|---|
| **Пул скиллов** | уровень героя (+ Skill Tome дроп) | 16 скиллов/класс, L1→L55 | какие ЭКИПИРОВАТЬ |
| **Ранги+таланты** | skill XP (киллы с экипом) | ранг 1-20, талант на 5/10/15/20 | 1 из 3 за тир |
| **Классовые кейстоуны** | Class Points (акт-боссы) | подДерево класса, 7 нод (маг 9) | какие ноды купить |

## 5.2 Пул скиллов — 16/класс
Типы: **Primary** (4, auto-attack replacers, КД=0) · **Spender** (6, КД-нюки) · **Aura** (2, перманент, резерв 25% маны) · **Utility** (2, бафф/хил/трап на своём таймере) · **Ultimate** (2, КД 60-90с).
Unlock-лестница (одна для всех): `1, 2, 4, 6, 8, 11, 14, 17, 20, 24, 28, 32, 36, 42, 48, 55`.
**Loadout-слоты (РЕВОРК 21.07 — общий пул):** 1 Primary (всегда, авто-атака) + **общий пул скилл-слотов**. ЛЮБОЙ тип (spender/aura/utility/ultimate) конкурирует за один и тот же пул — максимум **4 скилла** одновременно. Слоты открываются на уровнях героя **1 / 25 / 50 / 75** (`SKILL_SLOT_LEVELS=(1,25,50,75)`, `MAX_SKILL_SLOTS=4`, `slots_open(level)`). Мотивация: убрать «одновременно активно ~7 скиллов», игрок осознанно выбирает 2–4. Экип/своп бесплатны и мгновенны; полный пул — экип заменяет последний слот. Легаси-сейвы (`actives[3]`+`aura`+`utility`+`ultimate`) прозрачно сворачиваются в `loadout.slots` (`_migrate_legacy_loadout`, порядок сохранён, дубли выброшены).

## 5.3 Ранги (skill XP)
- Экип скиллы копят sxp/килл: `sxp = floor(mob_xp × 0.6)`. Неэкип — 25% (анти-FOMO осмос).
- Порог ранга: `sxp_need(r) = floor(40 × r^1.7)`, ранги 1→20.
- За ранг: **+4% more урона скилла** (свой MORE-бакет как один продукт-терм) + 2% secondary (длительность/радиус/скорость снаряда по тегу).

## 5.4 Таланты скиллов (ранг 5/10/15/20, 1 из 3)
Опции из архетип-пулов по тегам скилла (`skill_talents_v2.json`, 3 пула offense/tempo/utility, 4 тира):
- **Offense:** +10% more dmg · +12% attack speed · +20% crit chance · +30% crit multi
- **Tempo:** −25% cooldown · +1 chain/pierce/target · +15% inc dmg · −20% mana cost
- **Utility:** +20% effect duration · +10% lifesteal (melee)/+15% proj speed (ranged) · +25% radius (AoE) · +15% ailment chance (DoT)
- Ранг-20 тир = juiced ×1.5 («gem awakening» фил).
- **Respec талантов:** `100 × hero_level` gold (`RESPEC_GOLD_PER_LEVEL=100`). Ранги/XP не сбрасываются.

## 5.5 Awakening (эндгейм)
Скилл ранг 20 + герой 60 → потратить `25000 × act` золота → анлок рангов 21-25 (+4% more each, `AWAKENED_RANK_CAP=25`) + доп. тир талантов на 25 + золотая рамка иконки.

## 5.6 Классовые кейстоуны = ascendancy-подДеревья (S.4 REWORK) — ✅ РЕАЛИЗОВАНО
Не отдельная модалка/тиры, а **личное подДерево класса на общем канвасе дерева** (аналог Ascendancy в PoE), разворачивается кликом по шарику своего класса. **37 нод** (4 класса × 7 + маг 9), спека — `CLASS_KEYSTONES_TREE_REWORK.md §3`.
- **Данные:** `data/class_keystones.json` (генератор `tools/gen_class_keystones.py`, детерминированный). `game/tree.py` аддитивно мержит ноды+рёбра поверх baked `passives_v2.json` (последний НЕ трогается). Id `ck_<class>_<n>`.
- **Отдельная валюта — Class Points (CP).** Капают ТОЛЬКО за ПЕРВЫЙ килл акт-босса (PoE-лаб-стиль), НЕ с уровней: Goblin King +2, Lich Emperor +2, Lord of Ash +2, The Watcher (опц. Акт 4) +1 = максимум **7 CP** = полное подДерево. 1 нода = 1 CP. `class_points_total/available`, `grant_class_point`, `sync_class_points_from_kills` (ретро-грант старых сейвов).
- **Сейв:** `hero.class_point_sources: list[str]` (id боссов, дедуп). Аллоцированные ck-ноды живут в `hero.passives`. `rebuild` дропает чужеклассовые/битые ck-id → CP авто-рефанд.
- **Гейты в `tree.allocate`:** `class_req` (свой класс), `level_req` (mech 30 / cap 50), `exclusive_group` («mage_lock» — 1 из 3 стихий-локов).
- **4 боевых флага (белый список, хуки в `combat.py`):** `ck_cull_10` (добой <10% / боссы <5%), `ck_overheal` (лишний лайфстил→temp HP, кап 20% / распад 2%/с), `ck_fifth_shot` (каждый 5-й удар — крит), `ck_kill_heal` (килл лечит 2% max life).
- **UI (`ui/tree_panel.py`):** разворот/сворот подДерева кликом по шарику своего класса (ck-ноды скрыты в свёрнутом виде, аллоцированные видны всегда), тултип «<Class> only» на чужих шариках, индикатор непотраченных CP.
- **Тесты:** `tests/test_class_keystones.py` (13) — мердж, гейты, экономика CP+ретро+roundtrip, coverage, 4 хука, легаси-сейв.
- **v1 упразднён:** старая система (`keystones_v2.py`/`keystone_modal.py`/модалка 90 кейстоунов при level-up) снесена целиком.

Дизайн подДеревьев (числа — в json, темы):
- **Warrior «Bastion»** (танк→палач): armor/life-сустейн + крит-ветка, mech Executioner (cull), cap Avatar of the Bastion.
- **Barbarian «Fury»** (темп→кровь): attack_speed/leech, mech Blood Frenzy (overheal), cap Warlord.
- **Archer «Deadeye»** (крит→ритм): crit_multi/evasion/as, mech Marked Rhythm (5-й крит), cap Windborne Executioner.
- **Mage «Attunement»** (стекло остаётся стеклом): mana/cast/dmg, 3 взаимоисключающих Lock (Flame/Frost/Storm — движок без per-element, честный фолбэк +20% dmg каждый), cap Archon.
- **Cleric «Radiant»** (сустейн→возмездие): armor/life/cast, mech Light's Harvest (kill_heal), cap Ascendant.

## 5.7 Rotation AI (idle, priority queue)
```
# всё кастуемое живёт в общем пуле loadout.slots (реворк 21.07)
if ultimate(из пула) ready and (boss or pack>=4): cast ultimate
for spender(из пула) in priority-порядке: if ready and target_in_range: cast; break
# primary НЕ кастуется из ротации — он = автоатака в combat.py (единств. источник)
```
- Приоритет спендеров = порядок в пуле `slots` (кнопки ▲/▼ в панели, не drag); `priority` — зеркало этого порядка (`_sync_priority`).
- Ауры авто-применяются на экип, если заслочены в пул (`_refresh_aura_buffs` сворачивает ВСЕ заслоченные ауры); utility само-кастуется по КД (heal только если HP<70%).
- **МОДЕЛЬ (важно, фикс спама):** primary = автоатака (combat.py, КД по attack_speed, крит/cleave/leech/проджектайлы). skills_v2 = ТОЛЬКО скиллы с КД. `primary_growth_mult(hero)` отдаёт ранги+таланты primary в автоатаку.

## 5.8 API game/skills_v2.py (14 сигнатур ядра + хелперы UI)
Ядро: `load_skills_v2` / `load_talents_v2` / `SkillV2` / `sxp_need` / `rank_from_sxp` / `skill_rank` / `skill_more_mult` / `unlocked_by_level` / `slots_open` / `loadout_slots_open` / `default_skills_v2` / `ensure_skills_v2` / `tick_skills_v2` / `grant_skill_xp` / `primary_growth_mult`. Слот-константы: `SKILL_SLOT_LEVELS=(1,25,50,75)` / `MAX_SKILL_SLOTS=4`.
UI-хелперы (S.6): `slot_family_for` (→ 'primary' | 'slots') / `can_equip` / `equip_skill` / `unequip_skill` / `move_priority` / `rank_progress` / `talent_tiers_for` / `can_pick_talent` / `pick_talent` / `respec_talents` / `_equipped_ids`.
Урон НЕ дублирован — через `game.skills._deal`. Диспатч — 1 функция `_apply_effect` по type+tags+params. CDR_CAP=60, cast_speed только mage/cleric.

## 5.9 Save-формат (в hero.skills_v2, save v5)
```json
"skills_v2": {
  "unlocked": ["slash","cleave","war_cry"],
  "loadout": {"primary":"sunder","slots":["blade_storm","rupture","defiance",null]},
  "priority": ["blade_storm","rupture","defiance"],
  "sxp": {"slash": 4210, "sunder": 12800},
  "talents": {"sunder": {"5":0,"10":2}},
  "awakened": [], "tomes_read": 3
}
```
> **РЕВОРК 21.07:** `loadout` = `{"primary", "slots"}` (общий пул до 4, §5.2). Любой тип делит `slots`. `priority` — зеркало порядка `slots` (`_sync_priority`). Легаси-ключи (`actives`/`aura`/`utility`/`ultimate`) прозрачно сворачиваются в `slots` при load (`_migrate_legacy_loadout`) — старые сейвы грузятся без потерь.
> S.4 REWORK: классовые кейстоуны переехали из `skills_v2.keystones` в ноды дерева. CP-источники — отдельное поле `hero.class_point_sources` (см. §5.6). Старый ключ `skills_v2.keystones` при load игнорится (не падает).

## 5.10 Все 80 скиллов (компакт: `Lvl Name — Type [tags] effect`)
Маппинг урона в enum core: holy→phys, arcane/poison→chaos, light→lightning (стихия=тег).

**Warrior** (phys/bleed): 1 Slash P·2 Cleave S[AoE] 170% arc cd6·4 War Cry U +20%dmg 8s cd20·6 Shield Bash S 140%+stun1.5s cd8·8 Precise Strike P 90%+15%crit·11 Shockwave S[AoE] 200% cd10·14 Defiance A +25%armor·17 Sunder P 85%+bleed40%/4s·20 Blade Storm S 6×45% cd12·24 Second Wind U heal25% cd30·28 Executioner's Swing P 110% +50%vs<30%·32 Earthquake S[AoE,DoT] 240% cd14·36 Battle Standard A +15%dmg/+10%as·42 Rupture S[Bleed] 150% ×3 cd9·48 Avatar of War ULT 10s +60%more immune-stun cd75·55 Undying Rage ULT 8s cannot-die +40%as cd90

**Barbarian** (fury/axe): 1 Savage Chop P·2 Leap Slam S[Move,AoE] 160% cd8·4 Battle Roar U fear+15%dmg cd18·6 Whirlwind S[AoE] 55%×hits cd10·8 Frenzy P stacks+4%as(max5)·11 Bloodthirst S 180%+heal30% cd9·14 Berserker Rage A +20%as/-10%armor·17 Rampage P 95% kills+10%move/as·20 Seismic Slam S 220% cd11·24 Ancestral Spirit U ghost cd25·28 Skullsplitter P 130% +30%critmulti·32 Ancient Fury S 6×50% cd13·36 Bloodlust A 8%lifesteal·42 Decapitate S 320% cd15·48 Wrath of the Ancients ULT 3 ancestors cd80·55 Undying Fury ULT 10s WW free +30%more cd90

**Archer** (proj/poison): 1 Quick Shot P·2 Poison Arrow S[DoT] 120%+60%/5s cd7·4 Mark for Death U +25%taken cd15·6 Split Arrow P 70%×3·8 Rain of Arrows S[AoE] 30%×8 cd10·11 Explosive Arrow S 190% cd9·14 Hawk Eye A +20%crit·17 Piercing Shot P 100% pierce2·20 Barrage S 45%×5 cd8·24 Caltrops U trap cd20·28 Lightning Arrow P 90%+chain1·32 Snipe S 350% cd14·36 Wind Dancer A +15%as/+10%evade·42 Toxic Volley S poison AoE ×3 cd12·48 Arrow Storm ULT 8s cd75·55 Phantom Volley ULT clones 10s cd90

**Mage** (elemental): 1 Fire Bolt P[Fire]·2 Ice Nova S[Cold,AoE] 150%+chill cd8·4 Mana Shield U 30%dmg→mana cd25·6 Spark P[Light] 80%+shock·8 Fireball S[Fire,AoE] 200% cd7·11 Chain Lightning S[Light] 130% chain3 cd9·14 Elemental Attunement A +15%ele·17 Frost Bolt P[Cold] 95%+slow·20 Meteor S[Fire,AoE] 300% cd13·24 Time Warp U +25%cast cd22·28 Arcane Missile P[Arcane] 85%×2·32 Frost Beam S[Cold] channel cd12·36 Archmage A mana→spell dmg·42 Arcane Orb S 180% cd11·48 Cataclysm ULT meteors 10s cd85·55 Mirror Image ULT 2 clones cd90

**Cleric** (holy, medium): 1 Holy Bolt P[Holy]·2 Consecration S[AoE,DoT] 40%/s cd10·4 Heal U 30%HP cd18·6 Smite P 110%·8 Holy Nova S[AoE] 160% cd9·11 Divine Hammer S 190%+stun1s cd10·14 Blessing of Might A +12%dmg/+8%as·17 Radiant Lance P 100% pierce·20 Wrath of Light S 90%×3 cd8·24 Divine Shield U absorb40%HP cd28·28 Judgement P 105% every-4th+100%·32 Purifying Flame S[Holy,Fire] 220% cd12·36 Sanctuary A -12%taken +1%HP/s·42 Celestial Strike S 280% cd14·48 Avatar of Light ULT 10s +50%more heals cd80·55 Last Rites ULT 500% all-screen cd95

## 5.11 Skill Tomes (S.5, game/tomes.py — ⬜ НЕ ПОДКЛЮЧЁН к main)
- Редкий дроп: `TOME_BASE_RATE=1/220` моба, pity-safe, act-scaled.
- Чтение → анлок случайного ещё запертого скилла до +10 ур над героем (`TOME_UNLOCK_OVERSHOOT=10`). Дубль (нечего анлочить) → конверт в skill-XP `500 × act`.
- НЕ Item (в инвентарь не кладётся). Дроп = событие/счётчик; main решает как показать («Skill Tome!» флеш).
- API: `roll_tome_drop(hero,act,rng,pity=0)→bool`, `readable_tome_targets(hero)→list[str]`, `read_tome(hero,act,rng)→dict`. Состояние: `hero.skills_v2["unlocked"/"sxp"/"tomes_read"]`.

## 5.12 Skill Sockets (легаси §4) — ⚰️ МЁРТВАЯ МЕХАНИКА (движок удалён 20.07)
Сокет = выбор ПАССИВКИ (не гем/руна). Жила на СТАРОМ `skills.py`, который **удалён** (легаси-чистка 20.07: ноль импортёров, `_deal`/`_heal` давно в `combat_math.py`). Функции `skill_sockets()`/`_skill_socket_bonus()` НИКОГДА не звались живьём, `skills_v2` сокет-бонусы НЕ применяет → механика была де-факто мертва ещё до удаления. Остались только: сейв-поле `hero.skill_runes` (SAVE_VERSION 5, грузится/пишется, но ни на что не влияет) + `combat_math.load_socket_passives()` (loader без консьюмера) + `data/skill_socket_passives.json` (5 пассивок Power/Swiftness/Focus/Savagery/Siphon). **Судьба:** либо оживить (провести сокет-бонусы в skills_v2), либо выпилить поле в SAVE_VERSION 6. Отдельное решение.

---

# 6. ДЕРЕВО ПАССИВОК (game/tree.py + ui/tree_panel.py)
- **Данные:** `data/passives_v2.json` — 1002 ноды, планарный граф, positions BAKED, `edge_arcs` (768, часть рёбер = дуги окружностей). Центр ПУСТОЙ, каждый класс стартует со своего `class_start` (r=140).
- Топология: class cores r=320, 12 theme-кластеров r=520 (flame/frost/storm/slaughter/precision/alacrity/vitality/bulwark/wind/decay/thirst/eldritch), 20 keystones r=820.
- **Очки:** 1/уровень со 2-го (`points = level - 1`). +3 за первый килл акт-босса на сложности. Post-100 (Stage 6.6): +1 очко/уровень (дерево размерено под это).
- Кейстоун-гейт lvl30 УБРАН (кейстоун = 1 очко).
- **API:** `allocate/deallocate/path_to (BFS)/allocate_path (клик по дальней = весь путь, как PoE)/points_available/rebuild (дроп неизвестных id = авто-рефанд)`.
- **Кейстоун-флаги дерева** (hero.flags): glass_cannon (+60% inc dmg) / juggernaut (life more -30, move -10) / deadeye (дист≥100 →×1.2) / berserker_oath (+2%/1% missing life) / vampiric_pact (heal ×0.5) / timeworn (XP ×0.9). Остальные ~15 keystone-флагов = TODO без потребителя (тултип честный).
- UI: зум 0.4–2.5, пан драгом, виньетка, кольца-направляющие, drawArc, иконки нод, ✕+Esc.

---

# 7. МИР

## 7.1 Акты, зоны (19), сложности
Сложности = **4 обязательных лупа кампании**: **Normal → Cruel → Merciless → Nightmare**. Кампания (Акты 1-3, mlvl 1-58) переигрывается на каждом лупе с ростом *эффективного* mlvl через `mlvl_offset`. Достичь ~100 на одном Normal НЕЛЬЗЯ — путь наверх лежит через лупы (Вариант 1 + Вариант A «перенос нагрузки»).

| Сложн. | monster_mult | xp_mult | loot | unlock lvl | mlvl_offset |
|---|---|---|---|---|---|
| Normal | 1.0 | 1.0 | 0 | 1 | 0 |
| Cruel | 1.6 | 1.6 | 20 | 20 | +10 |
| Merciless | 2.6 | 2.5 | 50 | 40 | +20 |
| Nightmare | 4.8 | 4.0 | 100 | 60 | +30 |

**Вариант A (перенос нагрузки):** `mlvl_offset` — основной носитель сложности; `monster_mult` СНИЖЕН относительно наивного стэка, чтобы суммарный урон (`mob_dmg_mult(base+offset)·monster_mult`) остался ≈ текущего и мили-классы не ловили death-wall на Nightmare. **Грайндвол = фича, но проходимый:** offset снижен 15/28/40→10/20/30 (sim 21.07 показал: старые числа давали 40ч+ тупик на бос­сах Акта 3 каждого лупа). Цель — стена, которую ломают правильный билд + фарм гира, а не вечный грайнд. **Правило:** `mlvl_offset` применяется ТОЛЬКО в боевом скейле мобов (`Spawner`→`scale_monster`) и в `zone_xp_mult` (эфф. mlvl), НИКОГДА в гейтах зон/сложностей (иначе высокий луп залочит собственные ранние зоны).

**Auto-advance (idle-фича):** после клира зоны персонаж сам идёт в следующую зону кампании (`world.next_campaign_zone`); после клира финала Акта 3 (`lord_of_ash`) и при открытом гейте — ролловер в Акт 1 следующей сложности (`_maybe_start_next_loop`). Переключаемо галочкой в ZonesPanel («☑ Auto» / «☐ Farm here») — снятая галка = засесть/фармить текущую зону. Act 4 и рифты — вне auto-chain (эндгейм).

| Акт | Зоны (тема, mlvl) | Босс |
|---|---|---|
| **1** | Twilight Shore(пляж,1) · Rotting Swamp(болото,4) · Darkroot Forest(лес,8) · Ember Caves(пещеры,13) · Ruins of the Firstborn(руины,18) | Goblin King |
| **2** | Stony Wastes(22) · Far Dunes(26) · Lost City(30) · Serpent Crypts(гробница,34) · Great Tomb(38) | Lich Emperor |
| **3** | Jungle's Edge(40) · Deep Canopy(44) · Orc Warcamp(48) · Sunken Temple(храм,52) · Slime Pits(55) · Ashen Sanctum(58) | Orc Warlord / Mother of Slimes / Lord of Ash |
| **4** | «The Abyss» — 3 зоны (mlvl 61-68) | skeleton_chieftain / abyssal_behemoth / the_watcher |

`FINAL_ACT_BOSS_ID = lord_of_ash` (Акт 4 = опц. эндгейм-мост). Nightmare→рифты открываются после килла lord_of_ash.

## 7.2 Бестиарий (~55 мобов)
По тематике зон: пляж (ледяные слизни/крысы/пауки), болото (токс. слизни/зомби/жабы), лес (орки/скелеты/тени/призраки), пещеры (импы/магма/горгульи/броня), руины (демоны/маги/призраки), пустыня (песчаные/бандиты/скараби/шаманы), гробницы (змеи/мумии/скелеты/рыцари), джунгли (хищники/жабы/инсекты/обезьяны), храмы (големы/жрецы/культисты), ямы слизней (все слизни+мутанты), Акт 4 (8 undead_jungle + 12 demons_eldritch).
Спрайты: manifest.json ~55 id, все файлы на диске. Атлас-формат: манифест поддерживает `dir` (папка≠id) и `all` (единый список, split по all_split=0.5).

---

# 8. BALANCE STAGE 6 — idle/AFK канон (168ч+ до 100) ✅ СДЕЛАН 6.0-6.6

> Вектор: idle/AFK ARPG (Diablo×PoE×idle). Игра 24/7 с открытым окном; прогресс плавный и бесконечный. Оффлайн = вторичный catch-up. Уровень 100 ≈ 168ч РЕАЛЬНОГО онлайна = ПОЛ, не потолок. После 100 — бесконечный скейл.
> Числа из `новый приколы/BALANCE_PASS_STAGE6.md` — канон, не изобретать. Калибровать ТОЛЬКО `XP_A` через sim.

## 6.0 Sim harness — `tools/sim.py` (23КБ, есть)
Headless, детерминир. (`--seed`), timescale. Сценарии `--hours 4|24|168`, `--class`, `--offline H`. Auto-play = idle-поведение. Метрики/час → `docs/sim_report.md` + CSV.

## 6.1 AFK core (progression.py + save.py)
- **XP-кривая:** `xp_to_level(L) = int(XP_A · (L-1)^XP_E · XP_G^(L-1))`, где `XP_A=60.0` (единственный калибровочный кноб), `XP_E=2.6`, `XP_G=1.05`. Целевой пейсинг: lvl 100 ≈ 172ч; на 90+ уровень каждые ~3.5ч.
- **Анти-чиз / стена лупов:** `zone_xp_mult(hero,mlvl) = max(0.02, 1.0 - 0.08·max(0, hero-mlvl-5))`. Считается по ЭФФЕКТИВНОМУ mlvl (`zone.monster_level + difficulty.mlvl_offset`), поэтому высокий луп держит героя в grace-band, а засиживание на слишком низком лупе декеит XP к 2%-полу (было 10%) — этот глубокий пол и делает 100 на одном Normal недостижимым (Вариант 1).
- **XP single-source:** `xp_gain_inc` ровно раз в `grant_xp`; offline отдаёт RAW xp.
- **Оффлайн:** `OFFLINE_TIERS=[(8ч,0.60),(24ч,0.35),(72ч,0.15)]`, >72ч=0; снапшоты рейтов; лут→золото+до 20 дропов; OFFLINE_LEVEL_CAP снят.

## 6.2 Loot pass (loot.py/item_roller.py)
`DROP_CHANCE=0.10` (было 0.25); `RARITY_WEIGHTS={N:100,M:55,R:8}` (rare≈4.9%). Цель: 2-4 rare/ч мидгейм, 1-3 uniques/24ч. `item_rarity_inc_pct` шифтит WEIGHTS, не DROP_CHANCE. Боссы: гарант 1 rare + boss-only pity unique. Золото +30% (компенсация).

## 6.3 Длина зон (world.py)
`kills_to_boss(act, zone_pos) = round(24 · 1.6^(act-1) · (1 + 0.25·zone_pos))`. Акт1: 24/30/36 · Акт2: 38/48/58 · Акт3: 61/77/92 · Акт4: 98/123/147 (≈×4 Акт1). Re-farm после килла: ×0.75.

## 6.4 Скейл мобов (world.py)
`mob_life_mult(m) = (1 + 0.32·m) · 1.022^m` · `mob_dmg_mult(m) = (1 + 0.20·m) · 1.016^m`. mlvl18≈×9.9 life, mlvl68≈×100 life. `mob_xp = life_mult^0.8`. Champions/elites (Акт2+): +120% life/+40% dmg/+1 rarity tier. Boss-стена = фича (гир решает); on-level босс с гиром дохнет 60-180с.

## 6.5 Zone auto-mods (zone_mods.py + data/zone_mods.json) ✅ подключён (world+main)
Активация: lvl≥25 или Акт≥2. Roll кол-ва: Акт2 50/35/15, Акт3 40/40/20, Акт4 60/40 (+1 на Cruel). 12 модов danger→reward (ferocity/vitality/horde/swiftness/champions/deadly/burning/toxic/draining/armored/frenzied/unstable). Reward-райдеры ТОЛЬКО zone-local (xp/drop/gold), не глобал. Реролл на килле босса. В сейве `zone_mods:{zone_id:[ids]}`.

## 6.6 Endless endgame
- **MAX_LEVEL снят:** post-100 = +1 очко дерева/уровень.
- **Рифты** (rifts.py, после килла lord_of_ash на сложности): `mlvl=62+2·tier`, `kills_to_boss=60+10·tier`, forced 3-5 модов (+1/5 тиров), клир→tier+1, 3 смерти→tier-1 (пол 1). Награды: ilvl 71+ (T0 аффиксы только тут), unique pity ×1.5, gold ×(1+0.06·tier). **⬜ НЕ подключён к UI/main** (нет входа в рифты, сейва rift_tier).

---

# 9. ЛОР-КАНОН (имена не менять)
Мир **Vessara** / Sundered Coast; империя **Kael**; **Vharos** the Smith of Tides; the **Ember Below**; **Sar-Hazan**; **Gromm'kar**; гэмблер **Ferek**.
Задумка (лор-библия утеряна с opus_pack, восстановить как надо):
- Герой = изгнанник Kael, выброшен на Twilight Shore.
- Акт 1 = руины Firstborn Vessara, Goblin King — узурпатор реликвий.
- Акт 2 = Lich Emperor — последний император Kael, забальзамировал себя против воли Vharos.
- Акт 3 = пробуждение Ember Below; Lord of Ash — глашатай, Sar-Hazan — финал.
- Флейвор: боссам по 1 строке спавн/смерть; уникам по строке.

---

# 10. АССЕТЫ (справочник)
```
assets/
├── sprites/     нарезанные спрайты мобов/героев + manifest.json (~55 id)
├── icons/       иконки (items/talents/skills) + map.json (36 баз) + skills_map.json (80). helmet 173 / sword 166 (расширены 18.07 из запаса; map.json пока ссылается на подмножество)
├── backgrounds/ фоны по темам (beach/cave/desert/forest/jungle/ruins/swamp/temple/tomb)
├── ui/          кнопки/рамки/курсоры/map/launcher/launcher2 + index.json
└── vfx/         эффекты (levelup/hit/proj_mage/proj_arrow/skill_*) + manifest.json (fps)
```
- Кадры анимации: единый канвас, якорь по низу (VFX — по центру), RGBA. Грузить `frame_*.png` по сортировке имён.
- **Грабли ассетов:** (1) для плоского фона flood-fill допуск ≤6 (иначе прожирает тёмную броню). (2) один scale-factor на героя от walk-листа (не масштабировать каждое состояние отдельно). (3) dead-кадр НЕ поворачивать (ломает широких мобов). (4) арт из «новый приколы/ui» часто МОКАПЫ с запечённым текстом — глянуть глазами перед использованием как фон/рамку. (5) в некоторых атласах запечён текст-подпись (undead_jungle/skeleton_chieftain, act1_2 row_12) — артефакт исходника.
- Правило: **не резать вслепую**, ничего не удалять из ассетов без явного указания.
- Маппинг мобов на ряды атласов был в `assets/_mob_mapping.md`: где у моба только папка `all` — первая половина кадров = walk, вторая = attack. Все текущие ~55 мобов уже нарезаны в `sprites/manifest.json`; маппинг нужен только при ре-нарезке из атласов (замороженный бэклог).

## Запас в `_source/` (не внедрено, склад — 18.07.2026)
Папка `новый приколы/` разобрана и удалена: дубли и `_smooth`-варианты выкинуты, иконки helmet/sword добавлены в игру, невнедрённое перенесено в `_source/`. **Ничего оттуда не удалять без указания юзера; внедрять отдельными шагами с тестами.**
- **`_source/ranger/`** — 6-й класс Ranger ПРО ЗАПАС (walk+attack). До запуска игра на 5 классах. Внедрить: нарезать в `assets/sprites/ranger/` + manifest + `classes.py` + скиллы + иконки лаунчера.
- **`_source/hero_states/`** — новые СОСТОЯНИЯ героев, требуют доработки стейт-машины в render.py (сейчас знает только walk/attack/dead): `barbarian_whirlwind`, `cleric_idle`, `mage_cast` (17 кадров).
- **`_source/knight_new/`** — потенциальный новый арт воина (рыцарь 767×700, walk10+atk10) взамен текущего (воин = арт моба dark_knight). Внедрить: flood-fill + нарезка h≈44 + замена `assets/sprites/warrior/` + manifest.
- **`_source/dark_mage/`** — dark mage: `walk_*` (549×776, назначение неясно — альт-скин/моб?) + `fx/` (bolt/cast/impact альт-проджектайлы).
- **`_source/data/`** — `affixes_v3.json` (в игре v2), `skills_full.json` (легаси). Внедрение = код + миграция сейвов.
- **`_source/tools/`** — генераторы: gen_affixes_v3, gen_skills_full, passive_tree_v2/v3. SEED=20260715.
- **`_source/skills_button_sheet.jpeg`** — неразрезанный лист иконок кнопки скиллов/дерева.
- **opus_pack** — БОЛЬШЕ НЕТ на диске (был внутри `новый приколы/data`, вычищен ранее). Данные из него давно влиты в `data/`. Комментарии в `game/atlas.py`/`tools/gen_skills_v2.py` ссылаются на него только как на источник — не рабочие пути.

---

# 11. ИСТОРИЯ РАЗРАБОТКИ (сжато)
- **Этап 1** (15.07): играбельный каркас, Акт 1.
- **Этап 2.0** (15.07): большой рефактор — англификация, 5 классов, дерево PoE-стиль.
- **Opus Pack 2b** (15-16.07): more-бакет, дерево v3 (1002 ноды), гэмбл Ferek, 29 уников.
- **Items Tree V2** (16.07): affixes_v2 (195), ItemRoller, economy.
- **Fix Wave 1** (16.07): boss lifecycle, inventory overflow, sell junk, unique weight.
- **Fix Wave 2** (16-17.07): statmap хуки (coverage-тест), ailments ядро+рендер+интеграция.
- **Fix Wave 3** (16-17.07): HUD-прогресс, оффлайн-нерф, очередь флешей, каскад панелей, онбординг.
- **Master Pack v3.1** (17.07): дерево планарное+дуги, affixes v3, UX-волна (PanelFrame/PanelManager).
- **Сессия 17.07:** сокеты скиллов (save v4), меню 6+6, лаунчер (3 экрана).
- **Сессия 18.07:** фикс integration-теста, §5 баланс-пасс (cleave melee), Акт 4 + 20 новых мобов, воин v2 арт, проджектайлы, ui2-лаунчер+Settings.
- **Эпик Skills V2** (18.07): Фаза 0 санитария → S.0 данные (80 скиллов) → S.1 движок → S.2/S.3 бой+save v5 → S.5 tomes (логика) → S.6 UI-панель + иконки. Фиксы: спам скиллов, скользящий труп, Character-панель.
- **Balance Stage 6** (18.07): 6.0-6.6 все в коде (XP-кривая, оффлайн-рефворк, loot pass, длина зон, скейл мобов, zone-mods, рифты-логика, uncapped leveling).

---

# 12. ГРАБЛИ (кровью)
1. Сначала ROADMAP + `python _test_integration.py` — код не врёт, память/доки могут врать.
2. `_entries/*.json` без walk_00.png рядом = агент умер, json врёт.
3. Память и ROADMAP обновлять СРАЗУ после блока — сессии умирают.
4. `data/passives.json` и `passives_v2.json` РАЗОШЛИСЬ с opus_pack — НИКОГДА не «восстанавливать из источника».
5. `game/*` не импортит `ui/*`. Смоук-ассерты размеров арта через `>=`, не `==`.
6. Изменил baseline/якорь в render — проверить `_draw_entity`/`_hp_bar`/VFX + скрин.
7. Параллельные агенты: каждому явный список файлов, запрет на main.py/window.py пересечения; два агента в один файл = конфликт.
8. `python -m tests.<x>` СЛОМАН чужим site-packages «tests» — гонять `python tests/<x>.py`.
9. opus_pack однажды удаляли — восстанавливали из корзины Windows. Беречь `новый приколы/`.
10. Уники: числовые моды пишут raw-ключ мимо statmap → инертны. Оживлять через `statmap.mods_for`.

---

# 13. ПРАВИЛА ПРОЦЕССА / АГЕНТЫ
1. Один шаг = одна сессия правок → юзер тестит → фидбек → следующий шаг. (Юзер снимает ради скорости — сверяться с ROADMAP.)
2. После каждого шага: все смоуки + `_test_integration.py` зелёные.
3. Контракты интеграции (не нарушать): события kill из двух источников (флаг `_rewarded`), `Spawner.notify_kill`, дренаж `combat.events`, `apply_level_growth` после `grant_xp`.
4. Агентам НЕ давать трогать `main.py`/`window.py` — интеграция руками.
5. Каждому агенту — узкая задача + явный список файлов. Агентам НЕЛЬЗЯ читать PNG/листать папки кадров — только `manifest.json`.
6. Два агента не пишут в один файл. Отчёт агента: `docs/_report_<task>.md`.
7. Временные файлы — в `_tmp/`, удалять после себя.
