"""Servidor local do painel de Margem por Grupo (SISMOURA).

Consulta os bancos das lojas em modo SOMENTE LEITURA e entrega os dados
para o index.html.

  python servidor.py             -> modo local: só este computador, abre o navegador
  python servidor.py --producao  -> servidor da empresa: aceita acesso da rede, sem navegador
A porta vem de PORT no .env (padrão 3004); --porta tem prioridade.
"""
import argparse
import json
import os
import re
import socket
import sys
import threading
import time
import webbrowser
from datetime import date, datetime
from decimal import Decimal
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import mssql_python

PASTA = Path(__file__).resolve().parent
ENV = PASTA / ".env"  # credenciais e lojas; modelo em .env.example


def ler_env():
    if not ENV.exists():
        sys.exit(f"Arquivo {ENV.name} não encontrado. Copie .env.example para .env e preencha.")
    env = {}
    for linha in ENV.read_text(encoding="utf-8-sig").splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#") and "=" in linha:
            k, v = linha.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def carregar_config():
    env = ler_env()
    lojas = {}
    for k in env:
        m = re.fullmatch(r"LOJA_(\w+?)_SERVIDOR", k)
        if not m:
            continue
        p = f"LOJA_{m.group(1)}_"
        l = {"nome": env.get(p + "NOME") or m.group(1).title(), "servidor": env[k], "banco": env.get(p + "BANCO", "")}
        for campo in ("usuario", "senha"):
            if env.get(p + campo.upper()):
                l[campo] = env[p + campo.upper()]
        lojas[m.group(1).lower()] = l
    ativas = [a.strip().lower() for a in env.get("LOJAS_ATIVAS", "").split(",") if a.strip()]
    if ativas:
        lojas = {a: lojas[a] for a in ativas if a in lojas}
    return {"usuario": env.get("DB_USUARIO", ""), "senha": env.get("DB_SENHA", ""), "lojas": lojas}


def _chaves(v):
    """Valor entre chaves na string de conexão (aceita ; e } na senha)."""
    return "{" + str(v).replace("}", "}}") + "}"


def conectar(cfg, loja, timeout):
    l = cfg["lojas"][loja]
    cs = (
        f"Server={l['servidor']};Database={l['banco']};"
        f"UID={_chaves(l.get('usuario', cfg['usuario']))};PWD={_chaves(l.get('senha', cfg['senha']))};"
        "Encrypt=yes;TrustServerCertificate=yes"
    )
    return mssql_python.connect(cs, timeout=timeout, autocommit=False)

LOJAS_SEM_PRODUTOS = {"cd"}  # CD não tem cadastro de preços de venda
CACHE_SEGUNDOS = 300

SQL_PRODUTOS = """
SELECT
    p.Codigo,
    p.Nome,
    ISNULL(g.Descricao, '(sem grupo)')    AS Grupo,
    ISNULL(s.Descricao, '')               AS SubGrupo,
    CAST(p.Preco_Custo   AS float)        AS Custo,
    CAST(p.Preco_Produto AS float)        AS Venda,
    CAST(ISNULL(p.Preco_Promocao, 0) AS float) AS Promocao,
    CONVERT(char(10), p.Data_Vigencia, 23)   AS Vigencia,
    CONVERT(char(10), p.Data_Ult_Compra, 23) AS Ult_Compra,
    CAST(ISNULL(p.Quantidade, 0) AS float) AS Estoque,
    p.Unidade
FROM Produto p
LEFT JOIN Grupo_Produto g ON g.Codigo = p.Grupo
LEFT JOIN SubGrupo s      ON s.Codigo = p.SubGrupo
WHERE ISNULL(p.Inativo, 'N') <> 'S'
"""

SQL_VENDAS = """
WITH it AS (
    SELECT i.Produto,
           SUM(i.Quantidade)                                                     AS Qtde,
           SUM(i.Valor_Total - ISNULL(i.Desconto, 0) + ISNULL(i.Acrescimo, 0))   AS Faturamento,
           SUM(i.Quantidade * ISNULL(i.Valor_Custo, 0))                          AS Custo_Total,
           COUNT(DISTINCT i.Venda)                                               AS Cupons
    FROM Venda v
    JOIN Venda_Item i ON i.Venda = v.Codigo AND i.Cancelado = 'N'
    WHERE v.Cancelada = 'N' AND v.Data >= ? AND v.Data < ?
    GROUP BY i.Produto
)
SELECT
    it.Produto                              AS Codigo,
    ISNULL(p.Nome, '(produto excluído)')    AS Nome,
    ISNULL(g.Descricao, '(sem grupo)')      AS Grupo,
    ISNULL(s.Descricao, '')                 AS SubGrupo,
    CAST(it.Qtde        AS float)           AS Qtde,
    CAST(it.Faturamento AS float)           AS Faturamento,
    CAST(it.Custo_Total AS float)           AS Custo_Total,
    it.Cupons,
    CAST(ISNULL(p.Preco_Custo, 0)   AS float) AS Custo_Atual,
    CAST(ISNULL(p.Preco_Produto, 0) AS float) AS Venda_Atual,
    p.Unidade
FROM it
LEFT JOIN Produto p       ON p.Codigo = it.Produto
LEFT JOIN Grupo_Produto g ON g.Codigo = p.Grupo
LEFT JOIN SubGrupo s      ON s.Codigo = p.SubGrupo
"""

