-- título: Faturamento mensal com variação
-- resumo: Receita, volume e ticket médio por mês, com a variação contra o mês anterior.

WITH por_mes AS (
    SELECT
        date_trunc('month', coletado_em)        AS mes,
        count(*)                                AS entregas,
        sum(valor_pedido + taxa_entrega)        AS receita,
        avg(valor_pedido + taxa_entrega)        AS ticket_medio
    FROM {fonte}
    GROUP BY 1
)
SELECT
    strftime(mes, '%Y-%m')                      AS mes,
    entregas,
    round(receita, 2)                           AS receita,
    round(ticket_medio, 2)                      AS ticket_medio,
    -- LAG olha a linha anterior da janela ordenada por mês. É a forma
    -- barata de calcular variação sem fazer a tabela se juntar com ela mesma.
    round(
        100.0 * (receita - lag(receita) OVER (ORDER BY mes))
              / nullif(lag(receita) OVER (ORDER BY mes), 0),
        2
    )                                           AS variacao_pct
FROM por_mes
ORDER BY mes;
