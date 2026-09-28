-- título: Desempenho dos entregadores
-- resumo: Mediana e p90 de duração por entregador, entre os que tem volume relevante.

SELECT
    entregador_id,
    count(*)                                                  AS entregas,
    round(median(duracao_min), 1)                             AS mediana_min,
    round(quantile_cont(duracao_min, 0.90), 1)                AS p90_min,
    round(avg(distancia_km), 2)                               AS distancia_media_km,
    round(avg(duracao_min) / nullif(avg(distancia_km), 0), 2) AS min_por_km,
    round(avg(avaliacao), 2)                                  AS avaliacao_media
FROM {fonte}
GROUP BY entregador_id
-- HAVING corta pelo resultado da agregação. Entregador com pouco volume
-- distorce o ranking: com três entregas rápidas qualquer um chega ao topo.
HAVING count(*) >= 200
-- QUALIFY faz o mesmo papel, mas para função de janela. A diferença e que
-- o rank só pode ser calculado depois que todos os grupos existem, então
-- ele não caberia no HAVING nem numa clausula WHERE.
QUALIFY rank() OVER (
    ORDER BY avg(duracao_min) / nullif(avg(distancia_km), 0)
) <= 15
ORDER BY min_por_km;
