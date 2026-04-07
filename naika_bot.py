"""
内科専門医試験 教育Bot
====================================
- 内科専門医試験の全分野をカバーする教育的投稿
- PubMed から根拠となる文献を取得して引用
- Gemini 2.5 Flash で臨床シナリオ + 解説を生成
- 1日4回 Discord に投稿
"""

import os
import json
import random
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import requests
import google.generativeai as genai

# ============================================================
# 設定
# ============================================================
NAIKA_WEBHOOK_URL = os.environ["NAIKA_WEBHOOK_URL"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

genai.configure(api_key=GEMINI_API_KEY)
GEMINI_MODEL = "gemini-2.5-flash"

POSTED_FILE = Path(__file__).parent / "posted_naika.json"

SEARCH_DAYS = 180  # 半年分から検索（教育的に良質な文献を広く拾う）
MAX_RESULTS = 30
PAPERS_PER_POST = 2  # 1投稿あたりの引用論文数

# ============================================================
# 内科専門医試験 出題分野・トピック
# 各分野に複数のサブトピックと PubMed 検索クエリを定義
# ============================================================
EXAM_TOPICS = [
    # ================================================================
    # 1. 消化器
    # ================================================================
    {
        "field": "消化器",
        "topic": "炎症性腸疾患 (IBD) の診断と治療",
        "query": '("Inflammatory Bowel Diseases/diagnosis"[MeSH] OR "Inflammatory Bowel Diseases/therapy"[MeSH]) AND "humans"[MeSH] AND "Review"[Publication Type]',
        "exam_points": [
            "UCとCDの鑑別ポイント（内視鏡所見・病理所見）",
            "5-ASA製剤、ステロイド、免疫調節薬、生物学的製剤の使い分け",
            "extraintestinal manifestationsの種類と対応",
        ],
        "emoji": "🔥",
    },
    {
        "field": "消化器",
        "topic": "肝硬変の合併症管理",
        "query": '("Liver Cirrhosis/complications"[MeSH]) AND "humans"[MeSH] AND ("Review"[Publication Type] OR "Practice Guideline"[Publication Type])',
        "exam_points": [
            "Child-Pugh分類とMELDスコア",
            "食道静脈瘤の予防・治療（EVL、β遮断薬）",
            "肝性脳症の病態と治療（ラクツロース、リファキシミン）",
            "腹水・SBPの管理",
        ],
        "emoji": "🫁",
    },
    {
        "field": "消化器",
        "topic": "急性膵炎の重症度評価と管理",
        "query": '("Pancreatitis/diagnosis"[MeSH] OR "Pancreatitis/therapy"[MeSH]) AND "Acute Disease"[MeSH] AND "humans"[MeSH]',
        "exam_points": [
            "重症度判定基準（厚生労働省基準、Ranson、APACHE II、CT Grade）",
            "初期輸液と絶食管理",
            "感染性膵壊死の診断と介入時期",
        ],
        "emoji": "💛",
    },
    {
        "field": "消化器",
        "topic": "消化管出血の初期対応",
        "query": '("Gastrointestinal Hemorrhage/diagnosis"[MeSH] OR "Gastrointestinal Hemorrhage/therapy"[MeSH]) AND "humans"[MeSH]',
        "exam_points": [
            "上部・下部消化管出血の鑑別",
            "Glasgow-Blatchford Score による緊急内視鏡の適応判断",
            "PPIの投与タイミングと内視鏡的止血術の選択",
        ],
        "emoji": "🔴",
    },
    # ================================================================
    # 2. 循環器
    # ================================================================
    {
        "field": "循環器",
        "topic": "急性冠症候群 (ACS) の診断と初期対応",
        "query": '("Acute Coronary Syndrome/diagnosis"[MeSH] OR "Acute Coronary Syndrome/therapy"[MeSH]) AND "humans"[MeSH]',
        "exam_points": [
            "STEMI vs NSTEMI vs 不安定狭心症の鑑別",
            "トロポニンの解釈と連続測定の意義",
            "primary PCI の適応と Door-to-Balloon Time",
            "DAPT（抗血小板薬2剤併用療法）の期間",
        ],
        "emoji": "❤️",
    },
    {
        "field": "循環器",
        "topic": "心不全の分類と治療戦略",
        "query": '("Heart Failure/classification"[MeSH] OR "Heart Failure/therapy"[MeSH]) AND "humans"[MeSH]',
        "exam_points": [
            "HFrEF vs HFpEF vs HFmrEF の分類と治療の違い",
            "Fantastic Four（ARNI/ACEi, β遮断薬, MRA, SGLT2i）",
            "BNP/NT-proBNP の臨床的意義",
            "急性心不全のNohria-Stevenson分類と初期治療",
        ],
        "emoji": "❤️",
    },
    {
        "field": "循環器",
        "topic": "心房細動の管理",
        "query": '("Atrial Fibrillation/therapy"[MeSH]) AND "humans"[MeSH]',
        "exam_points": [
            "CHA₂DS₂-VASc スコアと抗凝固療法の適応",
            "DOAC vs ワルファリンの選択",
            "レートコントロール vs リズムコントロール",
            "カテーテルアブレーションの適応",
        ],
        "emoji": "❤️",
    },
    # ================================================================
    # 3. 呼吸器
    # ================================================================
    {
        "field": "呼吸器",
        "topic": "間質性肺疾患の診断と治療",
        "query": '("Lung Diseases, Interstitial/diagnosis"[MeSH] OR "Idiopathic Pulmonary Fibrosis/therapy"[MeSH]) AND "humans"[MeSH]',
        "exam_points": [
            "UIP vs NSIP パターンの画像・病理所見の違い",
            "IPF の診断基準と抗線維化薬（ピルフェニドン、ニンテダニブ）",
            "膠原病関連間質性肺疾患のスクリーニング",
        ],
        "emoji": "🫁",
    },
    {
        "field": "呼吸器",
        "topic": "気管支喘息とCOPDの管理",
        "query": '("Asthma/therapy"[MeSH] OR "Pulmonary Disease, Chronic Obstructive/therapy"[MeSH]) AND "humans"[MeSH]',
        "exam_points": [
            "喘息の重症度分類とステップアップ治療",
            "ACO（Asthma-COPD Overlap）の概念",
            "COPD の GOLD 分類と LAMA/LABA/ICS の使い分け",
            "増悪時の対応（全身性ステロイド、抗菌薬の適応）",
        ],
        "emoji": "🌬️",
    },
    {
        "field": "呼吸器",
        "topic": "肺癌の診断と治療",
        "query": '("Lung Neoplasms/diagnosis"[MeSH] OR "Lung Neoplasms/therapy"[MeSH]) AND "humans"[MeSH]',
        "exam_points": [
            "組織型分類とドライバー遺伝子変異（EGFR, ALK, ROS1, BRAF等）",
            "TNM分類とステージ別治療戦略",
            "免疫チェックポイント阻害薬（PD-L1発現と治療選択）",
        ],
        "emoji": "🌬️",
    },
    # ================================================================
    # 4. 腎臓
    # ================================================================
    {
        "field": "腎臓",
        "topic": "慢性腎臓病 (CKD) のステージ管理",
        "query": '("Renal Insufficiency, Chronic/therapy"[MeSH]) AND "humans"[MeSH]',
        "exam_points": [
            "CKD ステージ分類（GFR + アルブミン尿）とリスク層別化",
            "腎保護戦略（RAS阻害薬、SGLT2阻害薬、MRA）",
            "CKD-MBD の管理（リン、カルシウム、PTH、ビタミンD）",
            "透析導入基準と腎代替療法の選択",
        ],
        "emoji": "🫘",
    },
    {
        "field": "腎臓",
        "topic": "急性腎障害 (AKI) の診断と管理",
        "query": '("Acute Kidney Injury/diagnosis"[MeSH] OR "Acute Kidney Injury/therapy"[MeSH]) AND "humans"[MeSH]',
        "exam_points": [
            "KDIGO による AKI ステージング",
            "腎前性・腎性・腎後性の鑑別（FENa, FEUrea）",
            "腎毒性物質の回避と輸液戦略",
            "緊急透析の適応（AEIOU）",
        ],
        "emoji": "🫘",
    },
    # ================================================================
    # 5. 内分泌・代謝
    # ================================================================
    {
        "field": "内分泌・代謝",
        "topic": "糖尿病の薬物治療アルゴリズム",
        "query": '("Diabetes Mellitus, Type 2/drug therapy"[MeSH]) AND "humans"[MeSH]',
        "exam_points": [
            "メトホルミンを第一選択とする根拠",
            "SGLT2阻害薬・GLP-1受容体作動薬の心血管・腎保護エビデンス",
            "インスリン導入のタイミングと病態別の薬剤選択",
            "シックデイルールとDKA/HHSの管理",
        ],
        "emoji": "🧬",
    },
    {
        "field": "内分泌・代謝",
        "topic": "甲状腺疾患の鑑別と治療",
        "query": '("Thyroid Diseases/diagnosis"[MeSH] OR "Thyroid Diseases/therapy"[MeSH]) AND "humans"[MeSH]',
        "exam_points": [
            "バセドウ病 vs 無痛性甲状腺炎 vs 亜急性甲状腺炎の鑑別",
            "抗甲状腺薬の副作用（無顆粒球症の対応）",
            "甲状腺クリーゼの診断基準と緊急治療",
            "橋本病と甲状腺機能低下症の管理",
        ],
        "emoji": "🧬",
    },
    {
        "field": "内分泌・代謝",
        "topic": "副腎疾患の診断",
        "query": '("Adrenal Gland Diseases/diagnosis"[MeSH]) AND "humans"[MeSH]',
        "exam_points": [
            "原発性アルドステロン症のスクリーニングと確定診断",
            "クッシング症候群の鑑別（デキサメタゾン抑制試験）",
            "褐色細胞腫の診断と術前管理",
            "副腎不全（Addison病）の急性期対応",
        ],
        "emoji": "🧬",
    },
    # ================================================================
    # 6. 血液
    # ================================================================
    {
        "field": "血液",
        "topic": "貧血の鑑別診断",
        "query": '("Anemia/diagnosis"[MeSH]) AND "humans"[MeSH] AND "Review"[Publication Type]',
        "exam_points": [
            "MCV による小球性・正球性・大球性貧血の分類",
            "鉄欠乏性貧血 vs 慢性疾患に伴う貧血 vs サラセミアの鑑別",
            "網赤血球を用いた産生低下 vs 破壊亢進の評価",
            "ビタミンB12/葉酸欠乏性貧血の原因検索",
        ],
        "emoji": "🩸",
    },
    {
        "field": "血液",
        "topic": "DICの診断と治療",
        "query": '("Disseminated Intravascular Coagulation/diagnosis"[MeSH] OR "Disseminated Intravascular Coagulation/therapy"[MeSH]) AND "humans"[MeSH]',
        "exam_points": [
            "DIC スコアリング（急性期DICスコア、ISTH基準）",
            "線溶亢進型 vs 線溶抑制型の病態と治療の違い",
            "基礎疾患の治療が最優先であることの理解",
            "アンチトロンビン製剤、トロンボモジュリン製剤の適応",
        ],
        "emoji": "🩸",
    },
    # ================================================================
    # 7. 膠原病・リウマチ
    # ================================================================
    {
        "field": "膠原病",
        "topic": "全身性エリテマトーデス (SLE) の診断と管理",
        "query": '("Lupus Erythematosus, Systemic/diagnosis"[MeSH] OR "Lupus Erythematosus, Systemic/therapy"[MeSH]) AND "humans"[MeSH]',
        "exam_points": [
            "2019 EULAR/ACR 分類基準",
            "ループス腎炎の ISN/RPS 分類と治療（MMF vs CY）",
            "ヒドロキシクロロキンの全例投与推奨の根拠",
            "抗リン脂質抗体症候群の合併と管理",
        ],
        "emoji": "🦴",
    },
    {
        "field": "膠原病",
        "topic": "関節リウマチの治療戦略",
        "query": '("Arthritis, Rheumatoid/therapy"[MeSH]) AND "humans"[MeSH]',
        "exam_points": [
            "Treat to Target 戦略と早期介入の重要性",
            "MTX を anchor drug とする根拠と投与量",
            "生物学的製剤・JAK阻害薬の選択基準",
            "寛解基準（Boolean寛解、SDAI寛解）",
        ],
        "emoji": "🦴",
    },
    # ================================================================
    # 8. 感染症
    # ================================================================
    {
        "field": "感染症",
        "topic": "敗血症の診断と初期治療",
        "query": '("Sepsis/diagnosis"[MeSH] OR "Sepsis/therapy"[MeSH]) AND "humans"[MeSH]',
        "exam_points": [
            "Sepsis-3 定義と qSOFA/SOFA スコア",
            "Hour-1 Bundle（血液培養、広域抗菌薬、輸液、乳酸測定）",
            "敗血症性ショックのバソプレッサー選択（ノルエピネフリン第一選択）",
            "procalcitonin の臨床的意義と限界",
        ],
        "emoji": "🦠",
    },
    {
        "field": "感染症",
        "topic": "抗菌薬の適正使用",
        "query": '("Anti-Bacterial Agents/therapeutic use"[MeSH]) AND ("Drug Resistance, Microbial"[MeSH]) AND "humans"[MeSH]',
        "exam_points": [
            "empiric therapy と definitive therapy の考え方",
            "de-escalation の原則",
            "ESBL産生菌、MRSA、緑膿菌のカバーが必要な状況",
            "抗菌薬のPK/PD（時間依存性 vs 濃度依存性）",
        ],
        "emoji": "🦠",
    },
    # ================================================================
    # 9. 神経
    # ================================================================
    {
        "field": "神経",
        "topic": "脳卒中の急性期対応",
        "query": '("Stroke/diagnosis"[MeSH] OR "Stroke/therapy"[MeSH]) AND "humans"[MeSH]',
        "exam_points": [
            "脳梗塞の病型分類（アテローム血栓性、心原性、ラクナ）",
            "rt-PA 静注の適応基準（発症4.5時間以内）と禁忌",
            "機械的血栓回収療法の適応と時間枠",
            "脳出血の急性期血圧管理",
        ],
        "emoji": "🧠",
    },
    {
        "field": "神経",
        "topic": "てんかんと意識障害の鑑別",
        "query": '("Epilepsy/diagnosis"[MeSH] OR "Consciousness Disorders/diagnosis"[MeSH]) AND "humans"[MeSH]',
        "exam_points": [
            "てんかん発作の国際分類（焦点発作 vs 全般発作）",
            "てんかん重積状態の初期対応（ベンゾジアゼピン → レベチラセタム/ホスフェニトイン）",
            "意識障害のAIUEOTIPS による鑑別",
        ],
        "emoji": "🧠",
    },
    # ================================================================
    # 10. アレルギー
    # ================================================================
    {
        "field": "アレルギー",
        "topic": "アナフィラキシーの診断と緊急対応",
        "query": '("Anaphylaxis/diagnosis"[MeSH] OR "Anaphylaxis/therapy"[MeSH]) AND "humans"[MeSH]',
        "exam_points": [
            "アナフィラキシーの臨床診断基準",
            "アドレナリン筋注が第一選択である根拠と投与量",
            "二相性反応のリスクと経過観察時間",
            "トリプターゼ測定の意義",
        ],
        "emoji": "⚠️",
    },
    # ================================================================
    # 11. 総合内科（横断的テーマ）
    # ================================================================
    {
        "field": "総合内科",
        "topic": "不明熱の鑑別アプローチ",
        "query": '("Fever of Unknown Origin/diagnosis"[MeSH]) AND "humans"[MeSH]',
        "exam_points": [
            "古典的不明熱の定義と3大カテゴリ（感染症・悪性腫瘍・膠原病）",
            "院内発症不明熱・好中球減少時不明熱・HIV関連不明熱",
            "系統的な検査アプローチ",
        ],
        "emoji": "🌡️",
    },
    {
        "field": "総合内科",
        "topic": "酸塩基平衡異常の解釈",
        "query": '("Acid-Base Imbalance/diagnosis"[MeSH]) AND "humans"[MeSH]',
        "exam_points": [
            "動脈血液ガスの系統的読み方（pH→PCO2→HCO3→AG）",
            "AG上昇型 vs 非AG上昇型代謝性アシドーシスの鑑別",
            "代償の予測式と混合性障害の判定",
            "尿中アニオンギャップの利用",
        ],
        "emoji": "🧪",
    },
    {
        "field": "総合内科",
        "topic": "電解質異常の鑑別と補正",
        "query": '("Electrolyte Imbalance"[MeSH] OR "Hyponatremia"[MeSH] OR "Hyperkalemia"[MeSH]) AND "humans"[MeSH]',
        "exam_points": [
            "低Na血症の病態分類（体液量評価 + 浸透圧）",
            "SIADHの診断基準と治療（水制限、トルバプタン）",
            "高K血症の緊急度判定とカルシウム・GI・透析の使い分け",
            "補正Na（高血糖時）の計算",
        ],
        "emoji": "🧪",
    },
]

# ============================================================
# PubMed E-utilities
# ============================================================
ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


def search_pubmed(query: str, reldate: int) -> list[str]:
    params = {
        "db": "pubmed",
        "term": query,
        "retmax": MAX_RESULTS,
        "datetype": "edat",
        "reldate": reldate,
        "retmode": "json",
        "sort": "relevance",
    }
    resp = requests.get(ESEARCH_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data.get("esearchresult", {}).get("idlist", [])


def fetch_articles(pmids: list[str]) -> list[dict]:
    if not pmids:
        return []

    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
        "rettype": "abstract",
    }
    resp = requests.get(EFETCH_URL, params=params, timeout=30)
    resp.raise_for_status()

    root = ET.fromstring(resp.content)
    articles = []

    for article_elem in root.findall(".//PubmedArticle"):
        pmid = _text(article_elem, ".//PMID")
        title = _full_text(article_elem, ".//ArticleTitle")

        abstract_parts = []
        for at in article_elem.findall(".//AbstractText"):
            label = at.get("Label", "")
            text = "".join(at.itertext()).strip()
            if label:
                abstract_parts.append(f"[{label}] {text}")
            else:
                abstract_parts.append(text)
        abstract = "\n".join(abstract_parts)

        if not abstract:
            abstract_node = article_elem.find(".//Abstract")
            if abstract_node is not None:
                abstract = "".join(abstract_node.itertext()).strip()

        if not abstract:
            continue

        journal = _full_text(article_elem, ".//Journal/Title")

        all_authors = []
        for author in article_elem.findall(".//Author"):
            last = _text(author, "LastName")
            fore = _text(author, "ForeName")
            if last:
                all_authors.append(f"{last} {fore}".strip())

        display_authors = all_authors[:3]
        if len(all_authors) > 3:
            display_authors.append("et al.")

        doi = ""
        for aid in article_elem.findall(".//ArticleId"):
            if aid.get("IdType") == "doi":
                doi = aid.text or ""

        pub_year = _text(article_elem, ".//PubDate/Year")
        if not pub_year:
            medline_date = _text(article_elem, ".//PubDate/MedlineDate")
            if medline_date:
                pub_year = medline_date[:4]

        articles.append({
            "pmid": pmid,
            "title": title,
            "abstract": abstract,
            "journal": journal,
            "authors": ", ".join(display_authors),
            "doi": doi,
            "year": pub_year or "2025",
        })

    return articles


def _text(elem, path: str) -> str:
    node = elem.find(path)
    if node is not None and node.text:
        return node.text.strip()
    return ""


def _full_text(elem, path: str) -> str:
    node = elem.find(path)
    if node is not None:
        return "".join(node.itertext()).strip()
    return ""


# ============================================================
# Gemini 2.5 Flash で教育的投稿を生成
# ============================================================
def generate_educational_post(topic_info: dict, articles: list[dict]) -> dict:
    model = genai.GenerativeModel(GEMINI_MODEL)

    # 論文情報をフォーマット
    papers_text = ""
    for i, art in enumerate(articles, 1):
        papers_text += f"""
--- 文献{i} ---
PMID: {art['pmid']}
タイトル: {art['title']}
ジャーナル: {art['journal']} ({art['year']})
著者: {art['authors']}
Abstract:
{art['abstract'][:1500]}
"""

    exam_points_text = "\n".join(f"- {p}" for p in topic_info["exam_points"])

    prompt = f"""あなたは内科専門医試験対策の教育コンテンツを作成する指導医です。
以下のトピックについて、専攻医が試験と臨床の両面で学べる教育的投稿を作成してください。

## トピック
{topic_info['topic']}（分野: {topic_info['field']}）

## このトピックの重要な試験ポイント
{exam_points_text}

## 参考文献（本文中で引用すること）
{papers_text}

## 出力フォーマット（厳守）

TITLE: （日本語のタイトル。トピックの核心を捉え、学習意欲を刺激する1行。）

CASE: （臨床シナリオ。3〜4文で典型的な症例提示を行う。年齢・性別・主訴・身体所見・検査所見を含む。
試験に出るような鑑別診断を考えさせる内容にする。）

TEACHING: （教育的解説。400〜600字。以下を含める:
- 症例の診断に至る思考プロセス
- 試験で問われるポイント（鑑別診断、検査の解釈、治療方針）
- 最新のエビデンスやガイドラインの内容を引用文献 [1], [2] で示す
- 「ここが出る！」的な試験頻出ポイントを明示する
- ピットフォールや間違いやすいポイントがあれば言及する）

KEYPOINTS: （箇条書きで3〜4点。試験で問われる最重要事項を簡潔に。各1文。）

REFS: （引用文献リスト。
[1] FirstAuthor, et al. Journal. Year. PMID: XXXXX
[2] FirstAuthor, et al. Journal. Year. PMID: XXXXX）

重要:
- 提供された文献のみに基づいて引用すること。文献を捏造しないこと
- 専攻医にとって実践的かつ試験に直結する内容にすること
- 症例は実臨床で遭遇しうるリアリティのある設定にすること
"""

    response = model.generate_content(prompt)
    text = response.text

    # パース
    result = {"title": "", "case": "", "teaching": "", "keypoints": "", "refs": ""}
    lines = text.split("\n")
    current_section = None
    section_lines = {k: [] for k in ["CASE", "TEACHING", "KEYPOINTS", "REFS"]}

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("TITLE:"):
            result["title"] = stripped.replace("TITLE:", "").strip()
            current_section = None
        elif stripped.startswith("CASE:"):
            content = stripped.replace("CASE:", "").strip()
            if content:
                section_lines["CASE"].append(content)
            current_section = "CASE"
        elif stripped.startswith("TEACHING:"):
            content = stripped.replace("TEACHING:", "").strip()
            if content:
                section_lines["TEACHING"].append(content)
            current_section = "TEACHING"
        elif stripped.startswith("KEYPOINTS:"):
            content = stripped.replace("KEYPOINTS:", "").strip()
            if content:
                section_lines["KEYPOINTS"].append(content)
            current_section = "KEYPOINTS"
        elif stripped.startswith("REFS:"):
            content = stripped.replace("REFS:", "").strip()
            if content:
                section_lines["REFS"].append(content)
            current_section = "REFS"
        elif current_section and stripped:
            section_lines[current_section].append(stripped)

    result["case"] = "\n".join(section_lines["CASE"]).strip()
    result["teaching"] = "\n".join(section_lines["TEACHING"]).strip()
    result["keypoints"] = "\n".join(section_lines["KEYPOINTS"]).strip()
    result["refs"] = "\n".join(section_lines["REFS"]).strip()

    if not result["title"]:
        result["title"] = topic_info["topic"]

    # 引用文献にPubMedリンク追加
    refs_with_links = []
    for ref_line in result["refs"].split("\n"):
        ref_line = ref_line.strip()
        if ref_line:
            for art in articles:
                if art["pmid"] in ref_line and "https://" not in ref_line:
                    ref_line += f"\n  → https://pubmed.ncbi.nlm.nih.gov/{art['pmid']}/"
                    break
            refs_with_links.append(ref_line)
    result["refs"] = "\n".join(refs_with_links)

    return result


# ============================================================
# Discord 通知
# ============================================================
FIELD_COLORS = {
    "消化器": 0x27AE60,
    "循環器": 0xE74C3C,
    "呼吸器": 0x3498DB,
    "腎臓": 0x9B59B6,
    "内分泌・代謝": 0xF39C12,
    "血液": 0xC0392B,
    "膠原病": 0x1ABC9C,
    "感染症": 0xE67E22,
    "神経": 0x2C3E50,
    "アレルギー": 0xD4AC0D,
    "総合内科": 0x5DADE2,
}


def send_discord_post(topic_info: dict, post: dict, articles: list[dict]):
    color = FIELD_COLORS.get(topic_info["field"], 0x95A5A6)

    fields = []

    # 症例提示
    if post["case"]:
        fields.append({
            "name": "🏥 症例提示",
            "value": post["case"][:1024],
            "inline": False,
        })

    # 解説
    if post["teaching"]:
        # Discord Embed field は1024文字制限なので分割
        teaching = post["teaching"]
        if len(teaching) > 1024:
            fields.append({
                "name": "📖 解説",
                "value": teaching[:1024],
                "inline": False,
            })
            fields.append({
                "name": "📖 解説（続き）",
                "value": teaching[1024:2048],
                "inline": False,
            })
        else:
            fields.append({
                "name": "📖 解説",
                "value": teaching,
                "inline": False,
            })

    # Key Points
    if post["keypoints"]:
        fields.append({
            "name": "🎯 試験のポイント",
            "value": post["keypoints"][:1024],
            "inline": False,
        })

    # 引用文献
    if post["refs"]:
        fields.append({
            "name": "📚 引用文献",
            "value": post["refs"][:1024],
            "inline": False,
        })

    embed = {
        "title": f"{topic_info['emoji']} {post['title']}"[:256],
        "color": color,
        "fields": fields,
        "footer": {
            "text": f"内科専門医試験対策  |  {topic_info['field']}  |  {datetime.now().strftime('%Y-%m-%d %H:%M')} JST",
        },
        "timestamp": datetime.utcnow().isoformat(),
    }

    payload = {
        "username": "内科専門医 学習Bot",
        "embeds": [embed],
    }

    resp = requests.post(NAIKA_WEBHOOK_URL, json=payload, timeout=15)
    resp.raise_for_status()
    print(f"[Discord] 投稿完了: {post['title'][:50]}")


# ============================================================
# 投稿済み管理
# ============================================================
def load_posted() -> dict:
    if POSTED_FILE.exists():
        return json.loads(POSTED_FILE.read_text())
    return {"pmids": [], "recent_topics": []}


def save_posted(data: dict):
    data["pmids"] = data["pmids"][-3000:]
    data["recent_topics"] = data["recent_topics"][-60:]
    POSTED_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


# ============================================================
# メイン処理
# ============================================================
def main():
    print(f"=== 内科専門医Bot 実行: {datetime.now().isoformat()} ===")

    posted = load_posted()
    posted_pmids = set(posted["pmids"])
    recent_topics = posted["recent_topics"]

    # 直近10投稿と同じトピックを避ける
    available = [
        t for t in EXAM_TOPICS
        if t["topic"] not in recent_topics[-10:]
    ]
    if not available:
        available = EXAM_TOPICS

    topic = random.choice(available)
    print(f"[Topic] {topic['emoji']} {topic['field']}: {topic['topic']}")

    # PubMed 検索
    pmids = search_pubmed(topic["query"], reldate=SEARCH_DAYS)
    print(f"[PubMed] {len(pmids)} 件ヒット")

    if not pmids:
        print("[Error] 論文が見つかりません。終了。")
        return

    # 候補からランダムに選択
    selected = random.sample(pmids, min(PAPERS_PER_POST + 3, len(pmids)))
    articles = fetch_articles(selected)

    if len(articles) < 1:
        print("[Error] abstract付き論文が不足。終了。")
        return

    use_articles = articles[:PAPERS_PER_POST]
    print(f"[Selected] {len(use_articles)} 件の文献を使用")

    # 教育的投稿を生成
    try:
        post = generate_educational_post(topic, use_articles)
        send_discord_post(topic, post, use_articles)

        for art in use_articles:
            posted["pmids"].append(art["pmid"])
        posted["recent_topics"].append(topic["topic"])
        save_posted(posted)

        print("=== 完了 ===")
    except Exception as e:
        print(f"[Error] {e}")
        raise


if __name__ == "__main__":
    main()
