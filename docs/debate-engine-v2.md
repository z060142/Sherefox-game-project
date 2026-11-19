# v2 論戰引擎（D01《守靈夜消失的遺囑》，v2 demo M1）

狀態：M1 草案 2026-11-19。依據：參考模型 `ref/src/sherefox_ref/v2/`（本里程碑的唯一判準：`resolve.py` 的 `resolve_round`、`policy.py` 的 `decide` 與抽籤順序契約、`results.py`、`known.py`）與 `ref/data/d01_debate.json`、`ref/data/d01_extra.json`；設計文字 `00_core_rules.md`、`11_demo_chapter.md` 只作參考。ref 的 SPEC-QUESTION 都是已定的決定，引擎照做。XTAtrium docs 04、05 §5.4、08 §8.2～§8.5a。

本里程碑只有遊戲邏輯：引擎流圖、衍生表與 headless 驗證。沒有 UI，`game.json` 沒有接上這張圖（v1 檔案一律不動）。

E1／E2（2026-11-19）：模糊預兆一律顯示「他若開口，會說」的牌（企劃 898b522，00_core_rules §15〔M2〕；§2.1 `d1TellCard`、§3.4）；亂數改用框架的 `atrium.rng.stream`，論戰有自己的種子 `d1Seed`（§3.4）。

M2（2026-11-19）：`game.json` 已接上（`tools/gen_flows.py` 把 §2 的訊號、集合與衍生表加進去，`flows` 中排在 `d01_debate_ui` 之後），論戰畫面見 `docs/flows.md` §4.12、`docs/ui-contracts.md` d1debate。

## 1. 檔案與產生方式

| 檔案 | 內容 | 產生 |
|---|---|---|
| `flows/d01_debate_engine.xtflow` | 引擎：一回合結算＋下一回合對手決定＋結算結果 | `uv run tools/gen_debate_v2.py`（`--check` 只比對） |
| `data/d01/d1Claim.json` 等 7 張 | 衍生表（§5） | 同上 |
| `tools/gen_debate_v2.py` | 產生器：資料、狀態鍵、規則（以 Python 寫成、逐行對應 ref） | — |
| `tools/v2trace.py` | 追蹤編譯器（§3.1） | — |
| `tests/check_debate_v2.py` | 重產 → 以 ref 重播 → headless harness → 逐回合逐欄比對 | `uv run tests/check_debate_v2.py` |

**資料來源的決定**：產生器直接讀 `ref/data/` 的兩個 JSON，而且透過 ref 自己的載入器（`sherefox_ref.v2.data.load_chapter`：exclusive 雙向合併、breakers 與 breakable_by 合併、`follow_pct = round(behavior.tendency × 100)`）。不在 `data/d01/` 放第二份拷貝，避免引擎與 oracle 對資料的讀法分歧；`data/d01/*.json` 全是衍生表。資料改了就重產（`--check` 會報 stale）。

不要手改產生的 `.xtflow` 與 `data/d01/*.json`。

產生器碰到它沒有建模的資料形狀會停下（`_static_checks`）：出牌順序沒點名的謊言／有利事實（ref 的「依手牌順序補在最後」）、最後一張牌順序不是 `[@pickup, <卡>]`、`opp_refute` 的 via 不是證物也不是卡。

圖的大小：4264 節點／10872 邊（E2 後；M1 的組成：expr 1782、map.set 756、constant 391、gate 329、map.get 282、coll.add 269、lookup 115、coll.remove 114、format 113）。

## 2. 介面

### 2.1 world 訊號

名稱一律 `d1` 前綴。接進主遊戲時照抄 `tools/gen_debate_v2.py` 的 `SIGNALS`。

輸入（debate UI 在脈衝之前寫好；同 tick 先執行的圖或更早）：

