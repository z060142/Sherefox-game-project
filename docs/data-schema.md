# 資料表規格（Ch.1～3 原型）

狀態：M1 草案 2026-11-06。產生器：`tools/build_data.py`（`uv run tools/build_data.py`）。本文件說明 `data/*.json` 與 `strings/*.csv` 的每一張表、每一欄的型別與意義，以及從哪一份來源、哪一節推導而來。遊戲規則以設計文件為準；本文只描述資料。

## 0. 總則

### 0.1 指令

| 指令 | 作用 |
|---|---|
| `uv run tools/build_data.py` | 重新產生全部表格與字串表，並執行驗證（錯誤 → 結束碼 1，不寫檔） |
| `uv run tools/build_data.py --check` | 只驗證，不寫檔 |
| `uv run tools/build_data.py --import-localization <dir>` | 先把新的在地化包複製進 `source/localization/`，再建置 |

只用標準函式庫；腳本帶 PEP 723 標頭，`tools/pyproject.toml` 供 `cd tools && uv run build_data.py` 使用。

### 0.2 來源（全部在專案內）

| 來源 | 內容 |
|---|---|
| `source/localization/` | 在地化包（2026-11-06 第四批：1659 個鍵，含 Ch.4 開場報紙、45 個調查點名稱 `HS_*`、4 個 `UI_PAPER_*`）原樣複製：`strings.json`、`ui_strings.csv`、`tutorial.csv`、`evidence_ch01-03.csv`、`script_ch01-03.csv`、`glossary.csv`、`README.md` |
| `source/staging/staging_ch01-03.csv` | 每一行劇本的 VN 演出（背景、立繪站位、說話焦點、文字樣式）；見 §3.1 |
| `source/tags/tags_ch01-03.csv` | 每張證物卡與每個節點的「類別：值」標籤（§0.4），抄自 10-cases 各章「標籤值」表 |
| `docs/design/01-systems.md` | §1.2、§1.3（以程式解析表格）、§1.5（解析鑑定揭露的類別）、§1.8、§2.8、§3.1、§3.3、§6.1、附錄 A |
| `docs/design/02-numbers.md` | §一（前期欄，解析）、§四（類型權重，解析）、§五（各案主導權／節點上限／主張傷害，解析；說明文字中的「Ch.n 鑑定 k 次」覆寫 01-systems §1.3 的鑑定次數） |
| `docs/design/10-cases-ch01-04.md` | 各章「場景與登場人物」「證物表」「對手行為表」「調查點」（解析；調查點表是 `hotspots` 的唯一來源，§5）；其餘條目以常數寫在腳本內並註明出處 |
| `docs/rulings.md` | 設計裁決 B15、B16、B20、A4、C1～C4，以常數寫在腳本內（以裁決編號註記） |

來源優先序（不一致時）：數值總表 ＞ 系統規格 ＞ 各章設計 ＞ 完整劇本 ＞ 設計總覽；裁決紀錄優先於尚未同步的快照。

### 0.3 格式

- 表格：XTAtrium 08 §8.2 的 JSON 表。每檔是平面物件陣列，值只有 number／bool／string，沒有 null、沒有巢狀；每一列的欄位與順序相同，同一欄的型別相同（產生器驗證）。表名合 `[a-z][A-Za-z0-9]*`，欄名合 `[A-Za-z_][A-Za-z0-9_]*`。
- 列順序固定（各表註明排序依據），LF 換行，UTF-8 無 BOM。沒有值的字串欄寫 `""`，沒有值的數字欄寫 `0`（另有說明者除外，例如 `-1`）。
- 文字格只放**字串鍵**，不放顯示文字。多值格以 `,` 分隔、無空白（適用 `atrium.table.has` 與 `atrium.coll.addAll`）。
- 字串表：`strings/zh-TW.csv`、`strings/en.csv`，RFC 4180 兩欄 `key,text`、首列為標頭 `key,text`，依鍵的字元序排序。兩檔的鍵集合完全相同。

### 0.4 標籤（裁決 C4、D8、D11、D13）

機器形式：`<類別>:<slug>`（例 `place:boiler_room`）。類別 id：

| 設計用語 | id |
|---|---|
| 時間 | `time` |
| 地點 | `place` |
| 人物 | `person` |
| 物理、物理特性 | `phys` |
| 醜聞 | `scandal` |

標籤來源是 `source/tags/tags_ch01-03.csv`（UTF-8，標頭列 `owner,category,value,slug,grazing,hidden,police,note`），一列一個標籤，內容抄自 10-cases 各章「標籤值」表（證物表與節點表）：

| 欄 | 意義 |
|---|---|
| owner | 證物 id（`E01_01`、`G-01`、`S-01`）或節點 id（`CH01_N1`、`CH02_T1`、`CH03_W1`） |
| category | 類別的設計用語（上表左欄） |
| value | 值的設計用語（例：鍋爐室），必填 |
| slug | 值的機器形式，`[a-z0-9_]+`，必填；＝在地化包 `TAG_<類別>_<SLUG>` 鍵的 slug 小寫（例 `boiler_room`、`0530`、`2200_2230`）。同一個 `category:slug` 在所有列必須是同一個 value |
| grazing | `擦邊`（表中 ※）→ 此標籤列入 `grazingTags`；空白＝非擦邊 |
| hidden | 表中「需鑑定」欄：`medical`（醫療）／`mech`（機械）／`no`（—，一開始就揭露）。只有證物可隱藏，且證物的鑑定類型必須能揭露它（醫療 → medical／dual，機械 → mechanical／dual） |
| police | `yes`：信任度 ≥ 3 時警方驗屍報告直接揭露此隱藏標籤（01-systems §3.1；目前只有 E03_01 的時間與蒸汽窒息）；必須是 hidden 標籤 |
| note | 備註（不進資料） |

S-01 依裁決 D11 用 G-01 的值，全部標擦邊。設計的「需鑑定」欄覆寫 01-systems §1.5 的類別預設（裁決 D8），所以建置不再依類別推導隱藏標籤。

標籤顯示鍵（裁決 D13）：`TAG_<TIME|PLACE|PERSON|PHYSICAL|SCANDAL>_<slug 大寫>`（類別名與 `UI_TAG_<類別>` 相同），例 `TAG_PLACE_BOILER_ROOM`、`TAG_PHYSICAL_BOILER_PRESSURE`；slug 與在地化包的鍵一致。表 `tags`（§13）列出每個標籤與它的鍵；46 個鍵都由在地化包提供（2026-11-06 第二批）。在地化包缺某個鍵時，建置以 zh-TW＝表中的值、en 暫同 zh-TW 補上，並以一則警告列出。

### 0.5 驗證（建置時執行）

