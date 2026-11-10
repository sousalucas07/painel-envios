"""Portal de envios D55: página estática (static/index.html) + API em FastAPI. Roda em Docker na VPS.

Só a camada web mora aqui. A lógica é a mesma do painel em Streamlit, importada dos arquivos
da raiz do repositório (sheets, tracker, emissao_shippo, leitor_foto, label_passaporte,
atualizar_tarefas) SEM alterar nenhum deles. As rotas abaixo repetem, passo a passo, o que as
telas do Streamlit fazem ao clicar em cada botão.
"""
import base64
import contextvars
import os
import re
import secrets
import sys
import threading
import time
from pathlib import Path
from typing import List, Optional

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
os.chdir(RAIZ)  # sheets.py procura credentials.json / .env / .streamlit/secrets.toml na pasta atual

import streamlit as st  # noqa: E402  (só para ler os secrets: st.secrets funciona fora do Streamlit)


def _carregar_secrets():
    """Mesmo esquema do dashboard.py: chaves de texto do secrets.toml viram variáveis de ambiente."""
    try:
        for chave, valor in st.secrets.items():
            if isinstance(valor, str):
                os.environ.setdefault(chave, valor)
    except Exception:
        pass  # sem secrets.toml: vale o .env (carregado pelo sheets.py) ou o ambiente


_carregar_secrets()

import atualizar_tarefas  # noqa: E402
import emissao_shippo as emi  # noqa: E402
import label_passaporte as l228  # noqa: E402
import leitor_foto as foto  # noqa: E402
import sheets  # noqa: E402
import tracker  # noqa: E402

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from starlette.middleware.sessions import SessionMiddleware  # noqa: E402

ESTATICOS = Path(__file__).resolve().parent / "static"
SENHA = os.environ.get("PORTAL_ENVIOS_SENHA") or os.environ.get("DASHBOARD_SENHA", "")
SENHA_EMISSAO = os.environ.get("EMISSAO_SENHA", "")
SEGREDO_SESSAO = os.environ.get("PORTAL_ENVIOS_SEGREDO", "")
COOKIE_SEGURO = os.environ.get("COOKIE_SEGURO", "1") != "0"  # na VPS (HTTPS) fica ligado

SESSAO_MIN = 60                       # login cai depois de 1 hora sem uso
MAX_TENTATIVAS, BLOQUEIO_MIN = 5, 15  # 5 senhas erradas = IP bloqueado por 15 min
MAX_FOTOS_POR_LEITURA = 20
OUTRO_DPT = "✏️ Outro endereço (digitar)"
PARES_ANTIGO = {  # igual ao TIPOS_PAR do dashboard.py
    "IDA + RETORNO": ("IDA", "RETORNO"),
    "Cli - Con / Con - Cli": ("Cli - Con", "Con - Cli"),
}

if not SEGREDO_SESSAO:
    # Sem segredo fixo, cada reinício derruba os logins (seguro, só incômodo)
    SEGREDO_SESSAO = secrets.token_hex(32)
    print("⚠️ PORTAL_ENVIOS_SEGREDO não configurado: usando um segredo temporário.", flush=True)

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    SessionMiddleware, secret_key=SEGREDO_SESSAO, session_cookie="portal_envios",
    max_age=12 * 3600, same_site="strict", https_only=COOKIE_SEGURO,
)
app.mount("/static", StaticFiles(directory=ESTATICOS), name="static")


@app.middleware("http")
async def proteger_api(request: Request, call_next):
    # Toda ação (POST) exige o cabeçalho X-Portal, que só a própria página manda:
    # outro site não consegue enviar cabeçalho próprio sem CORS (e aqui não há CORS).
    if request.method == "POST" and request.url.path.startswith("/api/") and request.headers.get("x-portal") != "1":
        return JSONResponse({"detail": "Requisição recusada."}, status_code=403)
    resposta = await call_next(request)
    resposta.headers["Cache-Control"] = "no-store"
    # Só scripts da própria página (bloqueia código injetado); fontes do Google; imagens de dados/blob
    resposta.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data: blob:;"
        " style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com;"
        " frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    )
    resposta.headers["X-Content-Type-Options"] = "nosniff"
    resposta.headers["Referrer-Policy"] = "no-referrer"
    return resposta


# ==============================================================================
# LOGIN E SESSÃO
# ==============================================================================
_falhas: dict = {}  # ip -> horários das senhas erradas
_trava_falhas = threading.Lock()