| 訊號 | 型別 | 意義 |
|---|---|---|
| `d1Start` | pulse | 開始一場論戰：依攜帶集合重設狀態、抽第 1 回合的對手決定。**攜帶集合（§2.2 的 `d1Carry`、`d1Appraised`、`d1Notes`）要在前一個 tick 或更早寫好**（集合查詢讀到的是 tick 開始時的內容，08 §8.3.2） |
| `d1Warmup` | string | 熱身結果 `pass_clean`／`pass`／`fail`（`d1Warmup` 表；只影響結算的督察好感） |
| `d1Lock` | pulse | 鎖定：結算本回合，抽下一回合的對手決定，論戰結束時算結果 |
| `d1CmdKind` | string | 玩家行動：`argue`（議論：正論／詭辯／心理牌／抓住他的話）、`intercept`（反駁・截斷）、`dismantle`（反駁・拆台）、`stall`（打迷糊仗）、`cut`（終局：截斷他的最後一張牌）、`accept`（終局承受／§7.5 放棄）、`last_stand`（§7.5 玩家自己的最後一張牌）。與 ref `PA` 同字 |
| `d1CmdClaim` | string | 說法 id（`01A`…）；`CATCH` 或 `CATCH:<卡>`＝抓住他的話（`CATCH` 自動對到本回合可抓的卡） |
| `d1CmdTarget` | string | 拆台的目標卡；§7.5 的目標卡（空字串＝不指定，取他鏈上第一張可破的謊言） |
| `d1CmdGuard` | number | 1＝本回合預先啟動援護 |
| `d1Seed` | number | 論戰的種子（整數，\|值\| < 2⁴⁹）：`d1Start` 時以它重設引擎的亂數流（§3.4）。debate UI 在步驟開始時寫入（`docs/flows.md` §4.12） |
| `d1OppAct`、`d1OppCard` | string | **劇本／測試用**：非空時本回合對手照這個行動（與 ref `OA` 同字）與卡出手，不用儲存的 AI 決定。遊戲寫空字串。AI 照樣在鎖定後抽下一回合的決定 |

輸出（引擎寫入 `d1State`，下一 tick 起可讀；全部由 `d1State` 推得）：

| 訊號 | 型別 | 意義 |
|---|---|---|
| `d1Phase` | string | `idle`／`choose`（一般回合）／`endgame`（他要打最後一張牌：截斷或承受）／`laststand`（§7.5：最後一擊或放棄）／`over` |
| `d1Round`、`d1RoundLimit` | number | 下一個要打的回合；回合上限 20（設計裁決：第 20 回合結束仍未分勝負＝聽眾散場，可信度百分比高者勝，最好 4 級） |
| `d1PlayerHp`／`d1PlayerMax`、`d1OppHp`／`d1OppMax` | number | 兩邊可信度 |
| `d1PCombo`、`d1OCombo` | number | 連擊 |
| `d1Hachiku` | number | 破竹層數 |
| `d1Broken`、`d1BrokenUntil` | number | 破防（下一回合生效中）、持續到第幾回合結束 |
| `d1Shisshu` | number | 失守 |
| `d1PsychP/G/A`、`d1PsychEndP/G/A`、`d1ThreshP/G/A` | number | 三條心理量表：目前值（已自然衰退）、上一回合事件後的值（ch §12 的「心理」欄）、門檻 |
| `d1OverP/G/A` | number | 超過門檻：P＝困獸、G＝認罪傾向、A＝怒氣 |
| `d1Cracks`、`d1Denials`、`d1GuardUsed` | number | 裂痕 c、否定事實次數、援護已用 |
| `d1CatchCard` | string | 本回合可「抓住他的話」的卡（空＝沒有） |
| `d1Endgame`、`d1LastCard`、`d1Dying` | string、string、number | 待打的終局回合：觸發 `ronpa`／`zero`、他要打的卡、是否為垂死反撲 |
| `d1LastCardUsed`、`d1PlayerLocked` | number | 他的最後一張牌已打出；§7.5 回合待打 |
| `d1HandCount` | number | 他手上的牌數（含不利事實與保留的撿走證物，不含最後一張牌） |
| `d1Outcome`、`d1Grade`、`d1EndReason` | string、number、string | `win`／`loss`、評級 1～5、結束原因（`REASONS`：`confession`、`zero`、`second_ronpa`、`dying_cut`、`last_card_cut`、`round_limit`…，同 ref） |
| `d1Truth`、`d1RepDelta`、`d1RepAfter`、`d1NextStartHp`、`d1Note`、`d1Paper` | | 結算（ref `results.compute`）：真相度 %、名聲增減、名聲結果、下一場起始可信度加成、筆記版本 `full`／`half`／`wrong`、報紙 `decent`／`normal`／`ugly` |
| `d1TellAction` | string | 他這一手的真正行動（UI 不顯示；給除錯與對手筆記） |
| `d1TellClarity`、`d1TellShown1`、`d1TellShown2`、`d1TellStar` | string | 預兆：`clear`／`vague`；顯示的行動（標準順序 立論、強辯、反駁、周旋；明示只有 Shown1；終局回合 Shown1＝`last`）；★（只標在真正行動上、且只在行為規則指向它時；空＝無） |
| `d1TellCard`、`d1TellPartial` | string、number | 預兆顯示的牌：明示＝他要說的牌（立論／強辯、終局的最後一張牌；不開口時空）；**模糊＝「他若開口，會說」的牌**（00_core_rules §15〔M2〕：他真的開口就是他說的牌〔口誤時是那張不利事實〕，不開口時是回合開始時以立論選牌規則〔不含口誤〕選定、留在手上的牌；無牌可立論時空）。1＝顯示前半句（那張牌是不利事實） |
| `d1TellRule`、`d1TellForced` | number、string | 適用的傾向規則（②①④，0＝無）；強制來源 `rule3`／`rage`／`endgame`／`none` |

