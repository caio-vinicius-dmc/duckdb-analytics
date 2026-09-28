-- título: Curva horária de demanda
-- resumo: Entregas por hora do dia, com média móvel de três horas para suavizar.

WITH por_hora AS (
    SELECT
        hour(coletado_em)          AS hora,
        count(*)                   AS entregas,
        round(avg(duracao_min), 1) AS duracao_media
    FROM {fonte}
    GROUP BY 1
)
SELECT
    printf('%02dh', hora)          AS hora,
    entregas,
    duracao_media,
    round(
        avg(entregas) OVER (ORDER BY hora ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING)
    )                              AS media_movel_3h
FROM por_hora
ORDER BY hora;