SQL_VENDAS_RESUMO = """
SELECT COUNT(*) AS Cupons, CAST(SUM(Valor_Final) AS float) AS Total,
       COUNT(DISTINCT CAST(Data AS date)) AS Dias
FROM Venda WHERE Cancelada = 'N' AND Data >= ? AND Data < ?
"""

_cache = {}
_trava = threading.Lock()


def _limpar(v):
    if isinstance(v, float):
        return round(v, 4)
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, str):
        return v.strip()
    return v


def _rodar(cur, sql, params=()):
    cur.execute(sql, *params)
    cols = [c[0] for c in cur.description]
    return cols, [[_limpar(v) for v in r] for r in cur.fetchall()]


def consultar(cfg, loja, fn):
    conn = conectar(cfg, loja, 60)
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")
        dados = fn(cur)
        cur.execute("SELECT CONVERT(char(10), GETDATE(), 23)")
        dados["hoje"] = cur.fetchone()[0]
        dados["atualizado"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        return dados
    finally:
        conn.rollback()
        conn.close()


def buscar_produtos(cur):
    cols, linhas = _rodar(cur, SQL_PRODUTOS)
    return {"colunas": cols, "linhas": linhas}


def buscar_vendas(mes):
    ano, m = map(int, mes.split("-"))
    ini = date(ano, m, 1)
    fim = date(ano + (m == 12), m % 12 + 1, 1)

    def fn(cur):
        cols, linhas = _rodar(cur, SQL_VENDAS, (ini, fim))
        rc, rl = _rodar(cur, SQL_VENDAS_RESUMO, (ini, fim))
        return {"mes": mes, "colunas": cols, "linhas": linhas, "resumo": dict(zip(rc, rl[0]))}
    return fn


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(PASTA / "web"), **kw)

    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, status=200):
        corpo = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def _cacheado(self, cfg, loja, chave, fn, forcar, rotulo):
        with _trava:
            item = _cache.get(chave)
        if forcar or not item or time.time() - item[0] > CACHE_SEGUNDOS:
            try:
                dados = consultar(cfg, loja, fn)
            except mssql_python.Error as e:
                print(f"[{loja}] ERRO: {e}", file=sys.stderr)
                return self._json({"erro": f"Não foi possível consultar {cfg['lojas'][loja]['nome']}. "
                                           "Verifique a conexão com o servidor da loja."}, 502)
            item = (time.time(), dados)
            with _trava:
                _cache[chave] = item
            print(f"[{cfg['lojas'][loja]['nome']}] {len(dados['linhas'])} {rotulo}")
        return self._json(item[1])

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/lojas":
            cfg = carregar_config()
            return self._json([{"id": k, "nome": v["nome"]} for k, v in cfg["lojas"].items()
                               if k not in LOJAS_SEM_PRODUTOS])
        if url.path in ("/api/produtos", "/api/vendas"):
            q = parse_qs(url.query)
            loja = q.get("loja", [""])[0]
            forcar = q.get("atualizar", ["0"])[0] == "1"
            cfg = carregar_config()
            if loja not in cfg["lojas"] or loja in LOJAS_SEM_PRODUTOS:
                return self._json({"erro": f"Loja '{loja}' inválida."}, 400)
            if url.path == "/api/produtos":
                return self._cacheado(cfg, loja, ("produtos", loja), buscar_produtos, forcar, "produtos carregados")
            mes = q.get("mes", [""])[0]
            if not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", mes):
                return self._json({"erro": "Mês inválido."}, 400)
            return self._cacheado(cfg, loja, ("vendas", loja, mes), buscar_vendas(mes), forcar,
                                  f"produtos vendidos em {mes}")
        return super().do_GET()


PORTA_PADRAO = 3004  # orientacoes-projetos-ia.md: Relatório de margens aplicadas
PORTA_OCUPADA = 3    # código de saída usado por servidor/iniciar.ps1 para não ficar tentando de novo


def porta_em_uso(porta):
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", porta)) == 0


def main():
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--porta", type=int)
    p.add_argument("--producao", action="store_true", help="escuta na rede (0.0.0.0) e não abre o navegador")
    p.add_argument("--sem-navegador", action="store_true")
    a = p.parse_args()
    porta = a.porta or int(os.getenv("PORT") or ler_env().get("PORT") or PORTA_PADRAO)
    if porta_em_uso(porta):
        print(f"ERRO: a porta {porta} já está em uso.", file=sys.stderr)
        sys.exit(PORTA_OCUPADA)
    host = "0.0.0.0" if a.producao else "127.0.0.1"
    srv = ThreadingHTTPServer((host, porta), Handler)
    url = f"http://{socket.gethostname() if a.producao else 'localhost'}:{porta}"
    print(f"Painel de margens rodando em {url}  (Ctrl+C para encerrar)", flush=True)
    if not (a.producao or a.sem_navegador):
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
