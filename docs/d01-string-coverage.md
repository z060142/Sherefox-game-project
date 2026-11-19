# D01 字串覆蓋表（v2 demo E7）

狀態：2026-11-20，設計 repo v2 分支 fdbf90c（含 4ac5faf）。來源 `source/localization/d01/` 四個檔，共 727 個 ID。

- 檢查：`uv run tests/check_d1_strings.py`（靜態）：每個 ID 不是被流圖、板子、資料表（劇本表只算 vn 會播的列）或產生器的樣式引用，就必須在 `NOT_DISPLAYED`（附理由）上；設計新增的字串沒人用、清單上的 ID 被用了或不存在，都算失敗。
- 實測：D01 各檢查以 `SHEREFOX_TEXTLOG=<dir>` 執行後，`check_d1_strings.py --coverage <dir>` 把每個 ID 的中英文文字對到 port 上出現過的值。本表依 E7 落地後的實測：685 個要顯示的 ID 中 680 個在測試的畫面上出現；其餘 5 個見文末。

## 1. 顯示在哪、哪個測試看到

| ID 或樣式 | 顯示在哪 | 涵蓋的測試 |
|---|---|---|
| `SCR_D01_S01_*`、`S09_*`、`NEWS_D01_DATELINE` | 報紙（`paper`；S01、S09 的頭條是 L001 去掉括號的 `HEAD_D01*`，導言與附加段照原文） | check_d1_story、check_d1_full |
| `SCR_D01_S02_*`、`S03_*`、`S07_L001～L003`、`L012～L019`、`S08_L*`、`S10_L*` | vn | check_d1_story、check_d1_full、check_d1_play、check_d1_lines（E7：S9 的 S10 L008） |
| `SCR_D01_S04_*`、`OBS_D01_W*` | 熱身畫面 | check_d1_story |
| `SCR_D01_S05_TITLE`、`HS_D01_<n>_*`、`SCENE_D01_<地點>`（無短名者）／`_TAB` | 蒐證畫面（分頁、彈窗） | check_d1_m3（26 點全看）、check_d1_full |
| `E_D01_*`、`C_D01_*`、`PN_D01_*`、`OBS_D01_01*`、`APR_D01_*` | 證物清單、人物筆記頁、鑑定 | check_d1_m3、check_d1_full |
| `SCR_D01_S06_*`、`UI_V2_CARRY_*` | 攜帶畫面 | check_d1_m3、check_d1_full |
| `SCR_D01_S07_L004～L011`、`L016` | 論戰的系統台詞（開場、論破、歸零、殘局、敗北） | check_d1_play、check_d1_lines（E7：S9 的 L006）、check_d1_fuzz |
| `CLM_D01_<id>`／`_SHORT`／`_LINE` | 說法選擇器與確認列／鏈與公開紀錄／Sherefox 的台詞 | check_d1_fuzz、check_d1_lines（E7：S7 的 03B） |
| `CARD_D01_<牌>`／`_SHORT`／`_STATE`／`_PUSH`／`_RETRACT`／`_DOWN`／`_TELL`／`_CATCH` | 論點框、確認列／他的鏈、公開紀錄（抓住他的話的節，E7）／他的台詞 | check_d1_fuzz、check_d1_lines（E7：S7 P06、U2_CATCH；S12 P07_PUSH、L3_DOWN、P05_DOWN；S13 P06_PUSH） |
| `CUT_D01_<說法>_<牌>`、`LINK_D01_<a>_<b>`、`REACT_D01_*`、`REFUTE_D01_*`（`_FACT` 填入 `SYS_D01_NOW_KNOWN`） | 他被打下、承接、反應、駁倒（↔ 的承接兩個順序都播，E7） | check_d1_play、check_d1_lines（E7：S7、S9、S12）、check_d1_fuzz |
| `EXCL_D01_<a>_<b>_CATCH`／`_SELL` | 紅色裂紋的代價之前：他抓矛盾、她硬撐（E7） | check_d1_play（路線 C R4、R7）、check_d1_lines（S9）、check_d1_fuzz |
| `SYS_D01_*`（樣板） | 論戰的系統台詞，數字由事件紀錄填入 | check_d1_play `check_lines`（逐項對 ref，含 E7 的 CHAIN_READY／REV_READY／CHAIN_NOBREAK／LASTSTAND_OK／DESPERATE_HIT／BLOCKED）、check_d1_lines、check_d1_fuzz |
| `BEAT_D01_*`、`STATE_D01_*`、`TELL_D01_*`、`FOG_D01_*`、`SPK_D01_CEDRIC` | 串場、狀態台詞、預兆與亞瑟的提示、打迷糊仗 | check_d1_play `check_steps`、check_d1_lines（E7：S13 的 LASTCARD_3）、check_d1_fuzz |
| `UI_V2_STAMP_*` 與大字（共用 `CUT_*`：論破、動搖、破竹、困獸、失守、逆論破） | `ui#cutin` | E7：`check_lines` 逐回合比對大字與小印（困獸：check_d1_lines S4）；罪惡感、怒氣越線沒有大字 |
| `UI_V2_*`（其他） | 各畫面的板上文字（`data-xt-key`）與 port | 板上文字隨畫面出現；port 的見 check_d1_play、check_d1_full、check_d1_m3 |
| `ISSUE_D01_*` | 爭點色塊（短）、`{issue}`／`{issues}`（全名） | check_d1_fuzz、check_d1_lines |
| `CHAP_D01_TITLE`、`UI_V2_TITLE_ENTRY` | 標題、vn 的章名頁籤 | check_d1_story |