def _ip(request: Request) -> str:
    # atrás do Caddy o IP real vem no X-Forwarded-For
    return (request.headers.get("x-forwarded-for") or request.client.host).split(",")[0].strip()


def _bloqueado(ip: str) -> bool:
    with _trava_falhas:
        agora = time.time()
        recentes = [t for t in _falhas.pop(ip, []) if agora - t < BLOQUEIO_MIN * 60]
        if recentes:
            _falhas[ip] = recentes
        return len(recentes) >= MAX_TENTATIVAS


def _registrar_falha(ip: str, onde: str):
    with _trava_falhas:
        _falhas.setdefault(ip, []).append(time.time())
    print(f"{time.strftime('%H:%M:%S')} [{onde}] senha errada de {ip}", flush=True)


def _senha_confere(digitada: str, correta: str) -> bool:
    return secrets.compare_digest((digitada or "").encode(), correta.encode())


def exigir_login(request: Request) -> dict:
    sessao = request.session
    if not sessao.get("auth") or time.time() - float(sessao["auth"]) > SESSAO_MIN * 60:
        sessao.clear()
        raise HTTPException(401, "Sessão expirada. Entre de novo.")
    sessao["auth"] = time.time()  # renova a cada uso
    return sessao


def exigir_emissao(sessao: dict = Depends(exigir_login)) -> dict:
    if not sessao.get("emissao"):
        raise HTTPException(403, "Libere a emissão com a senha da emissão.")
    return sessao


class Senha(BaseModel):
    senha: str = ""


@app.get("/")
def pagina():
    return FileResponse(ESTATICOS / "index.html")


@app.get("/api/sessao")
def sessao_atual(request: Request):
    s = request.session
    logado = bool(s.get("auth")) and time.time() - float(s.get("auth", 0)) <= SESSAO_MIN * 60
    return {"logado": logado, "emissao": logado and bool(s.get("emissao"))}


@app.post("/api/login")
def login(dados: Senha, request: Request):
    ip = _ip(request)
    if not SENHA:
        raise HTTPException(503, "Senha do portal não configurada (PORTAL_ENVIOS_SENHA). Acesso bloqueado.")
    if _bloqueado(ip):
        raise HTTPException(429, f"Muitas tentativas. Aguarde {BLOQUEIO_MIN} minutos.")
    if not _senha_confere(dados.senha, SENHA):
        _registrar_falha(ip, "login")
        time.sleep(1)
        raise HTTPException(401, "Senha incorreta.")
    with _trava_falhas:
        _falhas.pop(ip, None)
    request.session.clear()
    request.session.update({"auth": time.time(), "sid": secrets.token_hex(8), "emissao": False})
    return {"ok": True}


@app.post("/api/sair")
def sair(request: Request):
    request.session.clear()
    return {"ok": True}


@app.post("/api/emissao/liberar")
def liberar_emissao(dados: Senha, request: Request, sessao: dict = Depends(exigir_login)):
    ip = _ip(request)
    if not SENHA_EMISSAO:
        raise HTTPException(503, "EMISSAO_SENHA não configurada. Emissão bloqueada.")
    if _bloqueado(ip):
        raise HTTPException(429, f"Muitas tentativas. Aguarde {BLOQUEIO_MIN} minutos.")
    if not _senha_confere(dados.senha, SENHA_EMISSAO):
        _registrar_falha(ip, "emissao")
        time.sleep(1)
        raise HTTPException(403, "Senha incorreta.")  # 401 fica reservado para "sessão expirou"
    sessao["emissao"] = True
    return {"ok": True}


# ==============================================================================
# LIMITE DO GEMINI (substitui o do leitor_foto, que depende da sessão do Streamlit)
# Mesmos números: LIMITE_GEMINI_DIA no total e LIMITE_GEMINI_HORA_SESSAO por sessão.
# ==============================================================================
_sessao_atual = contextvars.ContextVar("sessao_atual", default="")
_uso_ia = {"dia": "", "total": 0, "sessoes": {}}
_trava_ia = threading.Lock()


