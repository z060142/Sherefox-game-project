# 論戰引擎（M4a：回合結算；M4b：對手 AI）

狀態：M4b 草案 2026-11-06。依據：系統規格附錄 A（A-1 結算順序、A-2、A-4 對決表、A-5～A-15）、數值總表、`docs/rulings.md`（A*、B*、C*、D15）、參考模型 `ref/`（本里程碑的唯一判準：設計文字與 `ref/`＋裁決不一致時以後者為準）；XTAtrium docs 04、05 §5.4、08 §8.2、§8.3、§8.5。

本文件說明論戰引擎的介面（給之後的 debate UI 流圖）、內部做法、資料、驗證與已知限制。引擎有回合結算、熱身與對手 AI（M4b：A-3 的行動選擇與預兆，§3.4）；劇本列（A-11）與尾聲仍覆蓋 AI。尚未接 UI、不接主遊戲的步驟序列（`debate`／`warmup` 步驟仍是 `stubs`）。

## 1. 檔案與產生方式

| 檔案 | 內容 | 產生 |
|---|---|---|
| `flows/debate_engine.xtflow` | 主論戰（布丁論戰、Ch.2、Ch.3）回合結算 | `uv run tools/gen_debate.py`（`--check` 只比對） |
| `flows/debate_warmup.xtflow` | 熱身小論戰（A-13） | 同上 |
| `data/debate/debCase.json`、`debCard.json`、`debNode.json`、`debCode.json`、`debLine.json` | 引擎用的衍生表（§5），由 `data/*.json` 推導 | 同上 |
| `tests/debate_routes.py` | 路線定義、以 `ref/` 重播得到每回合預期值、產生 harness 輸入表 | — |
| `tests/check_debate.py` | 重產 → 建 harness → headless 執行 → 逐回合比對 | `uv run tests/check_debate.py` |
| `tests/debate_harness/` | harness 專案（`game.json` 與 `flows/`、`data/` 全由 `check_debate.py` 產生，不要手改） | 同上 |
| `tests/check_policy.py` | 對手 AI 的統計與規則驗證（§6.2） | `uv run tests/check_policy.py` |
| `tests/policy_harness/` | 對手 AI 的 harness 專案（全由 `check_policy.py` 產生） | 同上 |

不要手改產生的 `.xtflow` 與 `data/debate/*.json`；改 `tools/gen_debate.py` 再重產。

| 圖 | 節點／邊 |
|---|---|
| `debate_engine` | 1180／2441（M4c：`debOppBonus` +1 節點）；M4b 為 1179／2438（expr 375、table.get 141、compare 123、state 88、map.set 81、coll.add 69、map.get 54、format 53；M4a 為 966／1954，AI 約 +213） |
| `debate_warmup` | 179／289 |
| harness `driver`（`check_debate`） | 164／285 |
| harness `driver`（`check_policy`） | 106／158 |

## 2. 介面

### 2.1 world 訊號

名稱不可含 `.`，一律 `deb` 前綴（熱身 `dw`）。接進主遊戲時照抄進 `game.json` 的 `signals`（`tools/gen_debate.py` 的 `SIGNALS`）。

輸入（由 debate UI 流圖寫入）：

