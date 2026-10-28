"""
Modelo de Probabilidade de Default (PD) — atraso > 90 dias — sobre a base de Contas a Receber.

Desenho temporal (sem vazamento de informação):
  T_obs = DATA_CORTE - 9 meses
  - Variáveis (X): tudo o que se sabia sobre o cliente até T_obs.
  - Alvo (y):      1 se alguma fatura com vencimento em (T_obs, DATA_CORTE - 90d] atrasou > 90 dias
                   (todas as faturas da janela tiveram 90 dias para "mostrar" o default).
  O modelo treinado nesse recorte é aplicado ao snapshot de DATA_CORTE para gerar a PD atual.

Saídas (pasta ./data):
  - clientes_score_preditivo.csv : PD atual, faixa de rating A–E, top 3 fatores de risco e
                                   pd_backtest (PD em T_obs, usada no simulador What-If do Power BI)
  - feature_importance.csv       : importância global das variáveis (modelo campeão x desafiante)
"""
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, roc_curve
from sklearn.model_selection import cross_val_predict, train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from generate_ar_data import DATA_CORTE

DATA = Path(__file__).parent / "data"
MESES_PERFORMANCE = 9
DIAS_DEFAULT = 90
T_OBS = DATA_CORTE - pd.DateOffset(months=MESES_PERFORMANCE)

# Régua de rating: limite superior de PD de cada faixa.
FAIXAS = {"A": .03, "B": .08, "C": .20, "D": .45, "E": 1.0}

# variável -> (nome para o gráfico de importância, rótulo quando o valor está ACIMA da média,
#              rótulo quando está ABAIXO). O rótulo usado é o do lado que empurra o risco para cima.
FEATURES = {
    "score_bureau_externo":       ("Score de bureau", "Score de bureau alto", "Score de bureau baixo"),
    "tempo_relacionamento_meses": ("Tempo de relacionamento", "Relacionamento longo", "Pouco tempo de relacionamento"),
    "historico_atraso_12m":       ("Histórico de atraso 12m", "Muitos atrasos nos últimos 12m", "Poucos atrasos nos últimos 12m"),
    "segmento_varejo":            ("Segmento Varejo", "Segmento Varejo", "Fora do Varejo"),
    "pct_faturas_pagas_atraso":   ("% faturas pagas com atraso", "Paga com atraso com frequência", "Raramente paga com atraso"),
    "atraso_max_dias":            ("Pior atraso (dias)", "Pior atraso elevado", "Pior atraso baixo"),
    "utilizacao_limite":          ("Comprometimento do limite", "Limite muito comprometido", "Limite pouco comprometido"),
}

cli = pd.read_csv(DATA / "dim_clientes.csv", index_col="cliente_id")
fat = pd.read_csv(DATA / "fato_faturas.csv", parse_dates=["data_emissao", "data_vencimento", "data_pagamento"])


def features(asof):
    """Snapshot de cada cliente em `asof`, usando SÓ informação disponível até essa data."""
    f = fat[fat["data_emissao"] <= asof]
    pago = f["data_pagamento"] <= asof  # NaT -> False (em aberto)
    atraso = np.where(pago, (f["data_pagamento"] - f["data_vencimento"]).dt.days,
                      (asof - f["data_vencimento"]).dt.days)
    g = pd.DataFrame({
        "cliente_id": f["cliente_id"],
        "pago_atraso": np.where(pago, atraso > 0, np.nan),
        "atraso": np.clip(atraso, 0, None),
        "saldo": f["valor_fatura"] * ~pago,
    }).groupby("cliente_id").agg(
        pct_faturas_pagas_atraso=("pago_atraso", "mean"),
        atraso_max_dias=("atraso", "max"),
        saldo=("saldo", "sum"),
    ).reindex(cli.index)

    meses_ate_corte = (DATA_CORTE - asof).days / 30.4
    X = pd.DataFrame({
        "score_bureau_externo": cli["score_bureau_externo"],
        "tempo_relacionamento_meses": (cli["tempo_relacionamento_meses"] - meses_ate_corte).clip(lower=0),
        "historico_atraso_12m": cli["historico_atraso_12m"],
        "segmento_varejo": (cli["segmento"] == "Varejo").astype(int),
        "pct_faturas_pagas_atraso": g["pct_faturas_pagas_atraso"],
        "atraso_max_dias": g["atraso_max_dias"],
        "utilizacao_limite": g["saldo"] / cli["limite_credito"],
    })
    return X.fillna(0)  # sem histórico = sem atraso observado


def alvo(t0, t1):
    """1 se o cliente teve fatura com vencimento em (t0, t1] paga (ou ainda aberta) com atraso > 90 dias."""
    f = fat[(fat["data_vencimento"] > t0) & (fat["data_vencimento"] <= t1)]
    atraso = (f["data_pagamento"].fillna(DATA_CORTE) - f["data_vencimento"]).dt.days
    return (atraso > DIAS_DEFAULT).groupby(f["cliente_id"]).any().astype(int)


def metricas(y, p):
    fpr, tpr, _ = roc_curve(y, p)
    auc = roc_auc_score(y, p)
    return f"AUC {auc:.3f} | Gini {2 * auc - 1:.3f} | KS {np.max(tpr - fpr):.3f}"


def faixa(pd_):
    return pd.cut(pd_, [0, *FAIXAS.values()], labels=list(FAIXAS), include_lowest=True)


