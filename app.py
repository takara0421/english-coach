import streamlit as st
import google.generativeai as genai
from gtts import gTTS
import json
import random
import os
import pandas as pd
from datetime import datetime
import time
import gspread
from google.oauth2.service_account import Credentials

# --- 🛠️ 設定: モデル名はサイドバーで選択します --- 

# --- ページ設定 ---
st.set_page_config(page_title="AI英会話コーチ", page_icon="🎙️", layout="wide")

# --- 🔐 セキュリティ設定 (パスワード保護) ---
def check_password():
    """パスワード認証が成功した場合のみTrueを返す"""
    if "password_correct" not in st.session_state:
        st.session_state.password_correct = False

    if st.session_state.password_correct:
        return True

    st.markdown("## 🔒 アクセス制限")
    st.info("課金保護のため、パスワード制限をかけています。")
    
    password = st.text_input("パスワードを入力してください", type="password")
    
    # Secretsに設定がない場合のデフォルトパスワード: "english2024"
    correct_password = st.secrets.get("APP_PASSWORD", "english2024")

    if st.button("ログイン"):
        if password == correct_password:
            st.session_state.password_correct = True
            st.rerun()
        else:
            st.error("パスワードが違います")
    return False

if not check_password():
    st.stop()

# --- CSS (スマホで見やすくするためのデザイン) ---
st.markdown("""
    <style>
    .big-font { font-size: 24px !important; font-weight: bold; color: #1E88E5; }
    .word-font { font-size: 24px !important; font-weight: bold; color: #2E7D32; margin-bottom: 5px; }
    .def-font { font-size: 16px; font-style: italic; color: #555; margin-bottom: 10px; }
    .stAudio { width: 100%; }
    .stButton button { width: 100%; border-radius: 20px; }
    </style>
    """, unsafe_allow_html=True)

# --- 履歴管理用の関数 ---
# --- 履歴管理用の関数 (Google Sheets対応版) ---
HISTORY_FILE = 'history.json'
SHEET_NAME = 'EnglishCoach_Data' # ユーザーに作成してもらうスプレッドシート名
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def get_gsheet_client():
    """st.secretsから認証情報を読み込んでgspreadクライアントを返す"""
    if "gcp_service_account" not in st.secrets:
        return None
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"Google Sheets認証エラー: {e}")
        return None

def load_history():
    """履歴を読み込む (Google Sheets優先)"""
    client = get_gsheet_client()
    if client:
        try:
            sheet = client.open(SHEET_NAME).sheet1
            data = sheet.get_all_records()
            if data:
                df = pd.DataFrame(data)
                # 日付変換
                if 'timestamp' in df.columns:
                     df['timestamp'] = pd.to_datetime(df['timestamp'])
                return df
        except gspread.exceptions.SpreadsheetNotFound:
            pass # シートがない、設定されていない場合はスルー
        except Exception:
            pass

    # フォールバック: ローカルJSON
    if os.path.exists(HISTORY_FILE):
        try:
            df = pd.read_json(HISTORY_FILE, orient='records', convert_dates=['timestamp'])
            return df
        except ValueError:
            pass
    return pd.DataFrame()

def save_log(user_name, word, action_type, score=None, is_correct=None, detail=""):
    """学習履歴を保存する (Google Sheets優先)"""
    new_data = {
        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "user": user_name,
        "word": word,
        "action": action_type,
        "score": score if score is not None else 0, # None対策
        "is_correct": bool(is_correct), # bool変換
        "detail": detail
    }
    
    # 1. Google Sheets
    client = get_gsheet_client()
    if client:
        try:
            sheet = client.open(SHEET_NAME).sheet1
            # ヘッダーがなければ書き込む
            if not sheet.get_all_values():
                 sheet.append_row(list(new_data.keys()))
            sheet.append_row(list(new_data.values()))
            return # クラウド保存できれば終了
        except gspread.exceptions.SpreadsheetNotFound:
            st.warning(f"⚠️ スプレッドシート '{SHEET_NAME}' が見つかりません。")
        except Exception as e:
            print(f"GSheet save error: {e}")

    # 2. ローカル (フォールバック)
    df = load_history() # ローカルファイルから読み込みなおす挙動になる(GSheet失敗時)
    # ここは単純化のため、ファイル直接読み書きに戻す
    local_df = pd.DataFrame()
    if os.path.exists(HISTORY_FILE):
        try:
            local_df = pd.read_json(HISTORY_FILE, orient='records', convert_dates=['timestamp'])
        except:
            pass
            
    new_df = pd.DataFrame([new_data])
    if not local_df.empty:
        local_df = pd.concat([local_df, new_df], ignore_index=True)
    else:
        local_df = new_df
        
    local_df.to_json(HISTORY_FILE, orient='records', force_ascii=False, indent=4)