| 訊號 | 型別 | 意義 |
|---|---|---|
| `debCase` | string | 論戰 id＝`opponents.id`（`CH01_MAIN`、`CH02_MAIN`、`CH03_MAIN`、`CH03_WARMUP`） |
| `debScript` | string | 劇本 id（`debScript.key` 的前綴）；空字串＝用 `debCase` |
| `debStart` | pulse | 開始一場論戰：重設狀態、擺上第 1 回合的節點（A-1 第 1 步：節點上限）、抽第 1 回合的對手決定（§3.4）。`debCase` 與板面集合要先寫好（同 tick 且寫入者先執行，或更早） |
| `debCmdKind` | string | 本回合玩家行動：`solid`／`sophistry`／`rebut`／`observe`（與 `opponents.playerActions` 同字） |
| `debCmdFrom`、`debCmdTo` | number | 鏈段的起訖板面格（§2.2，含兩端，`From > To`＝反向）；沒有鏈段為 −1。單張卡的「鏈段」（例：Ch.1 論破回合以反駁出示 E01_03）是 `From = To` |
| `debCmdCard` | string | 反駁的單張卡 id（`pa.card`）；用鏈段反駁（論破回合、尾聲）時為空字串 |
| `debCmdTarget` | string | 攻擊目標節點 id；空字串＝亮起的節點 |
| `debCmdAssist` | number | 1＝本回合預先啟動援護（鎖定前下注，A-7） |
| `debOppBonus` | number | 對手主導權起始值與最大值的加成（漏證，01-systems §1.8、裁決 D4：漏證數 × `opponents.hpPerMissed`）；只在有主導權的論戰生效（`c_oMax`＝`debCase.oMax`＋此值），由 debate UI 在 `debStart` 前寫好並保持到論戰結束（M4c） |
| `debInstinct` | pulse | 鎖定前使用狐耳直覺（A-3）：模糊預兆改為明示真正行動，次數 −1，發 `STAMP_SEEN` |
| `debLock` | pulse | 鎖定：結算本回合（A-1 第 2～5 步）、重述下一回合（第 1 步）並抽下一回合的對手決定（第 6 步，§3.4）。指令值要在 lock 之前寫好，而且保持到引擎處理該脈衝的 tick（§7 第 6 點） |
| `debRedecide` | pulse | 只給測試用（`check_policy.py`）：以目前儲存的狀態重抽本回合的對手決定，只寫決定鍵（§3.4）。遊戲不送 |

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
| `debTellClarity`、`debTellShown1`、`debTellShown2`、`debTellStar`、`debTellBasis`、`debTellLit`、`debTellGesture`、`debTellLine` | string | 本回合（等待鎖定的那一手）的預兆。來源依序：尾聲＝明示＋`script`；用過狐耳直覺＝明示＋`fox`；有劇本列＝該列；否則＝對手 AI 的決定（§3.4）。`Shown1`／`Shown2`＝模糊的左右兩個候選（明示只有 `Shown1`）；`Star`＝標 ★ 的行動；`Basis`＝依據小銅牌 `tutorial`／`observe`／`rule3`／`konju`／`script`／`fox` 或空字串；`Gesture` 是**真正行動**的小動作鍵（A-3）；`Line`＝預兆台詞的字串鍵（`tells.id`） |
| `debTellStarRule` | number | ★ 旁的規則編號（1／2／4；0＝沒有 ★） |
| `debTellRule` | number | AI 這一手適用的行為規則（1～4；0＝無），給對手筆記；劇本列與尾聲為 0 |
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

一列一個劇本回合（A-11）。`key`＝`<劇本 id>:<回合>`；`action`（`assert`／`rush`／`reinforce`／`trap`／`scorched`）、`lit`（亮起節點 id）、`scripted`（1＝劇本覆蓋：不更新行為規則記憶）、`clarity`／`shown1`／`shown2`／`star`／`starRule`（number）／`basis`／`lineKey`（預兆）。

- 優先序：尾聲 > 劇本列 > 對手 AI。尾聲回合不查表：一律玉石俱焚、亮起第二說詞、明示、依據 `script`（同 ref `policy.decide_next`）；台詞從該案 `tells` 的 `endgame:scorched` 組抽（§3.4）。
- 有列的回合整個預兆與行動都照列（AI 仍會抽，但不用；規則 3 的待執行旗標不被消耗，§3.4）。`scripted` 為 0 的列（harness 路線用）照樣更新行為規則記憶。
- 找不到列：用 AI 的決定（M4a 的 `debWarn`／`WARN_DEB_NO_SCRIPT` 已移除）。
- 主遊戲（M4c）：`data/debScript.json` 由 `tools/build_data.py` 產生，只有裁決 G2 的 Ch.1 R1～R3（`CH01_MAIN:1` 主張 N1 `SCR_CH01_S90_L003`、`:2` 補強 N2 `L006`、`:3` 主張 N3 `L005`；明示、依據 `tutorial`、`scripted` 1）；R4 起回到 AI。debate UI 一律寫 `debScript` ＝空字串（劇本 id ＝ `debCase`）。測試用的劇本對手（`tests/play_harness`）是同一張表加上 `CH02_MAIN:<回合>` 的列，不改遊戲資料。

