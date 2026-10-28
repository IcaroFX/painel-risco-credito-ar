# Catálogo DAX + Guia de Construção do Relatório

> Painel de Risco de Crédito, Contas a Receber (AR) e Inadimplência — Aging + Score Preditivo
>
> Tudo isto já está implementado em `PainelRiscoCredito.pbip` (modelo em TMDL, páginas geradas por `build_report.py`).
> Este documento explica cada medida e serve de guia para quem quiser reconstruir o relatório do zero.

Sumário: [0. Modelo de dados](#0-modelo-de-dados) · [1. Executivo](#1-pasta-executivo) · [2. Aging/PDD](#2-pasta-aging--pdd) · [3. Preditivo](#3-pasta-preditivo) · [4. Simulador What-If](#4-pasta-simulador-what-if) · [5. Layout das páginas](#5-guia-visual-das-4-páginas) · [6. Valores de conferência](#6-valores-de-conferência)

---

## 0. Modelo de dados

### 0.1 Importação (Power Query)

| Arquivo | Tabela | Observações |
|---|---|---|
| `data/dim_clientes.csv` | `dim_clientes` | `limite_credito` = Decimal |
| `data/fato_faturas.csv` | `fato_faturas` | 3 colunas de data = Data; `valor_fatura` = Decimal |
| `data/clientes_score_preditivo.csv` | `clientes_score_preditivo` | `probabilidade_default` e `pd_backtest` = Decimal, formato % |
| `data/feature_importance.csv` | `feature_importance` | `importancia_pct` = Decimal, formato % |

> ⚠️ **Power BI em pt-BR:** os CSVs usam ponto como separador decimal. Em cada consulta use
> *Transformar → Tipo de Dados → Usando Localidade… → Inglês (Estados Unidos)* nas colunas numéricas e de data,
> ou ajuste *Arquivo → Opções → Configurações Regionais* do arquivo para `Inglês (EUA)` antes de importar.

### 0.2 Tabelas calculadas

```dax
// Calendário contínuo do 1º mês com emissão até o mês da data de corte.
// Marcar como tabela de datas (coluna [Date]).
dim_calendario =
VAR _inicio = DATE ( YEAR ( MIN ( fato_faturas[data_emissao] ) ), MONTH ( MIN ( fato_faturas[data_emissao] ) ), 1 )
VAR _fim    = EOMONTH ( MAX ( fato_faturas[data_emissao] ), 0 )
RETURN
    ADDCOLUMNS (
        CALENDAR ( _inicio, _fim ),
        "Ano",     YEAR ( [Date] ),
        "Mês",     MONTH ( [Date] ),
        "Ano-Mês", FORMAT ( [Date], "yyyy-mm" ),   // usar como "Classificar por" do Mês/Ano
        "Mês/Ano", FORMAT ( [Date], "mmm/yy" )
    )
```

```dax
// Régua de Aging e PDD (matriz de provisão — CPC 48 / IFRS 9, abordagem simplificada).
// ÚNICA fonte da verdade: mudar uma taxa aqui muda a PDD do relatório inteiro.
// Classificar [Faixa] por [Ordem].
dim_aging =
DATATABLE (
    "Ordem",   INTEGER,
    "Faixa",   STRING,
    "DiasMin", INTEGER,
    "DiasMax", INTEGER,
    "TaxaPDD", DOUBLE,
    {
        { 1, "A Vencer",    -99999,     0, 0.00 },
        { 2, "1–30 dias",        1,    30, 0.02 },
        { 3, "31–60 dias",      31,    60, 0.10 },
        { 4, "61–90 dias",      61,    90, 0.30 },
        { 5, "90+ dias",        91, 99999, 1.00 }
    }
)
```

### 0.3 Colunas calculadas (`fato_faturas`)

```dax
// Dias de atraso na DATA DE CORTE (só faturas em aberto; liquidadas = BLANK).
// Sem CALCULATE, MAX() varre a coluna inteira = última data de emissão = data de corte.
dias_atraso_corte =
VAR _corte = MAX ( fato_faturas[data_emissao] )
RETURN
    IF ( ISBLANK ( fato_faturas[data_pagamento] ), INT ( _corte - fato_faturas[data_vencimento] ) )
```

```dax
// Faixa de Aging estática (na data de corte) — alimenta slicers e a matriz com drill-down.
// ALLNOBLANKROW evita dependência circular com o relacionamento dim_aging -> fato_faturas.
faixa_aging =
VAR _dias = fato_faturas[dias_atraso_corte]
RETURN
    IF (
        NOT ISBLANK ( _dias ),
        MAXX (
            FILTER ( ALLNOBLANKROW ( dim_aging ), _dias >= dim_aging[DiasMin] && _dias <= dim_aging[DiasMax] ),
            dim_aging[Faixa]
        )
    )
```

### 0.4 Relacionamentos

| De (1) | Para (*) | Direção | Ativo |
|---|---|---|---|
| `dim_clientes[cliente_id]` | `fato_faturas[cliente_id]` | Única | ✅ |
| `dim_clientes[cliente_id]` | `clientes_score_preditivo[cliente_id]` (1:1) | Ambas | ✅ |
| `dim_calendario[Date]` | `fato_faturas[data_emissao]` | Única | ✅ |
| `dim_calendario[Date]` | `fato_faturas[data_pagamento]` | Única | ❌ (usado via `USERELATIONSHIP`) |
| `dim_aging[Faixa]` | `fato_faturas[faixa_aging]` | Única | ✅ |

`feature_importance` e as tabelas de parâmetro What-If ficam **desconectadas**.

> 💡 **Conceito-chave — AR é estoque, não fluxo.** Faturamento soma o que foi emitido *no período*; a carteira é
> uma foto em uma data: *emitido até a data* **e** *não pago até a data*. Por isso as medidas de carteira removem o
> filtro do calendário e reconstroem o saldo "as-of" no último dia do período selecionado. É isso que permite
> plotar a evolução mensal da inadimplência com faturas que hoje já estão pagas.

---

## 1. Pasta: Executivo

```dax
// Data de corte da base ("hoje"). Independente de qualquer filtro.
Data Corte =
CALCULATE ( MAX ( fato_faturas[data_emissao] ), REMOVEFILTERS () )
```

```dax
// Data da "foto" da carteira: último dia do período em contexto, limitado à data de corte.
// Em um gráfico mensal = fim de cada mês; sem filtro de data = data de corte.
Data Referência =
MIN ( MAX ( dim_calendario[Date] ), [Data Corte] )
```

```dax
// Faturamento bruto emitido no período (relacionamento ativo: data_emissao).
Faturamento =
SUM ( fato_faturas[valor_fatura] )
```

```dax
// Caixa recebido no período (ativa o relacionamento por data_pagamento).
Recebimentos =
CALCULATE ( SUM ( fato_faturas[valor_fatura] ), USERELATIONSHIP ( dim_calendario[Date], fato_faturas[data_pagamento] ) )
```

```dax
// CARTEIRA TOTAL ATIVA (AR): saldo em aberto na Data Referência.
// KEEPFILTERS preserva filtros externos sobre as mesmas colunas (usado pelo simulador).
Carteira Total Ativa (AR) =
VAR _ref = [Data Referência]
RETURN
    CALCULATE (
        SUM ( fato_faturas[valor_fatura] ),
        REMOVEFILTERS ( dim_calendario ),
        KEEPFILTERS ( fato_faturas[data_emissao] <= _ref ),
        KEEPFILTERS ( ISBLANK ( fato_faturas[data_pagamento] ) || fato_faturas[data_pagamento] > _ref )
    )
```

```dax
// Parte da carteira com vencimento ultrapassado na Data Referência.
Valor Vencido =
VAR _ref = [Data Referência]
RETURN
    CALCULATE (
        [Carteira Total Ativa (AR)],
        KEEPFILTERS ( fato_faturas[data_vencimento] < _ref )
    )
```

```dax
// Vencido há mais de 90 dias (proxy de default / NPL 90).
Valor Vencido 90+ =
VAR _ref = [Data Referência]
RETURN
    CALCULATE (
        [Carteira Total Ativa (AR)],
        KEEPFILTERS ( fato_faturas[data_vencimento] < _ref - 90 )
    )
```

```dax
// % DE INADIMPLÊNCIA (Overdue %) = Vencido / Carteira.
% Inadimplência =
DIVIDE ( [Valor Vencido], [Carteira Total Ativa (AR)] )
```

```dax
// NPL 90: participação da carteira vencida há mais de 90 dias.
% Inadimplência 90+ =
DIVIDE ( [Valor Vencido 90+], [Carteira Total Ativa (AR)] )
```

```dax
// DSO — Days Sales Outstanding (Prazo Médio de Recebimento), método contábil:
//   DSO = Carteira (AR) / Faturamento dos últimos N dias × N
// Janela de 90 dias suaviza sazonalidade mensal. Lido como "quantos dias de venda estão na rua".
DSO (dias) =
VAR _ref    = [Data Referência]
VAR _janela = 90
VAR _vendas =
    CALCULATE (
        SUM ( fato_faturas[valor_fatura] ),
        REMOVEFILTERS ( dim_calendario ),
        KEEPFILTERS ( fato_faturas[data_emissao] > _ref - _janela && fato_faturas[data_emissao] <= _ref )
    )
RETURN
    DIVIDE ( [Carteira Total Ativa (AR)] * _janela, _vendas )
```

```dax
// PDD ESTIMADA (Provisão para Devedores Duvidosos) — matriz de provisão por Aging.
// Para cada fatura em aberto na Data Referência: valor × taxa da faixa (dim_aging).
// Dinâmica: recalcula o aging em qualquer data -> permite a série mensal Inadimplência × PDD.
PDD Estimada =
VAR _ref = [Data Referência]
VAR _abertas =
    CALCULATETABLE (
        fato_faturas,
        REMOVEFILTERS ( dim_calendario ),
        KEEPFILTERS ( fato_faturas[data_emissao] <= _ref ),
        KEEPFILTERS ( ISBLANK ( fato_faturas[data_pagamento] ) || fato_faturas[data_pagamento] > _ref )
    )
RETURN
    SUMX (
        _abertas,
        VAR _dias = INT ( _ref - fato_faturas[data_vencimento] )
        VAR _taxa =
            MAXX (
                FILTER ( ALL ( dim_aging ), _dias >= dim_aging[DiasMin] && _dias <= dim_aging[DiasMax] ),
                dim_aging[TaxaPDD]
            )
        RETURN fato_faturas[valor_fatura] * _taxa
    )
```

```dax
// PDD como % da carteira (índice de provisão).
PDD % Carteira =
DIVIDE ( [PDD Estimada], [Carteira Total Ativa (AR)] )
```

```dax
// Cobertura: quanto do vencido já está provisionado.
% Cobertura PDD =
DIVIDE ( [PDD Estimada], [Valor Vencido] )
```

```dax
// Número de clientes com ao menos uma fatura vencida na Data Referência.
Clientes em Atraso =
VAR _ref = [Data Referência]
RETURN
    CALCULATE (
        DISTINCTCOUNT ( fato_faturas[cliente_id] ),
        REMOVEFILTERS ( dim_calendario ),
        KEEPFILTERS ( fato_faturas[data_emissao] <= _ref ),
        KEEPFILTERS ( ISBLANK ( fato_faturas[data_pagamento] ) || fato_faturas[data_pagamento] > _ref ),
        KEEPFILTERS ( fato_faturas[data_vencimento] < _ref )
    )
```

```dax
// Variação da inadimplência vs. mês anterior (em p.p.) — para o cartão de KPI.
Δ % Inadimplência (p.p. m/m) =
VAR _atual    = [% Inadimplência]
VAR _anterior = CALCULATE ( [% Inadimplência], DATEADD ( dim_calendario[Date], -1, MONTH ) )
RETURN
    IF ( NOT ISBLANK ( _anterior ), _atual - _anterior )
```

---

## 2. Pasta: Aging / PDD

> As faixas usam a coluna `faixa_aging` (foto na data de corte), relacionada a `dim_aging`. Coloque
> `dim_aging[Faixa]` nas colunas da matriz — as medidas de carteira e PDD acima já respondem a esse filtro.

```dax
// Participação da faixa na carteira total.
% da Carteira =
DIVIDE ( [Carteira Total Ativa (AR)], CALCULATE ( [Carteira Total Ativa (AR)], REMOVEFILTERS ( dim_aging ) ) )
```

```dax
// Taxa de provisão da faixa em contexto (mostrar no eixo/rótulo da régua).
Taxa PDD da Faixa =
SELECTEDVALUE ( dim_aging[TaxaPDD] )
```

```dax
// Quantidade de faturas em aberto (na data de corte).
Faturas em Aberto =
CALCULATE ( COUNTROWS ( fato_faturas ), NOT ISBLANK ( fato_faturas[faixa_aging] ) )
```

```dax
// Atraso médio ponderado pelo valor (só vencidas) — mostra "quão velha" é a dívida.
Atraso Médio Ponderado (dias) =
VAR _vencidas = FILTER ( fato_faturas, fato_faturas[dias_atraso_corte] > 0 )
RETURN
    DIVIDE (
        SUMX ( _vencidas, fato_faturas[valor_fatura] * fato_faturas[dias_atraso_corte] ),
        SUMX ( _vencidas, fato_faturas[valor_fatura] )
    )
```

```dax
// Dias de atraso no nível da fatura (drill-down até fatura_id).
Dias de Atraso =
MAX ( fato_faturas[dias_atraso_corte] )
```

```dax
// Cor para formatação condicional (Formatar → Cor de fundo → Valor do campo).
// Escala pelo índice de provisão da célula: quanto mais PDD/Carteira, mais vermelho.
Cor Risco Aging =
VAR _idx = DIVIDE ( [PDD Estimada], [Carteira Total Ativa (AR)] )
RETURN
    SWITCH (
        TRUE (),
        ISBLANK ( _idx ), BLANK (),
        _idx >= 0.50, "#C0392B",   // vermelho  — majoritariamente 90+
        _idx >= 0.10, "#E67E22",   // laranja   — 31–90 dias relevante
        _idx > 0,     "#F4D03F",   // amarelo   — atraso curto
        "#27AE60"                  // verde     — a vencer
    )
```

---

## 3. Pasta: Preditivo

```dax
Clientes =
COUNTROWS ( clientes_score_preditivo )
```

```dax
// PD média simples (cada cliente pesa igual).
PD Média =
AVERAGE ( clientes_score_preditivo[probabilidade_default] )
```

```dax
// PD ponderada pela exposição: o "risco médio do real emprestado".
// Transição de contexto em cada cliente -> [Carteira] daquele cliente.
PD Ponderada pela Exposição =
DIVIDE (
    SUMX ( clientes_score_preditivo, clientes_score_preditivo[probabilidade_default] * [Carteira Total Ativa (AR)] ),
    [Carteira Total Ativa (AR)]
)
```

```dax
// Perda Esperada (Expected Loss) = PD × EAD × LGD.
// EAD = saldo em aberto; LGD = 60% (premissa de recuperação de 40% para crédito comercial sem garantia).
Perda Esperada (EL) =
VAR _LGD = 0.60
RETURN
    SUMX ( clientes_score_preditivo, clientes_score_preditivo[probabilidade_default] * [Carteira Total Ativa (AR)] * _LGD )
```

```dax
Limite de Crédito =
SUM ( dim_clientes[limite_credito] )
```

```dax
// Limite ainda disponível para novas compras (nunca negativo por cliente).
Limite Disponível =
SUMX ( dim_clientes, MAX ( 0, dim_clientes[limite_credito] - [Carteira Total Ativa (AR)] ) )
```

```dax
// % do limite tomado.
Utilização do Limite =
DIVIDE ( [Carteira Total Ativa (AR)], [Limite de Crédito] )
```

```dax
// Limite aberto para clientes de rating D/E: a "porta aberta" que a área de crédito deveria fechar.
Limite Exposto em Alto Risco (D/E) =
CALCULATE ( [Limite Disponível], KEEPFILTERS ( clientes_score_preditivo[faixa_risco] IN { "D", "E" } ) )
```

```dax
% Limite Exposto em Alto Risco =
DIVIDE ( [Limite Exposto em Alto Risco (D/E)], [Limite Disponível] )
```

```dax
// Importância de cada variável (gráfico de barras sobre feature_importance[variavel]).
Importância (Logit) =
SUM ( feature_importance[importancia_pct] )
```

```dax
Importância (Random Forest) =
SUM ( feature_importance[importancia_rf_pct] )
```

---

## 4. Pasta: Simulador What-If

### 4.1 Parâmetros (Modelagem → Novo parâmetro → Intervalo numérico)

| Parâmetro | Mín | Máx | Incremento | Padrão |
|---|---|---|---|---|
| `Corte PD` (PD máxima aceitável) | 0,05 | 0,50 | 0,01 | 0,20 |
| `Margem Contribuição` | 0,05 | 0,40 | 0,01 | 0,10 |

No projeto as tabelas são geradas com inteiros ÷ 100, para que cada valor seja exato (0,38 = 0,38) e o
slicer consiga guardar a seleção:

```dax
Corte PD = SELECTCOLUMNS ( GENERATESERIES ( 5, 50, 1 ), "Corte PD", [Value] / 100 )
Valor Corte PD = SELECTEDVALUE ( 'Corte PD'[Corte PD], 0.20 )

Margem Contribuição = SELECTCOLUMNS ( GENERATESERIES ( 5, 40, 1 ), "Margem Contribuição", [Value] / 100 )
Valor Margem Contribuição = SELECTEDVALUE ( 'Margem Contribuição'[Margem Contribuição], 0.10 )
```

### 4.2 Lógica (backtest de política)

*"Se há 9 meses tivéssemos reprovado todo cliente com PD acima de X%, quanto de PDD teríamos evitado e quanta
margem teríamos deixado na mesa?"* — usa `pd_backtest` (PD calculada em T-9m, fora da amostra), então o
simulador não "cola" do futuro. Esta página **não** deve ter filtro de data.

```dax
// Início da janela do backtest (T_obs = data de corte − 9 meses, igual ao credit_scoring.py).
Sim Início Janela =
EDATE ( [Data Corte], -9 )
```

```dax
// Clientes que a política reprovaria.
// O valor do parâmetro vai para uma VAR: medidas não podem ser usadas direto em filtros booleanos.
Sim Clientes Reprovados =
VAR _corte = [Valor Corte PD]
RETURN
    CALCULATE ( [Clientes], KEEPFILTERS ( clientes_score_preditivo[pd_backtest] > _corte ) )
```

```dax
Sim Taxa de Aprovação =
1 - DIVIDE ( [Sim Clientes Reprovados], [Clientes] )
```

```dax
// ECONOMIA DE RISCO: PDD hoje constituída sobre faturas que os reprovados receberam na janela.
Sim PDD Evitada (Economia de Risco) =
VAR _corte  = [Valor Corte PD]
VAR _inicio = [Sim Início Janela]
RETURN
    CALCULATE (
        [PDD Estimada],
        KEEPFILTERS ( clientes_score_preditivo[pd_backtest] > _corte ),
        KEEPFILTERS ( fato_faturas[data_emissao] > _inicio )
    )
```

```dax
// Inadimplência (valor vencido) que deixaria de existir.
Sim Inadimplência Evitada =
VAR _corte  = [Valor Corte PD]
VAR _inicio = [Sim Início Janela]
RETURN
    CALCULATE (
        [Valor Vencido],
        KEEPFILTERS ( clientes_score_preditivo[pd_backtest] > _corte ),
        KEEPFILTERS ( fato_faturas[data_emissao] > _inicio )
    )
```

```dax
Sim Carteira Evitada =
VAR _corte  = [Valor Corte PD]
VAR _inicio = [Sim Início Janela]
RETURN
    CALCULATE (
        [Carteira Total Ativa (AR)],
        KEEPFILTERS ( clientes_score_preditivo[pd_backtest] > _corte ),
        KEEPFILTERS ( fato_faturas[data_emissao] > _inicio )
    )
```

```dax
// Overdue % da carteira se a política estivesse ativa.
Sim % Inadimplência Pós-Política =
DIVIDE ( [Valor Vencido] - [Sim Inadimplência Evitada], [Carteira Total Ativa (AR)] - [Sim Carteira Evitada] )
```

```dax
// CUSTO DE OPORTUNIDADE: faturamento dos reprovados que TERIA sido pago
// (exclui faturas que viraram calote = em aberto há mais de 90 dias).
Sim Receita Perdida (Bons Pagadores) =
VAR _corte  = [Valor Corte PD]
VAR _inicio = [Sim Início Janela]
VAR _corte90 = [Data Corte] - 90
RETURN
    CALCULATE (
        SUM ( fato_faturas[valor_fatura] ),
        REMOVEFILTERS ( dim_calendario ),
        KEEPFILTERS ( clientes_score_preditivo[pd_backtest] > _corte ),
        KEEPFILTERS ( fato_faturas[data_emissao] > _inicio ),
        KEEPFILTERS ( NOT ( ISBLANK ( fato_faturas[data_pagamento] ) && fato_faturas[data_vencimento] < _corte90 ) )
    )
```

```dax
// Receita perdida só custa a MARGEM (o custo da mercadoria também não sai).
Sim Margem Perdida =
[Sim Receita Perdida (Bons Pagadores)] * [Valor Margem Contribuição]
```

```dax
// IMPACTO LÍQUIDO NA MARGEM = Economia de Risco − Margem Perdida.
// > 0: a política paga; < 0: estamos recusando bons clientes demais.
Sim Impacto Líquido =
[Sim PDD Evitada (Economia de Risco)] - [Sim Margem Perdida]
```

```dax
// Corte de PD que maximiza o impacto líquido, varrendo todos os valores do parâmetro.
// ALL (e não ALLSELECTED) para ignorar o valor escolhido no slicer.
Corte Ótimo de PD =
MAXX (
    TOPN ( 1, ALL ( 'Corte PD'[Corte PD] ), [Sim Impacto Líquido], DESC ),
    'Corte PD'[Corte PD]
)
```

```dax
Impacto no Corte Ótimo =
MAXX ( ALL ( 'Corte PD'[Corte PD] ), [Sim Impacto Líquido] )
```

```dax
// Texto dinâmico para o cartão narrativo da página.
Sim Narrativa =
"Reprovando clientes com PD acima de " & FORMAT ( [Valor Corte PD], "0%" )
    & ", evitamos " & FORMAT ( [Sim PDD Evitada (Economia de Risco)], "R$ #,##0" ) & " de PDD"
    & " e abrimos mão de " & FORMAT ( [Sim Margem Perdida], "R$ #,##0" ) & " de margem."
    & " Impacto líquido: " & FORMAT ( [Sim Impacto Líquido], "R$ #,##0;-R$ #,##0" ) & "."
```

---

## 5. Guia visual das 4 páginas

Tema sugerido: fundo `#F7F8FA`, cartões brancos, cor primária azul-petróleo `#0F4C5C`, alerta `#C0392B`.
Slicers globais (páginas 1–3): Segmento, Região, Faixa de Risco.

### Página 1 — Visão Executiva de Crédito e Cobrança

| Visual | Campos |
|---|---|
| 5 cartões de KPI (linha superior) | `Carteira Total Ativa (AR)` · `% Inadimplência` (+ `Δ % Inadimplência`) · `DSO (dias)` · `PDD Estimada` · `% Cobertura PDD` |
| Gráfico de colunas + linha (eixo duplo) | Eixo: `dim_calendario[Mês/Ano]` · Colunas: `PDD Estimada` · Linha: `% Inadimplência` |
| Gráfico de linhas | Eixo: `Mês/Ano` · `Faturamento` vs `Recebimentos` |
| Linha DSO | Eixo: `Mês/Ano` · `DSO (dias)` com linha de constante na meta (ex.: 60 dias) |
| Barras horizontais | `dim_clientes[segmento]` × `% Inadimplência` |
| Mapa/forma | `dim_clientes[regiao]` × `Carteira Total Ativa (AR)` |

> Os 3 primeiros meses mostram carteira "em formação" (a base começa com saldo zero) — filtre o eixo a partir do 4º mês.

### Página 2 — Gestão de Aging List

| Visual | Campos |
|---|---|
| Colunas empilhadas 100% ou funil | `dim_aging[Faixa]` × `Carteira Total Ativa (AR)` |
| Tabela da régua | `dim_aging[Faixa]`, `Taxa PDD da Faixa`, `Carteira Total Ativa (AR)`, `PDD Estimada`, `% da Carteira` |
| **Matriz com drill-down** | Linhas: `dim_clientes[segmento]` → `dim_clientes[nome_cliente]` → `fato_faturas[fatura_id]` · Colunas: `dim_aging[Faixa]` · Valores: `Carteira Total Ativa (AR)` · Formatação condicional: Cor de fundo → Valor do campo → `Cor Risco Aging` |
| Cartões | `Atraso Médio Ponderado (dias)`, `Faturas em Aberto`, `Clientes em Atraso` |
| Top N | Tabela Top 15 clientes por `Valor Vencido 90+` (filtro Top N no visual) |

### Página 3 — Score de Risco Preditivo

| Visual | Campos |
|---|---|
| Colunas | `clientes_score_preditivo[faixa_risco]` × `Clientes` e `Carteira Total Ativa (AR)` (eixo duplo) |
| Barras horizontais (Feature Importance) | `feature_importance[variavel]` × `Importância (Logit)` (cor por `efeito`) e `Importância (Random Forest)` |
| Dispersão (Limite × PD) | X: `PD Média` · Y: `Limite Disponível` · Tamanho: `Carteira Total Ativa (AR)` · Legenda: `faixa_risco` · Detalhes: `nome_cliente`. Linhas de referência em PD = 20% e na mediana do limite -> **quadrante superior direito = alto risco com limite alto exposto** |
| Matriz | Linhas: `faixa_risco` · Colunas: `segmento` · Valores: `Limite Disponível`, `Perda Esperada (EL)` |
| Cartões | `PD Ponderada pela Exposição`, `Perda Esperada (EL)`, `Limite Exposto em Alto Risco (D/E)` |
| Tabela de ação | Clientes D/E: `nome_cliente`, `probabilidade_default`, `Limite Disponível`, `fator_risco_1..3` |

### Página 4 — Simulador What-If de Política de Crédito

| Visual | Campos |
|---|---|
| Slicers (controle deslizante) | `Corte PD`, `Margem Contribuição` |
| Cartões | `Sim PDD Evitada (Economia de Risco)` · `Sim Margem Perdida` · `Sim Impacto Líquido` (verde/vermelho) · `Sim Taxa de Aprovação` · `Sim % Inadimplência Pós-Política` vs `% Inadimplência` |
| **Curva de trade-off** (linhas) | Eixo X: `'Corte PD'[Corte PD]` · Linhas: `Sim PDD Evitada`, `Sim Margem Perdida`, `Sim Impacto Líquido` — o pico da linha de impacto é o corte ótimo |
| Cartões | `Corte Ótimo de PD`, `Impacto no Corte Ótimo` |
| Cartão de texto | `Sim Narrativa` |
| Cascata | Inadimplência atual → (−) evitada → inadimplência pós-política |

> Experimente subir a margem: o corte ótimo também sobe — **quanto maior a margem, mais risco vale a pena aceitar.**

---

## 6. Valores de conferência

Com `SEED = 42` e `DATA_CORTE = 2026-10-31`, sem filtros, o relatório deve mostrar:

| Medida | Valor |
|---|---|
| Carteira Total Ativa (AR) | R$ 140.319.568 |
| Valor Vencido / % Inadimplência | R$ 26.374.993 / 18,8% |
| % Inadimplência 90+ | 9,9% |
| DSO (dias) | 68,0 |
| PDD Estimada / PDD % Carteira | R$ 14.941.048 / 10,6% |

| Faixa | Carteira | PDD |
|---|---|---|
| A Vencer | R$ 113.944.575 | — |
| 1–30 dias | R$ 7.837.009 | R$ 156.740 |
| 31–60 dias | R$ 2.447.601 | R$ 244.760 |
| 61–90 dias | R$ 2.215.477 | R$ 664.643 |
| 90+ dias | R$ 13.874.905 | R$ 13.874.905 |

Simulador (margem 10%): a tabela impressa ao final do `credit_scoring.py` reproduz `Sim Clientes Reprovados`,
`Sim PDD Evitada`, `Sim Margem Perdida` e `Sim Impacto Líquido` para cortes de 5% a 50%
na grade de 5 em 5 p.p. Varrendo de 1 em 1 p.p. (como o `Corte Ótimo de PD`), o ótimo é **38%**:
144 clientes reprovados, PDD evitada R$ 2.578.236, margem perdida R$ 929.690, impacto **R$ 1.648.546**.