### 2.2 集合

| 集合 | 種類 | 寫入者 | 內容 |
|---|---|---|---|
| `d1Carry`、`d1Appraised`、`d1Notes` | list string（unique） | UI | 攜帶的證物、做過的鑑定、找到的人物筆記／觀察（`d1Start` 前一 tick 寫好） |
| `d1State` | map number | 引擎 | 全部狀態（§3.2）；UI 讀 §2.1 的輸出即可 |
| `d1Events` | list string | 引擎 | 上一次 lock 的事件紀錄，依播放順序（§2.3）；每次 lock 先清空 |
| `d1PChain` | list string | 引擎 | 玩家的論證鏈（說法 id，依接上順序；`CATCH:<卡>`＝抓住他的話的節點）。裂痕：`d1State` 的 `pk_<說法>` |
| `d1OChain` | list string | 引擎 | 他的鏈（卡 id，依順序） |
| `d1Hand`、`d1Knocked` | list string | 引擎 | 他的手牌（順序同 ref）、被打下而可周旋重提的謊言 |
| `d1Known` | list string（unique） | 引擎 | 玩家已知項目（攜帶、鑑定、筆記、他說過的駁倒台詞 `said:…`、抓到的不利事實） |
| `d1Record` | list string | 引擎 | 公開紀錄，一筆一行：`回合\|說法\|用法\|詭辯\|裂痕\|真`（用法 `argue`／`intercept`／`dismantle`／`cut`／`last_stand`） |
| `d1ClaimList` | list string | 引擎 | **下一回合**的說法選擇器內容（ref `known.claim_list`）：抓住他的話在最前，其餘依資料順序、只列可用的（攜帶了證物、解鎖條件已知、沒被駁倒作廢）。依證物分組用 `d1Claim.evidence` |
| `d1ClaimSoph`、`d1ClaimCrack`、`d1ClaimStand` | map number | 引擎 | 鍵＝說法 id：顯示為詭辯、會紅色裂痕（與公開紀錄互斥）、已在鏈上（不能再接，仍可用來反駁） |
| `d1Rep`、`d1Favour` | list string | 引擎 | 結束時：名聲細項 `項目\|增減`（`grade_<n>`、`cracks`、`private`、`psych_card`、`stalls`、`denials`）、好感變化 `對象\|增減`（`inspector`、`mrs_hyde`） |

`atrium.ui.list` 可直接以 `d1ClaimList` 為來源，欄位用 `table:d1Claim[id].evidence`、`map:d1ClaimSoph` 等組出清單。

### 2.3 事件紀錄（`d1Events`）

每筆是 `|` 分隔的字串，第一欄是種類；數字 `%.6g`，布林 1／0，「沒有」為空字串或 0。順序＝ ref `resolve_round` 的事件順序（演出與配音照這個順序）。清單型欄位拆成緊跟其後的子紀錄。