## 2. E7 的處理

- **A 類（應顯示而沒做，已實作，先 ref 再流圖）**：`SYS_D01_CHAIN_READY`、`SYS_D01_REV_READY`、`SYS_D01_CHAIN_NOBREAK`（企劃 4ac5faf 裁定）；`EXCL_D01_*_CATCH`／`_SELL` 22 句（章 §7）；另外不是單一 ID 的三項：抓住他的話的節顯示 U 牌短標、↔ 承接的反向順序、殘局截斷成功的「截」（章 §12.1 R9）。
- **B 類（有實作、測試沒走到，已加劇本）**：`tests/check_d1_lines.py` S7～S14：LASTSTAND_OK（回到 30%，紅色裂紋時 30%−10）、DESPERATE_HIT（承受／截斷失敗）、BLOCKED、COVER、CARD_D01_P06／_SHORT／_STATE／_PUSH、P07_PUSH、L3_DOWN、P05_DOWN、U2_CATCH、CLM_D01_03B 三句與 REACT_D01_03B、CUT_D01_03A_L1、CUT_D01_09A_L3、四句承接、REFUTE_D01_05B 與其 `_FACT`、S07 L006、S10 L008、BEAT_D01_LASTCARD_3。

## 3. C 類：設計沒有給條件或位置（列給企劃，未實作）

