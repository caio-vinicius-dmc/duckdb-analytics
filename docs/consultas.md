# As consultas do catálogo

Cada consulta foi escolhida por exercitar um recurso diferente de SQL
analítico. Este arquivo explica o recurso e por que ele é a escolha certa
para aquele problema.

## resumo_mensal -- `LAG` para variação período a período

```sql
round(
    100.0 * (receita - lag(receita) OVER (ORDER BY mes))
          / nullif(lag(receita) OVER (ORDER BY mes), 0),
    2
) AS variacao_pct
```

`LAG` olha a linha anterior da janela ordenada por mês. A alternativa
clássica seria juntar a tabela com ela mesma deslocada em um mês, o que
custa uma passada a mais nos dados e ainda obriga a tratar o mês sem
antecessor.

O `nullif` no denominador evita divisão por zero. Sem ele, um mês com
receita zero derruba a consulta inteira.

## ranking_regioes -- janela vazia para calcular participação

```sql
100.0 * sum(valor_pedido + taxa_entrega)
      / sum(sum(valor_pedido + taxa_entrega)) OVER ()
```

O `OVER ()` sem `PARTITION BY` faz a janela enxergar o resultado inteiro da
agregação. Com isso dá para dividir o valor de cada grupo pelo total geral
sem uma segunda consulta e sem subconsulta correlacionada.

Repare no `sum(sum(...))`: o de dentro é a agregação do `GROUP BY`, o de
fora e a janela somando os resultados já agregados. É estranho de ler na
primeira vez, mas é a forma canônica.

## curva_horaria -- média móvel com `ROWS BETWEEN`

```sql
avg(entregas) OVER (ORDER BY hora ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING)
```

Média de três horas centrada na hora atual. `ROWS` conta linhas, diferente
de `RANGE`, que conta valores -- a distinção importa quando há horas sem
nenhuma entrega, porque `RANGE` continuaria olhando a mesma janela de
tempo e `ROWS` pularia para a hora seguinte que existe.

Nas pontas a janela fica incompleta (as 00h só existe a hora seguinte), e o
`avg` simplesmente calcula sobre o que existe. Esse é o comportamento
desejado aqui.

## desempenho_entregadores -- `HAVING` e `QUALIFY` lado a lado

```sql
GROUP BY entregador_id
HAVING count(*) >= 200
QUALIFY rank() OVER (ORDER BY avg(duracao_min) / avg(distancia_km)) <= 15
```

As duas clausulas filtram depois de agregar, mas em momentos diferentes:

- `HAVING` corta pelo resultado da **agregação**. Aqui ele tira quem tem
  pouco volume, porque um entregador com três corridas rápidas apareceria
  no topo do ranking sem merecer.
- `QUALIFY` corta pelo resultado da **função de janela**. O `rank` só pode
  ser calculado depois que todos os grupos existem, então ele não caberia
  nem no `WHERE` nem no `HAVING`.

Sem `QUALIFY` seria preciso envolver tudo em uma subconsulta só para poder
filtrar o rank. O DuckDB, o Snowflake e o BigQuery suportam a clausula; o
PostgreSQL ainda não, e lá a subconsulta continua sendo o caminho.

A métrica de ordenação e `min_por_km`, não a duração média. Ordenar por
duração premiaria quem só pega corrida curta.

## anomalias_duracao -- percentil por grupo e junção com o próprio limite

```sql
WITH limites AS (
    SELECT regiao, categoria, quantile_cont(duracao_min, 0.99) AS limite_p99
    FROM {fonte} GROUP BY regiao, categoria
)
SELECT ... FROM {fonte} e
JOIN limites l ON l.regiao = e.regiao AND l.categoria = e.categoria
WHERE e.duracao_min > l.limite_p99
```

O limite e calculado **por grupo**, não para a base inteira. Uma entrega de
70 minutos é normal no Interior e absurda no Centro; um corte único
acusaria o Interior inteiro e não veria nada no Centro.

`quantile_cont` interpola entre os dois valores vizinhos, diferente de
`quantile_disc`, que devolve um valor que existe na base. Para limite de
alerta a versão continua costuma ser preferível.

A consulta lê a fonte duas vezes -- uma para o CTE, outra para a junção.
Em um dado muito maior valeria materializar o CTE ou usar uma função de
janela com `PARTITION BY regiao, categoria`, evitando a segunda leitura.

## Sobre o marcador `{fonte}`

Todas as consultas referenciam `{fonte}` em vez de um caminho fixo. Na
execução ele vira `read_csv('...')` ou `read_parquet('...', hive_partitioning = true)`,
conforme o que foi pedido.

Isso existe por um motivo específico: a comparação entre formatos só tem
valor se o SQL for rigorosamente o mesmo nos dois lados. Duas versões do
arquivo, uma para CSV e outra para Parquet, virariam duas consultas
diferentes na primeira vez que alguém mexesse em uma delas.
