# R34 Observatory · 熱帶氣旋觀測台

https://popo825.github.io/TC_Radius_of_34knot_wind_Inference/

每小時批次推論的研究展示網站：GitHub Actions 取得全球氣旋與原始 11.2 µm IR → 既有 PyTorch 模型推論 → GitHub Pages 顯示地圖、59-bin 曲線與 mean。

網站前端已發布。此次每小時批次版本需推送更新並上傳模型 Release 後才會開始雲端推論。沒有更動或重新訓練模型；Python / PyTorch 只在排程工作中執行，訪客直接讀取靜態結果，不需要付費常駐後端。原本 FastAPI 仍保留作為研究用 API。

## 目前電腦啟動

專案位於 `C:\Users\cwycw\OneDrive\2026_Research\R34_website`，原本的 Notebook、權重均保留。

雙擊 `start.cmd`，先產出一批最新觀測，等待顯示 HTTP server 已啟動，然後開啟 **http://127.0.0.1:8000**。啟動後請保留終端視窗；按 Ctrl+C 停止服務。需要可對外連線的網路來更新氣旋與衛星資料。

也可從 PowerShell 執行：

```powershell
cd 'C:\Users\cwycw\OneDrive\2026_Research\R34_website'
.\start.ps1
```

此機已準備 `.runtime` 本地套件，使用現有 Miniconda Python 3.12 / PyTorch CPU；不改動原本的全域套件。首次載入與衛星下載可能需要數十秒到數分鐘。原始衛星檔案暫存在 `.cache`，最多保留最近 30 個原始檔；小型裁切與來源紀錄保留以便追溯。

## 新電腦安裝

建議 Python 3.12，先放入自己的可信任模型檔，再執行：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m backend.batch --output dist
.\.venv\Scripts\python -m http.server 8000 --bind 127.0.0.1 --directory dist
```

預設讀取根目錄的 `TCR34_reference_DNN_test1_25MAE.pth`。更換模型時設定 `$env:R34_MODEL_PATH='C:/path/model.pth'` 並重啟服務；新權重需維持相同架構與 bins。`.env.example` 只說明設定，不會自動載入。模型以 `weights_only=True` 與必要的 NumPy 型別白名單讀取，禁止退回任意 pickle 執行。

## 每小時雲端更新與第一次啟用

1. 此 repo 的 **Settings → Pages → Source** 維持 **GitHub Actions**。
2. 在 **Releases → Draft a new release** 建立 tag **`model-v1`**，title 可填 `R34 model v1`。把原始 `TCR34_reference_DNN_test1_25MAE.pth` 拖入 release assets，等待上傳完成後按 **Publish release**。公開 repo 的 Release 權重任何人都可下載；這是依本次選擇公開權重的設定。
3. 把這次修改的程式與 `.github/workflows/pages.yml` 提交並推送到 `main`。工作流程會自動執行；也可到 **Actions → Hourly R34 inference and Pages → Run workflow** 手動執行。
4. 預設從 `https://github.com/popo825/TC_Radius_of_34knot_wind_Inference/releases/download/model-v1/TCR34_reference_DNN_test1_25MAE.pth` 下載模型，SHA-256 必須符合 `3bca4f0a6007678298203692c29c17181753632e7fec2132105b1a7939a5a410`。模型下載失敗或雜湊不符時不發布新網站。
5. 成功後，GitHub Pages 會顯示本批次的全球系統、IR 與推論結果。網站每 5 分鐘檢查新批次；訪客按「查看 R34 辨識結果」只顯示已完成的推論，不啟動新運算。

排程為 `17 * * * *`，即每小時第 17 分鐘啟動（UTC 與台灣時間在每小時的分鐘數相同）。這是**啟動時間**，不是影像的觀測時間或結果完成時間。工作在 GitHub 的標準 Ubuntu runner 上執行；你的電腦可以關機。