錯誤（建置失敗）：標籤檔標頭不符、標籤缺 value 或 slug、同一 slug 對應兩個值、`hidden` 不是 medical／mech／no 或與證物的鑑定類型不符、非證物標籤被隱藏、`police=yes` 但標籤沒隱藏、`policeTags` 不是 `hiddenTags` 的子集、沒有鑑定類型的證物有隱藏標籤、節點或證物沒有標籤；表名／欄名不合法；值為 null 或巢狀；同欄型別混用；id 重複；任何表引用的字串鍵不在兩份字串表中（含多值的 `lines`）；引用不存在的證物（`hotspots.yields`、`nodes.refutedBy`、`opponents.hand`、`script.evidence`、`evidence.golden`）、節點（`evidence.refutes`、`script.node`、`opponents.tailNode`）、調查點、對手、報紙群組；標籤類別未知、slug 不合法、`hiddenTags`／`grazingTags` 不是 `tags` 的子集；在地化備註或劇本行無法分類；調查點（§5）的 id 格式錯誤、區域沒有 slug（`ZONE_SLUGS`）、一個點產出超過 2 張卡、`HOTSPOT_*` 常數與設計表的文字（「論戰後」「只在缺少 G-01 時出現」「事件中已取得」）不一致、`_NAME` 鍵缺少、檢視點沒有 `_NOTE`、產出證物的點有 `_NOTE`、設計表有／沒有提示但 `_HINT` 鍵沒有／有、各章列數與表頭句「共 n 個調查點，m 個產出證物、k 個只寫進案件筆記」不符（條件點不計入 n）、同一張證物由兩個點產出、佔位矩形超出 1280×720 或同一場景內重疊、`phase` 不在 `investigate`／`postDebate`、`requires` 格式錯誤；演出檔的驗證項（§3.1）；必需證物（`REQUIRED`）不在證物表、不是一般／關鍵、不由調查點或事件取得（`obtain` 必須是 `hotspot` 或 `event`）、`required` 與 `obtainable` 不符，或非一般／關鍵證物 `obtainable=true`（裁決 D2、D3）；章節步驟不符裁決 D5（每章必須以恰好一個 S01 paper 步驟開頭，除 Ch.3 末尾的最終報紙外沒有其他 paper 步驟，S01 不得是非 paper 步驟）；章首報紙沒有導言 `bodyKey`。

警告（照常輸出）：各章數量與 01-systems §1.3 不符（場景、調查點、一般／關鍵／劇情證物；調查點數不含條件點）；調查點名稱／案件筆記／提示的 zh-TW 與設計表文字不同；刻度÷調查點不在 0.65～0.75；純情報調查點比例偏離 40% 超過 10 個百分點；主張節點少於節點上限；在地化與 10-cases 證物表的等級／鑑定／類別不同；證物的非擦邊標籤類別與 10-cases 證物表的類別不同（擦邊值可以落在類別欄以外；全為擦邊的 S-01 比對全部標籤）；`TAG_` 顯示鍵不在在地化包（en 暫用 zh-TW）；對手小動作的在地化 zh 與 10-cases 對手行為表不同。

## 1. `chapters`：章節（每章一列，依章號）

| 欄 | 型別 | 意義 | 來源 |
|---|---|---|---|
| id | number | 章號 1～3 | — |
| key | string | `CH01`… | — |
| titleKey | string | 章名字串鍵 `CHAP_0n_TITLE` | 在地化包；缺鍵時才由結案筆記行（`SCR_CH0n_S0x_L002`）的「案件名稱：…。」擷取 |
| phase | string | `early`（前期） | 02-numbers §一 |
| scenes | number | 設計的場景數 | 01-systems §1.3（解析） |
| hotspotsDesign | number | 設計的調查點數 | 同上 |
| commonDesign／keyDesign／storyDesign | number | 設計的一般／關鍵／劇情證物數 | 同上 |
| ticks | number | 懷錶刻度；`-1`＝不限 | 同上（Ch.1「不限（教學）」） |
| appraisals | number | 鑑定次數 | 同上；02-numbers §五「Ch.2 鑑定 3 次」覆寫（Ch.2＝3） |
| appraisalUnlocked | bool | 可鑑定（Ch.2 起） | 01-systems §1.5 |
| assistUnlocked | bool | 援護可用（Ch.2 起） | 10-cases Ch.1 結算、TUT_01_19 |
| sophistry | bool | 論戰可出詭辯 | Ch.1：劇本「本章教學尚未解鎖」；Ch.2～3：裁決 B20 |
| sophistryReads | bool | 詭辯對補強算破竹「讀對」 | 裁決 B20（Ch.4 前不算）、01-systems A-15 |
| states | string | 本章生效的狀態，多值：`hachiku`（破竹）、`konju`（困獸）、`shisshu`（失守） | 01-systems A-15 共通：Ch.1 僅預覽、Ch.2 只有破竹、Ch.3 起全部 |
| trustShown | bool | 顯示警督信任度 | 01-systems §3.1（Ch.3 起） |
| trustDebate | bool | 主論戰勝 +1／敗 −1 | 01-systems §3.1 變動表（警督參與案件） |
| trustNotoriety | bool | 結算惡名 ≥ 3 → −1 | 01-systems §3.1（全部案件） |
| trustDeferred | bool | 本章的信任度變動暫存到下一章開始才套用 | 01-systems §3.1（Ch.2） |
| police | bool | 警察參與案件 | 01-systems §3.1 |
| warmup | bool | 有熱身小論戰 | 01-systems §4.1（SCR_WARMUP：Ch.3 起） |
| missToHand | bool | 漏證進對手手牌 | 01-systems A-13（Ch.1 不進） |
| playerHp | number | 我方主導權 | 02-numbers §一 |
| breakPct | number | 論破扣對手最大主導權的百分比 | 02-numbers §一 |
| breakLine | number | 破防線（百分比）；`0`＝無限制 | 02-numbers §一 |
| breakStrong | number | 論破門檻：強攻證物張數 | 01-systems A-8（前期：1 件強攻） |
| breakChain | number | 論破門檻：實證連鎖張數 | 01-systems A-8（前期：2 張以上） |
| tailPenalty | number | 尾聲答錯扣血 | 02-numbers §一 |
| tailRounds | number | 尾聲回合數 | 02-numbers §一 |
| debate | string | 主論戰對手 id（`opponents.id`） | — |
| openPaper | string | 章首報紙群組（`papers.group`）；即章節交界的合併報紙（§9） | 裁決 D5 |
| endPaper | string | 章末報紙群組（`papers.group`）；只有最後一章（Ch.3）有值＝`CH04_OPEN`（原型結尾，裁決 E1），Ch.1～2 為空白（章節交界只有一份報紙，在下一章開頭，見 §9） | 裁決 D5、E1 |
| next | number | 下一章章號 | — |

## 2. `steps`：章節步驟（依章號、idx）

| 欄 | 型別 | 意義 |
|---|---|---|
| id | string | `CH0n_ii` |
| chapter | number | 章號 |
| idx | number | 章內順序，0 起 |
| kind | string | `paper`／`vn`／`warmup`／`investigate`／`board`／`debate`／`result`／`end`（原型結尾「待續」卡，只出現在最後一步，裁決 E1） |
| sub | string | `paper`：`open`（章首合併報紙）或 `transition`（Ch.3 之後的最終報紙 `CH04_OPEN`）；`vn`：`daily`／`event`／`notes`（結案筆記）；其他空白 |
| scene | string | 該步驟對應的劇本場景（`script.scene`，例 `S02`）；章首報紙為 `S01`；`board`、最終報紙與 `end` 空白 |
| arg | string | `paper` → `papers.group`；`warmup`／`debate` → `opponents.id`；`investigate`／`board` → 章 key（`CH0n`，查 `hotspots.chapter`、`evidence.usable`）；`end` → 卡片文字的字串鍵 `UI_TO_BE_CONTINUED`；其他空白 |

