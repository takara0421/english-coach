import streamlit as st
import google.generativeai as genai
from gtts import gTTS
import json
import io
import threading
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
# --- 🛠️ 高速化のためのキャッシュ関数 ---
@st.cache_data
def get_tts_audio_bytes(text):
    """TTS音声を生成してバイト列で返す（キャッシュ対応・高速化）"""
    try:
        if not text:
            return None
        tts = gTTS(text, lang='en')
        mp3_fp = io.BytesIO()
        tts.write_to_fp(mp3_fp)
        return mp3_fp.getvalue()
    except Exception:
        return None

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

def load_history(force_reload=False):
    """
    履歴を読み込む (Google Sheets優先)。
    パフォーマンス向上のため、st.session_stateにキャッシュする。
    force_reload=True の場合のみGSheetから再取得する。
    """
    # キャッシュがあればそれを使う
    if not force_reload and 'history_df' in st.session_state and st.session_state.history_df is not None:
        return st.session_state.history_df

    expected_headers = ["timestamp", "user", "word", "action", "score", "is_correct", "detail"]
    df = pd.DataFrame(columns=expected_headers)
    
    client = get_gsheet_client()
    if client:
        try:
            sheet = client.open(SHEET_NAME).sheet1
            all_values = sheet.get_all_values()
            
            if all_values:
                # 1行目がヘッダーかどうか確認
                if all_values[0] == expected_headers:
                    # 1行目がヘッダーなら、2行目以降をデータとして作成
                    df = pd.DataFrame(all_values[1:], columns=expected_headers)
                else:
                    # 1行目がヘッダーでない（データ）なら、全行をデータとして使い、ヘッダーを付与
                    df = pd.DataFrame(all_values, columns=expected_headers)
        except gspread.exceptions.SpreadsheetNotFound:
            pass # シートがない、設定されていない場合はスルー
        except Exception:
            pass

    # フォールバック: ローカルJSON (GSheetが空、または失敗時かつローカルがある場合)
    if df.empty and os.path.exists(HISTORY_FILE):
        try:
            local_df = pd.read_json(HISTORY_FILE, orient='records', convert_dates=['timestamp'])
            if not local_df.empty:
                df = local_df
        except ValueError:
            pass

    # 型変換と整形
    if not df.empty:
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
        if 'score' in df.columns:
            df['score'] = pd.to_numeric(df['score'], errors='coerce').fillna(0)
    else:
        # 空の場合でもカラム定義は保持
        df = pd.DataFrame(columns=expected_headers)

    # セッションステートに保存
    st.session_state.history_df = df
    st.session_state.history_df = df
    return df

def write_gsheet_background(new_data, service_account_info):
    """バックグラウンドレッドでGSheetに書き込む（UIブロック回避）"""
    try:
        # スコープはグローバル定義のSCOPESを使用
        creds = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
        client = gspread.authorize(creds)
        sheet = client.open(SHEET_NAME).sheet1
        
        # データの書き込み (append)
        save_values = list(new_data.values())
        sheet.append_row(save_values)
    except Exception as e:
        # バックグラウンドでの失敗はコンソールに出力のみ
        print(f"Background GSheet save failed: {e}")

def save_log(user_name, word, action_type, score=None, is_correct=None, detail=""):
    """学習履歴を保存する (Google Sheets優先 + セッションステート更新)"""
    new_data = {
        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "user": user_name,
        "word": word,
        "action": action_type,
        "score": score if score is not None else 0, # None対策
        "is_correct": bool(is_correct), # bool変換
        "detail": detail
    }
    
    # 0. メモリ上のキャッシュ(history_df)を即時更新 (リロード回避)
    if 'history_df' not in st.session_state:
        load_history() # 初期化されてなければロード
    
    # DataFrameに追加するための形式変換
    new_row_df = pd.DataFrame([new_data])
    # timestampをdatetime型に変換しておくとソートで有利
    new_row_df['timestamp'] = pd.to_datetime(new_row_df['timestamp'])
    
    if st.session_state.history_df.empty:
        st.session_state.history_df = new_row_df
    else:
        st.session_state.history_df = pd.concat([st.session_state.history_df, new_row_df], ignore_index=True)

    # 1. Google Sheets (非同期バックグラウンド書き込み)
    if "gcp_service_account" in st.secrets:
        try:
            # st.secretsはスレッドセーフでない場合があるため、dictに変換して渡す
            sa_info = dict(st.secrets["gcp_service_account"])
            t = threading.Thread(target=write_gsheet_background, args=(new_data, sa_info))
            t.start()
        except Exception as e:
            print(f"Failed to start background thread: {e}")

    # 2. ローカル (フォールバック & バックアップ)
    # ここはコスト削減のため、頻繁には読み書きしない設計もアリだが、
    # 念のため追記しておく（ただし全量読み出しではなく追記モードが望ましいがJSONなので無理）
    # 簡易的にセッションのDFをダンプする
    try:
         st.session_state.history_df.to_json(HISTORY_FILE, orient='records', force_ascii=False, indent=4, date_format='iso')
    except Exception:
         pass