更換模型下載位置可在 **Settings → Secrets and variables → Actions → Variables** 設定 `R34_MODEL_URL` 與 `R34_MODEL_SHA256`。只有相同架構／bins 的新權重可直接更換；請同步更新實際 SHA-256。不要把權重加入一般 Git 提交，它仍被 `.gitignore` 排除。Release 資產與普通 Git 檔案是不同的儲存方式。

### 費用與排程限制

- 目前公開 repo 的標準 GitHub-hosted runner 運算免費；不使用付費大型 runner 或 GPU。Pages 受網站容量與流量限制。
- pip 套件與已驗證模型使用 Actions cache；不快取原始衛星檔。Pages artifact 只保留 1 天，只上傳 `dist`。仍需留意帳號的 cache／artifact 儲存配額及未來政策，不能視為無上限資源。
- 原始衛星資料與權重不發布到 Pages。產出圖、CSV、JSON 可公開下載，但不會每小時把新影像提交進 Git 歷史。
- GitHub 排程可能延遲或漏跑，公開 repo 60 天沒有活動時可能停用排程。這是研究展示更新，不是保證準點的作業服務。
- 網站超過 2 小時未更新會警示；影像與定位時間分別顯示。單一氣旋失敗可沿用同一模型、影像 6 小時內的上次成功結果並標為「上次成功」。整體清單來源失效時批次失敗，保留原部署。
- 部分印度洋系統缺乏目前 adapter 可用的即時 11.2 µm 覆蓋，仍會列出但不產生假預測。

### 網站操作

1. 從地圖或側欄選取氣旋，載入最近一批的 IR 裁切。
2. 按 **查看 R34 辨識結果**，顯示 59 個 bin 的 Softmax 機率與 `mean = Σ pᵢrᵢ`。
3. 按 **CSV ↓** 匯出分布、mean、中心、影像／定位時間、頻道與模型 SHA-256。
4. 按重新整理只重新讀取已發布批次，不會要求雲端重新推論；專案管理者可在 Actions 手動啟動一次工作。

沒有 Ground Truth，因此不畫真值、軟標籤或 MAE。`25MAE` 只是既有模型檔名，不是本網站已驗證的即時準確度。

## 科學規格與限制

- 原始架構：`HurricaneAlexNet_ReferenceDNN`，依 `Sep_LDL_test.ipynb` 重建並嚴格載入 `model_state_dict`。輸出 bins 從 checkpoint 讀取，驗證為 `10, 15, …, 300 n mi`，共 59 個。
- GOES：ABI Level-2 CMIP Full Disk 的 **C14 / 11.2 µm**。IR CMI 已為 Kelvin，保留 DQF 0/1，雙線性重採樣。GOES-16 訓練資料與現行 GOES-19/18 同頻段仍可能存在感測器差異。
- Himawari：AHI HSD **B14 / 11.2 µm**，由 Satpy 使用檔案校準係數解碼為 Kelvin，最近鄰重採樣。顯示的彩色 PNG 不參與推論。
- 空間：採 **8 km/pixel**，156 個像素的外緣寬度為 **1,248 km ≈ 673.87 n mi**。局地 WGS84 等距方位投影，北朝上，中心位於四個中央像素之間。像素中心間距 8 km，首尾中心相距 1,240 km。
- **仍需核對訓練時的實際格網**：約 `0.078°` 並不嚴格等於 8 km；經向寬度也隨緯度改變。本版選擇固定物理範圍。若原始 GridSat 裁切使用固定經緯間距，必須調整 adapter 才能精確一致。此差異與重採樣方式可能影響辨識結果，尚未量化。
- 正規化嚴格為 `(img_K - 236.54854) / 26.703743`，shape `[1,1,156,156]`，float32。缺值少於或等於 2% 以 245 K 補值；超過 2% 拒絕辨識。不做每張影像的 min-max normalization。
- 限定有限亮溫 100–350 K；影像須在 90 分鐘內、定位 12 小時內，影像與外推基準時間差不超過 6 小時；內插只使用相隔不超過 6 小時的兩筆分析定位。裁切中心現在會對齊影像產品標示時刻，依可用定位內插或作最多 6 小時移動外推；估計不等於新的觀測，轉向、加速及結構重組仍可能造成偏心。
- 全球清單來自 Tropical Tidbits 的 ATCF 位置摘要；失敗時只回退 NOAA NHC 海盆並顯示範圍縮限。來源失效與真正的空清單分開處理。全球清單不保證涵蓋各機構尚未列出的系統或全部擾動。
- **全球顯示不等於全球 IR 已接通**。GOES 與 Himawari 以距星下點較近者選擇，超過 65° 的區域停止自動擷取，且另檢查整片裁切的資料覆蓋。印度洋的部分區域需要 Meteosat／IODC；NOAA CPC 公開全球 IR 約延遲兩天，所以本版不把它作為即時備援。
- 模型主要以北大西洋資料訓練，其他海盆未驗證。模型輸出單一半徑分布，不表示四象限風圈。Softmax 曲線不是已校準的信賴區間。

