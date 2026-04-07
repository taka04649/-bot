"""
内科専門医試験対策 教育Bot
- Gemini APIで臨床問題を生成し、Discordに投稿
- 1日4回（GitHub Actionsで起動）
- 13サブスペシャルティをローテーション
"""

import os
import json
import re
import datetime
import hashlib
import requests
import google.generativeai as genai

# ============================================================
# 設定
# ============================================================
DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_NAIKA"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# 内科13分野（専門医試験出題範囲準拠）
SUBSPECIALTIES = [
    "消化器", "循環器", "呼吸器", "腎臓", "内分泌・代謝",
    "血液", "神経", "アレルギー・膠原病", "感染症", "救急",
    "腫瘍（総論）", "総合内科（一般）", "老年医学"
]

# 各分野の頻出テーマ（出題傾向を反映）
TOPIC_HINTS = {
    "消化器": "炎症性腸疾患、肝硬変の合併症、胆石・胆管炎、膵炎、消化管出血、GERD、肝細胞癌、自己免疫性肝炎、PBC/PSC",
    "循環器": "急性冠症候群、心不全（HFrEF/HFpEF）、不整脈（心房細動・VT）、弁膜症、心筋症、感染性心内膜炎、大動脈解離、肺塞栓",
    "呼吸器": "COPD、気管支喘息、間質性肺炎、肺癌、胸水、気胸、肺血栓塞栓症、サルコイドーシス、睡眠時無呼吸",
    "腎臓": "急性腎障害、CKD管理、糸球体腎炎（IgA腎症・膜性腎症）、ネフローゼ症候群、電解質異常、酸塩基平衡、透析導入基準、RPGN",
    "内分泌・代謝": "糖尿病（1型・2型）、甲状腺疾患（バセドウ・橋本）、副腎不全、クッシング、褐色細胞腫、下垂体疾患、脂質異常症、骨粗鬆症",
    "血液": "鉄欠乏性貧血、巨赤芽球性貧血、再生不良性貧血、白血病（AML/ALL/CML/CLL）、悪性リンパ腫、多発性骨髄腫、DIC、ITP/TTP",
    "神経": "脳梗塞（病型分類・治療）、パーキンソン病、てんかん、多発性硬化症、ギラン・バレー症候群、重症筋無力症、髄膜炎、認知症",
    "アレルギー・膠原病": "SLE、関節リウマチ、血管炎症候群（ANCA関連）、強皮症、皮膚筋炎/多発性筋炎、シェーグレン症候群、ベーチェット病、薬物アレルギー・アナフィラキシー",
    "感染症": "敗血症、肺炎（市中・院内）、尿路感染、感染性心内膜炎、結核、HIV、抗菌薬の選択、耐性菌（MRSA/ESBL）、COVID-19",
    "救急": "ショックの鑑別と初期対応、急性腹症、意識障害、アナフィラキシー、急性中毒、熱中症・低体温、心肺蘇生（ACLS）",
    "腫瘍（総論）": "がん薬物療法の原則、免疫チェックポイント阻害薬のirAE、腫瘍崩壊症候群、オンコロジーエマージェンシー、緩和ケア、がんゲノム医療",
    "総合内科（一般）": "不明熱、体重減少の鑑別、全身倦怠感、リンパ節腫脹、検診異常のフォロー、医療面接・身体診察のポイント",
    "老年医学": "フレイル・サルコペニア、ポリファーマシー、高齢者の薬物療法、せん妄、転倒予防、栄養管理、ACP"
}

# 難易度設定（時間帯で変化）
DIFFICULTY_MAP = {
    "morning":   "基本〜標準（研修医レベルの確認）",
    "noon":      "標準（専門医試験の典型問題レベル）",
    "evening":   "標準〜やや難（鑑別を深く考えさせる問題）",
    "night":     "やや難〜難（複合的な病態・治療判断）"
}


def get_session_info():
    """現在時刻（JST）から分野・難易度・セッション名を決定"""
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now_jst = now_utc + datetime.timedelta(hours=9)

    hour = now_jst.hour
    if 5 <= hour < 10:
        session = "morning"
        emoji = "☀️"
        label = "朝の基礎固め"
    elif 10 <= hour < 15:
        session = "noon"
        emoji = "📖"
        label = "昼の実力チェック"
    elif 15 <= hour < 20:
        session = "evening"
        emoji = "🔬"
        label = "夕方の鑑別トレーニング"
    else:
        session = "night"
        emoji = "🌙"
        label = "夜の総合演習"

    # 日付とセッションからサブスペシャルティを決定（均等ローテーション）
    day_of_year = now_jst.timetuple().tm_yday
    session_index = ["morning", "noon", "evening", "night"].index(session)
    specialty_index = (day_of_year * 4 + session_index) % len(SUBSPECIALTIES)
    specialty = SUBSPECIALTIES[specialty_index]

    difficulty = DIFFICULTY_MAP[session]

    return {
        "session": session,
        "emoji": emoji,
        "label": label,
        "specialty": specialty,
        "difficulty": difficulty,
        "date_str": now_jst.strftime("%Y年%m月%d日"),
        "time_str": now_jst.strftime("%H:%M"),
    }