| 紀錄 | 欄位 |
|---|---|
| `round\|回合` | 每次 lock 的第一筆 |
| `pAttach\|說法\|連擊\|論證\|基礎\|連擊倍率\|承接\|重提\|破竹\|破防\|承接前一句` | 玩家接上一節。倍率沒套用時寫 1；`承接前一句`＝承接成立時前一個節點的說法（承接台詞用的一對），否則空 |
| `oAttach\|卡\|連擊` | 他接上一節（卡種類查 `d1Card.kind`：不利事實＝口誤） |
| `pDmg\|量\|原因\|後`、`oDmg\|量\|原因\|後` | 原因：`argument`、`exposed`、`refuted`、`contradiction`、`whiff`、`fact_miss`、`stalemate`、`stall_repeat`、`bad_cut`、`dying`、`last_card`／`intercept`、`dismantle`、`whiff`、`stalemate`、`argument` |
| `oHeal\|前\|後`、`healVoid` | 周旋回復；困獸中作廢 |
| `reraise\|卡` | 周旋重提一張被打下的謊言 |
| `redCrack\|說法\|與之矛盾的說法`、`redCrackRemoved\|說法` | 紅色裂痕：第二欄是公開紀錄中最早說過、與它互斥的說法（矛盾台詞用的一對）；子紀錄＝因此從鏈上拿掉的節點 |
| `exposed\|說法`、`refuted\|說法\|駁倒台詞\|變成已知`、`blocked\|說法` | 議論對反駁：被拆穿、被駁倒（台詞 id `REFUTE_D01_*`）、被擋下 |
| `intercept\|說法\|卡\|成功\|抓漏洞\|被周旋擋下` | 截斷 |
| `dismantle\|說法\|卡\|成功` | 拆台 |
| `stall\|他的行動\|連續` | 打迷糊仗 |
| `guardSaved\|後` | 援護生效 |
| `broken\|原因\|到第幾回合` | 破防（`intercepted`、`rebut_whiff`、`crossed_P/G/A`） |
| `hachiku\|前\|後`、`shisshu\|1 或 0` | 破竹變化（只在改變時）、失守開始／解除 |
| `psych\|事件\|ΔP\|ΔG\|ΔA\|P\|G\|A` | 心理事件（`lie_down_proper`、`lie_down_soph`、`fact_down_soph`、`own_rebut_whiff`、`stalled`、`hit_player`、`few_options`、說法的 `heart_knot`／`weakness`／`private`／`psych_card`） |
| `crossed\|P/G/A` | 超過門檻 |
| `ronpa\|keystone 或 chain`、`ronpaNode\|說法` | 論破（子紀錄＝當下的論證鏈） |
| `reverseRonpa`、`reverseRonpaNode\|卡` | 反論破 |
| `endgame\|ronpa 或 zero\|裂痕` | 進入終局 |
| `lastCard\|卡\|被截斷\|垂死\|傷害\|他回到`、`lastCardRemoved\|說法` | 他的最後一張牌；子紀錄＝因此拿掉的有裂痕節點 |
| `lastStand\|說法\|目標\|成功\|可信度`、`lastStandDestroyed\|卡` | §7.5 |
| `rule3Armed` | 規則 ③ 待執行（他第一次 ≤ 50%） |
| `over\|win 或 loss\|評級\|原因` | 論戰結束 |

流圖不產生任何顯示文字；台詞與名稱用 `d1Claim`／`d1Card` 的 loc 鍵（`label`、`line`、`push`、`retract`、`down`、`tell`、`catch`…）。

## 3. 內部做法

### 3.1 一回合＝一個純函式，以追蹤編譯器產生

做法沿用 v1（`docs/debate-engine.md` §3.1）：狀態全部在數字 map `d1State`（一變數一鍵），集合查詢讀到 tick 開始時的內容，所以「本回合＋下一回合的對手決定」是狀態與指令的一張無環純函式圖，`d1Lock` 依邊的順序執行效果，最後每個鍵一個 `map.set`。

和 v1 不同的是寫法。v2 的回合邏輯分支多（四種玩家行動 × 四種對手行動、終局、§7.5、論破、反論破…），所以不手寫運算式，而是在 `tools/gen_debate_v2.py` 用 Python **逐行照 ref 寫一份**，以符號值執行（`tools/v2trace.py`）：

- 數值是運算式節點（`N`），字串是 `S`（常數、`lookup`、`select`、`format`）。資料在產生時代入，所以大部分條件在產生器裡就摺疊掉。
- 對遊戲狀態的分支（`T.when(cond, then, else)`）兩邊都執行，結束時每個改變過的變數以 `cond ? a : b` 合併；單純的 Python `if` 只用在資料（常數）上。
- 每個效果（事件紀錄、清單鏡像的增刪、亂數抽籤、map 寫入）依程式順序記下，守衛＝當下的路徑條件。輸出時連續同守衛的效果共用一個 `atrium.gate`。
- 數值與 ref 位元相同：常數摺疊用 Python float（＝IEEE double），每個運算保留 ref 的運算元順序並完整加括號（例：`d = base × 連擊倍率`、`× 1.2`、`× 0.5`、`× (1 + 0.1 × 破竹)`、`× 1.25`，沒套用的倍率就不乘）。
- 共用或過大的子運算式各成一個 `atrium.expr`，其餘內聯。