## 氣旋中心與影像時間對齊

- 活躍系統探索仍使用 Tropical Tidbits / ATCF 清單。這個網站約每 15 分鐘更新，但上游定位主要是 00/06/12/18 UTC；不能把頁面取得時間當成新定位。
- 以 NOAA NHC/CPHC `CurrentStorms.json` 的有效定位補充大西洋與東／中太平洋；以 JTWC warning 的 **WARNING POSITION** 補充其管轄海盆。JTWC 通報發布時間、REMARKS 中的 POSITION NEAR 不直接當成新的分析定位。
- 同時取得最近兩個 GFS 週期中的 **NCEP TCVitals 分析紀錄**，作為官方定位與移動向量的彙整備援。使用的是 tcvitals，不是 GFS 預報路徑。相同時間優先直接的 NHC/CPHC 或 JTWC 通報；不同時間保留成歷史定位。
- 速度單位有別：NHC JSON 的 `movementSpeed` 是 **mph**（乘 1.609344 轉 km/h），JTWC 通報是 **kt**（乘 1.852），TCVitals 為 **0.1 m/s**（乘 0.36）。方向是由真北順時針量到**移動朝向**。這些是氣旋平移速度，不是最大持續風速。
- 影像時刻剛好有分析定位時直接使用；若介於兩筆相隔 ≤6 小時的分析定位之間，以 WGS84 測地線按時間比例內插；若晚於最新定位，用該定位的移動向量等速外推，最多 6 小時。沒有向量時，才用前兩筆相隔 0.25–12 小時的定位推算最近速度。
- 不使用氣候平均移動向量；缺少可靠移動資訊、速度超過 200 km/h 或超過外推時限時停止該系統的新辨識，保留清楚標示的上次結果（若符合原本的保留限制）。
- 對齊目標為目前 adapter 使用的**全圓盤掃描起始／名義時刻**；不是每一個像素的精確掃描時刻。GOES／Himawari 的全圓盤掃描有數分鐘的時間幅度。
- JSON 的 `metadata.center_estimation` 紀錄方法、對齊時刻、基準時刻、原始座標、估計座標、移動速度／方向、位移及參考來源。CSV 也新增中心時刻、方法、來源與移動向量。側欄來源座標保留官方有效時刻，IR 下方另外列出估計裁切中心。
- `intensity_at` 保留清單中的強度資訊時間；更新中心來源並不代表強度也在該時刻重新分析。估計中心改善幾何對中，但本次尚未量化 R34 準確度改善。