def consumir_leitura_gemini():
    agora = sheets.agora_br()
    dia, hora = agora.strftime("%Y-%m-%d"), agora.strftime("%Y-%m-%d %H")
    with _trava_ia:
        if _uso_ia["dia"] != dia:
            _uso_ia.update(dia=dia, total=0, sessoes={})
        sid = _sessao_atual.get()
        hora_sessao, usadas = _uso_ia["sessoes"].get(sid, (hora, 0))
        if hora_sessao != hora:
            usadas = 0
        if _uso_ia["total"] >= foto.LIMITE_GEMINI_DIA:
            raise RuntimeError(
                f"Limite diário de {foto.LIMITE_GEMINI_DIA} leituras da IA atingido."
                " Volta amanhã, ou preencha os campos à mão."
            )
        if usadas >= foto.LIMITE_GEMINI_HORA_SESSAO:
            raise RuntimeError(
                f"Limite de {foto.LIMITE_GEMINI_HORA_SESSAO} leituras por hora nesta sessão atingido."
                " Aguarde a próxima hora."
            )
        _uso_ia["total"] += 1
        _uso_ia["sessoes"][sid] = (hora, usadas + 1)


def _leituras():
    with _trava_ia:
        total = _uso_ia["total"] if _uso_ia["dia"] == sheets.agora_br().strftime("%Y-%m-%d") else 0
    return {"total": total, "limite": foto.LIMITE_GEMINI_DIA}


# ler_etiquetas e extrair_endereco chamam o limite pelo nome global do próprio módulo
foto.consumir_leitura_gemini = consumir_leitura_gemini
l228.consumir_leitura_gemini = consumir_leitura_gemini


async def _ler_arquivo(arquivo: Optional[UploadFile]):
    if not arquivo or not arquivo.filename:
        return None, None
    dados = await arquivo.read()
    if len(dados) > foto.TAMANHO_MAX_FOTO:
        raise HTTPException(413, f"{arquivo.filename}: arquivo maior que 15 MB.")
    return dados, arquivo.content_type or "application/octet-stream"


def _erro_ia(e: Exception) -> HTTPException:
    if isinstance(e, RuntimeError):  # limite atingido / chave ausente: mensagem feita para o usuário
        return HTTPException(429 if "Limite" in str(e) else 503, str(e))
    print(f"❌ Leitura da IA: {type(e).__name__}", flush=True)
    return HTTPException(502, f"Falha na leitura da IA ({type(e).__name__}). Tente de novo.")


# ==============================================================================
# PLANILHA DO PAINEL
# ==============================================================================
_cache_planilha = {"t": 0.0, "df": None}
_trava_planilha = threading.Lock()


def _planilha(fresca=False):
    """DataFrame da planilha. A conferência da foto relê a cada edição: cache curto evita estourar a cota."""
    with _trava_planilha:
        if fresca or _cache_planilha["df"] is None or time.time() - _cache_planilha["t"] > 20:
            _cache_planilha.update(df=sheets.ler_envios_sheets(), t=time.time())
        return _cache_planilha["df"]


def _planilha_mudou():
    with _trava_planilha:
        _cache_planilha["t"] = 0.0


def _num_rastreio(valor) -> str:
    m = re.search(r"\d{15,30}", str(valor))
    return m.group(0) if m else foto.so_digitos(valor)


@app.get("/api/envios")
def envios(sessao: dict = Depends(exigir_login)):
    df = _planilha(fresca=True)
    if df.empty:
        return {"linhas": [], "hoje": sheets.agora_br().strftime("%Y-%m-%d")}
    col = lambda *t: foto._coluna(df, *t)  # noqa: E731
    mapa = {
        "data": col("data"), "pedido": col("id", "pedido", "bitrix"), "tarefa": col("tarefa"), "nome": col("nome"),
        "rastreio": col("rastreio", "tracking"), "tipo": col("tipo"), "status": col("status"), "ult": col("ult", "atualiz"),
    }
    linhas = []
    for _, linha in df.iterrows():
        item = {k: (str(linha[c]).strip() if c else "") for k, c in mapa.items()}
        item["numero"] = _num_rastreio(item["rastreio"])
        item["problema"] = any(p in item["status"].upper() for p in tracker.PALAVRAS_ERRO)
        if not item["tarefa"].startswith("http"):
            item["tarefa"] = ""
        linhas.append(item)
    linhas.sort(key=lambda x: x["ult"], reverse=True)  # mais recentes primeiro, como no painel atual
    return {"linhas": linhas, "hoje": sheets.agora_br().strftime("%Y-%m-%d")}


_cache_atrasos = {"t": 0.0, "dados": None}
_trava_atrasos = threading.Lock()