## 3. 內部做法

### 3.1 一回合＝一個純函式

Flow 不允許節點圖有環（Kahn 排序含所有節點邊），而且一張圖讀不到自己寫入的 world 值（05 §5.4 自我回音），所以「hp = hp − 傷害」不能用計數器或訊號回授。引擎的做法：

- 狀態全部放在數字 map `debState`（一變數一鍵）。集合查詢節點讀到的是**本 tick 開始時**的內容（08 §8.3.2：效果在下一次求值才看得到），所以一整個回合（A-1 第 1～5 步加下一回合的重述）可以寫成一張無環的純函式圖：輸入＝狀態（`map.get`，含上一次抽好的對手決定）、本回合指令（`debCmd*`）、劇本列；輸出＝每個狀態變數的下一個值（`n_<鍵>`，`atrium.expr`），以及由下一狀態與 7 個亂數算出的下一回合對手決定（§3.4）。`atrium.rng` 是事件型節點：觸發時立即推值，後面的 `map.set` 脈衝送出前已結算，所以同一次 lock 內就能寫入。
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
| `pln` | 剛結算的回合顯示的預兆台詞（`debLine` 列 + 1；0＝無），「不連續兩回合同一句」用 | | |

對手決定鍵（§3.4，`debStart`／`debLock`／`debRedecide` 寫入，描述本回合等待鎖定的那一手）：

| 鍵 | 意義 | 鍵 | 意義 |
|---|---|---|---|
| `da` | 行動代碼 0 主張／1 猛攻／2 補強／3 設陷／4 玉石俱焚 | `dlit` | 亮起的節點池序 1～3（0＝無） |
| `dcl` | 清晰度 0 明示／1 模糊 | `ds1`、`ds2` | 顯示的候選（代碼 + 1；明示時 `ds2`＝0） |
| `dst`、`dsr` | ★ 的行動（+1）與規則編號（0＝無） | `db` | 依據 0 無／1 tutorial／2 observe／3 rule3／4 konju |
| `dru` | 適用的規則 1～4（0＝無） | `dln` | 預兆台詞的 `debLine` 列 + 1（0＝無） |

行為規則記憶只有 AI 會用；劇本覆蓋的回合不更新（A-11），與 ref 相同。

### 3.3 熱身（`debate_warmup`）

與主引擎共用 `debCase`、指令訊號、`debStart`、`debLock`、`debBoard`、`debEvents`；各圖只在自己的種類（`debCase.kind` 是否為 `warmup`）下動作，`debStart` 時兩張圖都重設，另一張變為不作用。規則（A-13、B16、ref `warmup.py`）：只開放反駁（其他行動的 lock 被忽略）；出示**一張**在目前說法破解清單內的卡＝糾正，否則失誤（鏈段一律算失誤）；失誤達 `opponents.mistakeLimit`（3）時剩下的說法自動糾正、獎勵取消、信任度 −1；零失誤 +1。

### 3.4 對手 AI（A-3、數值總表 四；ref `policy.decide_next`）

決定在**上一回合結算完**就抽好（A-1 第 6 步；第 1 回合在 `debStart`），存進決定鍵（§3.2），所以對手的行動在玩家鎖定前已經固定（系統規格 4.4「對手不看牌」）。同一張決定圖有三個入口，由 `state` 節點 `dMode` 選輸入：`debLock`＝剛算出的下一狀態 `n_*`（含重述後的節點）、`debStart`＝初始狀態、`debRedecide`＝已儲存的狀態 `s_*`。每個入口都依序觸發 7 個 `atrium.rng`（不論用不用得到；值域 [0, 1)，來自 `Simulation.Rng`）：

