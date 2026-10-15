import io
import json
import os

import streamlit as st
from PIL import Image, ImageDraw, ImageFont

from leitor_foto import MODELO_GEMINI, TAMANHO_MAX_FOTO

ENDERECOS_CONSULADOS = {
    "WASHINGTON": "CONSULATE GENERAL OF BRAZIL IN WASHINGTON\n1030 15TH ST NW, SUITE 280W\nATT: SETOR DE PASSAPORTE\nWASHINGTON, DC 20005-1506",
    "ATLANTA": "CONSULATE GENERAL OF BRAZIL IN ATLANTA\n3500 LENOX RD NE, SUITE 800\nATLANTA, GA 30326",
    "BOSTON": "CONSULATE GENERAL OF BRAZIL IN BOSTON\n175 PURCHASE ST\nBOSTON, MA 02110",
    "CHICAGO": "CONSULATE GENERAL OF BRAZIL IN CHICAGO\n401 N MICHIGAN AVE, SUITE 1850\nCHICAGO, IL 60611",
    "HARTFORD": "CONSULATE GENERAL OF BRAZIL IN HARTFORD\n1 CONSTITUTION PLAZA, GROUND FLOOR\nHARTFORD, CT 06103",
    "HOUSTON": "CONSULATE GENERAL OF BRAZIL IN HOUSTON\n5444 WESTHEIMER RD, SUITE 1900\nHOUSTON, TX 77056",
    "LOS ANGELES": "CONSULATE GENERAL OF BRAZIL IN LOS ANGELES\n8484 WILSHIRE BLVD, SUITE 300\nBEVERLY HILLS, CA 90211",
    "MIAMI": "CONSULATE GENERAL OF BRAZIL IN MIAMI\n3150 SW 38TH AVE, FIRST FLOOR\nMIAMI, FL 33146",
    "NEW YORK": "CONSULATE GENERAL OF BRAZIL IN NEW YORK\n225 E 41ST ST\nNEW YORK, NY 10017",
    "ORLANDO": "CONSULATE GENERAL OF BRAZIL IN ORLANDO\n355 N ORANGE AVE\nORLANDO, FL 32801",
    "SAN FRANCISCO": "CONSULATE GENERAL OF BRAZIL IN SAN FRANCISCO\n300 MONTGOMERY ST, SUITE 300\nSAN FRANCISCO, CA 94104",
}

# ---------------------------------------------------------------------------
# AJUSTES (posições em proporção da ETIQUETA já em pé: 0.0 a 1.0)
# ---------------------------------------------------------------------------
TEMPLATE_PADRAO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "LABEL_3.png")

# Como a etiqueta está girada dentro do template:
# 90 = etiqueta girada 90° no sentido horário.
# Se o texto sair de cabeça para baixo, troque para -90.
ROTACAO_TEMPLATE = 90

POS_X = 0.015          # distância da borda esquerda da etiqueta (em pé)
POS_FROM_Y = 0.265     # início do texto do remetente (abaixo de "FROM:")
POS_TO_Y = 0.640       # início do texto do destinatário (abaixo de "TO:")

TAM_FONTE = 0.027      # tamanho da fonte relativo à altura da etiqueta
ESPACAMENTO = 1.30     # espaçamento entre linhas

# Se a detecção automática da etiqueta falhar, informe manualmente
# (esquerda, topo, direita, base) em pixels do LABEL_3.png. Ex.: (150, 95, 560, 480)
CAIXA_MANUAL = None