def _atraso_da_linha(linha):
    """(numero, {"prazo", "dias"}) se o envio passou do prazo de SLA, pela mesma regra das tarefas."""
    tipo, status, numero = linha["tipo"], linha["status"], linha["numero"]
    regra = tracker.PRAZOS_SLA.get(tracker.classificar_envio(tipo))
    if not numero or not regra:
        return None
    _, base = regra
    data_saida = None
    if base == "saida":
        if not status.upper().startswith("TRANSIT"):
            return None  # ainda em pré-envio (não conta) ou já entregue
        try:
            _, _, data_saida, _ = tracker.consultar_shippo(numero)
        except Exception:
            return None
    atraso = tracker.dias_atrasado(tipo, status, data_saida, linha["data"])
    return (numero, {"prazo": atraso[0], "dias": atraso[1]}) if atraso else None


@app.get("/api/envios/atrasados")
def atrasados(sessao: dict = Depends(exigir_login)):
    """Envios atrasados (SLA). Consulta a USPS só dos que estão em trânsito; guarda por 10 min."""
    from concurrent.futures import ThreadPoolExecutor

    with _trava_atrasos:
        if _cache_atrasos["dados"] is not None and time.time() - _cache_atrasos["t"] < 600:
            return {"atrasados": _cache_atrasos["dados"]}
        linhas = envios(sessao)["linhas"]
        with ThreadPoolExecutor(max_workers=6) as pool:
            achados = [r for r in pool.map(_atraso_da_linha, linhas) if r]
        _cache_atrasos.update(dados=dict(achados), t=time.time())
        return {"atrasados": _cache_atrasos["dados"]}


class Rastreios(BaseModel):
    rastreios: List[str]


@app.post("/api/envios/excluir")
def excluir(dados: Rastreios, sessao: dict = Depends(exigir_login)):
    if not dados.rastreios:
        raise HTTPException(400, "Nenhuma linha marcada.")
    nao_apagados = sheets.deletar_envios_sheets(dados.rastreios)
    _planilha_mudou()
    return {"nao_apagados": nao_apagados}


@app.post("/api/envios/imprimir")
def imprimir(dados: Rastreios, sessao: dict = Depends(exigir_login)):
    if not dados.rastreios:
        raise HTTPException(400, "Nenhuma linha marcada.")
    try:
        pdf, nao_achados = emi.etiquetas_para_reimprimir(dados.rastreios[:50])
    except Exception as e:
        print(f"❌ Reimpressão: {type(e).__name__}", flush=True)
        raise HTTPException(502, f"Falha ao buscar as etiquetas ({type(e).__name__}).")
    if not pdf:
        return JSONResponse({"detail": "Nenhuma das etiquetas foi emitida por este sistema (ou tem mais de 90 dias).",
                             "nao_achados": nao_achados}, status_code=404)
    return Response(pdf, media_type="application/pdf", headers={"X-Nao-Achados": ",".join(nao_achados)})


_trava_acao = threading.Lock()


def _acao_unica(funcao):
    if not _trava_acao.acquire(blocking=False):
        raise HTTPException(409, "Já tem uma atualização em andamento. Aguarde terminar.")
    try:
        funcao()
    finally:
        _trava_acao.release()
        _planilha_mudou()


@app.post("/api/acoes/bitrix")
def sincronizar_bitrix(sessao: dict = Depends(exigir_login)):
    _acao_unica(atualizar_tarefas.sincronizar_links_tarefas)
    return {"ok": True}


@app.post("/api/acoes/usps")
def atualizar_usps(sessao: dict = Depends(exigir_login)):
    _acao_unica(tracker.rodar_monitoramento)  # o mesmo ciclo do botão do painel atual (pode mandar WhatsApp)
    return {"ok": True}


# ==============================================================================
# EMISSÃO (Shippo)
# ==============================================================================
_trava_compra = threading.Lock()  # uma compra/reembolso por vez: o teto é conferido sem corrida


def _teto():
    try:
        qtd, gasto = sheets.compras_do_dia()
        return {"qtd": qtd, "gasto": round(gasto, 2), "max_qtd": emi.TETO_ETIQUETAS_DIA, "max_usd": emi.TETO_GASTO_DIA_USD}
    except Exception as e:
        return {"erro": f"Não consegui conferir o teto diário na auditoria ({type(e).__name__}). Compra bloqueada."}


