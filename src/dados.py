"""Geração da massa e conversão para Parquet.

Tudo passa pelo DuckDB, inclusive a escrita dos arquivos. Gerar alguns
milhões de linhas em Python levaria minutos; em SQL, com generate_series,
leva segundos e o dado nunca precisa existir em memória do lado do Python.

A massa não é uniforme de propósito. Uma base onde toda região vende igual
e todo horário tem o mesmo volume deixa as consultas analíticas sem nada
para encontrar -- o ranking fica com todo mundo em 4,1% e a curva horária
vira uma linha reta.
"""

from __future__ import annotations

import time
from pathlib import Path

import duckdb

# As faixas são acumuladas: sorteia-se um número entre 0 e 1 e escolhe-se a
# primeira faixa que o contem. Mudar os pesos aqui muda o formato de todos
# os relatórios, o que é útil para testar as consultas contra outra forma.
PESOS_REGIAO = [
    (0.22, "Zona Sul", 1.00),
    (0.40, "Zona Norte", 1.05),
    (0.56, "Zona Leste", 1.12),
    (0.70, "Zona Oeste", 0.98),
    (0.82, "Centro", 0.88),
    (0.94, "Regiao Metropolitana", 1.35),
    (1.01, "Interior", 1.60),
]

PESOS_CATEGORIA = [
    (0.46, "Restaurante", 62.0, 38.0),
    (0.68, "Mercado", 145.0, 90.0),
    (0.82, "Farmacia", 74.0, 52.0),
    (0.94, "Conveniencia", 41.0, 26.0),
    (1.01, "Pet", 118.0, 70.0),
]


def _caso_regiao(campo: str, indice: int) -> str:
    """Monta o CASE WHEN que traduz o sorteio em região ou no fator dela."""
    partes = []
    for limite, nome, fator in PESOS_REGIAO[:-1]:
        valor = f"'{nome}'" if indice == 0 else str(fator)
        partes.append(f"WHEN {campo} < {limite} THEN {valor}")
    _, nome, fator = PESOS_REGIAO[-1]
    padrao = f"'{nome}'" if indice == 0 else str(fator)
    return "CASE " + " ".join(partes) + f" ELSE {padrao} END"


def _caso_categoria(campo: str, indice: int) -> str:
    partes = []
    for limite, nome, base, amplitude in PESOS_CATEGORIA[:-1]:
        valor = [f"'{nome}'", str(base), str(amplitude)][indice]
        partes.append(f"WHEN {campo} < {limite} THEN {valor}")
    _, nome, base, amplitude = PESOS_CATEGORIA[-1]
    padrao = [f"'{nome}'", str(base), str(amplitude)][indice]
    return "CASE " + " ".join(partes) + f" ELSE {padrao} END"


# Horario de pico: almoco e jantar concentram mais da metade das entregas.
HORA_SQL = """
CASE
    WHEN r_hora < 0.22 THEN 11 + CAST(random() * 2 AS INTEGER)
    WHEN r_hora < 0.52 THEN 18 + CAST(random() * 3 AS INTEGER)
    WHEN r_hora < 0.64 THEN 14 + CAST(random() * 3 AS INTEGER)
    WHEN r_hora < 0.80 THEN 21 + CAST(random() * 2 AS INTEGER)
    WHEN r_hora < 0.95 THEN 7  + CAST(random() * 3 AS INTEGER)
    ELSE                      CAST(random() * 6 AS INTEGER)
END
"""

