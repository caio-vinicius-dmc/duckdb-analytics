-- título: Entregas fora da curva
-- resumo: Entregas cuja duração passou do p99 da própria região e categoria.

WITH limites AS (
    SELECT
        regiao,
        categoria,
        quantile_cont(duracao_min, 0.99) AS limite_p99
    FROM {fonte}
    GROUP BY regiao, categoria
)
SELECT
    e.regiao,
    e.categoria,
    count(*)                                    AS entregas_fora_da_curva,
    round(avg(e.duracao_min), 1)                AS duracao_media_min,
    round(max(l.limite_p99), 1)                 AS limite_p99,
    round(avg(e.distancia_km), 2)               AS distancia_media_km
FROM {fonte} e
JOIN limites l
  ON l.regiao = e.regiao
 AND l.categoria = e.categoria
WHERE e.duracao_min > l.limite_p99
GROUP BY e.regiao, e.categoria
ORDER BY entregas_fora_da_curva DESC
LIMIT 15;