推導：依劇本每個場景的標題（`L001`）判定種類——含「報紙頭版」→ paper/open、「熱身小論戰」→ warmup、「主論戰」→ debate、「蒐證」→ investigate、「結算」→ result、「結案筆記」→ vn/notes、「日常」→ vn/daily、「事件」→ vn/event（依此順序比對）。`investigate` 之後插入 `board`（線索板沒有劇本場景，01-systems §4.1）。裁決 D5：每章開頭只有**一個** paper 步驟（`sub=open`、`scene=S01`、`arg=CH0n_OPEN`），它是章節交界的合併報紙，不再有獨立的 S01 vn 步驟，章末也不再有轉場報紙步驟；只有最後一章（Ch.3）末尾保留一個 paper 步驟（`sub=transition`、`arg=CH04_OPEN`：Ch.4 的開場合併報紙，側欄刊 Ch.3 結果），之後是 `end` 步驟（「待續」卡，`arg=UI_TO_BE_CONTINUED`）；Ch.4 本身不在範圍內（裁決 E1）。裁決 D6：`result` 步驟播放劇本的結算台詞；`NEWS_*` 結果頭條只出現在下一份報紙的側欄（§9），不在結算步驟播放。論戰台詞庫 `S90` 不是步驟。

每章步驟序列（Ch.1～3）：

| 章 | 序列 |
|---|---|
| Ch.1 | paper(S01) → vn daily(S02) → vn event(S03) → investigate(S04) → board → debate(S05) → result(S06) → vn notes(S07) |
| Ch.2 | paper(S01) → vn daily(S02) → vn event(S03) → investigate(S04) → board → debate(S05) → result(S06) → vn notes(S07) |
| Ch.3 | paper(S01) → vn daily(S02) → vn event(S03) → warmup(S04) → investigate(S05) → board → debate(S06) → result(S07) → vn notes(S08) → paper transition(`CH04_OPEN`) → end(`UI_TO_BE_CONTINUED`) |

## 3. `script`：劇本行（每行一列，依章、場景號、行號）

| 欄 | 型別 | 意義 |
|---|---|---|
| id | string | 劇本行 id，`SCR_CH0n_Sss_Lnnn` |
| chapter | number | 章號 |
| scene | string | `S01`…；`S90`＝論戰台詞庫 |
| seq | number | 場景內行號（`L` 的數字；`1` 是場景標題） |
| kind | string | `heading`（場景標題，L001）、`subheading`（場景中的小標，例 Ch.3 S07 L009「（尾聲：碼頭）」）、`evidence`（證物描述）、`staging`（純演出行）、`branch`（分支標記）、`note`（備註，不播放）、`line`（有說話者的一般行；含旁白、系統、報紙） |
| speaker | string | 說話者字串鍵 `SPK_*`；`line` 以外為空白 |
| text | string | 顯示文字的字串鍵（＝id） |
| branch | string | 這行所在的分支：`win`／`lose`；分支標記本身也帶值；沒有分支時空白 |
| round | number | 論戰／熱身場景中所在回合（由系統行「（第 n 回合…」起算，延續到下一個回合標記）；其他場景 0 |
| act | string | 論戰／熱身場景中，行首括號註記的行動：`tell`（預兆）、`assert`、`rush`、`reinforce`、`trap`、`rebut`、`rebutBreak`（反駁論破）、`solid`（實證連鎖）、`solidBreak`、`sophistry`、`observe`、`cutin`（截斷）、`shaken`（動搖）、`hint`（亞瑟提示）、`misjudge`（警督誤判）、`appraised`（鑑定後）、`tail`（尾聲・玉石俱焚）、`present`（出示）；沒有則空白 |
| node | string | 這行指向的主張節點（行首括號的 `N1`，或系統行的「亮起節點：N1」）→ `nodes.id` |
| evidence | string | 這行涉及的證物，多值：蒐證場景取自在地化備註 `evidence Exx_nn`；論戰行取自行首括號（「出示 A＋B」「實證連鎖，A→B」） |
| appraisal | bool | 此行是鑑定台詞（在地化備註含 `appraisal`） |
| banner | string | 演出行中的書法大字／印章：`【大字：X】`→ `CUT_*`、`【印：X】`→ `STAMP_*`（以 ui_strings 中 zh-TW 文字對應；`破竹×n` 取 `STAMP_HACHIKU`），多值依出現順序 |
| inactive | bool | 在地化備註寫「Not triggered in this chapter」或「not yet unlocked」（本章不會觸發，保留供重玩） |
| bg | string | 這行的背景 id（`vn.bg`）：`office_night`、`office_day`、`kitchen_morning`、`clockshop`、`dock_fog`、`barge_deck`、`boiler_room`、`debate`，空字串＝新聞紙底。來自演出檔（§3.1） |
| slot_l、slot_c、slot_r | string | 左／中／右立繪的角色 id（`vn.slot_*`），空字串＝無人。來自演出檔 |
| focus | number | 說話位置：0 無（旁白、系統、報紙）、1 左、2 中、3 右；指向的位置一定有人。來自演出檔 |
| style | number | 文字樣式（`vn.style`）：0 對白、1 亞瑟筆記旁白、2 系統／報紙／證物描述等非人物文字。來自演出檔 |

不產生 `expr`（立繪表情）、`cmd`、`next`：劇本沒有寫明，不自行設計。`bg`、立繪與焦點、樣式由演出檔（§3.1）補上，劇本行文字與數量不因此改變。

### 3.1 演出檔 `source/staging/staging_ch01-03.csv`

UTF-8，LF，有標頭：`id,bg,slot_l,slot_c,slot_r,focus,style,note`。每個 `script.id` 恰好一列（含場景標題 L001 與論戰台詞庫 S90）；`note` 只供人讀，不進資料表。建置時逐欄併入 `script`，缺列、多列、重複、未知 id 都是錯誤。

驗證（錯誤）：`bg` 必須在背景集合內；`slot_*` 必須是角色 id 或空字串，同一列不得重複；`focus` 0～3 且不為 0 時對應的位置必須有人；`style` 0～2。允許的角色 id：`sherefox`、`arthur`、`baskerville`、`victor`、`wolfhart`、`valet`（Ch.2 費奇）、`partner`（Ch.3 皮爾斯），以及尚無立繪的佔位 id（英文名的小寫 slug，之後 UI 補立繪）：`holloway`、`gresham`、`tommy`、`old_tom`。新增背景或角色要同時改 `docs/ui-contracts.md`（vn 一節）與 `build_data.py` 的 `STAGING_*` 常數。

