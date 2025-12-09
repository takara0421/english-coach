import streamlit as st
import google.generativeai as genai
from gtts import gTTS
import json
import random
import os

# --- 🛠️ 設定: ここでモデル名を一括指定します ---
# 動作確認済み安定版: 'gemini-1.5-flash'
# 開発者プレビュー版: 'gemini-2.0-flash-exp' (もしエラーが出る場合は 1.5-flash に戻してください)
GEMINI_MODEL_NAME = 'gemini-2.0-flash-exp' 

# --- ページ設定 ---
st.set_page_config(page_title="AI英会話コーチ", page_icon="🎙️")

# --- CSS (スマホで見やすくするためのデザイン) ---
st.markdown("""
    <style>
    .big-font { font-size: 24px !important; font-weight: bold; color: #1E88E5; }
    .word-font { font-size: 20px; font-weight: bold; color: #2E7D32; margin-bottom: 5px; }
    .def-font { font-size: 16px; font-style: italic; color: #555; margin-bottom: 10px; }
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
def evaluate_pronunciation(audio_bytes, target_sentence, api_key):
    try:
        genai.configure(api_key=api_key)
        # 設定されたモデル名を使用
        model = genai.GenerativeModel(GEMINI_MODEL_NAME)
        
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
        if text_resp.startswith("```json"):
            text_resp = text_resp.replace("```json", "").replace("```", "")
        return json.loads(text_resp)
        
    except Exception as e:
        return {"error": str(e)}

# --- 関数: Geminiによる意味判定 (日本語回答) ---
@st.cache_data(show_spinner=False)
def evaluate_meaning_jp(audio_bytes, target_word, target_meaning, api_key):
    try:
        genai.configure(api_key=api_key)
        # 設定されたモデル名を使用
        model = genai.GenerativeModel(GEMINI_MODEL_NAME)
        
        prompt = f"""
        あなたは英語教師です。
        ユーザーは英単語 "{target_word}" の日本語訳を音声で入力しました。
        想定される正解は "{target_meaning}" です。
        ユーザーの発言が、この単語の意味として適切か判定してください。
        一字一句同じでなくても、類義語や文脈として正しい意味であれば正解としてください。

        以下のJSON形式のみで評価を出力してください:
        {{
            "transcription": "聞き取った日本語",
            "is_correct": true または false (ブール値),
            "comment": "判定コメント（正解なら褒める、不正解なら惜しい点や正解を教える）"
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

# --- 関数: Geminiによる英英定義判定 (英語回答) ---
@st.cache_data(show_spinner=False)
def evaluate_meaning_en(audio_bytes, target_word, target_def_en, api_key):
    try:
        genai.configure(api_key=api_key)
        # 設定されたモデル名を使用
        model = genai.GenerativeModel(GEMINI_MODEL_NAME)
        
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


# --- メイン画面 ---
st.title("🎙️ AI English Coach")

api_key = st.secrets.get("GEMINI_API_KEY")
if not api_key:
    st.error("⚠️ APIキーが設定されていません。")
    st.stop()

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
        res_jp = evaluate_meaning_jp(meaning_jp_audio.read(), q.get('word'), q.get('word_jp'), api_key)
        
        if "error" in res_jp:
            st.error(f"エラー: {res_jp['error']}")
        elif res_jp:
            if res_jp.get('is_correct'):
                st.success(f"⭕ **正解！** (聞き取り: {res_jp['transcription']})\n\n{res_jp['comment']}")
            else:
                st.error(f"❌ **不正解...** (聞き取り: {res_jp['transcription']})\n\n{res_jp['comment']}")

st.markdown("---")

# --- B. 単語の意味チェック (英語) ---
# word_enがある場合のみ表示
if q.get('word_en'):
    st.write("🇺🇸 **意味を「英語」で説明してみよう**")
    st.caption(f"ヒント: {q.get('word_en')}") # 難易度調整のためヒントとして表示（隠してもOK）
    
    meaning_en_key = f"rec_meaning_en_q{st.session_state.q_index}"
    meaning_en_audio = st.audio_input("録音ボタンを押して、英語で意味を説明してください", key=meaning_en_key)

    if meaning_en_audio:
        st.spinner("英語の説明を判定中... 🤔")
        res_en = evaluate_meaning_en(meaning_en_audio.read(), q.get('word'), q.get('word_en'), api_key)
        
        if "error" in res_en:
            st.error(f"エラー: {res_en['error']}")
        elif res_en:
            if res_en.get('is_correct'):
                st.success(f"⭕ **Great!** (You said: \"{res_en['transcription']}\")\n\n{res_en['comment']}")
            else:
                st.error(f"❌ **Not quite...** (You said: \"{res_en['transcription']}\")\n\n{res_en['comment']}")

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
    
    result = evaluate_pronunciation(audio_value.read(), q['en'], api_key)
    
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
