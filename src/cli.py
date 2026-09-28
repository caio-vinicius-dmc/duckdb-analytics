"""Linha de comando.

    python -m src.cli gerar --linhas 2000000
    python -m src.cli converter
    python -m src.cli listar
    python -m src.cli consultar resumo_mensal
    python -m src.cli consultar ranking_regioes --formato csv
    python -m src.cli exportar resumo_mensal --destino saida/resumo.parquet
    python -m src.cli comparar --consulta ranking_regioes
    python -m src.cli motores
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from . import bancada, dados, motor

console = Console()

RAIZ = Path(__file__).resolve().parent.parent
CSV_PADRAO = RAIZ / "dados" / "entregas.csv"
PARQUET_PADRAO = RAIZ / "dados" / "entregas_parquet"


def _fonte_preferida(args: argparse.Namespace) -> Path:
    """Escolhe o Parquet quando ele existe; cai para o CSV se não existir.

    Assim o fluxo normal (gerar, converter, consultar) usa o formato rápido
    sem que ninguém precise lembrar de apontar o caminho.
    """
    if args.fonte:
        return Path(args.fonte)
    if PARQUET_PADRAO.exists() and any(PARQUET_PADRAO.rglob("*.parquet")):
        return PARQUET_PADRAO
    if CSV_PADRAO.exists():
        return CSV_PADRAO
    raise FileNotFoundError(
        "Nenhum dado encontrado em dados/. Rode 'python -m src.cli gerar' primeiro."
    )


def comando_gerar(args: argparse.Namespace) -> int:
    console.print(f"Gerando {args.linhas:,} entregas...".replace(",", "."))
    caminho, segundos = dados.gerar_csv(CSV_PADRAO, args.linhas)
    console.print(
        f"{caminho.name}: {dados.tamanho_em_mb(caminho):.0f} MB em {_segundos(segundos, 1)}"
    )
    console.print("Próximo passo: [bold]python -m src.cli converter[/bold]")
    return 0


def comando_converter(args: argparse.Namespace) -> int:
    console.print("Convertendo para Parquet particionado por ano e mês...")
    destino, segundos = dados.converter_para_parquet(
        CSV_PADRAO, PARQUET_PADRAO, compressao=args.compressao
    )

    mb_csv = dados.tamanho_em_mb(CSV_PADRAO)
    mb_parquet = dados.tamanho_em_mb(destino)

    tabela = Table(title=f"Conversão concluída em {_segundos(segundos, 1)}")
    tabela.add_column("Formato")
    tabela.add_column("Tamanho", justify="right")
    tabela.add_column("Arquivos", justify="right")
    tabela.add_row("CSV", f"{mb_csv:.0f} MB", "1")
    tabela.add_row(
        f"Parquet ({args.compressao})",
        f"{mb_parquet:.0f} MB",
        str(dados.contar_arquivos(destino)),
    )
    console.print(tabela)
    console.print(f"Redução de {100 * (1 - mb_parquet / mb_csv):.0f}% no espaço em disco.")
    return 0


def comando_listar(args: argparse.Namespace) -> int:
    tabela = Table(title="Consultas disponíveis")
    tabela.add_column("Nome", style="bold")
    tabela.add_column("O que traz")

    for consulta in motor.carregar_catalogo().values():
        tabela.add_row(consulta.nome, consulta.resumo or consulta.titulo)

    console.print(tabela)
    return 0


def comando_consultar(args: argparse.Namespace) -> int:
    catalogo = motor.carregar_catalogo()
    if args.nome not in catalogo:
        console.print(
            f"[red]Consulta '{args.nome}' não existe.[/red] "
            f"Disponíveis: {', '.join(catalogo)}"
        )
        return 2

    fonte = _fonte_preferida(args)
    execucao = motor.executar(catalogo[args.nome], fonte, limite_linhas=args.linhas)

    if args.formato == "csv":
        # Saída limpa, para redirecionar com > ou jogar em outro programa.
        print(",".join(execucao.colunas))
        for linha in execucao.linhas:
            print(",".join("" if v is None else str(v) for v in linha))
        return 0

    tabela = Table(
        title=f"{execucao.consulta.titulo}  ({len(execucao.linhas)} linhas em {_segundos(execucao.segundos, 2)})"
    )
    for coluna in execucao.colunas:
        tabela.add_column(coluna, justify="right" if coluna != execucao.colunas[0] else "left")
    for linha in execucao.linhas:
        tabela.add_row(*["-" if v is None else str(v) for v in linha])

    console.print(tabela)
    console.print(f"Fonte: {execucao.fonte}")
    return 0


def comando_exportar(args: argparse.Namespace) -> int:
    catalogo = motor.carregar_catalogo()
    if args.nome not in catalogo:
        console.print(f"[red]Consulta '{args.nome}' não existe.[/red]")
        return 2

    destino = motor.exportar(catalogo[args.nome], _fonte_preferida(args), Path(args.destino))
    console.print(
        f"Resultado em {destino} ({dados.tamanho_em_mb(destino):.2f} MB)"
    )
    return 0


def comando_comparar(args: argparse.Namespace) -> int:
    catalogo = motor.carregar_catalogo()
    consulta = catalogo[args.consulta]

    if not CSV_PADRAO.exists() or not PARQUET_PADRAO.exists():
        console.print(
            "[red]Preciso do CSV e do Parquet para comparar.[/red] "
            "Rode 'gerar' e depois 'converter'."
        )
        return 2

    console.print(f"Medindo '{consulta.titulo}' nos dois formatos...")
    amostras = bancada.comparar_formatos(
        consulta, CSV_PADRAO, PARQUET_PADRAO, repeticoes=args.repeticoes
    )
    _mostrar_amostras(amostras, f"Mesma consulta, formatos diferentes")
    return 0


def comando_motores(args: argparse.Namespace) -> int:
    if not PARQUET_PADRAO.exists():
        console.print("[red]Rode 'converter' antes.[/red]")
        return 2

    console.print("Medindo a mesma agregação em DuckDB, Polars e pandas...")
    amostras = bancada.comparar_motores(PARQUET_PADRAO, repeticoes=args.repeticoes)
    _mostrar_amostras(amostras, "Mesmo dado, motores diferentes")
    return 0


def _segundos(valor: float, casas: int = 3) -> str:
    """Tempo com vírgula decimal, como se escreve em português."""
    return f"{valor:.{casas}f}".replace(".", ",") + "s"


def _vezes(valor: float) -> str:
    """Quantas vezes mais lento, também com vírgula."""
    return f"{valor:.1f}".replace(".", ",") + "x"


def _mostrar_amostras(amostras: list[bancada.Amostra], titulo: str) -> None:
    if not amostras:
        console.print("[yellow]Nada a comparar.[/yellow]")
        return

    referencia = min(a.mediana for a in amostras)
    tabela = Table(title=titulo)
    tabela.add_column("Alternativa")
    tabela.add_column("Mediana", justify="right")
    tabela.add_column("Relativo", justify="right")
    tabela.add_column("Observação")

    for amostra in sorted(amostras, key=lambda a: a.mediana):
        tabela.add_row(
            amostra.rotulo,
            _segundos(amostra.mediana),
            "-" if amostra.mediana == referencia else _vezes(amostra.mediana / referencia),
            amostra.detalhe,
        )

    console.print(tabela)


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="duckdb-analytics",
        description="Análise de arquivos grandes com DuckDB, sem servidor de banco.",
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    p_gerar = sub.add_parser("gerar", help="cria o CSV bruto de entregas")
    p_gerar.add_argument("--linhas", type=int, default=2_000_000)
    p_gerar.set_defaults(funcao=comando_gerar)

    p_conv = sub.add_parser("converter", help="converte o CSV em Parquet particionado")
    p_conv.add_argument(
        "--compressao", default="zstd", choices=["zstd", "snappy", "gzip", "uncompressed"]
    )
    p_conv.set_defaults(funcao=comando_converter)

    p_listar = sub.add_parser("listar", help="mostra o catálogo de consultas")
    p_listar.set_defaults(funcao=comando_listar)

    p_cons = sub.add_parser("consultar", help="executa uma consulta do catálogo")
    p_cons.add_argument("nome")
    p_cons.add_argument("--fonte", help="caminho alternativo de dados")
    p_cons.add_argument("--linhas", type=int, help="limita as linhas exibidas")
    p_cons.add_argument("--formato", choices=["tabela", "csv"], default="tabela")
    p_cons.set_defaults(funcao=comando_consultar)

    p_exp = sub.add_parser("exportar", help="grava o resultado em Parquet ou CSV")
    p_exp.add_argument("nome")
    p_exp.add_argument("--destino", required=True)
    p_exp.add_argument("--fonte")
    p_exp.set_defaults(funcao=comando_exportar)

    p_comp = sub.add_parser("comparar", help="CSV contra Parquet na mesma consulta")
    p_comp.add_argument("--consulta", default="ranking_regioes")
    p_comp.add_argument("--repeticoes", type=int, default=3)
    p_comp.set_defaults(funcao=comando_comparar)

    p_mot = sub.add_parser("motores", help="DuckDB contra Polars e pandas")
    p_mot.add_argument("--repeticoes", type=int, default=3)
    p_mot.set_defaults(funcao=comando_motores)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    try:
        return args.funcao(args)
    except (FileNotFoundError, ValueError) as erro:
        console.print(f"[red]{erro}[/red]")
        return 2


if __name__ == "__main__":
    sys.exit(main())
