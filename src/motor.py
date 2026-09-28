"""Catálogo de consultas e execução sobre CSV ou Parquet."""

from __future__ import annotations

import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import duckdb

RAIZ = Path(__file__).resolve().parent.parent
PASTA_CONSULTAS = RAIZ / "consultas"


@dataclass(frozen=True)
class Consulta:
    nome: str
    titulo: str
    resumo: str
    sql: str


def _sem_acento(texto: str) -> str:
    """Remove acentos para efeito de comparação.

    O cabeçalho das consultas e escrito em portugues corrente, com acento
    (`-- título:`, `-- resumo:`). Comparar sem acento tira a dependência de
    alguém ter digitado exatamente do mesmo jeito.
    """
    return "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    ).lower()


def _ler_metadado(linhas: list[str], chave: str) -> str:
    """Le um campo do cabeçalho do arquivo .sql.

    O formato e um comentário simples no topo (-- título: ...). Manter a
    descrição junto da consulta evita o problema clássico de um catálogo
    separado que ninguém lembra de atualizar.
    """
    alvo = _sem_acento(f"-- {chave}:")
    for linha in linhas:
        if _sem_acento(linha.strip()).startswith(alvo):
            return linha.split(":", 1)[1].strip()
        if not linha.strip().startswith("--") and linha.strip():
            break
    return ""


def carregar_catalogo() -> dict[str, Consulta]:
    catalogo: dict[str, Consulta] = {}

    for arquivo in sorted(PASTA_CONSULTAS.glob("*.sql")):
        texto = arquivo.read_text(encoding="utf-8")
        linhas = texto.splitlines()
        catalogo[arquivo.stem] = Consulta(
            nome=arquivo.stem,
            titulo=_ler_metadado(linhas, "titulo") or arquivo.stem,
            resumo=_ler_metadado(linhas, "resumo"),
            sql=texto,
        )

    if not catalogo:
        raise FileNotFoundError(f"Nenhuma consulta encontrada em {PASTA_CONSULTAS}")

    return catalogo


def expressao_fonte(caminho: Path) -> str:
    """Monta o trecho SQL que representa a origem dos dados.

    E o único ponto do projeto que sabe se o dado está em CSV ou Parquet.
    As consultas usam o marcador {fonte} e não precisam mudar quando o
    formato muda -- que é justamente o que permite compara-los.
    """
    if caminho.is_dir():
        # hive_partitioning faz o DuckDB entender as pastas ano=/mes= como
        # colunas, e com isso pular arquivos que não atendem ao filtro.
        alvo = (caminho / "**" / "*.parquet").as_posix()
        return f"read_parquet('{alvo}', hive_partitioning = true)"

    if caminho.suffix.lower() == ".parquet":
        return f"read_parquet('{caminho.as_posix()}')"

    if caminho.suffix.lower() in {".csv", ".gz"}:
        return f"read_csv('{caminho.as_posix()}', header = true, auto_detect = true)"

    raise ValueError(
        f"Não sei ler '{caminho}'. Esperado um .csv, um .parquet ou uma pasta particionada."
    )


@dataclass
class Execucao:
    consulta: Consulta
    colunas: list[str]
    linhas: list[tuple]
    segundos: float
    fonte: str


def executar(
    consulta: Consulta, fonte: Path, limite_linhas: int | None = None
) -> Execucao:
    sql = consulta.sql.format(fonte=expressao_fonte(fonte))

    conexao = duckdb.connect()
    inicio = time.perf_counter()
    resultado = conexao.execute(sql)
    colunas = [d[0] for d in resultado.description]
    linhas = resultado.fetchall()
    decorrido = time.perf_counter() - inicio
    conexao.close()

    if limite_linhas:
        linhas = linhas[:limite_linhas]

    return Execucao(
        consulta=consulta,
        colunas=colunas,
        linhas=linhas,
        segundos=decorrido,
        fonte=str(fonte),
    )


def exportar(consulta: Consulta, fonte: Path, destino: Path) -> Path:
    """Grava o resultado da consulta em Parquet ou CSV.

    A escrita acontece dentro do DuckDB: o resultado não passa pelo Python,
    o que evita carregar em memória um resultado grande só para escreve-lo.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    sql = consulta.sql.format(fonte=expressao_fonte(fonte)).rstrip().rstrip(";")

    sufixo = destino.suffix.lower()
    if sufixo == ".parquet":
        opcoes = "(FORMAT PARQUET, COMPRESSION 'zstd')"
    elif sufixo == ".csv":
        opcoes = "(FORMAT CSV, HEADER)"
    else:
        raise ValueError(f"Formato de saída não suportado: '{sufixo}'. Use .parquet ou .csv.")

    conexao = duckdb.connect()
    conexao.execute(f"COPY ({sql}) TO '{destino.as_posix()}' {opcoes}")
    conexao.close()

    return destino