撰寫規則：
- 背景依場景標題與 10-cases 的場景表；場景換地點時，在劇本寫明的那一行換。報紙場景與純筆記場景用空字串。論戰場景（含熱身）用 `debate`；論戰結束後回到現實對話的行換回原地點（備註註明）。蒐證場景 Ch.3 S05 依調查點所在地（§5.1）逐行換背景。
- 站位：Sherefox 在她出場的場景一律站左；場景的主要對手站右；第三人站中。角色在自己第一句台詞（或舞台指示寫明出場／被點名在場）時上場，留到場景結束或劇本寫明離開；場景內位置不跳動。同場超過三人時，沉默最久的人下場讓位（備註註明）。論戰場景從第一列起雙方都在場。
- `focus`＝該行說話者的位置；旁白、系統、報紙、證物描述、演出行、分支標記為 0。場景標題與論戰台詞庫（S90）不會當作對白播放：背景取所屬場景、三個位置空、`focus` 0、`style` 2。
- `style`：說話者是人物 0；`旁白（亞瑟筆記）` 1；其餘（系統、報紙、證物描述、演出、備註、分支、場景標題）2。

## 4. `evidence`：證物卡（依 id；G-01、S-01 在最後）

| 欄 | 型別 | 意義 | 來源 |
|---|---|---|---|
| id | string | `E0n_nn`、`G-01`（黃金線索）、`S-01`（G-01 的次級替代證物） | 在地化包；S-01 命名依 01-systems §2.8 |
| chapter | number | 來源章 | id |
| usable | string | 會出現在線索板／可參戰的章，多值 | 一般卡＝本章；G-01＝`3,12`（00-overview 黃金線索表） |
| grade | string | `common`／`key`／`story`／`golden`／`substitute` | 在地化 `_NAME` 備註的 grade；與 10-cases 證物表交叉檢查 |
| nameKey | string | 卡名 | `E.._NAME`；G-01 → `G-01`；S-01 → `G-01_SUB` |
| descKey | string | 說明文字 | `E.._DESC`（黃金／替代沒有） |
| tagsKey | string | 標籤類別的顯示字串（例「物理・時間」） | `E.._TAGS` |
| tags | string | 機器標籤，多值 | §0.4 |
| hiddenTags | string | 要鑑定後才揭露的標籤（`tags` 的子集）；用 `appraise` 的鑑定揭露 | §0.4：標籤檔 `hidden`（10-cases 標籤值「需鑑定」欄，裁決 D8） |
| grazingTags | string | 擦邊標籤（`tags` 的子集） | §0.4：標籤檔 `grazing` |
| policeTags | string | 信任度 ≥ 3 時由警方驗屍報告直接揭露的隱藏標籤（`hiddenTags` 的子集；只有 E03_01） | §0.4：標籤檔 `police`；01-systems §3.1；10-cases Ch.3 標籤值 |
| appraise | string | `none`／`medical`／`mechanical`／`dual` | 在地化 `_NAME` 備註 appraisal |
| appraiseCost | number | 鑑定消耗次數 0／1／1／2 | 01-systems §1.5 |
| appraisalKey | string | 鑑定後亞瑟的說明行（§2.8 appraisalText） | 劇本中備註含 `appraisal` 的行 |
| reason0Key／reason1Key／reason2Key | string | 三個歸類理由的**顯示順序** | 見下 |
| correct | number | 正確理由在顯示順序中的位置 0～2；`-1`＝理由固定（黃金／替代，01-systems §2.3） | 見下 |
| onBoard | bool | 會出現在線索板（劇情證物不會，§2.1） | grade |
| strong | bool | 強攻 | 10-cases 明寫（E01_03 N3「強攻」、E03_04「強攻」）＋裁決 C1（E02_01）、C2（G-01） |
| scandal | bool | 醜聞旗標＝帶醜聞類標籤 | 01-systems §2.8 |
| motive | bool | 動機 | 設計未指定任何一張 → 全部 false |
| offChain | bool | 鏈外事實 | 01-systems §2.8（黃金線索都帶）；裁決 C2 |
| required | bool | 必需證物 | 裁決 D2：Ch.1 E01_03；Ch.2 E02_02、E02_06；Ch.3 E03_02、E03_07；其餘 false（建置常數 `REQUIRED`）。E03_02 在事件中已取得（`obtain=event`），所以自動滿足 |
| obtainable | bool | 對手可取得（漏撿時進對手手牌） | 裁決 D3：一般與關鍵可取得；劇情、黃金線索（G-*）、替代證物（S-*）不可；再套用 D2：必需證物一律不可取得。Ch.1 另由 `chapters.missToHand=false` 關掉 |
| refutes | string | 這張卡能破解的節點，多值 | `nodes.refutedBy` 反查 |
| golden | string | 推理正確時產出的黃金線索 id | 10-cases Ch.2 結算（E02_01 → G-01） |
| obtain | string | 取得方式：`hotspot`（蒐證時由調查點取得）／`event`（事件中已取得，調查點只供重看與鑑定：E03_02、E03_05）／`afterDebate`（論戰後的調查點 `phase=postDebate`：E02_08）／`golden` | 由產出它的調查點的 `phase`、`revisit` 推導；G-01：E02_01 理由正確 |
| hotspot | string | 產出它的調查點 id（`HS_CH0n_nn`；`golden` 為空白） | `hotspots.yields` 反查 |
| lines | string | 調查時播放的劇本行（證物描述＋反應，不含鑑定行），多值 | 劇本蒐證場景，依在地化備註 `evidence Exx_nn` 分組 |

理由顯示順序（固定、可重現）：令 `h` 為 id 的 UTF-8 位元組做 SHA-256 後的第一個位元組，`correct = h mod 3`；`REASON_A`（在地化包中 A 恆為正確）放在 `correct` 位置，其餘兩格依序放 `REASON_B`、`REASON_C`。劇情證物也照此計算（雖然不上線索板）。

## 5. `hotspots`：調查點（依章、設計表順序；條件點 `HS_CH03_23` 在 Ch.3 最後）

來源是設計文件各章分頁的「調查點」表（10-cases，每章一張，欄位：ID、調查點、區域、證物、案件筆記、提示），逐列轉成一列；沒有再由管線自行對應或補點。數量：Ch.1 10（證物點 7、檢視點 3）、Ch.2 12（8、4；含論戰後的 `HS_CH02_08`）、Ch.3 22（9、13；另有條件點 `HS_CH03_23`，不計入 22），與 01-systems §1.3 一致。