# --- 関数: スマート出題順ソート (SRS + 関連語) ---
def smart_sort_questions(questions, history_df, user_name, next_recommended_word=None):
    """
    学習履歴とおすすめ単語に基づいて問題をソートする。
    優先順位:
    1. AIおすすめ単語 (関連語チェイン)
    2. 新規・忘却・失敗した単語 (SRS Review Due)
    3. まだ先の単語
    """
    now = datetime.now()
    scored_questions = []

    # 履歴データを辞書化して高速化 (O(N)対策)
    # word -> list of history records
    word_history_map = {}
    
    if not history_df.empty and 'user' in history_df.columns:
        user_history = history_df[history_df['user'] == user_name]
        for record in user_history.to_dict('records'):
            w = record['word']
            if w not in word_history_map:
                word_history_map[w] = []
            word_history_map[w].append(record)
    
    for q in questions:
        word = q['word']
        priority = 0
        
        # 0. AIおすすめ単語ブースト
        if next_recommended_word and word.lower() == next_recommended_word.lower():
            priority += 999999 # 最優先
            
        else:
            # SRSロジック
            # 辞書から履歴を取得 (高速)
            records = word_history_map.get(word, [])
            
            streak = 0
            last_review = None
            
            if records:
                # 日付降順に並び替え (辞書化してるのでここでソートが必要だが、レコード数は少ないはず)
                # stringのtimestampをdatetimeに変換してソート
                for r in records:
                    if not isinstance(r['timestamp'], datetime):
                         try:
                             r['timestamp'] = pd.to_datetime(r['timestamp'])
                         except:
                             pass
                
                # timestampを持つものだけでソート
                valid_records = [r for r in records if isinstance(r['timestamp'], datetime)]
                valid_records.sort(key=lambda x: x['timestamp'], reverse=True)
                
                if valid_records:
                    last_review = valid_records[0]['timestamp']
                    
                    # ストリーク計算
                    for row in valid_records:
                        is_pass = row['is_correct']
                        
                        # 自己評価や発音スコアの考慮
                        if row['action'] == 'Pronunciation' and row['score'] < 80:
                            is_pass = False
                        if row['action'] == 'SelfRating' and row['detail'] == 'Hard':
                            is_pass = False
                            
                        if is_pass:
                            streak += 1
                        else:
                            break # 連続正解ストップ
            
            # 間隔（日数）の決定
            if streak == 0: interval = 0
            elif streak == 1: interval = 1
            elif streak == 2: interval = 3
            elif streak == 3: interval = 7
            elif streak == 4: interval = 14
            else: interval = 30
            
            # 優先度（どれくらい期限を過ぎているか）
            if last_review is None:
                # 未学習: 優先度高めだが、おすすめよりは下
                priority = 1000 + random.random()
            else:
                try:
                     days_since = (now - last_review).total_seconds() / 86400
                     # (経過日数 - 間隔) がプラスなら復習時期
                     priority = days_since - interval
                except:
                     priority = 1000 # エラー時は未学習扱い
        
        q['priority'] = priority
        scored_questions.append(q)
        
    # 優先度が高い順にソート
    scored_questions.sort(key=lambda x: x['priority'], reverse=True)
    return scored_questions

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
    # 初回はランダムではなく、スマートソート（履歴なし=ランダムに近い）
    # ユーザー名がまだ決まっていない(sidebar前)なので、後で再ソートするフラグを立てるか、デフォルトでやる
    # ここでは仮に空履歴でソート
    st.session_state.questions = smart_sort_questions(st.session_state.questions, pd.DataFrame(), "Guest")

if 'q_index' not in st.session_state:
    st.session_state.q_index = 0

if 'current_user' not in st.session_state:
    st.session_state.current_user = None


