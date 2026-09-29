# Wii Fit Giant Trackpad

手元のWii Fitバランスボードを、Windows用の「くそでかトラックパッド」にする実験アプリです。

別プロジェクトの自作アプリ **Vibe SpaceMouse Bridge for Codex** で使っている
`hidapi + Python + Tkinter + PyInstaller` の構成、設定保存、ログ、配布方法を土台にしています。
SpaceMouse固有の仮想HIDや3DxWare制御は使いません。

## 現在できること

- Wii Balance Board (`Nintendo RVL-WBC-01`) をBluetooth HIDとして直接読む
- EEPROMの0 / 17 / 34kg校正値から4隅の荷重をkgへ変換
- 4点荷重から重心X/Yを求め、足を動かした差分だけカーソルを相対移動
- 基準位置から傾けている間カーソルが動き続ける「ジョイスティック」モード
- ボードから降りると、カーソルを現在位置で停止
- ボード前面のボタンで左クリック
- 瞬間的な荷重増加（軽い踏み込み）で左クリック
- 任意の「静止クリック」（既定はオフ）
- 現在の荷重・重心を表示するTkinterダッシュボード
- ゲイン、平滑化、反応開始荷重、上下左右反転、静止時間を保存
- ハードウェアなしで実行できる単体テスト

## 安全

バランスボードは平らで滑らない場所へ置き、最初は机や手すりにつかまって試してください。
クリックには軽く素早い踏み増しを使います。ジャンプや強い踏みつけはしないでください。
「静止クリック」は意図しないクリックを避けるため既定でオフです。

## セットアップ

Windows 10/11 x64とPython 3.12を想定しています。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

1. バランスボードの電池カバーを開き、赤い `SYNC` ボタンを押します。
2. WindowsのBluetooth画面で `Nintendo RVL-WBC-01` をペアリングします。
3. 次のコマンドでボードが見えることを確認します。

```powershell
.\.venv\Scripts\python.exe -m wiifit_trackpad list
```

WindowsのBluetoothドライバによっては、バランスボードでも `Nintendo RVL-CNT-01` と
表示されます。その場合も候補として開き、EEPROMの校正データを読めるかで実機判定します。

## 使い方

まず、カーソルを動かさない診断モードでセンサー値を確認します。

```powershell
.\.venv\Scripts\python.exe -m wiifit_trackpad monitor --seconds 10
```

GUIを起動します。

```powershell
.\.venv\Scripts\python.exe -m wiifit_trackpad gui
```

または `Start-WiiFit-Trackpad.cmd` をダブルクリックします。

1. `開始` を押す
2. ボードに乗る
3. 足を置いた地点が移動開始地点になる
4. そこから足／重心を左右・前後へ動かしてカーソルを操作する
5. 足を離して置き直してもカーソルは飛ばず、新しい地点から続けられる

「ジョイスティック」へ切り替えると、足を置いた位置がニュートラルになります。そこから
左右・前後へ傾けている間はカーソルが動き続け、ニュートラル付近へ戻すと停止します。
接地直後の偏った荷重を中心にしないよう、足を置いてから約0.5秒間は姿勢を取り込みます。
傾きを大きくするほど速くなり、中央付近のセンサーノイズだけを小さな遊びとして無視します。

一度の足移動で進む距離が短い場合は「カーソル移動量」を上げます。カーソルが揺れる場合は
「平滑化」を右へ動かすと、荷重変化を時間方向にならして滑らかに動きます。
微小なセンサーノイズはデッドバンドで自動的に無視します。

既定では合計 `0.15kg` から反応します。「反応開始荷重」は `0.05～3.0kg` で調整でき、
小さくすると指や手で軽く押した場合にも反応します。無荷重でカーソルが動く場合は少し上げてください。

既定では、接地してから約0.18秒以内に荷重が4kg増えると左クリックします。最初に乗った
瞬間はクリックになりません。「踏み込みクリック」の値を小さくすると軽い入力で反応し、
大きくすると誤クリックしにくくなります。ボード前面のボタンと任意の「静止クリック」も使えます。

## CLI

```powershell
python -m wiifit_trackpad list
python -m wiifit_trackpad monitor --seconds 10
python -m wiifit_trackpad run
python -m wiifit_trackpad gui
```

設定とログ:

- 設定: `%LOCALAPPDATA%\WiiFitGiantTrackpad\settings.json`
- ログ: `%LOCALAPPDATA%\WiiFitGiantTrackpad\logs\app.log`

## テスト

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 配布版ビルド

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_release.ps1
```

`dist\WiiFitGiantTrackpad\WiiFitGiantTrackpad.exe` が生成されます。

## 現時点の制限

- 初回BluetoothペアリングはWindows側で行います。
- 実機ごとのBluetoothスタック差は未検証です。
- ドラッグ、右クリック、スクロール、ジェスチャーは未実装です。
- マルチボード選択UIは未実装です。

## License

MIT。依存ライブラリと商標については `THIRD_PARTY_NOTICES.txt` を参照してください。