| 抽 | 用途 |
|---|---|
| u1 | 傾向規則照做？`u1 × 100 < ruleBias`（80） |
| u2 | 行動（加權） |
| u3 | 清晰度：`u3 × (明示 + 模糊) ≥ 明示` → 模糊 |
| u4 | 模糊的誘餌（加權） |
| u5 | 模糊的左右順序：`u5 ≥ 0.5` → 誘餌在左 |
| u6 | 亮起節點：`floor(u6 × 可見節點數)`，依節點池順序 |
| u7 | 預兆台詞（均勻；排除上一回合那一句） |

加權抽：`t = u × Σw`，依固定順序（主張、猛攻、補強、設陷）取第一個累計權重 > t 者；與 ref `RngChooser` 的順序相同，只是 ref 用 SplitMix64 的 `roll(total)`，引擎用 xoshiro128** 的浮點，所以**數值序列不同、分布相同**（驗證以統計比對，§6.2）。

決定順序（與 ref 逐條對應）：

1. 尾聲：玉石俱焚（`da`＝4），預兆由讀取端給明示＋`script`、亮起第二說詞；只抽台詞。
2. 可用行動＝權重 > 0（Ch.1 亞瑟 25／0／50／0，裁決 D7：沒有猛攻與設陷）。刪去：規則 5（同一行動連續兩次，含劇本回合與尾聲的行動）、「不能補強」（實證對上設陷）、困獸中（不補強，A-15）。
3. 強制：規則 3（`r3p`：主導權第一次 ≤ 50%，B9）→ 猛攻、明示、依據 `rule3`；否則觀察拆穿陷阱（`man`）→ 依性格在主張／猛攻（扣掉規則 5 刪去的；全被刪時不刪）中抽、明示、依據 `observe`。
4. 傾向規則 1（`lnr`→補強）、2（玩家上一手詭辯→設陷）、4（`lrs`→主張）：取編號最小、且指向的行動沒有被刪去者；80% 照做，否則依性格從全部可用行動抽（B11，可能抽到同一個）。
5. 清晰度：教學章（`tut`，Ch.1）＝明示＋`tutorial`（蓋過 rule3／observe 依據）；強制＝明示；上一回合觀察且對手攻擊（`nco`）＝明示＋`observe`；否則依配比抽（Ch.2～3 60／40；偽裝未實作）。困獸中、沒有依據的模糊改為明示＋`konju`。
6. 模糊：有傾向規則時 ★＝規則指向的行動（B12），它不是真正行動時就是誘餌；否則誘餌依性格從其餘可用行動抽；沒有合法誘餌時改為明示（ref 的 SPEC-QUESTION）。
7. 亮起節點：重述後可見的一般節點中均勻抽（B13；脆弱節點不算）。
8. 台詞：該行動在 `debLine` 的那一組（`tells` 表 `tell:<行動>`；尾聲 `endgame:scorched`）中均勻抽，排除上一回合顯示的那一句（系統規格 4.4「不會連續兩回合重複同一句」；上一句可以來自劇本列的 `lineKey`）。小動作＝真正行動的鍵（`debCase.g0`～`g3`）。

規則 3 的待執行旗標：ref 在 `decide_next` 選出規則 3 時清掉它；引擎改在**打出那一手的回合鎖定時**清（`r3used`＝該回合用了 AI 決定且 `dru`＝3），效果相同，且 `debRedecide` 之前仍看得到旗標。下一回合是劇本列或尾聲時旗標不被消耗，尾聲失效後才觸發（同 ref）。