| 欄 | 型別 | 意義 |
|---|---|---|
| id | string | 設計表的 ID，`HS_CH0n_nn`；也是字串鍵的前綴 |
| chapter | number | 章號 |
| scene | string | 場景 slug：`kitchen`（Ch.1）、`clock_shop`（Ch.2）、`boiler_room`／`deck`／`dock`（Ch.3，由區域欄決定）。對應 `script.bg`：`kitchen_morning`、`clockshop`、`boiler_room`、`barge_deck`、`dock_fog` |
| area | number | 區域索引；每個場景一個區域，全部 0（裁決 D10；見待確認 Q24） |
| zone | string | 設計表「區域」欄的 slug（`ZONE_SLUGS`）：Ch.1 `kitchen`／`living_room`；Ch.2 `counter`／`shop_floor`／`outside`／`back_room`／`corner`／`behind_counter`；Ch.3 同場景 slug。是調查點在畫面中的位置分組，無字串鍵 |
| type | string | `inspect`（沒有證物）／`evidence`（產出證物）／`testimony`（產出的卡是證詞：卡名含「證詞」，目前只有 `HS_CH02_04` 報童小湯米）；01-systems §1.2。目前沒有 `mechanism`、`locked`（裁決 D9） |
| phase | string | 何時可調查：`investigate`（蒐證步驟，預設）／`postDebate`（主論戰之後，目前只有 `HS_CH02_08`，名稱帶「（論戰後）」） |
| yields | string | 產出的證物 id，多值（最多 2） |
| lines | string | 首次調查播放的劇本行，多值（＝所產出證物的 `evidence.lines` 依序串接）；檢視點空白（檢視點播放 `noteKey` 文字） |
| nameKey | string | 調查點名稱 `HS_CH0n_nn_NAME`（每個點都有） |
| noteKey | string | 案件筆記句 `HS_CH0n_nn_NOTE`：只有檢視點（`type=inspect`）有；證物點空白（設計表寫「見證物描述」或一句導引，後者不是字串鍵，見下） |
| hintKey | string | 可選提示句 `HS_CH0n_nn_HINT`（設計表「提示」欄不是「—」者，共 9 個）；空白＝沒有 |
| requires | string | 出現條件：`missing:G-01`＝沒有 G-01 時才出現（01-systems §1.9，裁決 D11；只有 `HS_CH03_23`）；空白＝永遠出現 |
| revisit | bool | 產出的卡在事件中已取得（設計表案件筆記「事件中已取得…」：`HS_CH03_03`＝E03_02、`HS_CH03_07`＝E03_05）；此點只重看與鑑定，不再給卡。這兩張證物的 `evidence.obtain=event` |
| x, y, w, h | number | **佔位**版面矩形，1280×720 場景座標：同場景內第 i 個點（依設計表順序）`x=100+(i mod 4)×280`、`y=140+⌊i/4⌋×200`、`w=160`、`h=120`；同場景最多 12 點，矩形不重疊（建置驗證）。條件點與論戰後的點也占一格 |
| placeholder | bool | 版面為佔位（全部 true） |

設計表中不是字串鍵的導引句（`HS_CH03_01` 的「警督信任度 ≥ 3 時，驗屍報告已由警方提供，這裡只看得到現場」、`HS_CH03_03`、`HS_CH03_07` 的「事件中已取得…」）只在設計文件，不進資料表；`revisit` 與 E03_01 的信任度分支由流圖處理（待確認 Q13、Q14）。

調查點行為備註：
- 已調查過的點再點只重播情報，不再扣刻度（01-systems §1.2）；`phase=postDebate` 的點在蒐證步驟不出現。
- Ch.1 刻度不限；Ch.2 刻度 10、Ch.3 刻度 16，各自對 12、22 個點（`requires` 空白者計入；論戰後的點也計入設計數）。

### 5.1 各章調查點一覽

| id | 區域 | 調查點 | 類型 | 產出 |
|---|---|---|---|---|
| HS_CH01_01～07 | 廚房／客廳（`kitchen` 場景） | 冰箱、空布丁盤、廚房地板（廚房）；亞瑟房門、亞瑟的外套口袋、大門門縫、亞瑟（袖口）（客廳） | evidence | E01_02、E01_01、E01_04、E01_05、E01_06、E01_07、E01_03 |
| HS_CH01_08～10 | 廚房、廚房、客廳 | 窗台、流理台上的茶杯、壁爐架上的相框 | inspect | — |
| HS_CH02_01～07 | 櫃台、店面、店面、店門外、櫃台、後室門口、店面 | 櫃台上的懷錶、報時鳥鐘、鐘擺護蓋、報童小湯米（`testimony`）、寄修收據簿、零件櫃與目錄、費奇 | evidence／testimony | E02_01～E02_07 |
| HS_CH02_08 | 角落 | 角落咖啡座（論戰後） | evidence，`phase=postDebate` | E02_08 |
| HS_CH02_09～12 | 櫃台後、櫃台、店面、店面 | 工作台、櫃台旁的糖果罐、格雷沙姆先生、牆上的掛鐘群 | inspect | — |
| HS_CH03_01～04 | 鍋爐室 | 遺體、死者的外套內袋、從內側落下的門閂（`revisit`）、洩壓閥 | evidence | E03_01、E03_07、E03_02、E03_04 |
| HS_CH03_05～06 | 甲板 | 甲板上的壓力閥門、航行日誌 | evidence | E03_03、E03_08 |
| HS_CH03_07～09 | 碼頭 | 警方臨時拘留處（老湯姆，`revisit`）、皮爾斯先生、市政公告欄 | evidence | E03_05、E03_06、E03_09 |
| HS_CH03_10～13 | 鍋爐室 | 貨箱、鍋爐本體、牆上的水痕、死者的懷錶 | inspect | — |
| HS_CH03_14～17 | 甲板 | 纜繩、欄杆邊的空酒瓶、舵輪、通往鍋爐室的小窗 | inspect | — |
| HS_CH03_18～22 | 碼頭 | 碼頭上的煤灰腳印、煤棧、「錨與燈」酒館、巴斯克維爾警督、霧中的河面 | inspect | — |
| HS_CH03_23 | 鍋爐室 | 鍋爐室角落的新調查點（`requires=missing:G-01`） | evidence | S-01 |

Ch.3 的 E03_01 與 E03_07 分屬 `HS_CH03_01`（遺體）與 `HS_CH03_02`（外套內袋）兩個點；舊版的「兩張卡同一點」對應已廢除。

## 6. `nodes`：主張節點（主張依章、編號；之後是尾聲與熱身節點）

| 欄 | 型別 | 意義 | 來源 |
|---|---|---|---|
| id | string | `CH0n_Nk`（主張）、`CH0n_T1`（尾聲第二說詞）、`CH0n_W1`（熱身的錯誤說法） | — |
| chapter | number | 章號 | — |
| case | string | 所屬論戰 `opponents.id` | — |
| kind | string | `claim`／`tail`／`warmup` | — |
| idx | number | 節點池順序（1 起；裁決 B19：回復依節點池順序） | 10-cases 主張節點表 |
| textKey | string | 主張文字 | 主張：`CLM_CH0n_Nk`；尾聲：`CLM_CH0n_T1`；熱身：`CLM_CH03_W1`（在地化包，裁決 D12） |
| tags | string | 節點自己的標籤（§0.4；裁決 C4） | `tags_ch01-03.csv`（10-cases 標籤值的節點表） |
| grazingTags | string | 節點的擦邊標籤 | 同上 |
| truth | bool | 主張為真 | `CLM` 備註 truth（真／假） |
| refutable | bool | 有破解證物（Ch.2 N2 為 false：反駁必定空過） | — |
| refutedBy | string | 破解證物，多值 | 主張：`CLM` 備註「refuted by」中的證物 id（含「或」「＋」「、」皆列入）；尾聲：裁決 C3；熱身：10-cases Ch.3 熱身＋裁決 B16（單張，任一皆可） |