@app.get("/api/emissao/opcoes")
def opcoes_emissao(sessao: dict = Depends(exigir_login)):
    return {
        "modos": {m: [list(t) for t in trechos] for m, trechos in emi.MODOS.items()},
        "consulados": sorted(l228.ENDERECOS_CONSULADOS),
        "departamentos": sorted(emi.DEPARTAMENTOS_ESTADO) + [OUTRO_DPT],
        "outro_dpt": OUTRO_DPT,
        "campos": l228.CAMPOS_CLIENTE, "obrigatorios": l228.CAMPOS_OBRIGATORIOS,
        "teto": _teto() if sessao.get("emissao") else None,
        "leituras": _leituras(),
    }


@app.post("/api/endereco/ler")
async def ler_endereco(request: Request, texto: str = Form(""), arquivo: Optional[UploadFile] = File(None),
                       sessao: dict = Depends(exigir_login)):
    dados, mime = await _ler_arquivo(arquivo)
    texto = texto.strip()[:1000]
    if not dados and not texto:
        raise HTTPException(400, "Envie um comprovante (ou a Driver's License) ou cole o endereço.")
    _sessao_atual.set(sessao.get("sid", ""))
    try:
        resultado = await _em_thread(l228.extrair_endereco, texto, dados, mime)
    except Exception as e:
        raise _erro_ia(e)
    return {"dados": resultado, "leituras": _leituras()}


async def _em_thread(funcao, *args):
    from starlette.concurrency import run_in_threadpool  # copia o contexto (sessão atual) para a thread
    return await run_in_threadpool(funcao, *args)


class Endereco(BaseModel):
    nome: str = ""
    endereco: str = ""
    cidade: str = ""
    estado: str = ""
    zip: str = ""
    telefone: str = ""


def _limpo(e: Optional[Endereco]) -> dict:
    d = e.model_dump() if e else {}
    return {c: str(d.get(c, "")).strip()[:120] for c in l228.CAMPOS_CLIENTE}


class Compra(BaseModel):
    pedido: str
    modo: str
    quais: str = "Ambas"
    consulado: str = ""
    departamento: str = ""
    endereco_departamento: Optional[Endereco] = None
    cliente: Optional[Endereco] = None
    forcar: bool = False


def _sem_marca(texto: str) -> str:
    """Mensagens para a tela sem o nome do fornecedor das etiquetas (vêm do emissao_shippo.py)."""
    trocas = [
        ("Compra não encontrada na Shippo", "Compra não encontrada"),
        (": a Shippo recusa o reembolso.", ": o reembolso não é aceito."),
        ("na Shippo", "no sistema de etiquetas"),
    ]
    for antes, depois in trocas:
        texto = texto.replace(antes, depois)
    texto = re.sub(r"\bShippo (\d{3}):", r"Erro \1 no sistema de etiquetas:", texto)
    return re.sub(r"(?i)\bshippo\b", "sistema de etiquetas", texto)


def _b64(dados: bytes) -> str:
    return base64.b64encode(dados).decode()