def simular_politica(pd_corte, margem=.10):
    """Espelho em Python do simulador What-If do Power BI (página 4), para conferência dos números.
    Política: reprovar, a partir de T_obs, clientes com pd_backtest acima do corte."""
    f = fat[fat["data_emissao"] > T_OBS].merge(score[["pd_backtest"]], left_on="cliente_id", right_index=True)
    aberto = f["data_pagamento"].isna()
    dias = (DATA_CORTE - f["data_vencimento"]).dt.days
    taxa = np.select([dias > 90, dias > 60, dias > 30, dias > 0], [1, .30, .10, .02], 0)
    f["pdd"] = f["valor_fatura"] * taxa * aberto
    f["boa"] = ~(aberto & (dias > DIAS_DEFAULT))  # faturas que seriam pagas
    rows = []
    for c in pd_corte:
        r = f[f["pd_backtest"] > c]
        economia = r["pdd"].sum()
        margem_perdida = r.loc[r["boa"], "valor_fatura"].sum() * margem
        rows.append((f"{c:.0%}", (score["pd_backtest"] > c).sum(), economia, margem_perdida, economia - margem_perdida))
    return pd.DataFrame(rows, columns=["corte_pd", "clientes_reprovados", "pdd_evitada", "margem_perdida", "impacto_liquido"])


# ---------------------------------------------------------------- treino (snapshot em T_obs)
X = features(T_OBS)
y = alvo(T_OBS, DATA_CORTE - pd.Timedelta(days=DIAS_DEFAULT))
X_train_all, y_all = X.loc[y.index], y  # só clientes com faturas na janela de performance
print(f"T_obs = {T_OBS.date()} | Clientes na amostra: {len(y_all):,} | Taxa de default: {y_all.mean():.1%}")

X_tr, X_te, y_tr, y_te = train_test_split(X_train_all, y_all, test_size=.3, stratify=y_all, random_state=42)
logit = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
rf = RandomForestClassifier(n_estimators=400, min_samples_leaf=20, random_state=42, n_jobs=-1)
for nome, m in [("Regressão Logística (campeão)", logit), ("Random Forest (desafiante)", rf)]:
    m.fit(X_tr, y_tr)
    print(f"{nome:32s} -> {metricas(y_te, m.predict_proba(X_te)[:, 1])}")

# Campeão = Regressão Logística: performance equivalente e explicável cliente a cliente
# (contribuição = coeficiente x valor padronizado), padrão de mercado em crédito.
logit.fit(X_train_all, y_all)
rf.fit(X_train_all, y_all)
scaler, lr = logit[0], logit[-1]

# ---------------------------------------------------------------- score atual (snapshot em DATA_CORTE)
X_now = features(DATA_CORTE)
pd_now = logit.predict_proba(X_now)[:, 1]
contrib = scaler.transform(X_now) * lr.coef_[0]  # contribuição de cada variável no log-odds
acima_media = scaler.transform(X_now) > 0


def top_fatores(i):
    ordem = np.argsort(-contrib[i])[:3]
    nomes = list(FEATURES)
    return [FEATURES[nomes[j]][1 if acima_media[i, j] else 2] if contrib[i, j] > 0 else "" for j in ordem]


# PD em T_obs (fora da amostra via validação cruzada) para o backtest de política no simulador.
pd_backtest = pd.Series(logit.predict_proba(X)[:, 1], index=X.index)
pd_backtest[y_all.index] = cross_val_predict(logit, X_train_all, y_all, cv=5, method="predict_proba")[:, 1]

score = pd.DataFrame({"probabilidade_default": pd_now.round(4)}, index=X_now.index)
score["faixa_risco"] = faixa(score["probabilidade_default"])
score[["fator_risco_1", "fator_risco_2", "fator_risco_3"]] = [top_fatores(i) for i in range(len(score))]
score["pd_backtest"] = pd_backtest.round(4)
score.to_csv(DATA / "clientes_score_preditivo.csv", encoding="utf-8-sig")

imp = pd.DataFrame({
    "variavel": [v[0] for v in FEATURES.values()],
    "coeficiente_logit": lr.coef_[0].round(4),
    "efeito": np.where(lr.coef_[0] > 0, "Aumenta o risco", "Reduz o risco"),
    "importancia_pct": np.abs(scaler.transform(X_train_all) * lr.coef_[0]).mean(axis=0),
    "importancia_rf_pct": rf.feature_importances_,
})
imp[["importancia_pct", "importancia_rf_pct"]] = (imp[["importancia_pct", "importancia_rf_pct"]]
                                                   / imp[["importancia_pct", "importancia_rf_pct"]].sum()).round(4)
imp.sort_values("importancia_pct", ascending=False).to_csv(DATA / "feature_importance.csv", index=False, encoding="utf-8-sig")

# ---------------------------------------------------------------- conferências
backtest = pd.DataFrame({"faixa": faixa(pd_backtest[y_all.index]), "default": y_all})
taxa_por_faixa = backtest.groupby("faixa", observed=False)["default"].agg(["size", "mean"])
assert roc_auc_score(y_all, pd_backtest[y_all.index]) > .70, "modelo sem poder discriminante"
assert taxa_por_faixa["mean"].dropna().is_monotonic_increasing, "rating não ordena o risco"

print("\nBacktest fora da amostra — default observado por faixa (em T_obs):")
print(taxa_por_faixa.rename(columns={"size": "clientes", "mean": "taxa_default"}).round(3).to_string())
print("\nCarteira atual por faixa:\n" + score["faixa_risco"].value_counts().sort_index().to_string())
print("\nImportância das variáveis:\n" + imp.sort_values("importancia_pct", ascending=False).to_string(index=False))
print("\nSimulador What-If (conferência do Power BI, margem de contribuição 10%):")
print(simular_politica(np.arange(.05, .51, .05)).round(0).to_string(index=False))