## 7. `opponents`：論戰對手（每場論戰一列，依章；熱身在該章主論戰之後）

| 欄 | 型別 | 意義 | 來源 |
|---|---|---|---|
| id | string | `CH0n_MAIN`、`CH03_WARMUP` | — |
| chapter | number | 章號 | — |
| kind | string | `pudding`（Ch.1 布丁論戰）／`main`／`warmup` | 01-systems A-13 |
| speaker | string | 對手名字的字串鍵 `SPK_*` | 劇本說話者 |
| type | string | `protector`（庇護者）／`culprit`（犯人）；熱身空白 | 10-cases 各章對手 |
| hp | number | 對手主導權；不扣血者 0 | 02-numbers §五 |
| playerHp | number | 我方主導權；不扣血者 0 | 02-numbers §一 |
| noDamage | bool | 不扣血 | 01-systems A-13 |
| nodeCap | number | 節點上限（熱身＝錯誤說法數） | 02-numbers §五；熱身：10-cases 數值卡「1 回合」 |
| damageBase | number | 主張傷害基礎值（`base + damagePerNode × n`） | 02-numbers §五 |
| damagePerNode | number | 每個節點 +4 | 02-numbers §一 |
| rushMul | number | 猛攻倍率 1.25 | 02-numbers §一 |
| w_claim／w_rush／w_reinforce／w_trap | number | 性格傾向權重（主張／猛攻／補強／設陷） | Ch.2～3：02-numbers §四 犯人型＋裁決 B15；Ch.1：庇護者型，猛攻與設陷改 0（待確認 Q9）；熱身：只有主張 |
| clear／fuzzy／disguise | number | 預兆清晰度配比（%，明示／模糊／偽裝） | 02-numbers §一前期；Ch.1 與熱身 100/0/0（A-3、A-13） |
| rules | string | 適用的行為規則編號，多值 | 10-cases 對手行為表「適用行為規則」（解析） |
| ruleBias | number | 傾向規則照做機率（%） | 02-numbers §四（約 80%） |
| mirror | bool | 鏡像（維多）；Ch.1～3 皆 false | — |
| gestureAssert／gestureRush／gestureReinforce／gestureTrap | string | 各行動固定小動作的字串鍵 `GESTURE_<ARTHUR\|FITCH\|PIERCE>_<ASSERT\|ONSLAUGHT\|REINFORCE\|TRAP>`；不使用的行動空白 | 在地化包；哪些行動有小動作依 10-cases 對手行為表「小動作預兆」（zh 不同時警告） |
| playerActions | string | 玩家可用行動，多值：`solid`、`sophistry`、`rebut`、`observe` | Ch.1：劇本「詭辯本章未解鎖」；Ch.2～3：裁決 B20；熱身：A-13 只開放反駁 |
| tail | string | 尾聲反撲類型：`scorched`（玉石俱焚）；無尾聲空白 | 10-cases 論破與尾聲 |
| tailNode | string | 尾聲第二說詞節點 `nodes.id` | 01-systems A-9 |
| roundLimit | number | 回合上限（Ch.1：6，第 6 回合結束仍未論破＝未達成）；0＝無 | 裁決 A4、D15 |
| contraTarget | number | 需指出的矛盾數（Ch.1：2）；0＝不適用 | 同上 |
| contraDeadline | number | 必須在此回合結束前指出 `contraTarget` 個矛盾，否則未達成（Ch.1：3）；之後論破回合不限，錯過可在下一個矛盾後再來（裁決 B21）；0＝不適用 | 裁決 D15 |
| mistakeLimit | number | 失誤上限：熱身錯誤出示 3 次 → 對手不耐；0＝無（Ch.1 依裁決 A4 沒有失敗狀態） | 01-systems A-13、裁決 A4 |
| hand | string | 熱身開始時的手牌（自動持有的證物），多值 | 10-cases Ch.3 熱身 |
| handPerMissed | number | 每漏 1 件證物對手手牌 +n | 10-cases Ch.2／Ch.3 數值卡（暫定） |
| hpPerMissed | number | 每漏 1 件證物對手主導權 +n | 同上（待確認 Q10） |

## 8. `tells`：論戰台詞庫（S90 每行一列，依章、行號；不含標題與備註行）

| 欄 | 型別 | 意義 |
|---|---|---|
| id | string | 劇本行 id |
| chapter | number | 章號 |
| case | string | 所屬論戰 `CH0n_MAIN` |
| category | string | `tell`（預兆台詞）、`action`（行動台詞）、`endgame`（尾聲台詞）、`sfAction`（Sherefox 行動台詞）、`reaction`（反應台詞）、`tutorialHint`（系統教學提示，Ch.1）、`arthurHint`（亞瑟的預兆提示）、`cornered`（困獸台詞）、`taunt`（嘲諷失守）、`sfState`（Sherefox 狀態台詞）、`arthurState`（亞瑟狀態台詞）、`stateHint`（狀態教學提示） |
| action | string | 行動或子類：`assert`、`rush`、`reinforce`、`trap`、`scorched`、`solid`、`sophistry`、`rebut`、`observe`、`clash`、`cutin`、`standoff`、`unstoppable1`～`3`、`unstoppable`、`breached`、`cornered`、`bannerBreak`、`bannerShaken`、`bannerUnstoppable`、`unstoppablePreview`、`corneredBreached`；沒有則空白 |
| speaker | string | 說話者 `SPK_*`；純演出行空白 |
| text | string | 字串鍵（＝id） |
| gesture | string | `tell` 列的小動作字串鍵（同 `opponents.gesture*`） |
| inactive | bool | 本章不會觸發／未解鎖（同 `script.inactive`） |
| group | string | `case:category:action`，供以 `atrium.table.find`（column=`group`、filterColumn=`n`）抽句 |
| n | number | 在 group 內的序號，0 起 |
| groupSize | number | 該 group 的列數（流圖以種子亂數取 `0..groupSize-1`） |

推導：在地化備註第一段決定 category 與（若有）action，例 `Tell line: Assert (gesture: …)`、`Action line: Onslaught`、`Arthur Tell-hint line | action: Reinforce`；`Sherefox action line | Solid Chain` 這類只在一組的第一行寫子類，同章同 category 之後沒寫子類的行沿用上一個子類（來源的寫法如此）。標籤對照見 `LIBRARY_LABELS`；遇到不認得的備註，建置失敗。

## 9. `papers`：報紙（章節交界的合併報紙；依章）

裁決 D5：章節交界只有**一份**報紙，放在下一章開頭。主頭條與導言（`headlineKey`、`subKey`、`bodyKey`）是該章劇本 S01 開場（`HEAD_CH0n`、`HEAD_CH0n_SUB`、`SCR_CH0n_S01_L003`）；側欄刊上一案的結果，提供勝利／惡名／敗北三個版本，由流圖在執行時依「頭條判定順序」（01-systems §3.3）選一個。共 4 列：`CH01_OPEN`、`CH02_OPEN`、`CH03_OPEN`，以及 Ch.3 之後的最終報紙 `CH04_OPEN`（原型結尾：Ch.4 的開場合併報紙，裁決 E1）。