@app.post("/api/emissao/comprar")
def comprar(dados: Compra, sessao: dict = Depends(exigir_emissao)):
    # --- mesmas validações da aba de emissão do Streamlit ---
    if dados.modo not in emi.MODOS:
        raise HTTPException(400, "Tipo de envio inválido.")
    trechos = emi.MODOS[dados.modo]
    if dados.modo == "Cli - Con / Con - Cli" and dados.quais in ("Cli - Con", "Con - Cli"):
        trechos = [t for t in trechos if t[0] == dados.quais]
    num_pedido = dados.pedido.strip()
    if not num_pedido.isdigit():
        raise HTTPException(400, "O número do pedido deve ter só dígitos.")

    usa_con = any("CON" in (de, para) for _, de, para in trechos)
    consulado = None
    if usa_con:
        if dados.consulado not in l228.ENDERECOS_CONSULADOS:
            raise HTTPException(400, "Escolha o consulado.")
        consulado = dados.consulado

    departamento = None
    faltando = []
    if dados.modo.startswith("D55"):
        if dados.departamento == OUTRO_DPT:
            dpt = _limpo(dados.endereco_departamento)
            faltando = [c for c in l228.CAMPOS_OBRIGATORIOS if not dpt[c]]
            departamento = emi.endereco_cliente(dpt) if not faltando else None
        elif dados.departamento in emi.DEPARTAMENTOS_ESTADO:
            departamento = dados.departamento
        else:
            raise HTTPException(400, "Escolha o departamento de estado.")
        cliente_dados = None
    else:
        cliente_dados = _limpo(dados.cliente)
        faltando = [c for c in l228.CAMPOS_OBRIGATORIOS if not cliente_dados[c]]
    if faltando:
        raise HTTPException(400, f"Faltando: {', '.join(faltando)}.")

    tipos = [t for t, _, _ in trechos]
    repetidas = emi._ja_emitidas(_planilha(fresca=True), num_pedido, tipos)
    if repetidas and not dados.forcar:
        return JSONResponse({"detail": f"O pedido {num_pedido} já tem etiqueta {', '.join(repetidas)} na planilha.",
                             "repetidas": repetidas}, status_code=409)

    if cliente_dados:
        nome = cliente_dados["nome"].upper()
    elif isinstance(departamento, dict):
        nome = departamento["name"]
    else:
        nome = f"DPT {departamento}"

    etiquetas, erro = [], ""

    def checar_teto(rate):
        # Relê na hora do pagamento: outra pessoa pode ter comprado desde que a tela abriu
        qtd, gasto = sheets.compras_do_dia()
        valor = float(rate["amount"])
        if qtd + 1 > emi.TETO_ETIQUETAS_DIA or gasto + valor > emi.TETO_GASTO_DIA_USD:
            raise RuntimeError(f"Teto diário atingido ({qtd} etiquetas, US$ {gasto:.2f}). Esta etiqueta NÃO foi comprada.")

    def registrar(etiqueta):
        etiquetas.append(etiqueta)  # já comprada: volta para a tela mesmo se a planilha falhar
        ok = sheets.registrar_envio_sheets({
            "num_pedido": num_pedido, "nome": nome,
            "tracking_code": emi.LINK_USPS + etiqueta["rastreio"],
            "tipo_envio": etiqueta["tipo"], "custo": etiqueta["custo"],
        })
        if not ok:  # para antes de comprar a próxima
            raise RuntimeError(
                f"Etiqueta {etiqueta['tipo']} comprada ({etiqueta['rastreio']}) mas NÃO gravada"
                " na planilha. Cadastre manualmente na aba Rastreio antigo."
            )

    with _trava_compra:
        try:
            emi.emitir(
                dados.modo, num_pedido,
                cliente=emi.endereco_cliente(cliente_dados) if cliente_dados else None,
                consulado=consulado, departamento=departamento, ao_comprar=registrar,
                trechos=trechos, antes_de_pagar=checar_teto,
            )
        except Exception as e:
            print(f"❌ Emissão pedido {num_pedido}: {e}", flush=True)
            erro = _sem_marca(str(e)) if isinstance(e, RuntimeError) else f"Falha na emissão ({type(e).__name__})."
        finally:
            _planilha_mudou()

    resposta = {
        "pedido": num_pedido, "erro": erro,
        "etiquetas": [{"tipo": e["tipo"], "rastreio": e["rastreio"], "custo": e["custo"],
                       "png": _b64(e["arquivo"]), "pdf": _b64(emi.etiqueta_meia_pagina_pdf(e["arquivo"]))} for e in etiquetas],
        "teto": _teto(),
    }
    if dados.modo == "Cli - Con (Passaporte)" and etiquetas and cliente_dados:
        png_228 = l228.gerar_label_passaporte_png(consulado, cliente_dados)
        resposta["label_228"] = _b64(png_228)
        resposta["label_228_pdf"] = _b64(l228.label_passaporte_pdf(png_228))
    return resposta


class Rastreio(BaseModel):
    rastreio: str


@app.post("/api/reembolso/consultar")
def consultar_reembolso(dados: Rastreio, sessao: dict = Depends(exigir_emissao)):
    r = foto.so_digitos(dados.rastreio)
    if not r:
        raise HTTPException(400, "Digite o rastreio da etiqueta.")
    try:
        c = emi.consultar_reembolso(r)
    except Exception as e:
        print(f"❌ Consulta de reembolso: {type(e).__name__}", flush=True)
        raise HTTPException(502, _sem_marca(str(e)) if isinstance(e, RuntimeError) else f"Falha ao consultar a compra ({type(e).__name__}).")
    c.pop("transacao", None)  # a tela não precisa do ID da compra
    if c.get("bloqueio"):
        c["bloqueio"] = _sem_marca(c["bloqueio"])
    return c