PASTA_FONTES = "fonts"
FONTES_REGULAR = [
    os.path.join(PASTA_FONTES, "OpenSans-Regular.ttf"),
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
FONTES_BOLD = [
    os.path.join(PASTA_FONTES, "OpenSans-Bold.ttf"),
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]

CAMPOS_CLIENTE = ["nome", "endereco", "cidade", "estado", "zip", "telefone"]
CAMPOS_OBRIGATORIOS = ["nome", "endereco", "cidade", "estado", "zip"]

PROMPT_ENDERECO = """Extraia o endereço residencial nos EUA do titular deste comprovante de residência (ou do texto informado).
- "nome": nome completo do titular.
- "endereco": número, rua e complemento (apt, unit, suite).
- "cidade": cidade.
- "estado": sigla do estado com 2 letras.
- "zip": ZIP code.
- "telefone": telefone, se houver.
Use o endereço de serviço/residência, não o endereço da empresa emissora nem o de pagamento.
Devolva vazio o que não estiver presente. Não invente dados."""

SCHEMA_ENDERECO = {
    "type": "OBJECT",
    "properties": {c: {"type": "STRING"} for c in CAMPOS_CLIENTE},
    "required": CAMPOS_CLIENTE,
}


# ==============================================================================
# GERAÇÃO DA IMAGEM
# ==============================================================================
def _carregar_fonte(candidatas, tamanho):
    for caminho in candidatas:
        if os.path.exists(caminho):
            return ImageFont.truetype(caminho, tamanho)
    return ImageFont.load_default(tamanho)


def _achar_caixa_etiqueta(img):
    """Acha a área da etiqueta (pixels com tinta: vermelho, azul, texto) no template."""
    if CAIXA_MANUAL:
        return CAIXA_MANUAL
    mascara = img.convert("L").point(lambda p: 255 if p < 200 else 0)
    caixa = mascara.getbbox()
    if not caixa:
        raise ValueError("Não foi possível detectar a etiqueta no template.")
    return caixa


def _desenhar_bloco(draw, linhas, x, y, altura, negrito_primeira=False):
    tam = max(8, int(altura * TAM_FONTE))
    fonte_reg = _carregar_fonte(FONTES_REGULAR, tam)
    fonte_bold = _carregar_fonte(FONTES_BOLD, tam)
    passo = int(tam * ESPACAMENTO)
    for i, linha in enumerate(linhas):
        fonte = fonte_bold if (negrito_primeira and i == 0) else fonte_reg
        draw.text((x, y + i * passo), linha, font=fonte, fill=(0, 0, 0))


def gerar_label_passaporte_png(consulado_nome, dados_cliente, caminho_template=TEMPLATE_PADRAO):
    """Escreve FROM (consulado) e TO (cliente) sobre o template e devolve os bytes do PNG.

    Nada é gravado em disco: a label tem nome e endereço do cliente.
    """
    img = Image.open(caminho_template).convert("RGB")

    caixa = _achar_caixa_etiqueta(img)
    recorte = img.crop(caixa)

    # Coloca a etiqueta em pé para escrever com as coordenadas normais
    em_pe = recorte.rotate(ROTACAO_TEMPLATE, expand=True)
    w, h = em_pe.size
    draw = ImageDraw.Draw(em_pe)

    consulado_upper = str(consulado_nome).strip().upper()
    texto_from = ENDERECOS_CONSULADOS.get(
        consulado_upper,
        f"CONSULATE GENERAL OF BRAZIL IN {consulado_upper}",
    )

    nome = str(dados_cliente.get("nome", "")).strip()
    endereco = str(dados_cliente.get("endereco", "")).strip().upper()
    cidade = str(dados_cliente.get("cidade", "")).strip().upper()
    estado = str(dados_cliente.get("estado", "")).strip().upper()
    zip_code = str(dados_cliente.get("zip", "")).strip().upper()
    telefone = str(dados_cliente.get("telefone", "")).strip()

    linhas_to = [nome, endereco, f"{cidade}, {estado} {zip_code}"]
    if telefone:
        linhas_to.append(f"TEL: {telefone}")

    x = int(w * POS_X)
    _desenhar_bloco(draw, texto_from.split("\n"), x, int(h * POS_FROM_Y), h, negrito_primeira=True)
    _desenhar_bloco(draw, linhas_to, x, int(h * POS_TO_Y), h)

    # Gira de volta e cola no mesmo lugar do template
    de_volta = em_pe.rotate(-ROTACAO_TEMPLATE, expand=True)
    img.paste(de_volta, (caixa[0], caixa[1]))

    saida = io.BytesIO()
    img.save(saida, "PNG")
    return saida.getvalue()


# ==============================================================================
# GEMINI: comprovante de residência (foto/PDF) ou texto colado -> campos
# ==============================================================================
def extrair_endereco(texto="", arquivo_bytes=None, mime_type=None):
    from google import genai
    from google.genai import types

    chave = os.getenv("GEMINI_API_KEY", "")
    if not chave:
        raise RuntimeError("GEMINI_API_KEY não configurada no .env / Secrets.")

    conteudo = [PROMPT_ENDERECO]
    if arquivo_bytes:
        conteudo.insert(0, types.Part.from_bytes(data=arquivo_bytes, mime_type=mime_type))
    if texto:
        conteudo.append(f"Texto informado:\n{texto}")

    client = genai.Client(api_key=chave)
    resposta = client.models.generate_content(
        model=MODELO_GEMINI,
        contents=conteudo,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=SCHEMA_ENDERECO,
            temperature=0,
        ),
    )
    dados = json.loads(resposta.text or "{}")
    return {c: str(dados.get(c) or "").strip() for c in CAMPOS_CLIENTE}


