# 論戰引擎（M4a：回合結算）

狀態：M4a 草案 2026-11-06。依據：系統規格附錄 A（A-1 結算順序、A-2、A-4 對決表、A-5～A-15）、數值總表、`docs/rulings.md`（A*、B*、C*、D15）、參考模型 `ref/`（本里程碑的唯一判準：設計文字與 `ref/`＋裁決不一致時以後者為準）；XTAtrium docs 04、05 §5.4、08 §8.2、§8.3、§8.5。

本文件說明論戰引擎的介面（給之後的 debate UI 流圖）、內部做法、資料、驗證與已知限制。引擎只有回合結算與熱身；對手 AI 是樁（M4b），對手行動一律來自劇本表。M4a 不接 UI、不接主遊戲的步驟序列（`debate`／`warmup` 步驟仍是 `stubs`）。

## 1. 檔案與產生方式

| 檔案 | 內容 | 產生 |
|---|---|---|
| `flows/debate_engine.xtflow` | 主論戰（布丁論戰、Ch.2、Ch.3）回合結算 | `uv run tools/gen_debate.py`（`--check` 只比對） |
| `flows/debate_warmup.xtflow` | 熱身小論戰（A-13） | 同上 |
| `data/debate/debCase.json`、`debCard.json`、`debNode.json`、`debCode.json` | 引擎用的衍生表（§5），由 `data/*.json` 推導 | 同上 |
| `tests/debate_routes.py` | 路線定義、以 `ref/` 重播得到每回合預期值、產生 harness 輸入表 | — |
| `tests/check_debate.py` | 重產 → 建 harness → headless 執行 → 逐回合比對 | `uv run tests/check_debate.py` |
| `tests/debate_harness/` | harness 專案（`game.json` 與 `flows/`、`data/` 全由 `check_debate.py` 產生，不要手改） | 同上 |

不要手改產生的 `.xtflow` 與 `data/debate/*.json`；改 `tools/gen_debate.py` 再重產。

| 圖 | 節點／邊 |
|---|---|
| `debate_engine` | 966／1954（expr 282、table.get 116、compare 108、state 82、coll.add 69、format 53、map.set 50、map.get 43） |
| `debate_warmup` | 179／289 |
| harness `driver` | 166／289 |

## 2. 介面

### 2.1 world 訊號

名稱不可含 `.`，一律 `deb` 前綴（熱身 `dw`）。接進主遊戲時照抄進 `game.json` 的 `signals`（`tools/gen_debate.py` 的 `SIGNALS`）。

輸入（由 debate UI 流圖寫入）：

| 訊號 | 型別 | 意義 |
|---|---|---|
| `debCase` | string | 論戰 id＝`opponents.id`（`CH01_MAIN`、`CH02_MAIN`、`CH03_MAIN`、`CH03_WARMUP`） |
| `debScript` | string | 劇本 id（`debScript.key` 的前綴）；空字串＝用 `debCase` |
| `debStart` | pulse | 開始一場論戰：重設狀態、擺上第 1 回合的節點（A-1 第 1 步：節點上限）。`debCase` 與板面集合要先寫好（同 tick 且寫入者先執行，或更早） |
| `debCmdKind` | string | 本回合玩家行動：`solid`／`sophistry`／`rebut`／`observe`（與 `opponents.playerActions` 同字） |
| `debCmdFrom`、`debCmdTo` | number | 鏈段的起訖板面格（§2.2，含兩端，`From > To`＝反向）；沒有鏈段為 −1。單張卡的「鏈段」（例：Ch.1 論破回合以反駁出示 E01_03）是 `From = To` |
| `debCmdCard` | string | 反駁的單張卡 id（`pa.card`）；用鏈段反駁（論破回合、尾聲）時為空字串 |
| `debCmdTarget` | string | 攻擊目標節點 id；空字串＝亮起的節點 |
| `debCmdAssist` | number | 1＝本回合預先啟動援護（鎖定前下注，A-7） |
| `debInstinct` | pulse | 鎖定前使用狐耳直覺（A-3）：模糊預兆改為明示真正行動，次數 −1，發 `STAMP_SEEN` |
| `debLock` | pulse | 鎖定：結算本回合（A-1 第 2～5 步）並重述下一回合（第 1 步）。指令值要在 lock 之前寫好（同 tick 且寫入者先執行，或更早） |

