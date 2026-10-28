"""
Gera uma base sintética e realista de Contas a Receber (AR) B2B/B2C.

Saídas (pasta ./data):
  - dim_clientes.csv  : 2.000 clientes com perfil cadastral e de crédito
  - fato_faturas.csv  : 30.000 faturas emitidas nos 18 meses até DATA_CORTE

Regras de negócio embutidas:
  - Cada cliente tem um "risco latente" (log-odds) NÃO exportado — é o comportamento
    real que o modelo de ML precisa descobrir a partir das variáveis observáveis.
  - Score de bureau baixo, pouco tempo de relacionamento e segmento Varejo
    elevam o risco latente -> mais atrasos, atrasos mais longos e mais defaults.
  - Clientes em default param de pagar a partir de uma data e têm o crédito
    bloqueado 30 dias depois (não recebem novas faturas).
"""
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
N_CLIENTES = 2_000
N_FATURAS = 30_000
DATA_CORTE = pd.Timestamp("2026-10-31")  # "hoje" da base: aging, status e DSO são medidos nesta data
JANELA_DIAS = 548                        # ~18 meses de emissões
OUT = Path(__file__).parent / "data"

# share da carteira, limite mediano, score médio, tempo médio de relacionamento (meses),
# prazos de pagamento possíveis (dias), frequência relativa de compra e risco base (log-odds)
SEGMENTOS = {
    "Varejo":        dict(share=.60, limite=60_000,    score=560, tempo=24, prazos=[28, 30],     freq=1.2, risco=0.6),
    "Middle Market": dict(share=.30, limite=150_000,   score=650, tempo=42, prazos=[30, 45, 60], freq=1.5, risco=0.0),
    "Corporate":     dict(share=.10, limite=600_000,   score=760, tempo=70, prazos=[60, 90],     freq=1.5, risco=-0.7),
}
REGIOES = {"Sudeste": .45, "Sul": .20, "Nordeste": .18, "Centro-Oeste": .10, "Norte": .07}
SUFIXO = {"Varejo": "ME", "Middle Market": "Ltda", "Corporate": "S.A."}
SOBRENOMES = ("Silva Souza Oliveira Santos Lima Pereira Costa Almeida Ferreira Rodrigues Carvalho Gomes "
              "Martins Araújo Barbosa Ribeiro Rocha Dias Teixeira Moreira Cardoso Mendes Nunes Freitas "
              "Vieira Castro Pinto Campos Moura Duarte").split()
RAMOS = ["Alimentos", "Distribuidora", "Atacadista", "Comércio", "Tecnologia", "Logística", "Construtora",
         "Farma", "Têxtil", "Agronegócio", "Metalúrgica", "Embalagens", "Autopeças", "Materiais Elétricos",
         "Supermercados", "Móveis", "Química", "Papelaria", "Calçados", "Bebidas"]

rng = np.random.default_rng(SEED)


def sigmoid(x):
    return 1 / (1 + np.exp(-x))


def gerar_clientes():
    seg = rng.choice(list(SEGMENTOS), N_CLIENTES, p=[c["share"] for c in SEGMENTOS.values()])
    cfg = lambda k: np.array([SEGMENTOS[s][k] for s in seg])

    tempo = np.clip(rng.gamma(2.0, cfg("tempo") / 2.0), 1, 240).round().astype(int)
    score = np.clip(rng.normal(cfg("score") + 0.6 * (tempo - 40), 140), 0, 1000).round().astype(int)
    limite = (cfg("limite") * rng.lognormal(0, .5, N_CLIENTES) * (0.5 + score / 1000)).round(-3).clip(1_000)

    # Risco latente: quanto menor o score e o relacionamento, maior o risco. Ruído = fatores não observáveis.
    risco = cfg("risco") - 1.0 - 0.009 * (score - 650) - 0.015 * (tempo - 40) + rng.normal(0, .7, N_CLIENTES)
    atrasos_12m = rng.poisson(4 * sigmoid(risco - 0.5))  # atrasos registrados nos 12 meses antes da janela

    # Default (calote): evento de cliente. Dia (desde o início da janela) em que ele para de pagar.
    entra_default = rng.random(N_CLIENTES) < sigmoid(risco - 3.1)
    dia_default = np.where(entra_default, rng.integers(60, JANELA_DIAS - 30, N_CLIENTES), np.inf)

    combos = [(a, b, r) for a, b, r in product(SOBRENOMES, SOBRENOMES, RAMOS) if a != b]
    nomes = [f"{a} & {b} {r} {SUFIXO[s]}" for (a, b, r), s in
             zip((combos[i] for i in rng.choice(len(combos), N_CLIENTES, replace=False)), seg)]

    cli = pd.DataFrame({
        "cliente_id": [f"C{i:05d}" for i in range(1, N_CLIENTES + 1)],
        "nome_cliente": nomes,
        "segmento": seg,
        "regiao": rng.choice(list(REGIOES), N_CLIENTES, p=list(REGIOES.values())),
        "tempo_relacionamento_meses": tempo,
        "limite_credito": limite,
        "score_bureau_externo": score,
        "historico_atraso_12m": atrasos_12m,
    })
    return cli, risco, dia_default, cfg("freq")


