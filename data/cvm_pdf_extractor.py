"""Extração da DRE direto do PDF da DFP protocolada na CVM, com citação de página.

Por que existe: a base aberta da CVM entrega o dado estruturado (CSV da DRE
consolidada), mas o documento que a companhia protocolou é um PDF. Para um
Arquivo Local, a diferença entre "a margem é 5,34%" e "a margem é 5,34%,
página 21 do documento protocolado, linha 'Resultado Antes do Resultado
Financeiro e dos Tributos'" é a diferença entre um número e uma prova.

Este módulo é ENRIQUECIMENTO SOB DEMANDA — nunca roda sozinho numa busca. Cada
rodada custa em torno de US$ 0,50 no Bedrock, e a maioria das buscas não vira
laudo; quem decide gastar é o usuário, sobre um comparável que já escolheu.

Validado em 15/07/2026 contra a Hypera (pág. 22) e a Blau (pág. 21): 8 de 8
números exatos, exercício correto nas duas.

Duas guardas que não existiam na PoC e são obrigatórias aqui:

1. **As margens são recalculadas a partir dos valores extraídos.** O modelo é
   bom em ler a tabela e ruim em ser confiável na divisão; a aritmética é nossa.
2. **Confronto com o dado estruturado.** Temos as duas fontes para a mesma
   empresa, então comparar é grátis: divergência acima de meio ponto percentual
   é DEVOLVIDA ao usuário, não escondida. Duas fontes que concordam valem mais
   que uma; duas que discordam são um aviso, nunca uma média.
"""
import io
import json
import os
import re
import zipfile
from typing import Optional, Tuple

import requests
import streamlit as st
from pypdf import PdfReader

DEFAULT_MODEL_ID = "us.anthropic.claude-opus-4-5-20251101-v1:0"
DEFAULT_REGION = "us-east-1"
MAX_DIVERGENCE_PP = 0.5      # tolerância de arredondamento entre PDF e CSV
SESSION_LIMIT = 3            # extrações por sessão — protege o crédito

PROMPT_TMPL = """Você é um analista contábil brasileiro. Abaixo está o texto COMPLETO de um documento DFP \
(Demonstrações Financeiras Padronizadas) da CVM. Cada página é marcada com "===== PÁGINA N =====".

Da DEMONSTRAÇÃO DO RESULTADO (DRE) CONSOLIDADA do EXERCÍCIO MAIS RECENTE, extraia os valores abaixo. \
Para CADA valor informe: o número exatamente como aparece, a página onde encontrou, e o rótulo exato da linha.

Valores:
1. Receita líquida de vendas (conta 3.01)
2. Resultado bruto / lucro bruto (conta 3.03)
3. Resultado antes do resultado financeiro e dos tributos / EBIT (conta 3.05)
4. Lucro/prejuízo consolidado do período (conta 3.11)

ATENÇÃO: use a coluna do ÚLTIMO exercício, nunca a do exercício comparativo anterior.

Responda APENAS com um JSON válido nesta estrutura exata, sem nenhum texto antes ou depois:
{{
  "empresa": "...",
  "exercicio": "AAAA",
  "escala": "MIL",
  "itens": {{
    "receita_liquida":       {{"valor": 0, "pagina": 0, "rotulo": "..."}},
    "lucro_bruto":           {{"valor": 0, "pagina": 0, "rotulo": "..."}},
    "resultado_operacional": {{"valor": 0, "pagina": 0, "rotulo": "..."}},
    "lucro_liquido":         {{"valor": 0, "pagina": 0, "rotulo": "..."}}
  }}
}}

Regras: se um valor não existir, use null nos campos. NÃO invente nada — só reporte o que está no texto. \
NÃO calcule margens; apenas extraia os valores.

DOCUMENTO:
{doc}
"""


# ── credenciais ──────────────────────────────────────────────────────────────
def _secret(name: str, default: str = "") -> str:
    """Lê de st.secrets com fallback para env. SEMPRE na thread principal.

    Ler st.secrets de dentro de thread daemon já derrubou o webhook em silêncio
    por três semanas em junho/2026 — o acesso falha, o except engole, e a
    funcionalidade simplesmente não acontece. Este módulo só é chamado a partir
    do clique do usuário, ou seja, na thread principal.
    """
    try:
        val = st.secrets.get(name, "")
    except Exception:
        val = ""
    return str(val or os.environ.get(name, "") or default)


def bedrock_available() -> bool:
    """A extração por PDF só aparece na interface quando há credencial."""
    return bool(_secret("AWS_BEARER_TOKEN_BEDROCK"))