輸出（引擎寫入；下一 tick 起可讀）：

| 訊號 | 型別 | 意義 |
|---|---|---|
| `debPhase` | string | `idle`（未開始或熱身中）／`choose`（等待鎖定）／`over` |
| `debRound` | number | 目前回合（結束後＝最後一回合 + 1） |
| `debHpModel` | number | 1＝有主導權（Ch.1 布丁論戰為 0） |
| `debPlayerHp`／`debPlayerMax`、`debOppHp`／`debOppMax` | number | 主導權 |
| `debShaken` | number | 動搖：0 無／1 已觸發（下一回合是論破回合）／2 論破後保持到尾聲結束 |
| `debInTail`、`debTailLeft` | number | 尾聲中、剩餘尾聲回合 |
| `debVoids` | number | 論破失效次數（門檻 +1，A-8、B18） |
| `debHachiku`、`debHachikuMode` | number | 破竹層數；模式 0 無／1 預覽（Ch.1）／2 生效 |
| `debKonju`、`debShisshu` | number | 困獸、失守剩餘回合 |
| `debParries`、`debContra`、`debInfamy`、`debAssist`、`debInstinctLeft` | number | 截斷次數、矛盾數（Ch.1）、惡名（本場詭辯被抓）、剩餘援護、剩餘狐耳直覺 |
| `debFragile` | number | 場上脆弱節點數 |
| `debOver`、`debOutcome` | number、string | 結束；`win`／`loss`／`unachieved`（Ch.1 未達成） |
| `debBreakLabel`、`debGoldenUsed` | string、number | `primary`／`alternative`（Ch.3，B17）；論破用了黃金線索 |
| `debTellClarity`、`debTellShown1`、`debTellShown2`、`debTellStar`、`debTellBasis`、`debTellLit`、`debTellGesture`、`debTellLine` | string | 下一手的預兆：來自劇本列；尾聲為明示＋`script`；用過狐耳直覺為明示＋`fox`。`Gesture` 是**真正行動**的小動作鍵（A-3） |
| `debWarn` | string | `WARN_DEB_NO_SCRIPT`：本回合沒有劇本列，引擎改用「主張、亮起第一個節點」 |
| `dwActive`、`dwRound`、`dwIndex`、`dwClaim`、`dwMistakes`、`dwOver`、`dwAuto`、`dwTrustDelta`、`dwReward` | | 熱身：進行中、回合、已糾正（含自動）說法數、目前說法節點 id、失誤數、結束、失誤滿 3 自動解決、本案有效信任度增減（+1／0／−1）、獎勵是否保留 |

### 2.2 集合

| 集合 | 種類 | 寫入者 | 內容 |
|---|---|---|---|
| `debBoard` | list string（24） | 線索板／UI | 鎖定板面的卡 id，**固定格位**：第 c 條鏈（0～2）的第 i 張在 `5c + i`；散卡從 15 起；空格寫 `-` |
| `debBoardOk` | list number（24） | 線索板／UI | 同格位：該卡選的理由正確為 1 |
| `debBoardLink` | list number（24） | 線索板／UI | 格 s 的值＝格 s 與 s+1 之間的連結：1 實證、2 詭辯、0 無（鏈尾） |
| `debOn` | list string | 引擎 | 場上節點 id，依板面順序（新回復的節點接在最後）。`F<n>`＝脆弱節點；`opponents.tailNode`＝尾聲第二說詞 |
| `debEvents` | list string | 引擎 | 上一次 lock（或狐耳直覺）的事件紀錄，依播放順序（§2.3）；每次 lock 先清空 |
| `debState`、`dwState` | map number | 引擎 | 內部狀態（§3.2）；不要從 UI 讀，讀 §2.1 的輸出 |
| `debSnap`、`debAssisted` | map number | 引擎 | 鍵＝連結格（文字）：被設陷斷開的連結（值＝斷到哪一回合為止）、已被援護擋過的連結 |

