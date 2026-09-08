# Claude使用量ディスプレイ（2.8インチ TFT / ILI9341）

PCで取得したClaude使用量を、Picoにつないだ2.8インチカラーTFT（MSP2807 / ILI9341）に常時表示するプロジェクト。
**部品（MSP2807）到着前に、コードと手順を先に用意した状態**です。

## 構成
```
[PC] claude_usage で使用量取得 ──(60秒ごと WiFi POST)──▶ [Pico] TFTに描画
```
Pico自身はClaude認証を持てないため、PCが値を取得してPicoへ送る方式。

---

## 1. 配線（Pico ⇔ MSP2807 / 表示に使う8本）

| MSP2807側 | Pico GP | Pico 物理ピン | 役割 |
|-----------|---------|--------------|------|
| VCC       | 3V3 OUT | 36           | 電源 |
| GND       | GND     | 38           | グランド |
| CS        | GP17    | 22           | チップセレクト |
| RESET     | GP14    | 19           | リセット |
| DC / RS   | GP15    | 20           | データ/コマンド切替 |
| SDI(MOSI) | GP19    | 25           | データ入力（SPI0 TX） |
| SCK       | GP18    | 24           | クロック（SPI0 SCK） |
| LED       | 3V3 OUT | 36           | バックライト（常時点灯） |

- 使わない端子（SDO/MISO・タッチ T_*・SD関連）は**未接続でOK**。
- VCC と LED はどちらも 3V3 OUT(36番)へ。物理36番が2本になる場合は近くのもう一つの3V3でも可。
- ⚠️ MSP2807は 3.3V 動作。Picoは3.3Vなので直結OK（5Vは使わない）。
- これらのピンは可変抵抗(GP26)とは別系統なので、可変抵抗の実験はそのまま残せる（このプロジェクトでは使わない）。

---

## 2. Picoに入れるファイル（Thonny経由で保存）

表示ドライバを GitHub **rdagger/micropython-ili9341** から入手してPicoへ保存する。

1. ブラウザで `https://github.com/rdagger/micropython-ili9341` を開く
2. 次の3ファイルの中身をコピーし、Thonnyで新規ファイルに貼り付け → Raspberry Pi Pico に保存:
   - `ili9341.py`
   - `xglcd_font.py`
   - `fonts/Unispace12x24.c` → ファイル名 **`Unispace12x24.c`** でPicoに保存
3. `usage_display/pico/main.py`（このリポジトリ）をThonnyに貼り付け → Picoに **`main.py`** で保存
   - WiFi（SSID / パスワード）は記入済み

→ Picoのファイル一覧が `main.py / ili9341.py / xglcd_font.py / Unispace12x24.c` の4つになればOK。

---

## 3. PC側スクリプトの準備

1. `usage_display/pc/send_usage.py` を、`claude_usage.py` を import できる場所に置く
   （`claude_usage.py` と同じフォルダに置くのが簡単）
2. Picoを起動し、Thonnyの下のShellに出る **IPアドレス**を確認
   ```
   WiFi接続成功! PicoのIP: 192.168.x.x
   ```
3. `send_usage.py` の `PICO_IP = "192.168.x.x"` を、その値に書き換える

---

## 4. 動かす

1. Picoに電源（USB）→ TFTに日付・時計と「Waiting for PC data...」が出る
2. PCで `python3 send_usage.py` を実行
3. 60秒以内に、TFTにラベル・％・カラーバー・リセット時刻が表示される

---

## 注意・既知の調整ポイント
- `main.py` の表示部は **rdagger版ドライバのAPI前提**。実機で `rotation` や色など微調整が要る場合あり
  （その時は描画関連の関数だけ直せばよい構造にしてある）。
- 円形ゲージではなく**横棒ゲージ**にしている（SPI描画で確実・高速なため）。動作確認後、見た目を強化していく。
- 時計はNTPで同期（UTC+9）。同期に失敗しても表示は動く（時刻だけずれる）。

## 次にやること（部品到着後）
- 実機で配線→ファイル保存→動作確認
- 色・レイアウトの調整、必要なら円形ゲージ化
- PC起動時に `send_usage.py` を自動実行する設定