### 3.2 狀態鍵（`d1State`）

純量（`SCALARS`）：`act` 進行中、`r` 下一個回合、`php`／`ohp`、`pcb`／`ocb` 連擊、`hk` 破竹、`bu` 破防到第幾回合、`ss` 失守、`p0..2` 心理（衰退後）、`e0..2` 上一回合事件後、`o0..2` 超過門檻、`cr0..2` 曾經超過、`cracks`、`den`、`cc`／`cn` 本回合／下回合可抓的卡（索引 + 1）、`nu` 下一次立論打不利事實、`few` 選項所剩無幾已觸發、`r3f`／`r3p` 規則 ③、`nclr` 下一個預兆明示、`nir` 不能截斷的回合、`sstk`／`stalls` 打迷糊仗、`fps`／`fkl`／`fhp` 規則 ②①④ 的條件、`gu` 援護已用、`priv`、`pcu`、`bz` 雙方歸零、`out` 結果、`grade`、`why`、`eg`／`egc`／`egd` 待打的終局回合、`rdn` 已論破、`rev`、`pl` §7.5 待打、`lcu` 最後一張牌已用、`rl` 保留的最後一張牌、`h1`／`h2` 他最近兩手、`wu` 熱身；結果 `truth`、`nfc`、`kl`、`rdl`、`rpa`、`nhp`、`note`、`paper`。

對手決定（`DEC_KEYS`，描述等待鎖定的那一手）：`da` 行動、`dc` 卡（結算用的真正出牌）、`dcl` 清晰度、`ds1`／`ds2` 顯示的行動、`dst` ★、`dp` 預兆的牌只顯示前半句、`drl` 規則、`dfo` 強制、`dtc` 預兆顯示的牌（§2.1 `d1TellCard`）。

清單與集合以「每一項一個鍵」表示，順序用遞增序號：

| 鍵 | 意義 |
|---|---|
| `pc_<說法>`、`pk_<說法>` | 在玩家鏈上的序號（0＝不在）、該節點有裂痕；抓住他的話的節點鍵是 `pc_CU1` 等 |
| `kc_`、`sd_`、`vd_`、`pu_`、`sn_<說法>` | 被拿掉過（重提 ×0.5）、第一次說出的公開紀錄序號（紅色裂痕與「與之矛盾的說法」）、被駁倒作廢、一場一次的心理作用已觸發、說過幾次（私事好感） |
| `hd_`、`oc_`、`rr_`、`kk_<卡>` | 在他手上的序號、在他鏈上的序號、周旋重提的序號、被打下的序號 |
| `kn_<項目>`（`kn_said<i>`＝第 i 句 `said:`）、`car_<證物>`、`pe_<證物>` | 已知、攜帶、被他撿走 |
| `pcs`、`ocs`、`hs`、`rrs`、`kks`、`rs` | 各序號計數器 |

`d1PChain` 等清單集合是這些鍵的**鏡像**：效果在 ref 改清單的同一點做 `coll.add`／`remove`，所以兩者同序；需要清單內容的事件（`ronpaNode` 等）在那一點用 `atrium.coll.forEach` 逐項寫子紀錄（先寫紀錄、再做移除）。驗證兩者都比（§6）。

### 3.3 進入點

- `d1Start`：清空引擎的清單、依攜帶集合寫初值（撿走證物＝優先序前兩個沒帶的；第一個保留為最後一張牌，其餘進手牌）、抽第 1 回合的對手決定、寫說法選擇器、`map.clear` 後寫全部鍵。
- `d1Lock`（`act` 且未結束時才作用）：清空 `d1Events` → 結算（ref `resolve_round`：一般回合／終局回合／§7.5 回合三選一、規則 ③、回合上限、下一回合開始的衰退與可抓的卡）→ 未結束時抽下一回合的對手決定 → 寫說法選擇器 → 結束時寫 `d1Rep`／`d1Favour` → 每個鍵 `map.set`。

### 3.4 對手 AI 與亂數（ref `policy.decide`）

