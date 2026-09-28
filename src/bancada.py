"""Bancada de medição: formato de arquivo e motor de processamento.

Duas comparações diferentes:

- `comparar_formatos` roda a mesma consulta no mesmo motor, mudando só o
  arquivo de origem. Mede o efeito do formato colunar.
- `comparar_motores` roda a mesma agregação no mesmo arquivo, mudando o
  motor. Mede o que cada ferramenta faz com o mesmo trabalho.

As duas descartam a primeira execução, que paga cache de disco frio.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass
from pathlib import Path

import duckdb

from .dados import tamanho_em_mb
from .motor import Consulta, expressao_fonte


@dataclass
class Amostra:
    rotulo: str
    tempos: list[float]
    detalhe: str = ""

    @property
    def mediana(self) -> float:
        return statistics.median(self.tempos)


def _medir(funcao, repeticoes: int) -> list[float]:
    funcao()  # aquecimento, descartado
    tempos = []
    for _ in range(repeticoes):
        inicio = time.perf_counter()
        funcao()
        tempos.append(time.perf_counter() - inicio)
    return tempos


def comparar_formatos(
    consulta: Consulta, csv: Path, parquet: Path, repeticoes: int = 3
) -> list[Amostra]:
    amostras = []

    for rotulo, caminho in (("CSV", csv), ("Parquet particionado", parquet)):
        if not caminho.exists():
            continue

        sql = consulta.sql.format(fonte=expressao_fonte(caminho))

        def rodar(sql=sql):
            conexao = duckdb.connect()
            conexao.execute(sql).fetchall()
            conexao.close()

        amostras.append(
            Amostra(
                rotulo=rotulo,
                tempos=_medir(rodar, repeticoes),
                detalhe=f"{tamanho_em_mb(caminho):.0f} MB em disco",
            )
        )

    return amostras


# Agregação usada na comparação entre motores. É de propósito simples e
# identica nos três: group by com duas métricas. Comparar consultas
# diferentes só mediria quem tem o dialeto mais expressivo.
AGREGACAO_SQL = """
SELECT regiao,
       count(*) AS entregas,
       sum(valor_pedido + taxa_entrega) AS receita
  FROM {fonte}
 GROUP BY regiao
 ORDER BY receita DESC
"""


def comparar_motores(parquet: Path, repeticoes: int = 3) -> list[Amostra]:
    amostras: list[Amostra] = []
    arquivos = (parquet / "**" / "*.parquet").as_posix()

    def com_duckdb():
        conexao = duckdb.connect()
        conexao.execute(
            AGREGACAO_SQL.format(fonte=expressao_fonte(parquet))
        ).fetchall()
        conexao.close()

    amostras.append(
        Amostra("DuckDB", _medir(com_duckdb, repeticoes), "SQL sobre os Parquet")
    )

    try:
        import polars as pl

        def com_polars():
            (
                pl.scan_parquet(arquivos)
                .group_by("regiao")
                .agg(
                    pl.len().alias("entregas"),
                    (pl.col("valor_pedido") + pl.col("taxa_entrega")).sum().alias("receita"),
                )
                .sort("receita", descending=True)
                .collect()
            )

        amostras.append(
            Amostra("Polars", _medir(com_polars, repeticoes), "scan_parquet preguiçoso")
        )
    except ImportError:
        pass

    try:
        import pandas as pd

        def com_pandas():
            quadro = pd.read_parquet(
                parquet, columns=["regiao", "valor_pedido", "taxa_entrega"]
            )
            quadro["receita"] = quadro["valor_pedido"] + quadro["taxa_entrega"]
            quadro.groupby("regiao").agg(
                entregas=("receita", "size"), receita=("receita", "sum")
            ).sort_values("receita", ascending=False)

        amostras.append(
            Amostra(
                "pandas",
                _medir(com_pandas, repeticoes),
                "lê as colunas necessárias para a memória",
            )
        )
    except ImportError:
        pass

    return amostras