@app.post("/api/reembolso/confirmar")
def confirmar_reembolso(dados: Rastreio, sessao: dict = Depends(exigir_emissao)):
    r = foto.so_digitos(dados.rastreio)
    with _trava_compra:
        try:
            c = emi.consultar_reembolso(r)  # consulta de novo: nunca confia no que veio da tela
            if c.get("bloqueio"):
                raise HTTPException(409, _sem_marca(c["bloqueio"]))
            status = emi.pedir_reembolso(c["transacao"])
        except HTTPException:
            raise
        except Exception as e:
            print(f"❌ Reembolso: {type(e).__name__}", flush=True)
            raise HTTPException(502, _sem_marca(str(e)) if isinstance(e, RuntimeError) else f"Falha ao pedir o reembolso ({type(e).__name__}).")
        if status == "ERROR":
            raise HTTPException(409, "O reembolso foi recusado (etiqueta usada ou já reembolsada).")

        # Pedido aceito: tira do painel (o tracker não monitora mais) e lança o negativo na auditoria
        df = _planilha(fresca=True)
        linha = {}
        if not df.empty:
            col_r = foto._coluna(df, "rastreio", "tracking")
            achadas = df[df[col_r].astype(str).str.replace(r"\D", "", regex=True) == c["rastreio"]] if col_r else df.iloc[0:0]
            if not achadas.empty:
                linha = {
                    "pedido": achadas.iloc[0][foto._coluna(df, "id", "pedido", "bitrix")],
                    "nome": achadas.iloc[0][foto._coluna(df, "nome")],
                    "tipo": achadas.iloc[0][foto._coluna(df, "tipo")],
                }
        pedido, _, tipo = c["referencia"].partition(" ")  # referência = "<pedido> <tipo>"
        nao_apagados = sheets.deletar_envios_sheets([c["rastreio"]])
        auditoria_ok = sheets.registrar_reembolso_sheets({
            "num_pedido": linha.get("pedido") or pedido,
            "nome": linha.get("nome", ""),
            "tracking_code": emi.LINK_USPS + c["rastreio"],
            "tipo_envio": f"REEMBOLSO {linha.get('tipo') or tipo} ({status})",
            "custo": -c["valor"],
        })
        _planilha_mudou()
    return {"status": status, "valor": c["valor"], "nao_apagado": bool(nao_apagados), "auditoria_ok": auditoria_ok}


# ==============================================================================
# RASTREIO ANTIGO + LABEL 228
# ==============================================================================
class Antigo(BaseModel):
    tipo: str
    pedido: str
    nome: str
    rastreio: str
    rastreio_volta: str = ""
    data: str  # AAAA-MM-DD


@app.post("/api/antigo")
def cadastrar_antigo(dados: Antigo, sessao: dict = Depends(exigir_login)):
    par = PARES_ANTIGO.get(dados.tipo)
    if dados.tipo not in ("IDA", "RETORNO") and not par:
        raise HTTPException(400, "Tipo de envio inválido.")
    pedido, nome = dados.pedido.strip(), dados.nome.strip()
    ida, volta = dados.rastreio.strip(), dados.rastreio_volta.strip()
    if not pedido or not nome or not ida or (par and not volta) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", dados.data):
        raise HTTPException(400, "Preencha os campos obrigatórios (*).")
    if par and ida == volta:
        raise HTTPException(400, "O rastreio da ida e o da volta não podem ser iguais.")

    envios = [(ida, par[0]), (volta, par[1])] if par else [(ida, dados.tipo)]
    resultados = []
    for codigo, tipo in envios:
        ok = sheets.registrar_envio_sheets({
            "num_pedido": pedido, "nome": nome, "tracking_code": codigo,
            "tipo_envio": tipo, "data_criacao": f"{dados.data} 00:00",
        })
        resultados.append({"tipo": tipo, "ok": bool(ok)})
    _planilha_mudou()
    return {"resultados": resultados}