決定在上一回合結算完就抽好（第 1 回合在 `d1Start`），所以鎖定前已固定。決定圖與 ref 逐條對應：可用行動（手上沒牌就不能立論／強辯；怒氣中只有強辯／反駁，忽略規則 ⑤；規則 ⑤ 連兩次同一行動就換）、規則 ③（強辯＋明示）、傾向規則 ②＞①＞④、清晰度、口誤、基本行動、誘餌、★（只標在真正行動、且只在行為規則指向它時）、出牌順序。

**抽籤只在 ref 抽的時候抽，順序相同**（`policy.py` 的契約：1 傾向是否照做 percent、2 清晰度 weighted、3 基本行動 weighted、4 口誤 percent〔只在他真的開口（立論／強辯）時，00_core_rules §15〔M2〕〕、5 誘餌 uniform）。`weighted` 是 `roll(總權重)` 依標準順序取第一個累計權重大於它的、`percent(p)` 是 `roll(100) < p`、`uniform(xs)` 是 `xs[roll(len)]`。

**模糊預兆的牌**（E1，企劃 898b522）：決定的開頭以立論的選牌規則（`choose_card`，不含口誤；困獸待打的不利事實照算）選出「他若開口，會說」的牌。選牌不用亂數（出牌順序固定），所以不抽籤。他真的開口就說這張（口誤時說那張不利事實、只顯示前半句，所以「欲言又止」仍只出現在他真的開口的回合）；不開口時這張留在手上（`dc` 為 0，只有 `dtc` 帶它）。無牌可立論時誘餌已排除立論／強辯，兩個候選都不開口，`dtc` 為 0。明示預兆照舊（只有開口才帶牌）。不開口而那張牌是不利事實（正常的牌已用完、或困獸待打）時照樣只顯示前半句（§8 待確認 2）。

**亂數流**（E2）：亂數來自框架的 `atrium.rng.stream`（XTAtrium 04 §4.3：每個節點自己的 xoshiro128** 狀態，種子以 SplitMix64 展開，`roll` 推 `[0, n)` 的無偏整數〔Lemire〕再發 `done`；狀態進雜湊與快照），與模擬的全域亂數、執行的種子無關。ref 的 `rng.py` 是它逐位元的 Python 移植（對照序列：種子 0、n＝6 → 4,1,0,3,3,5,1,3；種子 12345、n＝100 → 25,21,77,30,24,83,64,99，見 `ref/tests/test_v2_rng.py`），是 ref 真正的亂數（`play.play(攜帶, 種子)`），不是測試時的替換。

**抽籤的排程：每個抽籤一條流**。一個節點只有一份狀態，而且框架的環判定含脈衝邊（04 §4.3、53 §53.6）：「流的值 → 閘的條件 → 同一個流的 `roll`」是編譯錯誤。契約中後面的抽籤依賴前面抽到的值（基本行動只在傾向沒照做時抽；口誤只在行動是立論／強辯時抽；誘餌的 n＝其餘可用行動數，依行動而定），所以同一個 dispatch 內不可能讓一個節點依序抽完一次決定（`done` 串接也一樣是環）；改成多 tick 依序抽會讓決定晚兩個 tick 才出來，動到 UI 與所有重播的時序。因此 ref 與引擎都用**五條流，契約的每個抽籤一條**（ref `rng.DebateRng`；引擎 `rs_tendency`、`rs_clarity`、`rs_base`、`rs_slip`、`rs_decoy`），第 k 條（k＝契約編號 1..5）的種子＝`d1Seed × 8 + k`：

- 每條流每次決定最多抽一次，抽的時機、條件與 n 和 ref 相同；所以每條流的抽籤序列在 ref 與引擎逐筆相同（各自都是「這個抽籤在這場論戰中依序的第 1、2、…次」），這就是可證明相同的理由。
- 一條流的守衛與 n 只依賴遊戲狀態和**其他**流的值，圖上沒有環；後面的抽籤讀前面的值靠同一派送內的立即推送（`value` 一律推送，值未變亦推）。沒抽的流的值不被使用（以路徑條件 select 掉）。
- `d1Start` 的串接先發 `reset`（五條流以 `d1Seed` 重設；`reset` 不推輸出），再做第 1 回合的決定；`d1Lock` 的決定接著同一組節點的狀態。
- n：在兩個進入點都是同一常數的流（傾向、清晰度、口誤：100）用 param `n`；其餘（基本行動的總權重、誘餌的候選數）的 `n` 輸入接 `toggle` `rsFrom` 選出的值——`d1Start` 的串接第一步 `setTrue`、`d1Lock` 的第一步 `setFalse`，`n ＝ rsFrom ? 開始時的 n : 鎖定時的 n`。