def extraction_allowed(email: str) -> bool:
    """Só e-mails liberados podem gastar crédito de IA.

    O app é PÚBLICO e cada extração custa dinheiro real. O limite de
    SESSION_LIMIT protege contra clique repetido, não contra volume: sessão
    qualquer visitante abre quantas quiser, e cem curiosos fazendo três
    extrações cada consomem uma fatia séria do crédito. A trava de verdade é
    esta.

    Configuração no secrets: `PDF_EXTRACTION_ALLOWLIST` com e-mails e/ou
    domínios separados por vírgula —
        PDF_EXTRACTION_ALLOWLIST = "gabriela@x.com, @algoritimado.com"

    **Falha FECHADA de propósito:** lista vazia = ninguém autorizado. Se a chave
    do Bedrock entrar no secrets e a lista não, o pior caso é a funcionalidade
    não aparecer — nunca crédito queimando por engano.
    """
    raw = _secret("PDF_EXTRACTION_ALLOWLIST").strip()
    if not raw:
        return False
    alvo = (email or "").strip().lower()
    if not alvo or "@" not in alvo:
        return False
    dominio = alvo.split("@")[-1]
    for entrada in raw.split(","):
        item = entrada.strip().lower()
        if not item:
            continue
        if item.startswith("@"):
            if dominio == item[1:]:
                return True
        elif item == alvo:
            return True
    return False


# ── PDF ──────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=86400, show_spinner=False)
def download_dfp_pdf(link_doc: str) -> Optional[bytes]:
    """Baixa o pacote oficial do LINK_DOC da CVM e devolve os bytes do PDF.

    O LINK_DOC entrega um ZIP com o PDF do DFP + XMLs — é o mesmo link que já
    vai como fonte no laudo, então a citação de página aponta exatamente para o
    documento que o usuário pode abrir.
    """
    if not link_doc:
        return None
    url = str(link_doc).replace("http://", "https://")
    try:
        r = requests.get(url, timeout=180)
        if r.status_code != 200:
            return None
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            name = next((n for n in z.namelist() if n.lower().endswith(".pdf")), None)
            if not name:
                return None
            return z.read(name)
    except Exception:
        return None


def page_numbered_text(pdf_bytes: bytes) -> Tuple[str, int]:
    """Texto do PDF com marcador de página — é o marcador que permite a citação."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    parts = []
    for i, page in enumerate(reader.pages):
        parts.append(f"\n===== PÁGINA {i + 1} =====\n{page.extract_text() or ''}")
    return "".join(parts), len(reader.pages)


def build_prompt(doc: str) -> str:
    return PROMPT_TMPL.format(doc=doc)


# ── Bedrock ──────────────────────────────────────────────────────────────────
def call_bedrock(prompt: str) -> Tuple[str, dict]:
    import boto3

    token = _secret("AWS_BEARER_TOKEN_BEDROCK")
    if token:
        # boto3 ≥1.43 consome a API key do Bedrock por variável de ambiente.
        os.environ["AWS_BEARER_TOKEN_BEDROCK"] = token
    client = boto3.client(
        "bedrock-runtime", region_name=_secret("AWS_REGION", DEFAULT_REGION))
    resp = client.converse(
        modelId=_secret("BEDROCK_MODEL_ID", DEFAULT_MODEL_ID),
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 2000, "temperature": 0},
    )
    return resp["output"]["message"]["content"][0]["text"], resp.get("usage", {})


# ── parsing e validação ──────────────────────────────────────────────────────
def parse_extraction(raw: str) -> Optional[dict]:
    """Extrai o JSON da resposta. Texto que não contém JSON válido = falha limpa."""
    if not raw:
        return None
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _num(v):
    """Converte para float aceitando formato brasileiro ('1.754.376' / '1,5')."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(" ", "")
    if not s:
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    elif "." in s:
        # Só pontos: pode ser separador de milhar ("1.754.376") ou decimal
        # ("18.7415"). Grupos de exatamente 3 dígitos depois de cada ponto = milhar.
        # A aposta é segura aqui porque esta função só lê VALORES da DRE, que são
        # inteiros em milhares de reais — margem nenhuma passa por aqui, ela é
        # sempre calculada por nós a partir destes valores.
        grupos = s.lstrip("-").split(".")
        if len(grupos) > 1 and all(len(g) == 3 for g in grupos[1:]) and len(grupos[0]) <= 3:
            s = s.replace(".", "")
    try:
        val = float(s)
    except ValueError:
        return None
    return -val if neg else val