def gerar_faturas(cli, risco, dia_default, freq):
    # Cliente em default só tem o crédito bloqueado 60 dias após parar de pagar.
    fim = np.minimum(dia_default + 60, JANELA_DIAS)
    peso = freq * rng.lognormal(0, .5, N_CLIENTES) * fim / JANELA_DIAS
    n_por_cliente = 1 + rng.multinomial(N_FATURAS - N_CLIENTES, peso / peso.sum())
    c = np.repeat(np.arange(N_CLIENTES), n_por_cliente)  # índice do cliente de cada fatura

    emissao = rng.integers(0, fim[c].astype(int) + 1)  # dia da emissão (0 = início da janela)
    prazos = cli["segmento"].map({s: v["prazos"] for s, v in SEGMENTOS.items()}).to_numpy()
    vencimento = emissao + np.array([rng.choice(p) for p in prazos[c]])

    # Comportamento de pagamento: risco do cliente + ruído da fatura.
    r = risco[c] + rng.normal(0, .5, N_FATURAS)
    atrasa = rng.random(N_FATURAS) < sigmoid(r)
    dias_atraso = np.where(atrasa,
                           1 + rng.gamma(1.5, 10 * np.exp(0.4 * r)),  # risco maior -> atraso mais longo
                           -rng.integers(0, 6, N_FATURAS)).round()   # bons pagadores pagam até 5 dias antes
    pagamento = vencimento + dias_atraso
    calote = vencimento > dia_default[c]
    pago = ~calote & (pagamento <= JANELA_DIAS)

    status = np.select(
        [pago & (dias_atraso <= 0), pago, vencimento >= JANELA_DIAS],
        ["Pago em Dia", "Pago com Atraso", "A Vencer"],
        "Vencido",
    )
    limite = cli["limite_credito"].to_numpy()[c]
    # "Bust-out": nos 90 dias antes do default o cliente em dificuldade compra mais a prazo.
    bust_out = np.where(emissao >= dia_default[c] - 90, 2.0, 1.0)
    valor = np.clip(limite * .15 * rng.lognormal(0, .6, N_FATURAS) * bust_out, 150, limite).round(2)
    inicio = DATA_CORTE - pd.Timedelta(days=JANELA_DIAS)
    to_date = lambda d: inicio + pd.to_timedelta(d, unit="D")

    fat = pd.DataFrame({
        "cliente_id": cli["cliente_id"].to_numpy()[c],
        "data_emissao": to_date(emissao),
        "data_vencimento": to_date(vencimento),
        "data_pagamento": to_date(np.where(pago, pagamento, np.nan)),
        "valor_fatura": valor,
        "status_fatura": status,
    }).sort_values(["data_emissao", "cliente_id"], ignore_index=True)
    fat.insert(0, "fatura_id", [f"F{i:06d}" for i in range(1, len(fat) + 1)])
    return fat


def main():
    cli, risco, dia_default, freq = gerar_clientes()
    fat = gerar_faturas(cli, risco, dia_default, freq)

    OUT.mkdir(exist_ok=True)
    cli.to_csv(OUT / "dim_clientes.csv", index=False, encoding="utf-8-sig")
    fat.to_csv(OUT / "fato_faturas.csv", index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")

    # Sanidade: volumes e coerência das regras de negócio.
    aberto = fat["data_pagamento"].isna()
    vencido = aberto & (fat["data_vencimento"] < DATA_CORTE)
    atraso_cli = fat.assign(atr=fat["status_fatura"].isin(["Pago com Atraso", "Vencido"])) \
                    .merge(cli, on="cliente_id").groupby("segmento")["atr"].mean()
    assert len(cli) == N_CLIENTES and len(fat) == N_FATURAS
    assert fat["data_emissao"].max() == DATA_CORTE
    assert atraso_cli["Varejo"] > atraso_cli["Middle Market"] > atraso_cli["Corporate"], atraso_cli

    print(f"Clientes: {len(cli):,} | Faturas: {len(fat):,} | Clientes em default: {np.isfinite(dia_default).mean():.1%}")
    print(fat["status_fatura"].value_counts(normalize=True).round(3).to_string())
    print(f"Carteira em aberto: R$ {fat.loc[aberto, 'valor_fatura'].sum():,.0f} | "
          f"Overdue %: {fat.loc[vencido, 'valor_fatura'].sum() / fat.loc[aberto, 'valor_fatura'].sum():.1%}")
    print("% faturas com atraso por segmento:\n" + atraso_cli.round(3).to_string())


if __name__ == "__main__":
    main()
