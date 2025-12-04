import streamlit as st
import google.generativeai as genai
from gtts import gTTS
import json
import random
import os

# --- ページ設定 ---
st.set_page_config(page_title="AI英会話コーチ", page_icon="🎙️")

# --- CSS (スマホで見やすくするためのデザイン) ---
st.markdown("""
    <style>
    .big-font { font-size: 24px !important; font-weight: bold; color: #1E88E5; }
    .jp-font { font-size: 16px; color: #555; margin-bottom: 20px; }
    .stAudio { width: 100%; }
    .stButton button { width: 100%; border-radius: 20px; }
    </style>
    """, unsafe_allow_html=True)

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
            {"word": "Photography", "en": "I am interested in photography.", "jp": "私は写真に興味があります。"},
            {"word": "Appointment", "en": "I'd like to make an appointment.", "jp": "予約を取りたいのですが。"},
            {"word": "Recommendation", "en": "Do you have any recommendations?", "jp": "何かおすすめはありますか？"},
            {"word": "Atmosphere", "en": "I really like the atmosphere here.", "jp": "ここの雰囲気がとても気に入っています。"},
            {"word": "Schedule", "en": "Let me check my schedule.", "jp": "スケジュールを確認させてください。"}
        ]
    
    st.session_state.questions = questions_data
    random.shuffle(st.session_state.questions)

if 'q_index' not in st.session_state:
    st.session_state.q_index = 0

# --- 関数: Geminiによる判定 ---
# キャッシュを有効にしてAPIの無駄遣いを防ぐ
@st.cache_data(show_spinner=False)
def evaluate_pronunciation(audio_bytes, target_sentence, api_key):
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        prompt = f"""
        あなたは【非常に厳格な】英語の発音審査官です。
        ユーザーが以下の英文を読み上げました。
        
        【お題】: "{target_sentence}"

        以下のJSON形式のみで評価を出力してください:
        {{
            "transcription": "聞き取った英語",
            "score": 点数(0-100の数値),
            "advice": "日本語での具体的で厳しいアドバイス。"
        }}
        """
        
        response = model.generate_content([
            prompt,
            {"mime_type": "audio/wav", "data": audio_bytes}
        ])
        
        text_resp = response.text.strip()
        # JSONの前後に余計な文字がついている場合の除去処理
        if text_resp.startswith("```json"):
            text_resp = text_resp.replace("```json", "").replace("```", "")
        return json.loads(text_resp)
        
    except Exception as e:
        return {"error": str(e)}

# --- メイン画面 ---
st.title("🎙️ AI English Coach")

# ★【修正点】APIキー入力欄を完全撤廃
# Secretsからのみ読み込みます。見つからない場合はエラーメッセージだけ出します。
api_key = st.secrets.get("GEMINI_API_KEY")

if not api_key:
    st.error("⚠️ APIキーが設定されていません。")
    st.info("Streamlit Cloudの「Manage app」>「Secrets」を開き、GEMINI_API_KEY を登録してください。")
    st.stop() # キーがない場合はここで処理を強制終了

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

# UI表示
st.progress((st.session_state.q_index) / len(st.session_state.questions))
st.caption(f"Question {st.session_state.q_index + 1} / {len(st.session_state.questions)}")

st.markdown(f"<p class='big-font'>{q['en']}</p>", unsafe_allow_html=True)
st.markdown(f"<p class='jp-font'>意味: {q['jp']}</p>", unsafe_allow_html=True)

with st.expander("🎧 模範音声を聞く"):
    # 英文が空でないか確認してからTTSを実行
    if q.get('en'):
        try:
            tts = gTTS(q['en'], lang='en')
            tts.save("sample.mp3")
            st.audio("sample.mp3")
        except Exception as e:
            st.error("音声の生成に失敗しました")

st.markdown("---")

# ★【修正点】問題ごとにIDを変えて録音状態をリセットする（API制限対策）
audio_key = f"rec_q{st.session_state.q_index}"
audio_value = st.audio_input("録音ボタンを押して読んでください", key=audio_key)

if audio_value:
    st.write("判定中... 🤖")
    
    # 判定実行
    result = evaluate_pronunciation(audio_value.read(), q['en'], api_key)
    
    if "error" in result:
        st.error(f"エラーが発生しました: {result['error']}")
    elif result:
        st.subheader("診断結果")
        col1, col2 = st.columns([1, 2])
        with col1:
            st.metric("Score", f"{result['score']} / 100")
        with col2:
            st.write(f"**聞き取り:** {result['transcription']}")
        
        if result['score'] >= 80:
            st.success(f"**Excellent!**\n{result['advice']}")
            if st.button("次の問題へ (Next) ->", type="primary"):
                st.session_state.q_index += 1
                st.rerun()
        else:
            st.error(f"**Try Again...**\n{result['advice']}")
            st.info("80点以上で次に進めます。")
            
            # スキップボタン
            if st.button("今回はスキップする"):
                st.session_state.q_index += 1
                st.rerun()