種子的來源（`docs/flows.md` §4.12）：debate UI 在 `d1debate` 步驟開始時取全域 `atrium.rng` 的下一個值 u，寫 `d1Seed ＝ floor(u × 2²⁴)`。重播可重現（全域亂數由執行的種子決定），同一次執行的兩場論戰種子不同。測試直接寫 `d1Seed`（`tests/check_debate_v2.py` 的 harness），`tests/gen_d1_play.py` 的 `d1_bot` 以全域亂數的移植（`check_debate_v2.ui_debate_seed`）預測遊戲會給的種子。

## 4. 規則對應

全部照 ref（`resolve.py` 的每個函式在產生器裡有同名函式：`_use_claim`→`use_claim`、`_player_attach`、`_opp_attach`、`_reraise`、`_psych_step`、`_stance`、`_enter_endgame`、`_endgame_round`、`_last_stand`…）。ref 會丟 `IllegalAction` 的指令，引擎不驗證（不可用的說法、已在鏈上的說法、援護用第二次、不在他鏈上的拆台目標…），結果未定義：那些按鈕由 UI 依 `d1ClaimList`、`d1ClaimStand`、`d1GuardUsed`、`d1OChain` 停用。

## 5. 衍生表（`data/d01/`）

| 表 | 一列 | 欄 |
|---|---|---|
| `d1Claim` | 說法索引（說法依資料順序，之後是每張不利事實的 `CATCH:<卡>`） | `id`、`idx`、`evidence`、`issue`、`true`、`psychCard`、`private`、`catch`、`card`、`label`、`line`（loc 鍵） |
| `d1Card` | 卡 | `id`、`idx`、`kind`（lie／fav／unfav／pickup／last）、`issue`、`lie`、`fact`、`keystone`、`frames`、`source`、loc 鍵 `label`、`state`、`push`、`retract`、`down`、`tell`、`catch` |
| `d1Evidence` | 證物 | `id`、`appraisal`、`opponentUse`、`key`、`psychCard` |
| `d1Code` | 行動字 | `id`、`side`（opponent 0..5／player 0..6）、`code` |
| `d1Warmup` | 熱身結果 | `id`、`inspector`、`appraisalLimit` |
| `d1KnownItem` | 已知項目 | `id`、`key`（狀態鍵） |
| `d1Refute` | 駁倒台詞 | `id`、`reveals` |

規則常數（傷害、倍率、心理事件、門檻、名聲…）由產生器從 ref `model.py` 與資料代入運算式，不另成表。

## 6. 驗證（`uv run tests/check_debate_v2.py [--seeds K] [--route NAME] [--no-play] [--keep DIR] [--verbose]`）

1. 重產引擎。
2. **路線 A～D**：每次執行時從 ref `routes.py` 讀（不快取），以 ref `resolve_round` 強制重播（對手行動照路線表，引擎以 `d1OppAct`／`d1OppCard` 覆蓋；每條路線一個種子 1000＋i，AI 照樣每回合決定，決定也比）。ref 標 xfail 的列也一樣比 ref（ref 是判準，不是章節表）。
3. **ref 機器人對局**：`play.play(攜帶集合, 種子)`，論戰種子 1..K × 7 組攜帶集合（四條路線的，加上 `min`〔3 件、熱身失敗〕、`psych`〔通靈板〕、`liars`〔帶走被撿的證物〕），對手完全由 AI 決定；harness 以 `d1Seed` 給引擎同一個種子（§3.4）。
4. **隨機合法行動對局**（fuzz）：同樣的種子與攜帶集合，玩家每回合從所有候選行動（議論、截斷、拆台每個目標、打迷糊仗、25% 機率加援護、終局的截斷／承受、§7.5 的每個目標）隨機挑一個 ref 接受的（`random.Random` 固定種子），對手同 3。補上 ref 機器人不會走到的拆台、援護、駁倒、§7.5 成功等分支。
5. 每個工作（路線一組、每場對局一組）寫一個 harness 專案到暫存目錄，平行 `xtatrium run --seed S --dump`；driver 每 4 tick 一列：第 0 tick 寫指令、種子與攜帶集合、第 1 tick 發脈衝、第 3 tick 把 `d1State`、三張說法 map、全部清單集合與輸出訊號抄進 `hNum`／`hStr`／`hList`（第 0 列閒置：tick 0 的 compare 不發脈衝）。
6. 每回合比對：ref `State` 的每個欄位（由狀態鍵解碼：鏈與手牌依序號排序、已知集合…）、清單鏡像（`d1PChain`、`d1OChain`、`d1Hand`、`d1Knocked`、`d1Known`、`d1Record`）、**完整事件紀錄**（ref 事件依 §2.3 轉寫，逐筆相等）、下一回合的說法選擇器與三個旗標、下一回合的對手決定（行動、卡、預兆的牌、清晰度、顯示、★、前半句、規則、強制）與 `d1TellAction`、`d1TellCard`；結束時比 `results.compute`（評級、原因、回合數、真相度、假說法數、遺漏關鍵證物數、名聲細項與總和、下一場加成、好感、筆記、報紙）。印 PASS／FAIL（第一個分歧的回合與欄位）。