@app.post("/api/label228")
async def gerar_label_228(consulado: str = Form(...), texto: str = Form(""), arquivo: Optional[UploadFile] = File(None),
                          sessao: dict = Depends(exigir_login)):
    if consulado not in l228.ENDERECOS_CONSULADOS:
        raise HTTPException(400, "Escolha o consulado.")
    dados, mime = await _ler_arquivo(arquivo)
    texto = texto.strip()[:1000]
    if not dados and not texto:
        raise HTTPException(400, "Envie um comprovante (ou a Driver's License) ou cole o endereço.")
    _sessao_atual.set(sessao.get("sid", ""))
    try:
        cliente = await _em_thread(l228.extrair_endereco, texto, dados, mime)
    except Exception as e:
        raise _erro_ia(e)
    faltando = [c for c in l228.CAMPOS_OBRIGATORIOS if not cliente[c]]
    if faltando:
        raise HTTPException(422, f"A IA não encontrou: {', '.join(faltando)}. Cole o nome e o endereço completos no campo de texto.")
    png = await _em_thread(l228.gerar_label_passaporte_png, consulado, cliente)
    return {"png": _b64(png), "pdf": _b64(l228.label_passaporte_pdf(png)),
            "arquivo": "Label_Passaporte_" + "_".join(cliente["nome"].split()) + ".pdf",
            "cliente": cliente, "leituras": _leituras()}


# ==============================================================================
# FOTO DOS SELOS
# ==============================================================================
@app.post("/api/fotos/ler")
async def ler_fotos(fotos: List[UploadFile] = File(...), sessao: dict = Depends(exigir_login)):
    if len(fotos) > MAX_FOTOS_POR_LEITURA:
        raise HTTPException(400, f"Envie no máximo {MAX_FOTOS_POR_LEITURA} fotos por vez.")
    _sessao_atual.set(sessao.get("sid", ""))
    lidas, erros = [], []
    for f in fotos:
        dados = await f.read()
        if len(dados) > foto.TAMANHO_MAX_FOTO:
            erros.append(f"{f.filename}: foto maior que 15 MB.")
            continue
        try:
            lidas += await _em_thread(foto.ler_etiquetas, dados, f.content_type or "image/jpeg")
        except Exception as e:
            erros.append(f"{f.filename}: {_erro_ia(e).detail}")
            if isinstance(e, RuntimeError) and "Limite" in str(e):
                break
    return {"lidas": lidas, "erros": erros, "leituras": _leituras()}


class LinhaFoto(BaseModel):
    pedido: str = ""
    rastreio: str = ""
    salvar: bool = True


class LoteFoto(BaseModel):
    linhas: List[LinhaFoto]
    permitir_suspeitos: bool = False


def _conferencia(linhas: List[LinhaFoto], df):
    """O mesmo montar_conferencia da aba de foto do Streamlit."""
    ja_cadastrados = foto.rastreios_da_planilha(df)
    marcadas = [(foto.so_digitos(l.pedido), foto.so_digitos(l.rastreio)) for l in linhas if l.salvar]
    todos = [r for _, r in marcadas]
    repetidos = {r for r in todos if todos.count(r) > 1}
    conferencia = []
    for pedido, rastreio in marcadas:
        nome = foto.buscar_nome(pedido, df)
        nivel, motivo = foto.avaliar_linha(pedido, rastreio, nome, ja_cadastrados, repetidos)
        conferencia.append({"pedido": pedido, "nome": nome, "rastreio": rastreio, "nivel": nivel, "situacao": motivo})
    return conferencia


@app.post("/api/fotos/conferir")
def conferir_fotos(dados: LoteFoto, sessao: dict = Depends(exigir_login)):
    return {"conferencia": _conferencia(dados.linhas[:200], _planilha())}


@app.post("/api/fotos/salvar")
def salvar_fotos(dados: LoteFoto, sessao: dict = Depends(exigir_login)):
    aceitos = {"ok", "suspeito"} if dados.permitir_suspeitos else {"ok"}
    gravados, falhas = [], []
    # Relê a planilha: um duplo clique ou nova tentativa não duplica linhas
    for c in _conferencia(dados.linhas[:200], _planilha(fresca=True)):
        if c["nivel"] not in aceitos:
            continue
        ok = sheets.registrar_envio_sheets({
            "num_pedido": c["pedido"], "nome": c["nome"],
            "tracking_code": foto.LINK_USPS + c["rastreio"], "tipo_envio": foto.TIPO_ENVIO_FOTO,
        })
        (gravados if ok else falhas).append(c["pedido"])
        time.sleep(1)  # cota de escrita do Google Sheets
    _planilha_mudou()
    return {"gravados": gravados, "falhas": falhas}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8080")),
                proxy_headers=True, forwarded_allow_ips="*")
