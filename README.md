# duckdb-analytics

Análise de milhões de linhas direto de arquivos, sem servidor de banco e
sem cluster.

## Do que se trata, em linguagem simples

Quando o arquivo é pequeno, qualquer ferramenta serve. Quando passa de
alguns milhões de linhas, o Excel desiste e a conversa costuma pular
direto para "precisamos de um cluster".

Entre os dois extremos existe um espaço grande, e é dele que este projeto
trata. Duas perguntas práticas:

**1. Quanto muda guardar o arquivo em outro formato?**

Um CSV guarda os dados linha por linha, como uma planilha. O **Parquet**
guarda coluna por coluna. Se a sua consulta só precisa de três das quinze
colunas, o Parquet lê só aquelas três — o CSV precisa ler tudo para
descobrir onde elas estão.

**2. Nessa escala, a ferramenta ainda importa?**

DuckDB, Polars e pandas são três formas de analisar dados em Python. A
mesma soma nos três, sobre o mesmo arquivo, mostra o quanto a escolha
pesa.

O projeto monta uma base de 2 milhões de entregas, converte, mede e
responde as duas.

## O que você vai ver

### Formato: Parquet contra CSV

```bash
python -m src.cli comparar --consulta ranking_regioes
```

| Formato | Tempo | Espaço em disco |
|---------|-------|-----------------|
| Parquet | 0,043s | 38 MB |
| CSV | 0,264s | 157 MB |

Seis vezes mais rápido e um quarto do espaço. O ganho vem de duas coisas:
o Parquet lê só as colunas pedidas, e os arquivos são separados por ano e
mês — então uma consulta com filtro de período pula pastas inteiras sem
abrir.

### Ferramenta: DuckDB, Polars e pandas

```bash
python -m src.cli motores
```

| Ferramenta | Tempo |
|------------|-------|
| Polars | 0,030s |
| DuckDB | 0,032s |
| pandas | 0,157s |

A mesma soma nos três, sobre os mesmos arquivos. Polars e DuckDB ficam
praticamente empatados. O pandas perde porque carrega os dados na memória
antes de somar, mesmo lendo só as três colunas necessárias.

**A conclusão prática não é "use X".** É que, nessa escala, a escolha do
**formato do arquivo** pesa mais do que a escolha da biblioteca.

## O que você precisa ter instalado

- **Python 3.11 ou mais novo** —
  [python.org](https://www.python.org/downloads/), marcando "Add Python to
  PATH".

Só isso. Não precisa de Docker nem de banco de dados — é a graça do
DuckDB.

## Como rodar

**1. Prepare o ambiente.**

```bash
python -m venv .venv
.venv/Scripts/activate
pip install -r requirements.txt
```

No Linux ou macOS: `source .venv/bin/activate`.

**2. Gere os dados.** Cria um CSV de 157 MB com 2 milhões de entregas, em
cerca de 2 segundos.

```bash
python -m src.cli gerar
```

**3. Converta para Parquet.** Um segundo.

```bash
python -m src.cli converter
```

**4. Veja as consultas disponíveis e rode uma.**

```bash
python -m src.cli listar
python -m src.cli consultar resumo_mensal
```

A partir daqui, os comandos usam o Parquet automaticamente.

Se a sua máquina for modesta, `python -m src.cli gerar --linhas 500000`
mostra os mesmos efeitos com um terço do espaço.

## As cinco consultas

```
resumo_mensal              receita, volume e ticket médio por mês, com a variação
ranking_regioes            receita por região e categoria, com participação no total
curva_horaria              entregas por hora, com média móvel de três horas
desempenho_entregadores    mediana e p90 de duração, só de quem tem volume
anomalias_duracao          entregas acima do p99 da própria região e categoria
```

A curva horária mostra bem o formato dos dados gerados:

```
11h   110.061 entregas   41,3 min de duração média
12h   219.251            41,4
13h   110.165            41,3
14h    39.932            32,5     ← fora do pico, 9 minutos mais rápido
19h   199.839            41,4
20h   199.755            41,3
```

Almoço e jantar concentram a demanda, e no pico tudo demora mais —
trânsito, fila na cozinha, entregador ocupado.

Para levar o resultado para outro lugar:

```bash
python -m src.cli exportar resumo_mensal --destino saida/resumo.parquet
python -m src.cli exportar ranking_regioes --destino saida/ranking.csv
```

## Como as consultas são escritas

Cada consulta é um arquivo `.sql` na pasta `consultas/`, com o título e a
descrição no próprio cabeçalho:

```sql
-- título: Faturamento mensal com variação
-- resumo: Receita, volume e ticket médio por mês, com a variação contra o mês anterior.

SELECT ... FROM {fonte} ...
```

O `{fonte}` é trocado em tempo de execução pelo endereço real do arquivo —
o CSV ou o Parquet. É isso que permite rodar exatamente a mesma consulta
nos dois formatos sem duplicar código, e é a base da comparação lá em
cima.

Para acrescentar uma consulta, basta criar o arquivo. Nenhuma linha de
Python precisa mudar.

Os recursos de SQL usados em cada uma estão explicados em
[docs/consultas.md](docs/consultas.md).

## Estrutura das pastas

```
consultas/*.sql     as consultas, com título e descrição no cabeçalho
src/dados.py        a geração dos dados e a conversão para Parquet
src/motor.py        o catálogo e a troca da fonte em tempo de execução
src/bancada.py      as duas comparações
src/cli.py          a linha de comando
dados/              tudo gerado na sua máquina, fora do controle de versão
```

## Problemas comuns

**"Nenhum dado encontrado em dados/."** Rode `python -m src.cli gerar`
primeiro.

**"Preciso do CSV e do Parquet para comparar."** O comando `comparar`
precisa dos dois. Rode `gerar` e depois `converter`.

**Falta espaço em disco.** O CSV ocupa 157 MB e o Parquet mais 38 MB.
Gere menos linhas com `--linhas 500000`, ou apague a pasta `dados/` quando
terminar.

## Limitações

- Os tempos são de uma máquina só. O que deve se repetir em outro
  ambiente é a ordem de grandeza da diferença, não o número exato.
- Dois milhões de linhas cabem confortavelmente na memória, e é justamente
  aí que o pandas ainda compete. Acima de algumas dezenas de milhões, a
  diferença deixa de ser de cinco vezes.
- A comparação entre ferramentas usa uma soma simples de propósito.
  Consultas com vários cruzamentos mudariam o resultado, provavelmente a
  favor do DuckDB.
- Mede tempo, não memória. Para a pergunta "cabe na máquina ou não?",
  memória seria a medida mais relevante.

---

## 👤 Autor

Desenvolvido por **Caio Vinícius Barbosa Barros**.

Se você tiver dúvidas, sugestões ou quiser reportar um problema, sinta-se à vontade para entrar em contato:

*   **✉️ E-mail:** [caio@dynamicmotioncentury.com.br](mailto:caio@dynamicmotioncentury.com.br)
*   **🌐 Site/Portfólio:** [www.dynamicmotioncentury.com.br](https://dynamicmotioncentury.com.br)
*   **💼 LinkedIn:** [linkedin.com/in/caio-vinicius-dmc](https://linkedin.com/in/caio-vinicius-dmc)
*   **🐙 GitHub:** [@caio-vinicius-dmc](https://github.com/caio-vinicius-dmc)

💡 *Se este projeto te ajudou, deixe uma ⭐ no repositório!*