結果（2026-11-19，E1／E2 之後：`atrium.rng.stream`、模糊預兆帶牌、口誤只在開口時判定）：

- `--seeds 4`（預設）：60／60 PASS（路線 4＋機器人 28＋fuzz 28），57 次 harness 執行約 4 秒。
- `--seeds 40`：564／564 PASS（路線 4＋280 場機器人＋280 場 fuzz），561 次 harness 執行約 40 秒。涵蓋同 M1（議論／截斷／拆台／打迷糊仗、拆穿、駁倒、紅色裂痕、承接、重提、破竹、失守、反論破與 §7.5、論破與歸零、垂死反撲、最後一張牌、二次終局、投降、回合上限、規則 ③、怒氣、口誤、選項所剩無幾、心結／弱點／私事／心理牌），另加模糊預兆不開口時的牌。
- 變異檢查（M1）：拆台傷害 10→11、口誤 30%→31% 都被抓到。E2 另做兩個：口誤照舊在行動決定前抽（不論開不開口）、基本行動與誘餌互換流，都在預設的 4 個種子內被抓到（決定的卡／行動不同）。

## 7. 已知限制與框架能力需求

1. ~~沒有可設種子的亂數節點~~：XTAtrium AT-091 `atrium.rng.stream` 已出貨並採用（§3.4）。一個節點無法在同一 dispatch 內依自己前一次的值決定要不要再抽（環判定含脈衝邊），所以用「每個抽籤一條流」；這不是缺口，ref 同樣這樣抽。
2. 純函式圖裡沒有清單值：集合查詢在同一 tick 看不到效果，所以鏈、手牌、已知等改成「每項一鍵＋序號」（§3.2），UI 用的清單另以效果維持鏡像。這是 v1 架構的延伸，不需要框架改動，狀態鍵 282 個（`map.set` 756 個，含開始、鎖定兩條路徑與說法選擇器的 map）。
3. bool 輸出接 number 輸入要經 `select`（Flow 的邊不轉型）；`compare` 在 tick 0 的第一次求值不發 `true` 脈衝（harness 第 0 列閒置）。兩者都不影響遊戲。
4. 引擎不驗證指令合法性（§4）。
5. 產生器只建模 D01 的資料形狀（§1 的停止條件）；其他章節的資料若出牌順序不點名卡、或最後一張牌順序不同，要擴充產生器。

## 8. 待確認

1. M1：沒有（ref 的 SPEC-QUESTION 都已定）。
2. E1：模糊預兆時他不開口，而「會說」的那張是不利事實（正常的牌已用完，或困獸待打的不利事實）：照他開口時的樣子只顯示前半句（「欲言又止」）。這是保守讀法（論點框與他開口時一樣，不洩漏開不開口），但 §15 說「欲言又止」只出現在他真的立論的回合，兩者在這個情形衝突，待企劃確認。
3. E1：「說溜嘴的判定只在他真的立論時進行」的「立論」照原本的口誤規則讀成立論或強辯（開口）；若企劃的意思是只有立論，強辯時不再口誤。
4. E2：論戰的亂數用每個抽籤一條流（§3.4），種子由一個論戰種子導出；設計只說「每次遊玩一個種子」，這是實作上的分法。
