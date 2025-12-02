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
    </style>
    """, unsafe_allow_html=True)

# --- セッション状態の初期化 ---
if 'questions' not in st.session_state:
    # デフォルトの問題集（ファイル読み込みエラーを防ぐため内蔵）
    st.session_state.questions = [
        {"word": "Photography", "en": "I am interested in photography.", "jp": "私は写真に興味があります。"},
        {"word": "Appointment", "en": "I'd like to make an appointment.", "jp": "予約を取りたいのですが。"},
        {"word": "Recommendation", "en": "Do you have any recommendations?", "jp": "何かおすすめはありますか？"},
        {"word": "Atmosphere", "en": "I really like the atmosphere here.", "jp": "ここの雰囲気がとても気に入っています。"},
        {"word": "Schedule", "en": "Let me check my schedule.", "jp": "スケジュールを確認させてください。"}
    ]
    random.shuffle(st.session_state.questions)

if 'q_index' not in st.session_state:
    st.session_state.q_index = 0

# --- 関数: Geminiによる判定 ---
def evaluate_pronunciation(audio_bytes, target_sentence, api_key):
    try:
        genai.configure(api_key=api_key)
        # 処理速度と精度のバランスが良いモデルを選択
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        prompt = f"""
        あなたは【非常に厳格な】英語の発音審査官です。
        ユーザーが以下の英文を読み上げました。
        
        【お題】: "{target_sentence}"

        以下のJSON形式のみで評価を出力してください:
        {{
            "transcription": "聞き取った英語",
            "score": 点数(0-100の数値),
            "advice": "日本語での具体的で厳しいアドバイス。発音が甘い箇所を指摘すること。"
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
        st.error(f"APIエラー: {e}")
        return None

# --- メイン画面 ---
st.title("🎙️ AI English Coach")

# APIキーの読み込み (Streamlit Secrets または 入力)
# ※GitHubにAPIキーを直接書かないための安全策
api_key = st.secrets.get("GEMINI_API_KEY")
if not api_key:
    api_key = st.text_input("Gemini API Keyを入力してください", type="password")

if not api_key:
    st.warning("利用するにはAPIキーが必要です。")
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

# お題の表示
st.markdown(f"<p class='big-font'>{q['en']}</p>", unsafe_allow_html=True)
st.markdown(f"<p class='jp-font'>意味: {q['jp']}</p>", unsafe_allow_html=True)

# 模範音声 (TTS)
with st.expander("🎧 模範音声を聞く"):
    tts = gTTS(q['en'], lang='en')
    tts.save("sample.mp3")
    st.audio("sample.mp3")

st.markdown("---")

# ★録音機能 (Streamlit Audio Input)
# 元のコードの「Shiftキー」の代わりに、画面上の録音ボタンを使います
audio_value = st.audio_input("録音ボタンを押して読んでください")

if audio_value:
    st.write("判定中... 🤖")
    
    # 判定実行
    result = evaluate_pronunciation(audio_value.read(), q['en'], api_key)
    
    if result:
        # 結果表示エリア
        st.subheader("診断結果")
        
        col1, col2 = st.columns([1, 2])
        
        with col1:
            # スコア表示
            score = result['score']
            st.metric("Score", f"{score} / 100")
        
        with col2:
            st.write(f"**聞き取り:** {result['transcription']}")
        
        # アドバイス
        if score >= 80:
            st.success(f"**Excellent!**\n{result['advice']}")
            # 合格したら次へ進むボタンを表示
            if st.button("次の問題へ (Next) ->", type="primary"):
                st.session_state.q_index += 1
                st.rerun()
        else:
            st.error(f"**Try Again...**\n{result['advice']}")
            st.info("80点以上で次に進めます。もう一度録音ボタンを押してリトライしてください。")
            
            # どうしても進めないとき用
            if st.button("今回はスキップする"):
                st.session_state.q_index += 1
                st.rerun()