`addAll` 會跳過空片段，所以板面三個表用 `-`／`0` 補滿 24 格（`tests/debate_routes.py` 的 `board_layout`）。

### 2.3 事件紀錄

每筆是 `|` 分隔的字串，第一欄是種類；數字以 `%.6g` 寫出，布林寫 1／0，「沒有」寫空字串。播放順序＝ ref `resolve_round` 的事件順序（含 4.7 的大字整理：每回合最多一個全幕大字，取優先序最小者，其餘降為印章並標 demoted）。

| 紀錄 | 欄位 |
|---|---|
| `reveal\|回合\|玩家行動\|對手行動\|演出` | 演出：`player_attack_vs_defense`／`defense_vs_attack`／`clash`／`standoff` |
| `nodeRemoved\|節點\|原因` | `chain`／`parry`／`fragile_hit`／`break`／`tail_void` |
| `nodeAdded\|節點\|種類\|原因` | 種類 `normal`／`fragile`／`second_claim`；原因 `reinforce`／`restate`／`observe`／`tail_start` |
| `dmgOpp\|來源\|量\|前\|後` | `chain`／`counter`／`break`／`tail_finish` |
| `dmgPlayer\|來源\|量\|前\|後` | `claim`／`rush`／`trap_crit`／`tail_wrong` |
| `heal\|量\|前\|後` | 補強未被打中的回復 |
| `contradiction\|數\|節點` | Ch.1 矛盾 |
| `statusGained\|狀態\|方\|回合`、`statusLost\|狀態\|方\|原因` | 狀態 `shaken`／`konju`／`shisshu`／`tail` |
| `hachiku\|前\|後\|預覽` | 每回合一筆（尾聲也有） |
| `cutin\|id\|full 或 stamp\|優先序\|方\|播放全幕\|降級` | 大字與印章（`CUT_*`、`STAMP_*`；`STAMP_HACHIKU_LOST` 是 ref 自訂 id，4.7 沒給） |
| `break\|成功\|via\|標記\|黃金線索`、`tailStarted\|回合\|節點`、`tailResult\|正確`、`breakVoided\|主導權\|失效次數` | 論破與尾聲 |
| `linkSnapped\|卡\|卡\|到第幾回合`、`infamy\|前\|後`、`assistSpent\|浪費` | 設陷與援護 |
| `msg\|字串鍵` | `MSG_DEB_PARRY_BREAK_MISS`、`MSG_DEB_ASSIST_WASTED`、`ASSIST_BLOCKED`、`WARN_DEB_OBSERVE_TAIL` |
| `ended\|結果\|原因` | `opponent_zero`／`player_zero`／`break`／`contradiction_deadline`／`round_cap`／`break_no_tail`／`tail_finish` |
| `wReveal\|回合\|說法\|出示的卡`、`wCorrected\|說法`、`wMistake\|數`、`wAutoCorrected\|說法`、`wEnded\|信任度增減\|獎勵\|失誤數` | 熱身 |

流圖不產生任何顯示文字；UI 依紀錄種類與字串鍵自己組演出與台詞。

### 2.4 劇本表 `debScript`（由遊戲或 harness 提供）

一列一個劇本回合（A-11）。`key`＝`<劇本 id>:<回合>`；`action`（`assert`／`rush`／`reinforce`／`trap`／`scorched`）、`lit`（亮起節點 id）、`scripted`（1＝劇本覆蓋：不更新行為規則記憶）、`clarity`／`shown1`／`shown2`／`star`／`basis`／`lineKey`（預兆）。

- 尾聲回合不查表：一律玉石俱焚、亮起第二說詞、明示、依據 `script`（同 ref `policy.decide_next`）。
- 找不到列（M4b 的 AI 尚未接上）：主張、亮起 `debOn` 第一個節點、`debWarn`＝`WARN_DEB_NO_SCRIPT`。
- 主遊戲目前沒有這張表；接主遊戲前要決定它由 `tools/build_data.py` 產生（教學回合、尾聲之外的固定回合），或在 M4b 由 AI 取代。

## 3. 內部做法

### 3.1 一回合＝一個純函式

