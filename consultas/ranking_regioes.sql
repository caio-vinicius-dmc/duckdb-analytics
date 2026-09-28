-- título: Ranking de regiões
-- resumo: Receita por região e categoria, com a participação de cada uma no total.

SELECT
    regiao,
    categoria,
    count(*)                                    AS entregas,
    round(sum(valor_pedido + taxa_entrega), 2)  AS receita,
    -- A janela vazia (sem PARTITION BY) enxerga o resultado inteiro,
    -- então dá para dividir pelo total sem uma segunda passada nos dados.
    round(
        100.0 * sum(valor_pedido + taxa_entrega)
              / sum(sum(valor_pedido + taxa_entrega)) OVER (),
        2
    )                                           AS participacao_pct,
    round(avg(duracao_min), 1)                  AS duracao_media_min
FROM {fonte}
GROUP BY regiao, categoria
ORDER BY receita DESC
LIMIT 20;