CONSULTA_GERACAO = """
WITH sorteios AS (
    SELECT
        g,
        random() AS r_regiao,
        random() AS r_cat,
        random() AS r_hora,
        random() AS r_dia,
        random() AS r_dist,
        random() AS r_ruido,
        random() AS r_valor,
        random() AS r_taxa,
        random() AS r_aval,
        -- Sorteios próprios para as chaves. Reaproveitar o mesmo random()
        -- em duas colunas criaria uma correlação inexistente: o entregador
        -- de id baixo apareceria sempre com os pedidos mais baratos.
        random() AS r_entregador,
        random() AS r_cliente
    FROM generate_series(1, {linhas}) AS t(g)
),
bruto AS (
    SELECT
        g                                   AS id_entrega,
        {caso_regiao_nome}                  AS regiao,
        {caso_regiao_fator}                 AS fator_regiao,
        {caso_cat_nome}                     AS categoria,
        {caso_cat_base}                     AS valor_base,
        {caso_cat_amplitude}                AS valor_amplitude,
        -- O expoente enviesa o sorteio para os dias mais recentes e cria
        -- uma tendência de crescimento. Com 0.8 o último mês fica cerca de
        -- duas vezes maior que o primeiro; com 0.5 o crescimento vira uma
        -- rampa irreal de mais de dez vezes.
        CAST(729 * pow(r_dia, 0.8) AS INTEGER) AS dia_offset,
        {hora}                              AS hora,
        round((r_dist * r_dist * 23 + 0.5)::DECIMAL(6,2), 2) AS distancia_km,
        r_ruido, r_valor, r_taxa, r_aval, r_entregador, r_cliente
    FROM sorteios
)
SELECT
    id_entrega,
    TIMESTAMP '2024-01-01 00:00:00'
        + INTERVAL (dia_offset) DAY
        + INTERVAL (hora) HOUR
        + INTERVAL (CAST(r_ruido * 3599 AS INTEGER)) SECOND      AS coletado_em,
    1 + CAST(r_entregador * 4999 AS INTEGER)                     AS entregador_id,
    1 + CAST(r_cliente * 199999 AS INTEGER)                      AS cliente_id,
    regiao,
    categoria,
    distancia_km,
    -- duração = preparo + deslocamento, ponderado pela região, mais ruído
    duracao_min,
    round((valor_base + r_valor * valor_amplitude)::DECIMAL(8,2), 2) AS valor_pedido,
    round((4.5 + distancia_km * 0.62 + r_taxa * 2.5)::DECIMAL(6,2), 2) AS taxa_entrega,
    -- avaliação cai conforme a entrega demora: sem essa correlação a
    -- consulta de desempenho não encontraria nada
    CASE
        WHEN r_aval < 0.06 THEN NULL
        WHEN duracao_min > 70 THEN 1 + CAST(r_aval * 2 AS INTEGER)
        WHEN duracao_min > 45 THEN 3 + CAST(r_aval * 1 AS INTEGER)
        ELSE                        4 + CAST(r_aval * 1 AS INTEGER)
    END                                                          AS avaliacao
FROM (
    SELECT *,
           CAST(
               (9 + r_ruido * 7 + distancia_km * 2.1)
               * fator_regiao
               -- nos picos de almoco e jantar tudo demora mais: transito,
               -- fila na cozinha e entregador ocupado
               * CASE WHEN hora BETWEEN 11 AND 13 OR hora BETWEEN 18 AND 21
                      THEN 1.28 ELSE 1.0 END
               AS INTEGER
           ) AS duracao_min
    FROM bruto
)
"""


def gerar_csv(destino: Path, linhas: int, semente: float = 0.42) -> tuple[Path, float]:
    """Cria o CSV bruto de entregas.

    O setseed deixa a massa reprodutível: rodar duas vezes gera exatamente
    o mesmo arquivo, o que importa quando os números do README precisam
    bater com o que a pessoa ve na própria máquina.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)

    consulta = CONSULTA_GERACAO.format(
        linhas=int(linhas),
        caso_regiao_nome=_caso_regiao("r_regiao", 0),
        caso_regiao_fator=_caso_regiao("r_regiao", 1),
        caso_cat_nome=_caso_categoria("r_cat", 0),
        caso_cat_base=_caso_categoria("r_cat", 1),
        caso_cat_amplitude=_caso_categoria("r_cat", 2),
        hora=HORA_SQL.strip(),
    )

    inicio = time.perf_counter()
    conexao = duckdb.connect()
    conexao.execute(f"SELECT setseed({semente})")
    conexao.execute(
        f"COPY ({consulta}) TO '{destino.as_posix()}' "
        "(FORMAT CSV, HEADER, DELIMITER ',')"
    )
    conexao.close()

    return destino, time.perf_counter() - inicio


def converter_para_parquet(
    origem: Path, destino: Path, compressao: str = "zstd"
) -> tuple[Path, float]:
    """Converte o CSV em Parquet particionado por ano e mês.

    O particionamento por data é o que permite ao DuckDB pular arquivos
    inteiros quando a consulta filtra por período. Sem ele o Parquet ainda
    ganha do CSV, mas por causa da leitura por coluna, não do recorte.
    """
    if not origem.exists():
        raise FileNotFoundError(
            f"CSV não encontrado em {origem}. Rode 'python -m src.cli gerar' antes."
        )

    destino.mkdir(parents=True, exist_ok=True)
    inicio = time.perf_counter()

    conexao = duckdb.connect()
    conexao.execute(
        f"""
        COPY (
            SELECT *,
                   year(coletado_em)  AS ano,
                   month(coletado_em) AS mes
              FROM read_csv('{origem.as_posix()}', header = true, auto_detect = true)
        )
        TO '{destino.as_posix()}'
        (FORMAT PARQUET, PARTITION_BY (ano, mes),
         COMPRESSION '{compressao}', OVERWRITE_OR_IGNORE true)
        """
    )
    conexao.close()

    return destino, time.perf_counter() - inicio


def tamanho_em_mb(caminho: Path) -> float:
    if caminho.is_file():
        return caminho.stat().st_size / 1024 / 1024
    total = sum(p.stat().st_size for p in caminho.rglob("*") if p.is_file())
    return total / 1024 / 1024


def contar_arquivos(caminho: Path) -> int:
    if caminho.is_file():
        return 1
    return sum(1 for p in caminho.rglob("*.parquet"))