# --- 関数: Geminiによる判定 (英語発音 - 英文) ---
@st.cache_data(show_spinner=False)
def evaluate_pronunciation(audio_bytes, target_sentence, api_key, model_name):
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        
        prompt = f"""
        あなたは【発音に厳しいプロの】英語コーチです。
        ユーザーが以下の英文を読み上げました。
        
        【お題】: "{target_sentence}"
        
        あなたは、ネイティブスピーカーの基準で厳密に審査を行います。
        些細な発音のズレやアクセントの間違いも見逃さず、厳しく採点してください。
    
        以下のJSON形式のみで評価を出力してください:
        {{
            "transcription": "聞き取った英語",
            "score": 点数(0-100の数値。厳しめに判定してください),
            "advice": "日本語でのアドバイス。褒めるよりも、改善すべき点（発音、イントネーション、リズムなど）を具体的かつ論理的に指摘してください。"
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
        あなたは【採点の厳しい】英語教師です。
        ユーザーは英単語 "{target_word}" の日本語訳を音声で入力しました。
        想定される正解は "{target_meaning}" です。
        
        【指示】
        - 一字一句同じである必要はありません。類義語や、意味の本質が合っていれば正解としてください。
        - しかし、少しでもニュアンスが異なる場合や、曖昧な回答は厳しく「不正解(false)」にしてください。

        以下のJSON形式のみで評価を出力してください:
        {{
            "transcription": "聞き取った日本語",
            "is_correct": true または false (ブール値),
            "comment": "判定コメント（正解なら簡潔に。不正解なら、なぜ違うのかを厳しく指摘してください）"
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
        あなたは【採点の厳しい】英語教師です。
        ユーザーは英単語 "{target_word}" の意味を「英語」で説明しようとしています。
        
        【正解の定義】: "{target_def_en}"
        
        【指示】
        - 定義を一字一句暗記している必要はありません。その単語の「核心的な意味」を捉えられていれば正解です。
        - しかし、説明が曖昧だったり、文法ミスで意味が伝わらない場合は厳しく「不正解(false)」にしてください。

        以下のJSON形式のみで評価を出力してください:
        {{
            "transcription": "聞き取った英語",
            "is_correct": true または false (ブール値),
            "comment": "日本語でのフィードバック（改善点を厳しく具体的に指摘してください）"
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

# --- 関数: 関連語の取得 (AI) ---
@st.cache_data(show_spinner=False)
def get_related_words_ai(target_word, api_key, model_name):
    """
    指定された単語の類義語・反意語をAIにリストアップさせる。
    返り値: リスト ["word1", "word2", ...]
    """
    try:
        prompt = f"""
        Task: List 5 synonyms and 5 antonyms for the word "{target_word}".
        Output ONLY the words, separated by commas. No labels like 'Synonyms:'.
        Simple format: word1, word2, word3...
        """
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(prompt)
        
        text = response.text.strip()
        words = [w.strip().lower() for w in text.split(',')]
        return words
    except:
        return []



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
    
    # ユーザーが切り替わったら問題を再ソート
    if st.session_state.current_user != user_name:
        st.session_state.current_user = user_name
        history_df = load_history()
        # 次の単語のリセット
        if 'next_recommended_word' in st.session_state:
            del st.session_state['next_recommended_word']
            
        st.session_state.questions = smart_sort_questions(st.session_state.questions, history_df, user_name)
        st.session_state.q_index = 0
        if 'q_turn' not in st.session_state: st.session_state.q_turn = 0
        st.session_state.q_turn += 1 # ターンを進めてキーを一新
        st.rerun()

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
    # ターン数の初期化（キーの重複回避用）
    if 'q_turn' not in st.session_state:
        st.session_state.q_turn = 0

    # 全問終了チェック
    if st.session_state.q_index >= len(st.session_state.questions):
        st.balloons()
        st.success("🎉 すべてのトレーニングが完了しました！")
        if st.button("もう一度最初から"):
            st.session_state.q_index = 0
            random.shuffle(st.session_state.questions)
            st.session_state.q_turn += 1
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
        
        # 答えをチラ見する機能
        with st.expander("正解を表示 (Show Answer)"):
            st.write(q.get('word_jp'))

        meaning_jp_key = f"rec_meaning_jp_turn{st.session_state.q_turn}"
        meaning_jp_audio = st.audio_input("録音ボタンを押して、日本語で意味を話してください", key=meaning_jp_key)

        if meaning_jp_audio:
            st.spinner("日本語の意味を判定中... 🤔")
            res_jp = evaluate_meaning_jp(meaning_jp_audio.read(), q.get('word'), q.get('word_jp'), api_key, model_name)
            
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

    # word_enがある場合のみ表示
    if q.get('word_en'):
        st.write("🇺🇸 **意味を「英語」で説明してみよう**")
        
        with st.expander("正解を表示 (Show Answer)"):
            st.write(q.get('word_en'))
        
        meaning_en_key = f"rec_meaning_en_turn{st.session_state.q_turn}"
        meaning_en_audio = st.audio_input("録音ボタンを押して、英語で意味を説明してください", key=meaning_en_key)

        if meaning_en_audio:
            st.spinner("英語の説明を判定中... 🤔")
            res_en = evaluate_meaning_en(meaning_en_audio.read(), q.get('word'), q.get('word_en'), api_key, model_name)
            
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
            audio_bytes = get_tts_audio_bytes(q['en'])
            if audio_bytes:
                st.audio(audio_bytes, format='audio/mp3')
            else:
                st.error("音声生成エラー")

    # 3. 英文録音ボタン
    st.write("🗣️ **この英文を音読してください**")
    
    # 英文の日本語訳をチラ見する機能
    with st.expander("日本語訳を表示 (Show Translation)"):
        st.write(q.get('jp', '---'))
        
    audio_key = f"rec_q_turn{st.session_state.q_turn}"
    audio_value = st.audio_input("録音ボタンを押して、英文を読んでください", key=audio_key)

    if audio_value:
        st.write("発音判定中... 🤖")
        
        result = evaluate_pronunciation(audio_value.read(), q['en'], api_key, model_name)
        
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



            # (自己評価ボタンを下に移動しました)

            # AI判定のメッセージ表示
            if result['score'] >= 80:
                st.success(f"**Excellent!**\n{result['advice']}")
            else:
                st.error(f"**Try Again...**\n{result['advice']}")

    # アドバイスと次へ (自己評価付き)
    st.subheader("自己評価 & 次へ")
    
    col_next1, col_next2 = st.columns(2)
    
    # ロジック: ボタンが押されたら -> ログ保存 -> 関連語検索 -> 再ソート -> リロード
    
    # 1. まだ不安 (Hard)
    with col_next1:
        if st.button("😫 まだ不安 (Hard/Retry)", key=f"btn_hard_turn{st.session_state.q_turn}", type="secondary"):
            save_log(user_name, q['word'], "SelfRating", score=0, is_correct=False, detail="Hard")
            
            # 関連語検索はスキップ（苦手克服を優先）
            # 再ソートして次へ
            history_df = load_history()
            st.session_state.questions = smart_sort_questions(st.session_state.questions, history_df, user_name, None)
            st.session_state.q_index = 0
            st.session_state.q_turn += 1
            st.rerun()

    # 2. 覚えた (Easy) - 合格時のみ、またはスキップ時も
    with col_next2:
        # 発音が合格点、またはユーザーが自信ありと判断した場合
        if st.button("😎 覚えた！ (Easy/Next)", key=f"btn_easy_turn{st.session_state.q_turn}", type="primary"):
            save_log(user_name, q['word'], "SelfRating", score=100, is_correct=True, detail="Easy")
            
            # 関連語検索 (Dynamic Chaining) は動作高速化のためにスキップ
            st.session_state.next_recommended_word = None
            
            # 再ソート
            history_df = load_history()
            st.session_state.questions = smart_sort_questions(st.session_state.questions, history_df, user_name, st.session_state.next_recommended_word)
            st.session_state.q_index = 0
            st.session_state.q_turn += 1
            st.rerun()

# ==========================================
# タブ2: 学習履歴 (History)
# ==========================================
with tab_history:
    st.header(f"📊 {user_name}さんの学習履歴")
    
    df = load_history()
    
    if not df.empty:
        # ユーザーでフィルタリング
        if 'user' not in df.columns:
            st.error("⚠️ 履歴データの形式が正しくありません。")
            st.warning("Googleスプレッドシートの1行目に不要なテキストが入っている可能性があります。シートの **1行目(A1)** をすべて削除して、空の状態にしてください。")
            st.write("現在のヘッダー:", df.columns.tolist())
        else:
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
                # 修正: 'is_correct'が文字列の場合も考慮して集計
                correct_count = user_df['is_correct'].apply(lambda x: x.lower() == 'true' if isinstance(x, str) else bool(x)).sum()
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