| ID | 設計怎麼寫 | 問題 |
|---|---|---|
| `SHF_D01_CUT_OPEN_1～3` | 章 §6.7「截斷時 Sherefox 的開口」 | 每次截斷都播？三句怎麼選（1、2 共用、3 本章專屬）？播在說法台詞之前？ |
| `UI_V2_ACT_STALL_DESC`、`UI_V2_REBUT_CUT_DESC`、`UI_V2_REBUT_TOPPLE_DESC`、`UI_V2_SUPPORT_DESC`、`UI_V2_SEIZE_DESC`、`UI_V2_CLAIM_SOPH_DESC` | note：tooltip／說明 | 章 §13 沒有說明區或滑鼠提示，要放哪裡、何時出現？ |
| `UI_V2_ACT_STALL_REPEAT` | 「連續打迷糊仗」時的警告 | 選打迷糊仗時就顯示（鎖定前）？放在哪？ |
| `UI_V2_CLAIM_CAN_CUT` | 說法選擇器 | 沒有條件（證物的說法都能反駁） |
| `UI_V2_CLAIM_CRACK_COST` | 說法選擇器 | 紅色裂紋列已有標記，這句放哪？ |
| `UI_V2_CLAIM_RESTATE` | 說法選擇器 | §13 的選擇器只標正論／詭辯／紅色裂紋；被打掉後重提要不要加標？ |
| `UI_V2_CLAIM_VOID` | 說法選擇器 | 被駁倒的說法本場作廢，目前不列在選擇器；要改成灰色列並標這句嗎？ |
| `UI_V2_DMG_PREVIEW` | note：選擇器上的論證預估 | 預估要含哪些倍率（破防等算不算隱藏資訊）？ |
| `UI_V2_ENDGAME`、`UI_V2_ISSUE` | 標籤 | 沒有給位置（殘局有「最後一張牌」標題、說法有爭點色塊） |
| `UI_V2_SUPPORT_LEFT` | 「援護 剩 {n} 次」 | 每場一次，用完按鈕變灰；要顯示次數嗎？ |
| `UI_V2_TELL_POSSIBLE` | 預兆面板 | 面板已用兩個行動框加 `UI_V2_TELL_VAGUE`／`_LIKELY` |
| `UI_V2_RECORD_CRACKS` | 公開紀錄（4ac5faf 改成 "Cracks: {n}"） | §13 的公開紀錄只寫「裂紋處標記」；要在標題列顯示總數嗎？ |
| `UI_V2_BACK_TITLE`、`UI_V2_NEXT_PLACEHOLDER` | 結算／S11 | S11 用設計自己的 `SCR_D01_S11_L001～L003`（含按鈕字） |
| `UI_V2_CARRY_LEFT_ASK` | 攜帶畫面 | 確認框已顯示 S06 L009 與按鈕 |
| `SCENE_D01_ATTIC`、`SCENE_D01_BASEMENT` | 「全名留給標題」 | 蒐證畫面沒有地點標題（分頁用 `_TAB`）；要加標題嗎？ |
| （非 ID）CHAIN_READY／REV_READY 的 `{issues}` | 章 §12.1 R8 寫「機、法、動」 | 現用爭點全名、依鏈上出現順序、以 `UI_TAG_SEP`（・／, ）連接；要短名或「、」請給字串 |
| （非 ID）§7.5 最後一張牌帶紅色裂紋 | §7.5「先回復到 30% 再扣 10」 | 這時不播 `SYS_D01_REDCRACK`，也不播抓矛盾；要播嗎？ |
| （非 ID）同時與兩句矛盾 | 章 §7 | 現取公開紀錄最早的一句播抓矛盾 |

依裁定或性質不顯示（同在 `NOT_DISPLAYED`）：`SYS_D01_LASTSTAND_PROMPT`、`SYS_D01_TELL_*` 4 句、`EXCL_D01_TEMPLATE`（4ac5faf 裁定）；`BEAT_D01_GIVEUP_1`、`UI_V2_GIVE_UP`（由 S07 L007／L008 取代）、`UI_V2_CARRY_COUNT`（由 S06 L002 取代）、`UI_V2_CRED`（用 `_PLAYER`／`_OPP`）；場景標題 `SCR_D01_S01/S02/S03/S07/S09/S10/S11_TITLE`。

## 4. D 類：規則上到不了

| ID | 理由 |
|---|---|
| `CARD_D01_P05_PUSH` | 撿到的證物裡優先度最高的那張一律留作最後一張牌（§6.5、ref `initial_state` 的 `reserved_last`），P05 是第一優先，所以永遠不在手牌、不會被拿來強辯；殘局的最後一張牌用 `_STATE`。 |

另外 `SCR_D01_S01_L001`、`S09_L001`／`L003`／`L005` 不以原文出現：頭條是去掉括號的 `HEAD_D01`、`HEAD_D01_CLOSE_<版本>`（建置時產生，check_d1_story、check_d1_full 檢查）。