狐耳直覺照舊：只對模糊（劇本列或 AI 的）有效，用後預兆改為明示＋`fox`、顯示真正行動。

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
- `debCase` 的 AI 欄（§3.4）：`w0`～`w3`（`opponents.w_*`；0＝不可用）、`cC`／`cF`（明示／模糊配比）、`tut`（教學章：Ch.1 布丁論戰）、`fol`（`ruleBias` 80）、`ru1`～`ru5`（`opponents.rules`）、`lb0`～`lb4`／`lc0`～`lc4`（各行動台詞組在 `debLine` 的起始列與句數）。有偽裝配比的主論戰會讓產生器停下（ref 亦未實作）。
- `debLine`：`tells` 表中每場論戰、每個行動代碼（0～3 `tell:<行動>`，4 `endgame:scorched`）的台詞，依 `n` 排序、連續存放；欄 `id`、`case`、`code`、`n`。`inactive` 的列不收。

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

路線全部用劇本列給對手行動（`scripted` 0：照樣更新行為規則記憶），所以 AI 不影響這 30 條路線。`check_debate.py` 另外比對 `debCase` 的 AI 欄與 ref 的 `OpponentProfile`（可用行動、權重、規則、清晰度配比、教學、80%）。

### 6.2 對手 AI（`uv run tests/check_policy.py [--samples N] [--seeds K] [--verbose]`）

1. **情境**：每個情境＝起始狀態＋以劇本列重播的前置回合（同 `debate_routes`）＋必要時以 `set` 改狀態鍵（ref 端以 `replace()` 做同樣的改動）。oracle：對 ref `decide_next` 列舉每個選擇（`weighted` w／Σw、`percent` p／100、`uniform` 1／n，`Fraction` 精確），得到每個結果（行動、清晰度、左右順序的候選、★、★ 規則、依據、亮起節點、適用規則）的機率。
2. **引擎**：harness（`tests/policy_harness/`，每 tick 一步的 driver）在情境最後一次 `debStart`／`debLock` 抽一次，之後以 `debRedecide` 重抽；`--seed 1..K` 平行跑 K 次（預設 4 × 1000 ＝ 每情境 4000 次）。每次決定記下決定鍵與預兆輸出。
3. **比對**：每個結果、亮起節點、台詞的觀察頻率對精確機率，|z| ≤ 4（z ＝ (k − Np)／√(Np(1−p))）；ref 機率 0 的結果一次都不能出現、機率 1 的必須每次出現。4σ：全部約 300 格，正確的引擎任一格超標的機率約 2%；而裁決層級的錯誤（例：B11 的 80% 對 84%）在 N＝4000 時約 7σ。台詞的預期：該行動的組內均勻、排除上一句。
4. **自由對局**：Ch.1～3 各 30 場 × 4 種子，對手完全由引擎的決定驅動（沒有劇本列），玩家行動固定（觀察／實證／詭辯的種子序列）；每一手在 ref 以引擎的行動重播，並檢查該決定在 ref 的狀態下可能出現（含亮起節點可見、行動合法）。
5. **規則斷言**（每個決定）：行動可用且未被刪去（規則 5、不能補強、困獸）；規則 3＝猛攻＋明示＋`rule3`；觀察拆穿陷阱＝攻擊＋明示＋`observe`；教學章全部明示＋`tutorial`；模糊＝真正行動＋1 個合法誘餌；★ 只在模糊、只有規則 1／2／4、一定在候選中；沒有 ★ 的模糊沒有傾向規則；亮起節點可見且非脆弱；台詞屬於該行動、不等於上一句（自由對局：連續兩回合）；預兆輸出＝決定（有劇本列時＝該列）；每筆紀錄的回合數正確（確認取樣時機）。

結果（2026-11-06，`--seed 1..4`，每情境 N＝4000）：25／25 情境 PASS，規則斷言 0 失敗（約 10 萬個決定），自由對局 2053 手全部在 ref 的支撐集內；產生＋執行約 30 秒。

