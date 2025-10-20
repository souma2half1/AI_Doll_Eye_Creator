# ChatGPT 設定ファイルの場所

`config/chatgpt_settings.env` に OpenAI(API) の情報を記述してください。リポジトリには編集用のテンプレートとして `chatgpt_settings.env.template` を同梱しています。

## 設定手順
1. `config/chatgpt_settings.env.template` をコピーして `config/chatgpt_settings.env` を作成します。
2. `OPENAI_API_KEY` にご自身の API キーを入力します。
3. モデルや画像サイズを変更したい場合は、コメントアウトされている `PROMPT_MODEL` などの行のコメント (`#`) を外して希望の値を記入します。
4. アプリは起動時にこのファイルを読み込みます。

> ⚠️ `config/chatgpt_settings.env` には秘密情報が含まれるため、Git にはコミットしないでください。
