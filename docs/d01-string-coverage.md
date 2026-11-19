# D01 字串覆蓋表（v2 demo E7、E8）

狀態：2026-11-20，設計 repo v2 分支 fdbf90c（含 4ac5faf）；E8 套用企劃對 C 類的裁定（v2 demo 計畫 E8）。來源 `source/localization/d01/` 四個檔，共 727 個 ID。

- 檢查：`uv run tests/check_d1_strings.py`（靜態）：每個 ID 不是被流圖、板子、資料表（劇本表只算 vn 會播的列；E8 起音樂 cue 表 `data/bgmCues.json` 不算，它只拿行 ID 對音樂）或產生器的樣式引用，就必須在 `NOT_DISPLAYED`（附理由）上；設計新增的字串沒人用、清單上的 ID 被用了或不存在，都算失敗。
- 實測：D01 各檢查以 `SHEREFOX_TEXTLOG=<dir>` 執行後，`check_d1_strings.py --coverage <dir>` 把每個 ID 的中英文文字對到 port 上出現過的值。本表依 E8 落地後的實測：704 個要顯示的 ID 中 700 個在測試的畫面上出現；其餘 4 個（頭條，以去掉括號的形式出現）見文末。

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
| `SHF_D01_CUT_OPEN_1～3`（E8） | 一般回合截斷成功時，Sherefox 的說法台詞之前（要害論點 L2 用 `_3`，每場一次；其餘 `_1`、`_2` 輪流） | check_d1_play、check_d1_lines、check_d1_fuzz（`check_steps` 逐步對 ref `lines.cut_open`） |
| `UI_V2_DMG_PREVIEW`、`UI_V2_CLAIM_CRACK_COST`（E8） | 確認列（預估：議論的一般回合；代價：選了帶紅色裂紋的說法） | `check_e8`（路線與劇本每回合）、check_d1_fuzz（每次點擊） |
| `UI_V2_CLAIM_RESTATE`、`UI_V2_CLAIM_VOID`（E8） | 說法列的標籤（作廢的列反灰、排在最後） | `check_e8`（S9 R8 重提、S14 R8 作廢）、check_d1_fuzz（每一列） |
| `UI_V2_REBUT_CUT_DESC`、`_TOPPLE_DESC`、`UI_V2_ACT_STALL_DESC`／`_REPEAT`、`UI_V2_SUPPORT_DESC`、`UI_V2_CLAIM_SOPH_DESC`、`UI_V2_SEIZE_DESC`（E8） | 行動列上方的一行說明（滑鼠所在或選中的行動、援護、說法） | `check_e8`、check_d1_lines `HOVER_PROBE`（滑鼠移過四個鈕）、check_d1_fuzz |
| `UI_V2_SUPPORT_LEFT`、`UI_V2_TELL_POSSIBLE`＋`UI_V2_TELL_LIKELY`、`UI_V2_RECORD_CRACKS`（E8） | 援護鈕、模糊預兆的一行、公開紀錄標題列 | `check_e8`、check_d1_fuzz（每回合） |
| `UI_V2_ENDGAME`、`UI_V2_RECORD_DESC`、`UI_V2_NOTES_DESC`、`UI_V2_CARRY_LEFT_ASK`、`UI_V2_NEXT_PLACEHOLDER`、`UI_V2_BACK_TITLE` | 板上文字：殘局小標、公開紀錄與人物筆記的說明、攜帶確認框、S11 的標題與按鈕 | 隨畫面出現；check_d1_m3（確認框）、check_d1_full（S11 停到按下按鈕） |

## 2. E7 的處理

- **A 類（應顯示而沒做，已實作，先 ref 再流圖）**：`SYS_D01_CHAIN_READY`、`SYS_D01_REV_READY`、`SYS_D01_CHAIN_NOBREAK`（企劃 4ac5faf 裁定）；`EXCL_D01_*_CATCH`／`_SELL` 22 句（章 §7）；另外不是單一 ID 的三項：抓住他的話的節顯示 U 牌短標、↔ 承接的反向順序、殘局截斷成功的「截」（章 §12.1 R9）。
- **B 類（有實作、測試沒走到，已加劇本）**：`tests/check_d1_lines.py` S7～S14：LASTSTAND_OK（回到 30%，紅色裂紋時 30%−10）、DESPERATE_HIT（承受／截斷失敗）、BLOCKED、COVER、CARD_D01_P06／_SHORT／_STATE／_PUSH、P07_PUSH、L3_DOWN、P05_DOWN、U2_CATCH、CLM_D01_03B 三句與 REACT_D01_03B、CUT_D01_03A_L1、CUT_D01_09A_L3、四句承接、REFUTE_D01_05B 與其 `_FACT`、S07 L006、S10 L008、BEAT_D01_LASTCARD_3。