# ==============================================================================
# TELA (dentro da aba "Inserir Rastreio Antigo")
# ==============================================================================
def renderizar_label_passaporte():
    with st.expander("🏷️ Preencher Label para o E-Consular"):
        consulado = st.selectbox(
            "Consulado (remetente - FROM):", sorted(ENDERECOS_CONSULADOS), key="label_consulado"
        )
        comprovante = st.file_uploader(
            "Comprovante de residência do cliente",
            type=["jpg", "jpeg", "png", "webp", "pdf"],
            key="label_comprovante",
        )
        texto_colado = st.text_area(
            "...ou cole aqui o nome e o endereço do cliente",
            max_chars=1000,
            height=110,
            key="label_texto",
        )

        if st.button(
            "🏷️ Gerar label",
            type="primary",
            disabled=not (comprovante or texto_colado.strip()),
            use_container_width=True,
        ):
            st.session_state.pop("label_png", None)
            if comprovante and comprovante.size > TAMANHO_MAX_FOTO:
                st.error("❌ Arquivo maior que 15 MB.")
            else:
                try:
                    with st.spinner("Lendo o endereço, aguarde..."):
                        dados = extrair_endereco(
                            texto_colado.strip(),
                            comprovante.getvalue() if comprovante else None,
                            comprovante.type if comprovante else None,
                        )
                    faltando = [c for c in CAMPOS_OBRIGATORIOS if not dados[c]]
                    if faltando:
                        st.error(
                            f"❌ A IA não encontrou: {', '.join(faltando)}."
                            " Cole o nome e o endereço completos no campo de texto."
                        )
                    else:
                        st.session_state["label_png"] = gerar_label_passaporte_png(consulado, dados)
                        st.session_state["label_arquivo"] = (
                            "Label_Passaporte_" + "_".join(dados["nome"].split()) + ".png"
                        )
                except Exception as e:
                    st.error(f"❌ Falha na leitura ({type(e).__name__}: {e})")

        if st.session_state.get("label_png"):
            st.caption(
                "Confira o nome e o endereço na label. Se algo saiu errado,"
                " cole o endereço correto acima e gere de novo."
            )
            st.image(st.session_state["label_png"], width=420)
            st.download_button(
                "⬇️ Baixar label (PNG)",
                data=st.session_state["label_png"],
                file_name=st.session_state["label_arquivo"],
                mime="image/png",
                use_container_width=True,
            )


if __name__ == "__main__":
    # Auto-teste: python label_passaporte.py  (gera uma label fictícia e confere o tamanho)
    cliente = {
        "nome": "Maria Teste da Silva", "endereco": "123 Main St Apt 4B", "cidade": "Newark",
        "estado": "nj", "zip": "07105", "telefone": "(555) 010-0000",
    }
    png = gerar_label_passaporte_png("WASHINGTON", cliente)
    gerada, modelo = Image.open(io.BytesIO(png)), Image.open(TEMPLATE_PADRAO)
    assert gerada.size == modelo.size
    assert gerada.tobytes() != modelo.convert("RGB").tobytes(), "nada foi escrito na label"
    assert set(extrair_endereco.__code__.co_varnames) >= {"texto", "arquivo_bytes"}
    print("ok")