| 欄 | 型別 | 意義 |
|---|---|---|
| id | string | 章首報紙 `CH0n_OPEN`（n＝1～4；`CH04_OPEN` 是原型結尾的最終報紙） |
| chapter | number | 它開啟的那一章（`CH04_OPEN` 為 4；這一步記在 Ch.3 的步驟序列末尾） |
| kind | string | `open`（章首合併報紙，含 `CH04_OPEN`） |
| group | string | 報紙群組（＝id）；`steps.arg` 與 `chapters.openPaper`／`endPaper` 指向群組 |
| resultChapter | number | 側欄結果所屬的案件章號；`0`＝沒有上一案（Ch.1，側欄是開場城市新聞 `NEWS_00_OPEN`） |
| mastKey | string | 刊頭 `UI_PAPER_MAST` |
| headlineKey | string | 主頭條：`HEAD_CH0n` |
| subKey | string | 主頭條副標：`HEAD_CH0n_SUB` |
| bodyKey | string | 導言／頭版內文：劇本 `SCR_CH0n_S01_L003`（`CH04_OPEN` 用 `SCR_CH04_S01_L003`；Ch.4 的劇本行不進 `script` 表，只當這份報紙的導言） |
| page2Key | string | 第二版：只有 `CH01_OPEN` 有值（`NEWS_00_OPEN_SUB`，開場廣告）；其餘空白 |
| page2SubKey | string | 第二版副標；目前全空白 |
| sideKey | string | 側欄的社會短訊 `NEWS_SIDE_0n`（n＝`resultChapter`；`resultChapter=0` 時空白） |
| sideWinKey／sideWinSubKey | string | 側欄結果：勝利版的標題與副標（`NEWS_0n_WIN`、`NEWS_0n_WIN_SUB`） |
| sideNotoKey／sideNotoSubKey | string | 側欄結果：惡名版（`NEWS_0n_NOTO`、`_SUB`） |
| sideLoseKey／sideLoseSubKey | string | 側欄結果：敗北版（`NEWS_0n_LOSE`、`_SUB`） |

- 只有一個版本的結果（`NEWS_00_OPEN`、`NEWS_01_END`）：三組欄位填同一個鍵，流圖不需特判。
- 副標欄：zh 文字以「第二版」開頭的 `_SUB` 是下一案引子，不是副標，不寫進表（引子即下一章的 S01 主頭條）：`NEWS_01_END_SUB` 因此不使用；`NEWS_00_OPEN_SUB` 是第二版廣告，放 `CH01_OPEN.page2Key`。`NEWS_xx_NEXT` 鍵已廢除（裁決 E1）。
- `CH04_OPEN` 的側欄是 Ch.3 的結果（`NEWS_03_WIN`／`NOTO`／`LOSE` 與 `_SUB`）。
- 流圖選版：敗北 → `sideLoseKey`；勝利且惡名 ≥ 3 → `sideNotoKey`；否則 `sideWinKey`（01-systems §3.3 頭條判定順序）。
- 結算場景（裁決 D6）：劇本結算台詞在 `result` 步驟播放；`NEWS_*` 結果頭條只在這張表的側欄出現。

「據稱過程頗有爭議」（`UI_PAPER_DISPUTE`）、「偵探手法亦遭質疑」（`UI_PAPER_NOTO_LOSE`）、「另有民間人士協助」（`UI_PAPER_CREDIT`）屬於 §3.3 的組版規則，不寫進表，由流圖依惡名值附加。

## 10. `difficulty`：難度（`story`、`standard`、`master`）

全部數值依 01-systems §6.1 轉錄（表格是文字敘述，未以程式解析）。流圖一律從此表讀，原型只用 `standard`。

| 欄 | 型別 | 故事／標準／名偵探 | 意義 |
|---|---|---|---|
| id | string | story／standard／master | — |
| nameKey／descKey | string | `UI_DIFF_STORY`／`UI_DIFF_NORMAL`／`UI_DIFF_MASTER`（＋`_DESC`） | 名稱與說明 |
| playerHpMul | number | 1.5／1／1 | 玩家主導權倍率 |
| playerHpEarly／Mid／Late | number | 150,180,225／100,120,150／同標準 | 各期玩家主導權 |
| oppHpMul | number | 0.8／1／1.1 | 對手主導權倍率 |
| claimMul | number | 0.5／1／1.25 | 對手主張傷害倍率 |
| rushMul | number | 1.25 | 猛攻再乘 |
| trapCrit | number | 12／25／30 | 設陷暴擊 |
| ch10PenaltyPct／ch10PenaltyMin | number | 25,12／50,25／50,30 | Ch.10 詭辯懲罰 |
| parryCounter | number | 30 | 反駁截斷反擊 |
| reinforceHealPct | number | 5／10／10 | 補強未被打中的回復（最大主導權 %） |
| breakPctEarly／Mid／Late | number | 70／75／80 | 論破傷害 |
| shakenRounds | number | 2 | 動搖持續回合 |
| tailWrongEarly／Mid／Late | number | 15,30,40／30,60,80／同標準 | 尾聲答錯 |
| tailRoundsBonus | number | 1／0／0 | 尾聲收尾回合加成 |
| assists | number | 2／1／1 | 援護次數（每場） |
| instinct | number | 3／2／1 | 狐耳直覺次數 |
| clearBonusPct | number | 20／0／0 | 明示比例加點（從模糊扣） |
| starMark | bool | true | 模糊預兆顯示 ★ |
| gestureHint | string | `portrait`／`notes`／`none` | 小動作提示：立繪旁標出／只記在對手筆記／不記錄 |
| recommendCell | bool | true／false／false | 對決表推薦格 |
| estimates | bool | true／true／false | 顯示傷害與論破預估 |
| ticksDelta | number | 4／0／−2 | 蒐證刻度增減 |
| appraisalsDelta／appraisalsMin／appraisalsUnlimited | number／number／bool | 0,0,true／0,0,false／−1,1,false | 鑑定次數（名偵探 −1、最少 1；故事模式不限） |
| hotspotGlow | string | `always`／`near`／`nearDim` | 調查點顯示 |
| remainHint | string | `exact`／`vague`／`none` | 亞瑟剩餘證物提示 |
| reputationHint | bool | true／false／false | 結算顯示「風評」 |
| retry | bool | true／true／false | 可重新論戰 |
| save | string | `normal`／`normal`／`restricted` | 存檔限制 |
| trueEnd | bool | true | 可達成 True End |
| masterAchievement | bool | false／false／true | 名偵探成就 |

## 11. 字串表

- `strings.json` 的全部 1659 個鍵原樣輸出（zh-TW 為空字串的 `*_SUB` 鍵照樣保留空字串）。
- 新增（共 12 個）：
  - `SPK_*`（12 個）：劇本說話者欄的名稱，鍵＝`SPK_`＋英文說話者名稱大寫、非英數字元換成 `_`（例 `SPK_INSPECTOR_BASKERVILLE`、`SPK_NARRATION_ARTHURS_NOTES`）。演出、證物描述、分支、備註、場景標題這些偽說話者沒有鍵。