## 3. C 類：E8 的處理（企劃裁定）

E7 列給企劃的 C 類全部有了裁定，依 v2 demo 計畫 E8 實作（先 ref 再畫面）：

- 顯示（見第 1 節）：`SHF_D01_CUT_OPEN_1～3`、六個 `_DESC`、`UI_V2_ACT_STALL_REPEAT`、`UI_V2_CLAIM_CRACK_COST`、`UI_V2_CLAIM_RESTATE`、`UI_V2_CLAIM_VOID`、`UI_V2_DMG_PREVIEW`、`UI_V2_ENDGAME`、`UI_V2_SUPPORT_LEFT`、`UI_V2_TELL_POSSIBLE`、`UI_V2_RECORD_CRACKS`、`UI_V2_CARRY_LEFT_ASK`、`UI_V2_NEXT_PLACEHOLDER`、`UI_V2_BACK_TITLE`。
- 不顯示（`NOT_DISPLAYED`）：`UI_V2_CLAIM_CAN_CUT`（會洩漏哪個說法截得掉）、`UI_V2_ISSUE`、`SCENE_D01_ATTIC`／`SCENE_D01_BASEMENT`（全名；分頁用 `_TAB`）、`CARD_D01_P05_PUSH`（P05 只當最後一張牌：ref `model.never_in_hand`，兩個產生器不再引用它的 `_PUSH`）。另外 `SCR_D01_S11_L003`：S11 的按鈕改用 `UI_V2_BACK_TITLE`，這句不再顯示（計畫的清單沒有列，列給企劃確認）。
- 非 ID 的三項：`{issues}` 維持爭點全名、依鏈上出現的順序；一個說法與兩句矛盾取紀錄中最早的一句、只扣一次（確認不改）；§7.5 帶紅色裂紋的最後一擊改為兩步：先 `SYS_D01_LASTSTAND_OK`（42），再播該組矛盾台詞與 `SYS_D01_REDCRACK`（−10 → 32），裂紋照記（ref `resolve._last_stand` 與引擎都改成兩筆事件）。
- 給企劃的備註：`SCR_D01_S06_L009` 本身以「確定嗎？」結尾，`UI_V2_CARRY_LEFT_ASK` 在它下方又問一次。

覆蓋表 C 類沒有未被裁定涵蓋的 ID。

依裁定或性質不顯示（同在 `NOT_DISPLAYED`）：`SYS_D01_LASTSTAND_PROMPT`、`SYS_D01_TELL_*` 4 句、`EXCL_D01_TEMPLATE`（4ac5faf 裁定）；`BEAT_D01_GIVEUP_1`、`UI_V2_GIVE_UP`（由 S07 L007／L008 取代）、`UI_V2_CARRY_COUNT`（由 S06 L002 取代）、`UI_V2_CRED`（用 `_PLAYER`／`_OPP`）；場景標題 `SCR_D01_S01/S02/S03/S07/S09/S10/S11_TITLE`；E8 的 6 個（上列）。

## 4. D 類：規則上到不了

| ID | 理由 |
|---|---|
| `CARD_D01_P05_PUSH` | 撿到的證物裡優先度最高的那張一律留作最後一張牌（§6.5、ref `initial_state` 的 `reserved_last`），P05 是第一優先，所以永遠不在手牌、不會被拿來強辯；殘局的最後一張牌用 `_STATE`。E8 起列在 `NOT_DISPLAYED`（ref `model.never_in_hand`）。 |

另外 `SCR_D01_S01_L001`、`S09_L001`／`L003`／`L005` 不以原文出現：頭條是去掉括號的 `HEAD_D01`、`HEAD_D01_CLOSE_<版本>`（建置時產生，check_d1_story、check_d1_full 檢查）。