def normalize_extraction(data: dict) -> Optional[dict]:
    """Valida a estrutura e RECALCULA as margens a partir dos valores extraídos.

    A aritmética é nossa de propósito: o modelo lê a tabela bem e erra a divisão
    de vez em quando, e uma margem errada num laudo é indefensável.
    """
    if not isinstance(data, dict):
        return None
    itens = data.get("itens")
    if not isinstance(itens, dict):
        return None

    out_itens = {}
    for key in ("receita_liquida", "lucro_bruto", "resultado_operacional", "lucro_liquido"):
        raw_item = itens.get(key) or {}
        if not isinstance(raw_item, dict):
            raw_item = {}
        valor = _num(raw_item.get("valor"))
        pagina = _num(raw_item.get("pagina"))
        out_itens[key] = {
            "valor": valor,
            "pagina": int(pagina) if pagina else None,
            "rotulo": str(raw_item.get("rotulo") or "").strip() or None,
        }

    rev = out_itens["receita_liquida"]["valor"]
    if not rev:
        return None      # sem receita não há margem — falha honesta

    margens = {}
    for key, nome in (("lucro_bruto", "margem_bruta_pct"),
                      ("resultado_operacional", "margem_operacional_pct"),
                      ("lucro_liquido", "margem_liquida_pct")):
        val = out_itens[key]["valor"]
        margens[nome] = round(val / rev * 100, 4) if val is not None else None

    return {
        "empresa": str(data.get("empresa") or "").strip() or None,
        "exercicio": str(data.get("exercicio") or "").strip() or None,
        "escala": str(data.get("escala") or "").strip() or None,
        "itens": out_itens,
        "margens": margens,
    }


def cross_check(extracted: dict, structured_margin: Optional[float],
                pli: str = "operating_margin") -> dict:
    """Confronta a margem do PDF com a do dado estruturado da mesma empresa.

    Concordância vira reforço de prova; divergência vira aviso. Nunca média.
    """
    key = {"operating_margin": "margem_operacional_pct",
           "gross_margin": "margem_bruta_pct",
           "net_margin": "margem_liquida_pct"}.get(pli, "margem_operacional_pct")
    pdf_margin = (extracted.get("margens") or {}).get(key)
    if pdf_margin is None or structured_margin is None:
        return {"status": "indisponivel", "pdf": pdf_margin, "csv": structured_margin}
    diff = abs(pdf_margin - float(structured_margin))
    return {
        "status": "confere" if diff <= MAX_DIVERGENCE_PP else "divergente",
        "pdf": pdf_margin,
        "csv": round(float(structured_margin), 4),
        "diferenca_pp": round(diff, 4),
    }


def citation_text(extracted: dict, pli: str = "operating_margin", lang: str = "pt") -> str:
    """Uma linha citável: página + rótulo exato da linha do documento."""
    key = {"operating_margin": "resultado_operacional",
           "gross_margin": "lucro_bruto",
           "net_margin": "lucro_liquido"}.get(pli, "resultado_operacional")
    item = (extracted.get("itens") or {}).get(key) or {}
    pagina, rotulo = item.get("pagina"), item.get("rotulo")
    if not pagina:
        return ""
    if lang == "pt":
        base = f"DFP protocolada, pág. {pagina}"
        return f'{base} · linha "{rotulo}"' if rotulo else base
    base = f"Filed DFP, p. {pagina}"
    return f'{base} · line "{rotulo}"' if rotulo else base


# ── orquestração ─────────────────────────────────────────────────────────────
def extract_from_link(link_doc: str, email: Optional[str] = None) -> dict:
    """Pipeline completo. Devolve sempre um dict com 'ok' — nunca levanta.

    Quando `email` é informado, a autorização é checada AQUI também, e não só na
    interface: gasto de crédito não deve depender de a tela ter escondido o botão.
    """
    if not bedrock_available():
        return {"ok": False, "erro": "credencial_ausente"}
    if email is not None and not extraction_allowed(email):
        return {"ok": False, "erro": "nao_autorizado"}
    pdf = download_dfp_pdf(link_doc)
    if not pdf:
        return {"ok": False, "erro": "pdf_indisponivel"}
    try:
        doc, n_pages = page_numbered_text(pdf)
    except Exception:
        return {"ok": False, "erro": "pdf_ilegivel"}
    if len(doc.strip()) < 500:
        # PDF de imagem escaneada, sem camada de texto — pypdf não resolve.
        return {"ok": False, "erro": "pdf_sem_texto"}
    try:
        raw, usage = call_bedrock(build_prompt(doc))
    except Exception as e:
        return {"ok": False, "erro": "bedrock_falhou", "detalhe": str(e)[:300]}
    data = normalize_extraction(parse_extraction(raw) or {})
    if not data:
        return {"ok": False, "erro": "resposta_invalida"}
    return {"ok": True, "dados": data, "paginas": n_pages, "usage": usage}