Flow 不允許節點圖有環（Kahn 排序含所有節點邊），而且一張圖讀不到自己寫入的 world 值（05 §5.4 自我回音），所以「hp = hp − 傷害」不能用計數器或訊號回授。引擎的做法：

- 狀態全部放在數字 map `debState`（一變數一鍵）。集合查詢節點讀到的是**本 tick 開始時**的內容（08 §8.3.2：效果在下一次求值才看得到），所以一整個回合（A-1 第 1～5 步加下一回合的重述）可以寫成一張無環的純函式圖：輸入＝狀態（`map.get`）、本回合指令（`debCmd*`）、劇本列；輸出＝每個狀態變數的下一個值（`n_<鍵>`，`atrium.expr`）。
- `debLock` 依邊的檔案順序執行效果（05 §5.4：脈衝逐事件、同步深度優先）：清空 `debEvents` → 依 ref 的順序逐筆附加事件紀錄、同時對 `debOn` 做移除／加入（論破時以 `coll.forEach` 逐一記 `nodeRemoved` 後清空）→ 最後對每個鍵 `map.set` 下一個值。沒有任何效果在同一 tick 再讀 `debState`，因此結果與執行順序無關、可重現。
- 有條件的效果走「脈衝閘」（`state` 兩狀態互轉，`guard`＝條件）；條件是 `atrium.expr` 算出的 0／1，再經 `compare ne 0` 轉成布林（Flow 的邊不做數字／布林轉換）。
- 數值與 ref 位元相同：每個倍率照 `ref/rules.py` 的「整數分子／分母、依序」寫成同形的 `atrium.expr`（例：`cd0 = 14 * (10 + 5 * sL + 8 * pL) / 10`、破竹 `x * (10 + stacks) / 10`、猛攻 `x * 5 / 4`）。

修正順序（裁決 B10 與 A-1／A-15）：我方 基礎 → 動搖 ×3/2 → 破竹 ×(10+層)/10 → 交鋒／補強 ×1/2 → 脆弱 +10；對手 基礎 26 + 4n（n＝回合開始時的非脆弱節點，B5）→ 猛攻 ×5/4 → 困獸 ×5/4 → 第 15 回合起 +5 → 觀察 ×1/2；截斷反擊 30 ×(10+層)/10。

### 3.2 狀態鍵（`debState`）

`map.clear` 後全部為 0，`debStart` 只寫非 0 的初值（`act`、`r`、`php`、`ohp`、`as`、`fox`、`soph`）。

| 鍵 | 意義 | 鍵 | 意義 |
|---|---|---|---|
| `act` | 主論戰進行中 | `r` | 回合 |
| `php`、`ohp` | 主導權 | `g1`～`g3` | 節點池第 1～3 個不在場上 |
| `flo`、`fseq` | 已消耗／已產生的脆弱節點數（場上是 `F<flo+1>`～`F<fseq>`） | `sh` | 動搖 0／1／2 |
| `tail`、`tl`、`voids` | 尾聲、剩餘尾聲回合、論破失效次數 | `hk` | 破竹 |
| `kj`、`kjp`、`kjh` | 困獸剩餘回合、截斷條件已用、≤30% 條件已用 | `par` | 截斷次數 |
| `ss` | 失守剩餘回合 | `as`、`fox`、`foxr` | 援護、狐耳直覺、用直覺的回合 |
| `inf`、`con` | 惡名、矛盾 | `over`、`out` | 結束、結果 1 勝／2 敗／3 未達成 |
| `lbl`、`gold` | 論破標記、用過黃金線索 | `soph` | 詭辯對補強算破竹讀對（裁決 B20：Ch.4 起） |
| `lnr`、`lrs`、`nrn`、`man` | 行為規則記憶：上回合移除了節點（規則 1）、補強成功（規則 4）、下回合不能補強、下回合必須攻擊 | `r3f`、`r3p` | 規則 3（≤50%，B9）已觸發／待執行 |
| `nco` | 下一個預兆明示（觀察） | `h1`、`h2`、`lpa` | 對手最近兩手、玩家上一手（+1；0＝無） |

行為規則記憶只有 M4b 的 AI 會用；劇本覆蓋的回合不更新（A-11），與 ref 相同。