# --- セッション状態の初期化 ---
if 'questions' not in st.session_state:
    questions_data = []
    
    # questions.jsonが存在すれば読み込む
    if os.path.exists('questions.json'):
        try:
            with open('questions.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                # 英文(en)が入っているデータのみを抽出
                questions_data = [q for q in data if q.get('en')]
        except Exception as e:
            st.error(f"問題ファイルの読み込みに失敗しました: {e}")
    
    # ファイルがない、または読み込み失敗時のデフォルト問題
    if not questions_data:
        questions_data = [
            {
                "word": "Photography", 
                "word_jp": "写真撮影", 
                "word_en": "the art or practice of taking and processing photographs",
                "en": "I am interested in photography.", 
                "jp": "私は写真に興味があります。"
            },
            {
                "word": "Appointment", 
                "word_jp": "予約", 
                "word_en": "an arrangement to meet someone at a particular time and place",
                "en": "I'd like to make an appointment.", 
                "jp": "予約を取りたいのですが。"
            }
        ]
    
    st.session_state.questions = questions_data
    random.shuffle(st.session_state.questions)

if 'q_index' not in st.session_state:
    st.session_state.q_index = 0

# --- 関数: Geminiによる判定 (英語発音 - 英文) ---
@st.cache_data(show_spinner=False)
def evaluate_pronunciation(audio_bytes, target_sentence, api_key, model_name):
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        
        prompt = f"""
        あなたは【とても優しく褒め上手な】英語の先生です。
        ユーザーが以下の英文を読み上げました。
        
        【お題】: "{target_sentence}"
    
        以下のJSON形式のみで評価を出力してください:
        {{
            "transcription": "聞き取った英語",
            "score": 点数(0-100の数値),
            "advice": "日本語での具体的で丁寧なアドバイス。良い点はしっかり褒めて、改善点は優しく教えてあげてください。"
        }}
        """
        response = model.generate_content([
            prompt,
            {"mime_type": "audio/wav", "data": audio_bytes}
        ])
        
        text_resp = response.text.strip()
        if text_resp.startswith("```json"):
            text_resp = text_resp.replace("```json", "").replace("```", "")
        return json.loads(text_resp)
        
    except Exception as e:
        return {"error": str(e)}

# --- 関数: Geminiによる意味判定 (日本語回答) ---
@st.cache_data(show_spinner=False)
def evaluate_meaning_jp(audio_bytes, target_word, target_meaning, api_key, model_name):
    try:
        prompt = f"""
        あなたは英語教師です。
        ユーザーは英単語 "{target_word}" の日本語訳を音声で入力しました。
        想定される正解は "{target_meaning}" です。
        一字一句同じでなくても、類義語や文脈として正しい意味であれば正解としてください。

        以下のJSON形式のみで評価を出力してください:
        {{
            "transcription": "聞き取った日本語",
            "is_correct": true または false (ブール値),
            "comment": "判定コメント（正解なら褒める、不正解なら惜しい点や正解を教える）"
        }}
        """

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        response = model.generate_content([
            prompt,
            {"mime_type": "audio/wav", "data": audio_bytes}
        ])
        
        text_resp = response.text.strip()
        if text_resp.startswith("```json"):
            text_resp = text_resp.replace("```json", "").replace("```", "")
        return json.loads(text_resp)
        
    except Exception as e:
        return {"error": str(e)}

# --- 関数: Geminiによる英英定義判定 (英語回答) ---
@st.cache_data(show_spinner=False)
def evaluate_meaning_en(audio_bytes, target_word, target_def_en, api_key, model_name):
    try:
        prompt = f"""
        あなたは英語教師です。
        ユーザーは英単語 "{target_word}" の意味を「英語」で説明しようとしています。
        
        【正解の定義】: "{target_def_en}"
        
        ユーザーの音声を聞き取り、その説明が単語の意味として（大まかにでも）合っているか判定してください。
        完全に定義通りでなくても、その単語の概念を説明できていれば正解としてください。

        以下のJSON形式のみで評価を出力してください:
        {{
            "transcription": "聞き取った英語",
            "is_correct": true または false (ブール値),
            "comment": "日本語でのフィードバック（ユーザーの英語の良い点や、もっと良い表現など）"
        }}
        """

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        response = model.generate_content([
            prompt,
            {"mime_type": "audio/wav", "data": audio_bytes}
        ])
        
        text_resp = response.text.strip()
        if text_resp.startswith("```json"):
            text_resp = text_resp.replace("```json", "").replace("```", "")
        return json.loads(text_resp)
        
    except Exception as e:
        return {"error": str(e)}


# --- 関数: AIヒント生成 ---
@st.cache_data(show_spinner=False)
def generate_ai_hint(target_word, target_def, api_key, model_name):
    try:
        prompt = f"""
        Word: "{target_word}"
        Definition: "{target_def}"
        
        Task: Provide 3 simple English keywords or concepts that are related to this word, to help someone explain it. 
        Do not use the word itself or its direct derivatives.
        For example, if the word is 'Apple', keywords could be 'Fruit, Red, Pie'.
        Output format: Keyword1, Keyword2, Keyword3
        """
        
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(prompt)

        return response.text.strip()
    except Exception as e:
        return "Hint not available"

# --- サイドバー: ユーザー設定 ---
with st.sidebar:
    st.header("👤 ユーザー設定")
    
    # 履歴からユーザーリストを取得
    df_history = load_history()
    existing_users = []
    if not df_history.empty and 'user' in df_history.columns:
        existing_users = df_history['user'].dropna().unique().tolist()
    
    # ユーザー選択のUI
    if existing_users:
        # 既存ユーザーがいる場合は選択モードと新規作成モードを切り替え
        login_mode = st.radio("モード選択", ["既存ユーザー", "新規作成"], horizontal=True)
        
        if login_mode == "既存ユーザー":
            user_name = st.selectbox("ユーザーを選択してください", existing_users)
        else:
            new_user_input = st.text_input("新しいユーザー名を入力", value="")
            if new_user_input:
                user_name = new_user_input
            else:
                user_name = "Guest" # 入力がない場合のデフォルト
    else:
        # まだ履歴がない場合はテキスト入力のみ
        user_name = st.text_input("お名前 (History保存用)", value="Guest")

    st.info(f"現在のユーザー: **{user_name}** さん")
    st.caption(f"History File: {os.path.abspath(HISTORY_FILE)}")
    st.divider()
    
    model_name = st.selectbox(
        "使用するモデル",
        [
            "gemini-2.5-flash-lite", # リクエストされたFlashLite
            "gemini-2.5-flash", 
        ],
        index=0
    )

    if st.button("🛠️ 接続テスト (Test Connection)"):
        api_key_test = st.secrets.get("GEMINI_API_KEY")
        if not api_key_test:
            st.error("APIキーが設定されていません")
        else:
            try:
                genai.configure(api_key=api_key_test)
                model_test = genai.GenerativeModel(model_name)
                response_test = model_test.generate_content("Hello")
                st.success(f"[AI Studio] 接続成功！\nResponse: {response_test.text}")
            except Exception as e:
                st.error(f"接続エラー: {e}")

    st.divider()
    
    api_key = st.secrets.get("GEMINI_API_KEY")
    if not api_key:
        api_key = st.text_input("Gemini API Key", type="password")
        if not api_key:
            st.error("⚠️ APIキーが必要です")
            st.stop()

    st.divider()
    with st.expander("☁️ データ保存設定 (Google Sheets)"):
        if "gcp_service_account" in st.secrets:
            st.success("✅ 連携済み (Google Sheets)")
        else:
            st.warning("⚠️ 未連携 (データは一時保存のみ)")
            st.markdown("""
            **〜設定手順〜**
            1. [Google Cloud Console](https://console.cloud.google.com/)でプロジェクト作成
            2. **Google Sheets API** と **Google Drive API** を有効化
            3. **サービスアカウント**を作成し「キー(JSON)」をダウンロード
            4. Googleスプレッドシートを新規作成し、名前を `EnglishCoach_Data` にする
            5. そのシートの「共有」設定で、サービスアカウントのメールアドレス (`xxx@yyy.iam.gserviceaccount.com`) を編集者として追加
            6. Streamlit Cloudの **Settings > Secrets** にJSONの中身をコピペ（以下の形式）
            """)
            st.code("""
[gcp_service_account]
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = "..."
client_email = "..."
...
            """, language="toml")

# --- メイン画面 ---
st.title("🎙️ AI English Coach")

# タブの作成
tab_practice, tab_history = st.tabs(["🔥 トレーニング (Practice)", "📊 学習履歴 (History)"])

# ==========================================
# タブ1: トレーニング (Practice)
# ==========================================
with tab_practice:
    # 全問終了チェック
    if st.session_state.q_index >= len(st.session_state.questions):
        st.balloons()
        st.success("🎉 すべてのトレーニングが完了しました！")
        if st.button("もう一度最初から"):
            st.session_state.q_index = 0
            random.shuffle(st.session_state.questions)
            st.rerun()
        st.stop()

    # 現在の問題を取得
    q = st.session_state.questions[st.session_state.q_index]

    # --- UI表示 ---
    st.progress((st.session_state.q_index) / len(st.session_state.questions))
    st.caption(f"Question {st.session_state.q_index + 1} / {len(st.session_state.questions)}")

    # 1. 単語表示
    st.markdown(f"<p class='word-font'>Word: {q.get('word', '')}</p>", unsafe_allow_html=True)

    # --- A. 単語の意味チェック (日本語) ---
    if q.get('word_jp'):
        st.write("🇯🇵 **意味を「日本語」で答えてみよう**")
        meaning_jp_key = f"rec_meaning_jp_q{st.session_state.q_index}"
        meaning_jp_audio = st.audio_input("録音ボタンを押して、日本語で意味を話してください", key=meaning_jp_key)

        if meaning_jp_audio:
            st.spinner("日本語の意味を判定中... 🤔")
            res_jp = evaluate_meaning_jp(meaning_jp_audio.read(), q.get('word'), q.get('word_jp'), api_key, model_name, use_vertex, vertex_creds, project_id)
            
            if "error" in res_jp:
                st.error(f"エラー: {res_jp['error']}")
            elif res_jp:
                if res_jp.get('is_correct'):
                    st.success(f"⭕ **正解！** (聞き取り: {res_jp['transcription']})\n\n{res_jp['comment']}")
                    # 履歴保存 (正解のみ、または常に保存も可。今回は実施時に保存)
                    save_log(user_name, q['word'], "Japanese Meaning", score=100, is_correct=True, detail=res_jp['transcription'])
                else:
                    st.error(f"❌ **不正解...** (聞き取り: {res_jp['transcription']})\n\n{res_jp['comment']}")
                    save_log(user_name, q['word'], "Japanese Meaning", score=0, is_correct=False, detail=res_jp['transcription'])

    st.markdown("---")

    # --- B. 単語の意味チェック (英語) ---
    # word_enがある場合のみ表示
    if q.get('word_en'):
        st.write("🇺🇸 **意味を「英語」で説明してみよう**")
        
        # ヒント機能 (AI生成)
        hint_key = f"hint_content_{st.session_state.q_index}"
        if hint_key not in st.session_state:
            st.session_state[hint_key] = None

        col_hint, col_ans = st.columns([1, 1])
        with col_hint:
            if st.button("💡 AIヒントを表示", key=f"btn_hint_{st.session_state.q_index}"):
                with st.spinner("考えさせるヒントを生成中..."):
                    st.session_state[hint_key] = generate_ai_hint(q['word'], q.get('word_en'), api_key, model_name, use_vertex, vertex_creds, project_id)
        
        if st.session_state[hint_key]:
            st.info(f"**Keywords:** {st.session_state[hint_key]}")

        with col_ans:
            with st.expander("正解の定義を見る"):
                st.write(q.get('word_en'))
        
        meaning_en_key = f"rec_meaning_en_q{st.session_state.q_index}"
        meaning_en_audio = st.audio_input("録音ボタンを押して、英語で意味を説明してください", key=meaning_en_key)

        if meaning_en_audio:
            st.spinner("英語の説明を判定中... 🤔")
            res_en = evaluate_meaning_en(meaning_en_audio.read(), q.get('word'), q.get('word_en'), api_key, model_name, use_vertex, vertex_creds, project_id)
            
            if "error" in res_en:
                st.error(f"エラー: {res_en['error']}")
            elif res_en:
                if res_en.get('is_correct'):
                    st.success(f"⭕ **Great!** (You said: \"{res_en['transcription']}\")\n\n{res_en['comment']}")
                    save_log(user_name, q['word'], "English Definition", score=100, is_correct=True, detail=res_en['transcription'])
                else:
                    st.error(f"❌ **Not quite...** (You said: \"{res_en['transcription']}\")\n\n{res_en['comment']}")
                    save_log(user_name, q['word'], "English Definition", score=0, is_correct=False, detail=res_en['transcription'])

        st.markdown("---")

    # 2. 英文表示
    st.markdown(f"<p class='big-font'>{q['en']}</p>", unsafe_allow_html=True)

    # 模範音声
    with st.expander("🎧 英文の模範音声を聞く"):
        if q.get('en'):
            try:
                tts = gTTS(q['en'], lang='en')
                tts.save("sample.mp3")
                st.audio("sample.mp3")
            except:
                st.error("音声エラー")

    # 3. 英文録音ボタン
    st.write("🗣️ **この英文を音読してください**")
    audio_key = f"rec_q{st.session_state.q_index}"
    audio_value = st.audio_input("録音ボタンを押して、英文を読んでください", key=audio_key)

    if audio_value:
        st.write("発音判定中... 🤖")
        
        result = evaluate_pronunciation(audio_value.read(), q['en'], api_key, model_name, use_vertex, vertex_creds, project_id)
        
        if "error" in result:
            st.error(f"エラー: {result['error']}")
        elif result:
            # --- UI表示 (判定結果) ---
            st.subheader("診断結果")
            
            # スコアと聞き取り結果
            col1, col2 = st.columns([1, 2])
            with col1:
                st.metric("Score", f"{result['score']} / 100")
            with col2:
                st.write(f"**聞き取り:** {result['transcription']}")
            
            # 履歴保存
            save_log(user_name, q['word'], "Pronunciation", score=result['score'], is_correct=(result['score'] >= 80), detail=f"Transcription: {result['transcription']}")

            # 単語と文章の日本語訳を表示 (答え合わせ)
            with st.container():
                st.info(f"**単語:** {q.get('word', '')}\n\n**意味(JP):** {q.get('word_jp', '---')}\n\n**定義(EN):** {q.get('word_en', '---')}\n\n**文章訳:** {q.get('jp', '---')}")

            # アドバイスと次へボタン
            if result['score'] >= 80:
                st.success(f"**Excellent!**\n{result['advice']}")
                if st.button("次の問題へ (Next) ->", type="primary"):
                    st.session_state.q_index += 1
                    st.rerun()
            else:
                st.error(f"**Try Again...**\n{result['advice']}")
                
                if st.button("今回はスキップする"):
                    st.session_state.q_index += 1
                    st.rerun()

# ==========================================
# タブ2: 学習履歴 (History)
# ==========================================
with tab_history:
    st.header(f"📊 {user_name}さんの学習履歴")
    
    df = load_history()
    
    if not df.empty:
        # ユーザーでフィルタリング
        user_df = df[df['user'] == user_name].copy()
        
        if not user_df.empty:
            # 最新順に並び替え
            user_df = user_df.sort_values('timestamp', ascending=False)
            
            # 概要メトリクス
            col_m1, col_m2, col_m3 = st.columns(3)
            with col_m1:
                st.metric("Total Activities", len(user_df))
            with col_m2:
                pron_df = user_df[user_df['action'] == 'Pronunciation']
                avg_score = pron_df['score'].mean() if not pron_df.empty else 0
                st.metric("Avg Pronunciation Score", f"{avg_score:.1f}")
            with col_m3:
                correct_count = user_df['is_correct'].sum()
                st.metric("Total Correct/Pass", f"{correct_count}")

            # グラフ表示 (発音スコアの推移)
            if not pron_df.empty:
                st.subheader("📈 Pronunciation Score Progress")
                # 日時でソートしてグラフ化
                chart_df = pron_df.sort_values('timestamp')
                st.line_chart(chart_df, x='timestamp', y='score')
            
            # 詳細データテーブル
            st.subheader("📋 Detailed History")
            st.dataframe(
                user_df[['timestamp', 'word', 'action', 'score', 'is_correct', 'detail']],
                hide_index=True,
                use_container_width=True
            )
        else:
            st.info(f"{user_name}さんの履歴はまだありません。")
    else:
        st.info("履歴データはまだありません。")