| 情境 | 規則分支 | 期望／觀察（行動；模糊比例） | max\|z\| |
|---|---|---|---|
| ch2_open | 第 1 回合，性格 45／15／20／20、60／40 | 主張 .450／.451、猛攻 .150／.143、補強 .200／.203、設陷 .200／.203；模糊 .400／.397 | 1.83 |
| ch2_rule1 | 規則 1：80% ＋ 20% 性格（B11） | 補強 .840／.840 | 2.25 |
| ch2_rule4_prevline | 規則 4；上一句 L003 排除 | 主張 .890／.887 | 2.66 |
| ch2_rule2 | 規則 2（玩家詭辯） | 設陷 .840／.841 | 3.65 |
| ch2_rule1_beats_4 | 規則 1 與 4 同時：編號小者 | 補強 .840／.854 | 2.46 |
| ch2_rule1_deleted_nrn | 不能補強刪去規則 1 → 規則 4 | 主張 .912／.904、補強 0／0 | 2.02 |
| ch2_rule1_deleted_rule5 | 補強連兩次刪去規則 1 → 性格 | 主張 .562／.554、猛攻 .187／.197、設陷 .250／.249 | 2.07 |
| ch2_rule5_observe | 主張連兩次＋觀察過攻擊 | 猛攻 .273／.275、補強 .364／.355、設陷 .364／.370；全明示 | 1.65 |
| ch2_must_attack | 拆穿陷阱 → 必定攻擊 45：15 | 主張 .750／.756、猛攻 .250／.244 | 2.10 |
| ch2_must_attack_rule5 | 必定攻擊＋主張被規則 5 刪去 | 猛攻 1／1 | 1.30 |
| ch2_no_reinforce | 陷阱落空（含規則 1 刪去） | 主張 .562／.577、猛攻 .187／.188、設陷 .250／.235 | 2.48 |
| ch2_rule3 | 規則 3（≤50%，蓋過規則 1） | 猛攻 1／1、明示 `rule3` | 3.03 |
| ch2_route_r4 | 推薦路線 R4 前 | 補強 .840／.836 | 1.56 |
| ch2_tail | 尾聲 | 玉石俱焚 1／1；台詞 2 句各 .5 | 0.82 |
| ch2_after_void_rule3 | 論破回合觸發的規則 3 撐過尾聲、失效後才出 | 猛攻 1／1，亮 N1 | 1.60 |
| ch2_scripted_no_memory | 劇本回合不設規則 1（A-11） | 同 ch2_open | 2.46 |
| ch2_script_override | 劇本列覆蓋預兆輸出 | 輸出＝劇本列（404／404） | 2.16 |
| ch3_open | Ch.3 第 1 回合 | 主張 .450／.440 | 2.48 |
| ch3_konju_rule3 | 困獸＋HP 40：規則 3 優先 | 猛攻 1／1 | 1.16 |
| ch3_konju | 困獸（規則 3 已用）：不補強、模糊 → 明示 `konju`；主張被規則 5 刪去 | 猛攻 .429／.412、設陷 .571／.588；`konju` 依據 .400／.399 | 1.69 |
| ch3_route_r4 | 推薦路線 R4 前（裁決 A3） | 補強 .840／.835 | 2.04 |
| ch3_shisshu | 失守後 | 補強 .840／.837 | 3.03 |
| ch1_open | 亞瑟第 1 回合 25／50（D7）、教學明示 | 主張 .333／.342、補強 .667／.658 | 1.57 |
| ch1_rule1 | 亞瑟規則 1 | 補強 .933／.932 | 1.89 |
| ch1_rule4 | 亞瑟規則 4 | 主張 .867／.862 | 1.78 |

## 7. 已知限制