- 標籤值（`TAG_*`）、小動作（`GESTURE_*`）、章名（`CHAP_0n_TITLE`）、尾聲與熱身主張（`CLM_CH0n_T1`、`CLM_CH03_W1`）都由在地化包提供，不再由建置產生。
- 合計 1671 鍵。

## 12. `game.json` 的 tables 區塊

```json
"tables": {
  "chapters": "data/chapters.json",
  "steps": "data/steps.json",
  "script": "data/script.json",
  "evidence": "data/evidence.json",
  "tags": "data/tags.json",
  "hotspots": "data/hotspots.json",
  "nodes": "data/nodes.json",
  "opponents": "data/opponents.json",
  "tells": "data/tells.json",
  "papers": "data/papers.json",
  "difficulty": "data/difficulty.json"
}
```

## 13. `tags`：標籤（每個不同的 `category:slug` 一列，依 id 的字元序）

| 欄 | 型別 | 意義 | 來源 |
|---|---|---|---|
| id | string | 機器標籤 `category:slug`（`evidence.tags`／`nodes.tags` 中出現的值） | §0.4 |
| category | string | 類別 id（`time`／`place`／`person`／`phys`／`scandal`） | §0.4 |
| slug | string | 值的機器形式 | 標籤檔 `slug` |
| nameKey | string | 顯示鍵 `TAG_<CATEGORY>_<SLUG>`（裁決 D13） | §0.4 |

## 待確認

每一項：問題、來源、目前的選擇。裁決紀錄（`docs/rulings.md`）已回答的不再列（B15、B16、B20、A4、C1～C3、D2、D3、D5、D6 已套用；C4、D8、D11、D13 已依 10-cases 標籤值套用；D12、D13 的鍵已由在地化包第二批提供，原 Q1、Q2、Q18、Q19、Q20 刪除；原 Q3、Q4、Q5、Q11 因此刪除；調查點表（10-cases「調查點」，裁決 D1）定案後，原 Q6、Q7、Q8、Q15、Q16、Q17 刪除，新增 Q24～Q27；其餘編號不變）。

| # | 問題 | 來源 | 目前的選擇 |
|---|---|---|---|
| Q9 | Ch.1 亞瑟的性格權重未給（只說「補強居多、不用猛攻與設陷」） | 10-cases Ch.1 對手行為表；02-numbers §四 | 庇護者型 25／5／50／20 去掉猛攻與設陷 → 25／0／50／0 |
| Q10 | 「每漏 1 件 → 手牌 +1、主導權 +10」只出現在 10-cases 的暫定數值卡（Ch.2、Ch.3）；01-systems A-1 只對 Ch.4／Ch.5 寫明節點 +1 | 10-cases 數值卡；01-systems A-1；02-numbers §五 | `handPerMissed=1`、`hpPerMissed=10`（Ch.2、Ch.3） |
| Q12 | 在地化包的 E03_01_TAGS（時間・人物）、E03_03_TAGS（地點・物理）比 10-cases 證物表（時間・人物・物理、地點・物理・人物）少一類 | 10-cases Ch.3 證物表；在地化 evidence | 機器標籤照 10-cases 標籤值；顯示字串 `tagsKey` 待在地化更新（建置警告） |
| Q13 | 熱身手牌 E03_05、E03_02 依 A-13 在熱身前持有（事件中自動取得）；調查點表已把 `HS_CH03_03`、`HS_CH03_07` 寫成「事件中已取得，可重看」，建置標 `revisit=true`、`evidence.obtain=event`。未定：重看是否消耗刻度、鑑定 E03_02 在熱身中是否扣次數 | 01-systems A-13；10-cases Ch.3 調查點表、熱身；20-script Ch.3 S04 | 熱身開始時把 `hand` 加入持有；重看照一般調查點處理（首次花 1 刻度、之後免費）；熱身中的鑑定次數由流圖決定 |
| Q14 | 驗屍報告（E03_01）在信任度 ≥ 3 時由警方直接給予（已鑑定），調查點表的案件筆記寫「這裡只看得到現場」；信任度 < 3 時要在 `HS_CH03_01` 取得並醫療鑑定。信任度 ≥ 3 時這個點是否還花刻度、播放什麼，設計沒寫 | 10-cases Ch.3 調查點表、熱身；01-systems §3.1 | 表中 E03_01 `obtain=hotspot`；信任度分支由流圖處理 |
| Q21 | E02_01 的 `refutes` 同時含 N3 與尾聲 T1；E03_04（強攻）不在任何節點的破解清單，論破時靠 N2 的 E03_02 | 10-cases 主張節點表；裁決 C3 | 照列 |
| Q22 | 動機旗標：Ch.1 對手是庇護者但沒有尾聲；Ch.1～3 都沒有指定動機證物 | 01-systems §2.8；10-cases | 全部 false |
| Q23 | 進入蒐證場景時亞瑟的開場觀察台詞（§1.4「每章 1 句」）沒有指定是哪一句；Ch.1 亞瑟還不是助手 | 01-systems §1.4、§1.11 | 不寫入表，由流圖決定（ART_OPEN_GEN／ART_OPEN_BODY） |
| Q24 | 設計表「區域」欄：Ch.1 在同一場景分「廚房／客廳」，Ch.2 在同一場景分 6 個區域（櫃台、店面、店門外、後室門口、角落、櫃台後），超過 01-systems §1.2「每場景最多 3 個區域」；Ch.3 區域＝三個場景 | 10-cases 調查點表；01-systems §1.2；裁決 D10 | `area` 全部 0（每場景一個畫面）；區域欄轉成 `zone` slug 當位置分組，UI 可忽略；區域沒有字串鍵（只在在地化備註 `area: 廚房 / Kitchen`），需要顯示時再請在地化補 |
| Q25 | 論戰後的 `HS_CH02_08`（角落咖啡座）：蒐證步驟之後沒有第二個 investigate 步驟，設計沒寫它在哪個畫面、是否花刻度 | 10-cases Ch.2 調查點表；20-script Ch.2 S04「（論戰後取得）」 | `phase=postDebate`，`evidence.obtain=afterDebate`；步驟序列不加步驟，由流圖決定 |
| Q26 | 調查點數與 §1.3 一致後仍有兩項比例偏離：Ch.2 刻度 10 ÷ 12 點 ＝ 0.83（設計 0.65～0.75；蒐證階段實際可點 11 個，0.91）；Ch.3 檢視點 13／22 ＝ 59%（01-systems §1.2 約 40%，裁決 D1 原寫 11 個檢視點） | 01-systems §1.2、§1.3；裁決 D1；10-cases 調查點表 | 照設計表；建置以警告列出，不改數字 |
| Q27 | `HS_CH03_23_NAME` 的 zh-TW 文字是「鍋爐室角落的新調查點（只在缺少 G-01 時出現，不計入 22 個）」，括號是設計備註而非玩家文字；`HS_CH02_08_NAME` 帶「（論戰後）」 | 在地化包；10-cases 調查點表 | 照鍵輸出；UI 若不想顯示括號內文字需請在地化提供乾淨名稱 |