### 3.3 熱身（`debate_warmup`）

與主引擎共用 `debCase`、指令訊號、`debStart`、`debLock`、`debBoard`、`debEvents`；各圖只在自己的種類（`debCase.kind` 是否為 `warmup`）下動作，`debStart` 時兩張圖都重設，另一張變為不作用。規則（A-13、B16、ref `warmup.py`）：只開放反駁（其他行動的 lock 被忽略）；出示**一張**在目前說法破解清單內的卡＝糾正，否則失誤（鏈段一律算失誤）；失誤達 `opponents.mistakeLimit`（3）時剩下的說法自動糾正、獎勵取消、信任度 −1；零失誤 +1。

## 4. 規則對應（摘要）

| 規則 | 引擎 |
|---|---|
| A-1 第 1 步 重述 | 結算末尾：依節點池順序補回第一個被移除的節點（B19）；論破後尾聲改擺第二說詞 |
| A-2 節點 | 實證連鎖打中且鏈段含目標的破解證物 → 移除目標；4 張以上再移除一個（板面順序第一個可破解的一般節點，ref 的保守讀法）；截斷移除亮起節點；觀察對上補強／設陷產生脆弱節點；下一次打中的攻擊消耗第一個脆弱節點並 +10（B6）；補強（不論是否被打中）回復一個節點 |
| A-4 對決表 | `half`、`icpt`、`trapped` 等布林式 |
| A-7 設陷／援護 | 詭辯對設陷：最後一個未被援護過的詭辯連結被抓 → 暴擊 25、斷開到下一回合、惡名 +1；援護擋下並標記該連結 |
| A-8 論破 | 前期門檻（強攻 1 張或實證 2 張；每次失效 +1、破竹 3 層 −1，B18）；Ch.1 為 E01_03 且理由正確；論破回合打到 ≤0 鎖在 1（B8）；動搖來源：截斷猛攻、醜聞證物打人物／醜聞節點、4 張以上鏈（前期無破防線） |
| A-9 尾聲 | 犯人玉石俱焚：反駁＋2 張以上、全實證、含第二說詞破解證物的鏈段 → 勝；否則 −30；回合用完 → 失效，對手回到 25%、節點重述 |
| A-13 Ch.1 | 截斷主張、或實證對補強移除節點 → 矛盾 +1；第 2 個矛盾（之後每一個）→ 動搖；R3 結束不足 2 個 → 未達成；R6 結束未論破 → 未達成（D15） |
| A-15 狀態 | 失守 → 破竹 → 困獸 的判定順序；Ch.1 破竹只預覽、Ch.2 只有破竹、Ch.3 全部（`chapters.states`） |

## 5. 衍生表

`tools/gen_debate.py` 由 `data/opponents.json`、`chapters.json`、`nodes.json`、`evidence.json`、`difficulty.json`（`standard`）推導：

- `debCase`（每場論戰一列）：主導權、節點上限、傷害基礎、倍率（分子／分母）、論破與尾聲數值、狀態開關、援護與直覺次數、Ch.1 規則、節點池與第二說詞 id、小動作鍵。資料表沒有的常數寫在產生器裡並註明出處：困獸 ×5/4、動搖 ×3/2、聽眾不耐 15／+5、失效 25%、困獸 30%、規則 3 50%（B9）、困獸 2 回合、Ch.1 論破卡 E01_03、Ch.3 黃金線索主路線 {E03_04, G-01}（B17）。破竹模式：`states` 含 `hachiku` → 2；Ch.1 → 1（預覽）；否則 0。
- `debCard`（每場論戰 × 可用的卡）：鍵 `case:card`；是否破解節點池第 1～3 個與第二說詞、強攻、醜聞、是否為 Ch.1 論破卡、是否屬黃金線索主路線、黃金線索 id。
- `debNode`：節點 id、所屬論戰、池序（尾聲 0）、`case:idx` 鍵、是否帶人物或醜聞類標籤（醜聞動搖用）。
- `debCode`：行動字 → 代碼（玩家 0～3、對手 4～8）。