1. 節點池＝節點上限（Ch.1～3 都是 3 個）：「不在場上」與「被移除」用同一個旗標，`LAST_STAND` 不會出現。Ch.4 起池大於上限時要分開記。
2. 引擎不驗證指令合法性（A-5 選擇器、`MSG_DEB_NOTAG`、斷開的連結、失守中不能反駁、論破門檻不足的反駁鏈段）：那些按鈕由 UI 依同一份資料停用。ref 會丟 `IllegalAction` 的指令，引擎的結果未定義。
3. 每段鏈最多一張黃金線索（`golden` 以字串串接；Ch.1～3 只有 G-01）。
4. 破防 golden（A-8 觸發 3）、手牌回復（漏證）、動機旗標、破防線（中後期）沒有 Ch.1～3 的資料，未實作（ref 亦同）。
5. AI 沒有偽裝（維多、Wolfhart）與鏡像（維多）：Ch.1～3 沒有，ref 也沒有；`opponents.disguise` > 0 的主論戰會讓產生器停下。
6. `debLock` 之前的指令值必須已在匯流排上（寫入者同 tick 先執行或更早），而且要**保持到引擎處理脈衝的那個 tick**：實測（`check_policy.py` 的 driver 與一個兩張圖的探針）載入順序在前的圖送出的 world 脈衝，後面的圖晚一個 tick 才收到，值則同 tick 可見，所以同 tick 寫值＋送脈衝、下一 tick 又改值的寫法會讓引擎讀到新值。UI 流圖由 `UiSystem` 執行時同樣要比 lock 早寫值並保持一 tick。
7. 引擎的亂數序列與 ref 的 SplitMix64 不同（§3.4），同一個種子不會得到 ref 的同一手；驗證只比分布（§6.2）。抽法固定為每次決定 7 次，與用不用得到無關，所以抽數不會因分支而變。
8. `debRedecide` 只為測試存在（從儲存的狀態重抽）；遊戲送它會改掉玩家已看到的預兆。

## 8. 待確認

- ~~補強被打中時的節點回復~~：已裁決 G1（不論是否被打中都回復 1 個節點）。
- ~~**Ch.1 對手是 AI 還是劇本**~~（已裁決 G2：R1～R3 劇本列，見 §2.4）：本里程碑依 ref 與資料做成 AI（亞瑟 25／0／50／0、規則 1／4、全部明示＋教學，§3.4）。依據：各章設計 Ch.1 有完整的對手行為表（基本傾向、規則 1／4、小動作、明示 100%）與「亞瑟依規則 4 下一手改主張」的常見失誤；A-13「完整的同時出招制」；裁決 D7 定權重（劇本對手不需要權重）；ref `ch1_case` 是 AI 對手，ref 測試只驗證推薦路線的預兆「可能出現」。但系統規格 7.2 的引導教學寫死了對手的行動：TUT_01_12（第 1 回合挺胸叉腰說一覺睡到天亮＝主張 N1）、TUT_01_15（第 2 回合拉袖子＝補強）、TUT_01_17（動搖後「他又要開口了：用反駁對準最後一個主張」）。在 AI 下第 1 回合主張只有 1／3，第 2 回合（規則 1）補強 .933，動搖後的論破回合（N2 剛被移除、規則 1）主張只有 .067，TUT_01_17 有 93% 的機率說錯，而引導教學會鎖住其他操作；推薦路線的 R1 台詞也指定是 L003。請設計決定：(a) Ch.1 R1～R3（或引導教學出現的回合）是「教學指定的回合」，以劇本列固定（`debScript` 由 `tools/build_data.py` 依推薦路線產生：R1 主張 N1 L003、R2 補強 N2 L006、論破回合主張 N3 L005，明示＋`tutorial`；偏離推薦路線之後是否回到 AI 也要定），或 (b) 維持 AI、改寫 TUT_01_12／15／17 為不指定行動的說法。引擎兩種都支援，資料未產生。
- 尾聲的預兆台詞：引擎從 `tells` 的 `endgame:scorched` 組（Ch.2 L026／L027、Ch.3 L026／L027）抽，與推薦路線 R5 的台詞（L026）一致，但劇本沒有標明這兩句是預兆台詞還是行動台詞。
- 模糊預兆找不到合法誘餌時（可用行動只剩 1 個）改為明示，沿用 ref 的 SPEC-QUESTION；Ch.1～3 只有亞瑟會遇到，而亞瑟全部明示，實際不會發生。
- `STAMP_HACHIKU_LOST`（破竹中斷的小印章）在 4.7 沒有 id，沿用 ref 的名稱。
