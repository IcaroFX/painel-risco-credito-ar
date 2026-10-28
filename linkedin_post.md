# Roteiro do post — LinkedIn

**Público-alvo:** gestores de Dados, FP&A, Controladoria, Crédito & Cobrança e Risco.
**Formato recomendado:** carrossel em PDF (8 slides) + texto abaixo. Publicar terça a quinta, 8h–9h.

---

## Texto do post

Reprovar cliente arriscado sempre economiza dinheiro? 🤔

Fiz a conta. Em uma carteira de R$ 140 mi, a política de crédito mais rígida que testei **destruiu R$ 3,2 milhões de margem**.

Construí um projeto de ponta a ponta unindo Finanças, Ciência de Dados e BI para responder a pergunta que todo CFO faz:
👉 *"Quanto risco vale a pena correr para vender mais?"*

🔹 **1. A base**
Datasets públicos de crédito não têm histórico de faturas — e sem emissão, vencimento e pagamento não existe Aging, DSO nem PDD.
Então gerei em Python uma carteira B2B realista: 2.000 clientes, 30.000 faturas, 18 meses. Inclusive com "bust-out": o cliente que vai quebrar compra mais a prazo antes de parar de pagar.

🔹 **2. O diagnóstico financeiro (Power BI + DAX)**
• Carteira (AR) calculada como estoque "as-of", não como soma de vendas
• DSO de 68 dias para prazos de 28 a 90
• Aging List com drill-down até a fatura
• PDD por matriz de provisão (CPC 48): R$ 14,9 mi, 10,6% da carteira

🔹 **3. O modelo preditivo (scikit-learn)**
Probabilidade de Default (atraso > 90 dias) com recorte temporal sem vazamento de informação.
AUC 0,87. O rating A–E ordena o risco: 1% de default na faixa A, 57% na faixa E.
Escolhi Regressão Logística em vez de Random Forest (mesma performance) porque ela explica cada cliente: "score de bureau baixo", "limite muito comprometido"...

🔹 **4. O simulador What-If**
Um slider de "PD máxima aceitável" de 5% a 50%. Para cada corte, o painel calcula:
✅ PDD evitada (economia de risco)
❌ Margem perdida dos bons pagadores reprovados (custo de oportunidade)
= Impacto líquido na margem

📌 Resultado:
• Corte em 5%: reprova 760 clientes e **perde R$ 3,2 mi**
• Corte em 38% (o ótimo): reprova 144 clientes e **ganha R$ 1,65 mi**

💡 E o insight que mais gosto: a margem muda a resposta.
Com margem de 5%, o corte ótimo é 24%. Com 10%, sobe para 38%. Com 30%, nenhuma reprovação até 50% de PD se paga.
**Margem alta compra o direito de correr risco.** Crédito não é sobre evitar perda — é sobre maximizar resultado.

Para quem trabalha com FP&A, Crédito ou Dados: como vocês definem o corte de aprovação hoje? Score fixo, comitê ou simulação?

🔗 Código, medidas DAX comentadas e guia do dashboard no GitHub (link no primeiro comentário).

#PowerBI #DAX #CienciaDeDados #Python #RiscoDeCredito #FPandA #ContasAReceber #Financas #MachineLearning #BusinessIntelligence

---

## Primeiro comentário
Repositório completo: https://github.com/IcaroFX/painel-risco-credito-ar
(scripts Python, catálogo DAX por pasta, regras de negócio e valores de conferência para reproduzir o painel)

---

## Carrossel (8 slides)

| # | Título | Conteúdo visual |
|---|---|---|
| 1 | "Reprovar cliente arriscado destruiu R$ 3,2 mi de margem" | Curva de trade-off da página 4 com o pico marcado |
| 2 | O dilema do crédito | Balança: vender mais × perder menos |
| 3 | Visão Executiva | Print da página 1 (AR, Overdue %, DSO, PDD + evolução mensal) |
| 4 | Aging + régua de PDD | Print da matriz com formatação condicional + tabela 0/2/10/30/100% |
| 5 | Modelo de PD | Tabela do rating A–E (1% → 57%) + AUC 0,87 |
| 6 | Por que o cliente é arriscado? | Gráfico de feature importance + exemplo de "top 3 fatores" |
| 7 | O simulador | Print da página 4 com os sliders e os cartões de impacto |
| 8 | O que aprendi | "Margem alta compra o direito de correr risco" + link do GitHub |

## Dicas
- Grave um GIF de 10s movendo o slider de corte de PD — vídeo curto tem alcance maior que imagem.
- Responda todos os comentários na primeira hora.
- Marque 2–3 pessoas de FP&A/Crédito da sua rede que possam opinar sobre a régua de PDD.