def generate_question(info):
    """Gemini APIで臨床問題を生成"""
    topics = TOPIC_HINTS.get(info["specialty"], "")

    prompt = f"""あなたは内科専門医試験の出題委員です。以下の条件で臨床問題を1問作成してください。

【条件】
- 分野: {info["specialty"]}
- 難易度: {info["difficulty"]}
- 頻出テーマ例: {topics}
- 上記テーマから1つ選ぶか、同分野の別の重要テーマでもOK

【出力フォーマット（厳守）】
以下のJSON形式のみを出力してください。余計なテキストは不要です。

{{
  "theme": "出題テーマ（例：IgA腎症の治療）",
  "vignette": "臨床シナリオ（50〜80歳の患者。主訴、現病歴、身体所見、検査所見を含む。150〜250字程度）",
  "question": "問い（例：最も適切な対応はどれか）",
  "choices": ["a: 選択肢1", "b: 選択肢2", "c: 選択肢3", "d: 選択肢4", "e: 選択肢5"],
  "answer": "正解の記号（例: c）",
  "explanation": "解説（200〜350字。正解の根拠、誤答の除外理由、関連する診断基準やガイドラインへの言及を含む）",
  "pearl": "臨床パール（1文。試験で差がつくワンポイント知識）"
}}

【注意】
- 臨床的にリアルな症例にすること
- 選択肢は紛らわしいが、論理的に正解が1つに絞れるように
- 解説は教育的で、なぜその答えなのかを明確に
- 臨床パールは記憶に残るキャッチーな一文に
"""

    response = model.generate_content(prompt)
    text = response.text.strip()

    # JSON抽出（コードブロック対応）
    json_match = re.search(r'```(?:json)?\s*(.*?)```', text, re.DOTALL)
    if json_match:
        text = json_match.group(1).strip()

    return json.loads(text)


def build_question_embed(info, q_data):
    """問題投稿用のEmbed（答えは隠す）"""
    return {
        "embeds": [
            {
                "title": f"{info['emoji']} {info['label']}【{info['specialty']}】",
                "description": (
                    f"📅 {info['date_str']} {info['time_str']}\n"
                    f"🏷️ テーマ: **{q_data['theme']}**\n"
                    f"📊 難易度: {info['difficulty']}\n"
                    "━━━━━━━━━━━━━━━━━━━━"
                ),
                "color": 0x2E86C1,
                "fields": [
                    {
                        "name": "📋 症例",
                        "value": q_data["vignette"],
                        "inline": False
                    },
                    {
                        "name": "❓ " + q_data["question"],
                        "value": "\n".join(q_data["choices"]),
                        "inline": False
                    },
                    {
                        "name": "💡 ヒント",
                        "value": "||答えは次の投稿で公開します（約30秒後）||",
                        "inline": False
                    }
                ],
                "footer": {
                    "text": "内科専門医試験対策Bot ▸ リアクションで自分の回答を記録しよう！"
                }
            }
        ]
    }


def build_answer_embed(info, q_data):
    """解答・解説投稿用のEmbed"""
    return {
        "embeds": [
            {
                "title": f"✅ 解答・解説【{info['specialty']}】{q_data['theme']}",
                "color": 0x28B463,
                "fields": [
                    {
                        "name": "🎯 正解",
                        "value": f"**{q_data['answer']}**",
                        "inline": False
                    },
                    {
                        "name": "📝 解説",
                        "value": q_data["explanation"],
                        "inline": False
                    },
                    {
                        "name": "💎 臨床パール",
                        "value": f"*{q_data['pearl']}*",
                        "inline": False
                    }
                ],
                "footer": {
                    "text": f"📅 {info['date_str']} ▸ 間違えた問題は復習リストに追加しよう"
                }
            }
        ]
    }


def add_reactions(webhook_url, message_id):
    """投稿にa〜eのリアクション絵文字を付与（回答用）"""
    # Webhook経由では直接リアクション追加不可のため、
    # Bot Token使用時のみ有効。Webhook運用ではスキップ。
    pass


def post_to_discord(payload):
    """Discordに投稿し、message_idを返す"""
    # ?wait=true でメッセージIDを取得
    url = DISCORD_WEBHOOK_URL + "?wait=true"
    resp = requests.post(url, json=payload)
    resp.raise_for_status()
    return resp.json().get("id")


def main():
    info = get_session_info()
    print(f"[{info['date_str']} {info['time_str']}] "
          f"分野: {info['specialty']} / セッション: {info['label']}")

    # 問題生成（リトライ付き）
    for attempt in range(3):
        try:
            q_data = generate_question(info)
            # 必須キーのバリデーション
            required = ["theme", "vignette", "question", "choices", "answer", "explanation", "pearl"]
            if all(k in q_data for k in required) and len(q_data["choices"]) == 5:
                break
        except Exception as e:
            print(f"  生成リトライ {attempt+1}/3: {e}")
            if attempt == 2:
                raise

    # 問題を投稿
    q_payload = build_question_embed(info, q_data)
    msg_id = post_to_discord(q_payload)
    print(f"  問題投稿完了: message_id={msg_id}")

    # 少し間を置いて解答を投稿（GitHub Actionsではsleep使用）
    import time
    time.sleep(30)

    a_payload = build_answer_embed(info, q_data)
    post_to_discord(a_payload)
    print("  解答投稿完了")


if __name__ == "__main__":
    main()