來源格式：[Tropical Tidbits](https://www.tropicaltidbits.com/storminfo/)、[NHC JSON 規格](https://www.nhc.noaa.gov/productexamples/NHC_Tropical_Cyclone_Status_JSON_File_Reference.pdf)、[TCVitals 欄位與單位](https://www.emc.ncep.noaa.gov/emc/pages/infrastructure/obs-data/tcvitals_description.php)。

## 檔案與 API

```text
backend/model.py       原始架構、權重載入、固定正規化與推論
backend/storms.py      全球清單解析、NHC 有限範圍備援
backend/imagery.py     原始衛星資料、對中裁切、校準與重採樣
backend/centers.py     影像時刻中心內插／外推（WGS84）
backend/position_sources.py NHC/CPHC、JTWC、TCVitals 定位與移動向量
backend/app.py         FastAPI、背景下載工作、圖片與推論 API
backend/batch.py       每小時推論、失敗隔離與靜態結果產出
backend/fetch_model.py Release 下載與 SHA-256 核對
frontend/              純靜態介面與本地 Leaflet／海岸線
.github/workflows/     排程推論與 Pages 發布
tests/                 科學與 API 不變量檢查
artifacts/             本次真實案例輸出（預設不提交版本控制）
```

- `GET /api/health`：服務與模型檔案存在狀態。
- `GET /api/storms`：清單、資料範圍、取得時間與警示，快取 5 分鐘。
- `POST /api/imagery`：`{"storm_id":"31W"}`，回傳工作 ID。
- `GET /api/jobs/{id}`：下載與裁切進度、失敗原因或觀測 metadata。
- `GET /api/patches/{id}/image`：顯示用 PNG。
- `POST /api/patches/{id}/infer`：以同一份 Kelvin 裁切推論。
- `/docs`：FastAPI 互動 API 說明。

## 驗證

```powershell
# 此機使用本地套件
$env:PYTHONPATH="$PWD/.runtime"
python -m unittest discover -s tests -v
node --check frontend/app.js
node --test tests/frontend.test.cjs
```

測試包含格網方向及實距、南北／東西半球定位、資料來源格式變更、缺值與單位拒絕、正規化與 mean、過期推論阻擋及真實 checkpoint 形狀。另有下載當日 GOES 與 Himawari 真實觀測的端到端實測，詳見 `artifacts/validation.md`。測試通過不代表氣象準確度已驗證。

新電腦若要執行測試，請另安裝 `python -m pip install -r requirements-dev.txt`（TestClient 需要 HTTPX）。

## 本機批次與研究 API

```powershell
$env:PYTHONPATH="$PWD/.runtime"
python -m backend.batch --output dist
python -m http.server 8000 --bind 127.0.0.1 --directory dist
```

`dist/data/latest.json` 包含當批系統及完整結果；`dist/data/products/` 包含每個系統的 PNG、JSON、CSV。`dist`、`.models` 與原始資料快取不加入 Git。`start.ps1 -SkipUpdate -Port 8001` 可直接預覽已存在的批次。

保留的 FastAPI 可用 `python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000` 啟動並從 `/docs` 使用；其首頁提供靜態前端原始檔，沒有建立批次時只顯示等待狀態。原有 Dockerfile 提供這個研究 API，GitHub Actions 的每小時方案不使用 Dockerfile。

## 參考政策

- [GitHub Actions 計費](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
- [排程事件與限制](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- [GitHub Pages 限制](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)
- [Release 資產容量](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)

## 資料與第三方元件

- [NOAA GOES Open Data](https://registry.opendata.aws/noaa-goes/)、[JMA Himawari Open Data](https://registry.opendata.aws/noaa-himawari/)
- [Tropical Tidbits 氣旋位置摘要](https://www.tropicaltidbits.com/storminfo/)、[NOAA NHC current storms](https://www.nhc.noaa.gov/CurrentStorms.json)。只解析定位摘要，不使用其彩色 IR 當模型輸入；若未來大量公開提供服務，需再確認其使用規範。
- [CPC 資料格式與延遲說明](https://www.cpc.ncep.noaa.gov/products/global_precip/html/README)（僅調查，未用於實時推論）。
- [Leaflet 1.9.4](https://leafletjs.com/)（BSD-2-Clause，附 `frontend/vendor/LEAFLET-LICENSE`）；[Natural Earth 1:110m land](https://www.naturalearthdata.com/about/terms-of-use/)（public domain）。
- 介面需求參考使用者提供的 [Typhoon-Forecast](https://github.com/lkt0713/Typhoon-Forecast)，此處為自行撰寫的網站程式，未複製該專案程式碼。

自有程式與模型的授權由專案擁有者決定；本版未替模型或研究程式指定公開授權。