`check_debate.py` 另外比對 `debCase` 與 ref fixtures 的 `CaseConfig`（主導權、上限、論破、尾聲、狀態、援護、直覺、Ch.1 規則、節點 id）。

## 6. 驗證

`uv run tests/check_debate.py [--route NAME] [--keep] [--verbose]`：重產引擎 → 以 `ref/` 重播 `tests/debate_routes.py` 的每條路線 → 寫 harness → `xtatrium run --game tests/debate_harness --ticks N --dump F` 一次跑完全部路線 → 逐路線、逐回合比對，印 `PASS`／`FAIL`（第一個分歧的回合與欄位）。

- harness 的 driver 每 4 tick 處理 `hIn` 的一列（`start`／`set`／`instinct`／`round`）：第 0 tick 寫指令值、第 1 tick 發脈衝、第 3 tick 把引擎輸出抄進 `hNum`／`hStr`（`<列>:<訊號>`）並把 `debEvents` 抄進 `hEv`；`set` 列直接寫 `debState`，重現 ref 測試以 `replace()` 改過的起始狀態（B8、B9、Ch.3 大字優先序）。
- 比對欄：回合、主導權兩邊、場上節點（含順序）、動搖、尾聲、尾聲回合、失效、破竹、困獸、失守、截斷、矛盾、惡名、援護、結束、結果、論破標記、黃金線索、脆弱節點數，以及**每回合完整的事件紀錄**（逐筆相等）；熱身比回合、索引、失誤、結束、自動、信任度、獎勵與紀錄；狐耳直覺比次數、預兆與 `STAMP_SEEN`。

結果（2026-11-06）：30／30 路線 PASS，case 參數 PASS；harness 115 列、468 tick，載入＋編譯＋執行約 0.7 秒。

| 章 | 路線（ref 測試） |
|---|---|
| Ch.1 | 推薦路線；R2 讀錯仍在時限內完成；兩次讀錯未達成；錯過論破回合後再進入（B21）；R6 上限未達成 |
| Ch.2 | 推薦路線；R4 實證論破吃猛攻；R3 反駁對補強空過；數值卡讀錯代價 5 種（含尾聲觀察 → 論破失效） |
| Ch.3 | 推薦路線；沒有 G-01 的替代論破；R3 反駁對補強；吃滿猛攻 → 失守；第 2 次截斷 → 困獸；大字優先序（動搖蓋過破竹 3）；熱身 5 種 |
| 規則 | 詭辯被設陷暴擊、援護擋下、援護浪費（A-7）；B8 鎖 1；B9 規則 3；狐耳直覺 |

## 7. 已知限制

1. 節點池＝節點上限（Ch.1～3 都是 3 個）：「不在場上」與「被移除」用同一個旗標，`LAST_STAND` 不會出現。Ch.4 起池大於上限時要分開記。
2. 引擎不驗證指令合法性（A-5 選擇器、`MSG_DEB_NOTAG`、斷開的連結、失守中不能反駁、論破門檻不足的反駁鏈段）：那些按鈕由 UI 依同一份資料停用。ref 會丟 `IllegalAction` 的指令，引擎的結果未定義。
3. 每段鏈最多一張黃金線索（`golden` 以字串串接；Ch.1～3 只有 G-01）。
4. 破防 golden（A-8 觸發 3）、手牌回復（漏證）、動機旗標、破防線（中後期）沒有 Ch.1～3 的資料，未實作（ref 亦同）。
5. 預兆只來自劇本列；AI 決策、預兆抽句（`tells` 表）是 M4b。
6. `debLock` 之前的指令值必須已在匯流排上（寫入者同 tick 先執行或更早）；UI 流圖由 `UiSystem` 執行時要比 lock 早一 tick 寫值。

## 8. 待確認

- ref 的補強在被打中時仍回復一個節點（`resolve.py` 第 1 步對每個補強呼叫 `_recover_one`）；Ch.1 R2、Ch.2 R3、Ch.3 R3 的「移除後立刻以 reinforce 補回」都依賴它。A-4 只寫「被打中則無回復」（主導權），節點部分請設計確認。
- `STAMP_HACHIKU_LOST`（破竹中斷的小印章）在 4.7 沒有 id，沿用 ref 的名稱。
