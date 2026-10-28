"""
Gera a camada visual (formato PBIR) do relatório PainelRiscoCredito.Report: tema, 4 páginas e visuais.
Rode após qualquer mudança de layout:  python powerbi/build_report.py
"""
import json
import shutil
from pathlib import Path

RAIZ = Path(__file__).parent / "PainelRiscoCredito.Report"
DEF = RAIZ / "definition"
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"
M = "_Medidas"
DATA_INICIO_GRAFICOS = "2025-08-01"  # os 3 primeiros meses mostram a carteira "em formação"

TEMA = {
    "name": "Risco de Crédito",
    "dataColors": ["#0F4C5C", "#E36414", "#9A031E", "#5F0F40", "#FB8B24", "#2A9D8F", "#6C757D", "#264653"],
    "background": "#FFFFFF", "foreground": "#1F2933", "tableAccent": "#0F4C5C",
    "good": "#1E7B4F", "bad": "#C0392B", "neutral": "#F4A261",
    "textClasses": {
        "callout": {"fontSize": 24, "fontFace": "Segoe UI Semibold", "color": "#0F4C5C"},
        "title": {"fontSize": 11, "fontFace": "Segoe UI Semibold", "color": "#1F2933"},
        "header": {"fontSize": 11, "fontFace": "Segoe UI Semibold", "color": "#1F2933"},
        "label": {"fontSize": 10, "fontFace": "Segoe UI", "color": "#52606D"},
    },
    "visualStyles": {
        "*": {"*": {
            "background": [{"show": True, "color": {"solid": {"color": "#FFFFFF"}}, "transparency": 0}],
            "border": [{"show": True, "color": {"solid": {"color": "#E4E7EB"}}, "radius": 8}],
            "dropShadow": [{"show": False}],
        }},
        "page": {"*": {
            "background": [{"color": {"solid": {"color": "#F3F5F8"}}, "transparency": 0}],
            "outspace": [{"color": {"solid": {"color": "#F3F5F8"}}}],
        }},
        "textbox": {"*": {"background": [{"show": False}], "border": [{"show": False}]}},
    },
}


# ---------------------------------------------------------------- helpers de expressão
def lit(v):
    if isinstance(v, bool):
        v = "true" if v else "false"
    elif isinstance(v, int):
        v = f"{v}L"
    elif isinstance(v, float):
        v = f"{v}D"
    else:
        v = f"'{v}'"
    return {"expr": {"Literal": {"Value": v}}}


def cor(c):
    """Cor fixa ('#RRGGBB') ou dinâmica (medida que devolve a cor)."""
    return {"solid": {"color": {"expr": c} if isinstance(c, dict) else lit(c)}}


def medida(nome, tabela=M):
    return {"Measure": {"Expression": {"SourceRef": {"Entity": tabela}}, "Property": nome}}


def coluna(tabela, nome):
    return {"Column": {"Expression": {"SourceRef": {"Entity": tabela}}, "Property": nome}}


def proj(campo, rotulo=None):
    tipo = "Measure" if "Measure" in campo else "Column"
    ent, nome = campo[tipo]["Expression"]["SourceRef"]["Entity"], campo[tipo]["Property"]
    p = {"field": campo, "queryRef": f"{ent}.{nome}", "nativeQueryRef": nome}
    if rotulo:
        p["displayName"] = rotulo
    return p


def filtro_data_minima(tabela="dim_calendario", col="Date", data=DATA_INICIO_GRAFICOS):
    return {"filters": [{
        "name": "fDataMin",
        "field": coluna(tabela, col),
        "type": "Advanced",
        "filter": {"Version": 2, "From": [{"Name": "d", "Entity": tabela, "Type": 0}],
                   "Where": [{"Condition": {"Comparison": {
                       "ComparisonKind": 2,
                       "Left": {"Column": {"Expression": {"SourceRef": {"Source": "d"}}, "Property": col}},
                       "Right": {"Literal": {"Value": f"datetime'{data}T00:00:00'"}}}}}]},
    }]}


def selecao_igual(tabela, col, valor):
    """Seleção inicial de um slicer (fica em objects.general.filter, não em filterConfig)."""
    return {"filter": {"Version": 2, "From": [{"Name": "p", "Entity": tabela, "Type": 0}],
                       "Where": [{"Condition": {"Comparison": {
                           "ComparisonKind": 0,
                           "Left": {"Column": {"Expression": {"SourceRef": {"Source": "p"}}, "Property": col}},
                           "Right": {"Literal": {"Value": f"{valor}D"}}}}}]}}


def filtro_in(tabela, col, valores):
    return {"filters": [{
        "name": f"f{col}",
        "field": coluna(tabela, col),
        "type": "Categorical",
        "filter": {"Version": 2, "From": [{"Name": "c", "Entity": tabela, "Type": 0}],
                   "Where": [{"Condition": {"In": {
                       "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "c"}}, "Property": col}}],
                       "Values": [[{"Literal": {"Value": f"'{v}'"}}] for v in valores]}}}]},
    }]}


# ---------------------------------------------------------------- helpers de visual
class Pagina:
    def __init__(self, nome, titulo, subtitulo):
        self.nome, self.titulo, self.visuais, self.interacoes = nome, titulo, [], []
        self.texto("titulo", 16, 0, 840, 48, titulo, 20, True)
        self.texto("subtitulo", 16, 38, 840, 34, subtitulo, 10, False, "#52606D")

    def add(self, nome, tipo, x, y, w, h, papeis=None, titulo=None, objetos=None, container=None,
            ordem=None, filtros=None):
        visual = {"visualType": tipo}
        if papeis:
            visual["query"] = {"queryState": {r: {"projections": [proj(c) if "field" not in c else c for c in cs]}
                                              for r, cs in papeis.items()}}
            if ordem:
                visual["query"]["sortDefinition"] = {"sort": [{"field": ordem[0], "direction": ordem[1]}],
                                                     "isDefaultSort": False}
        if objetos:
            visual["objects"] = objetos
        vco = {"title": [{"properties": {"show": lit(bool(titulo)), **({"text": lit(titulo)} if titulo else {})}}]}
        vco.update(container or {})
        visual["visualContainerObjects"] = vco
        v = {"$schema": f"{SCHEMA}/visualContainer/2.4.0/schema.json", "name": nome,
             "position": {"x": x, "y": y, "z": len(self.visuais) * 1000, "width": w, "height": h,
                          "tabOrder": len(self.visuais) * 1000},
             "visual": visual}
        if filtros:
            v["filterConfig"] = filtros
        self.visuais.append(v)

    def texto(self, nome, x, y, w, h, txt, tamanho, negrito, cor_txt="#0F4C5C"):
        estilo = {"fontSize": f"{tamanho}pt", "color": cor_txt}
        if negrito:
            estilo["fontWeight"] = "bold"
        self.add(nome, "textbox", x, y, w, h, objetos={"general": [{"properties": {
            "paragraphs": [{"textRuns": [{"value": txt, "textStyle": estilo}]}]}}]})

    def cartao(self, nome, x, y, w, h, campo, rotulo, cor_valor=None, tamanho=24.0, milhoes=False):
        labels = {"fontSize": lit(tamanho)}
        if cor_valor:
            labels["color"] = cor(cor_valor)
        if milhoes:  # R$ 140,3 Mi em vez de R$ 140 Mi
            labels.update(labelDisplayUnits=lit(1000000.0), labelPrecision=lit(1))
        self.add(nome, "card", x, y, w, h, {"Values": [proj(campo, rotulo)]}, objetos={
            "labels": [{"properties": labels}],
            "categoryLabels": [{"properties": {"show": lit(True), "fontSize": lit(10.0)}}],
        })

    def linha_cartoes(self, y, itens, h=96):
        w = (1232 - 12 * (len(itens) - 1)) / len(itens)
        for i, (nome, campo, rotulo, *milhoes) in enumerate(itens):
            self.cartao(nome, 24 + i * (w + 12), y, w, h, campo, rotulo, milhoes=bool(milhoes))

    def segmentador(self, nome, x, y, w, h, campo, titulo, modo="Dropdown", inicio=None):
        objetos = {
            "data": [{"properties": {"mode": lit(modo)}}],
            "header": [{"properties": {"show": lit(True), "text": lit(titulo), "fontSize": lit(9.0)}}],
            "items": [{"properties": {"fontSize": lit(9.0)}}],
        }
        if inicio is not None:  # valor inicial do slider: posição (numericStart) + filtro aplicado
            objetos["data"][0]["properties"]["numericStart"] = lit(float(inicio))
            col = campo["Column"]
            objetos["general"] = [{"properties": {"filter": selecao_igual(
                col["Expression"]["SourceRef"]["Entity"], col["Property"], inicio)}}]
        self.add(nome, "slicer", x, y, w, h, {"Values": [proj(campo)]}, objetos=objetos)

    def salvar(self, pasta):
        pasta = pasta / self.nome
        page = {"$schema": f"{SCHEMA}/page/2.0.0/schema.json", "name": self.nome, "displayName": self.titulo,
                "displayOption": "FitToPage", "height": 720, "width": 1280}
        if self.interacoes:
            page["visualInteractions"] = [{"source": s, "target": t, "type": "NoFilter"} for s, t in self.interacoes]
        escrever(pasta / "page.json", page)
        for v in self.visuais:
            escrever(pasta / "visuals" / v["name"] / "visual.json", v)


def escrever(caminho, obj):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def slicers_globais(p):
    p.segmentador("sSegmento", 872, 4, 186, 66, coluna("dim_clientes", "segmento"), "Segmento")
    p.segmentador("sRating", 1070, 4, 186, 66, coluna("clientes_score_preditivo", "faixa_risco"), "Rating")


# ---------------------------------------------------------------- páginas
def pagina_executiva():
    p = Pagina("p1_executivo", "Visão Executiva de Crédito e Cobrança",
               "Carteira a receber, inadimplência, prazo médio de recebimento e provisão — foto na data de corte")
    slicers_globais(p)
    p.linha_cartoes(76, [
        ("cAR", medida("Carteira Total Ativa (AR)"), "Carteira Total Ativa (AR)", True),
        ("cOverdue", medida("% Inadimplência"), "% Inadimplência (Overdue)"),
        ("cNPL", medida("% Inadimplência 90+"), "% Inadimplência 90+ (NPL)"),
        ("cDSO", medida("DSO (dias)"), "DSO (dias)"),
        ("cPDD", medida("PDD Estimada"), "PDD Estimada", True),
        ("cCobertura", medida("% Cobertura PDD"), "% Cobertura PDD sobre Vencido"),
    ])
    mes = coluna("dim_calendario", "Mês/Ano")
    p.add("gInadPDD", "lineClusteredColumnComboChart", 24, 184, 780, 300,
          {"Category": [mes], "Y": [medida("PDD Estimada")], "Y2": [medida("% Inadimplência")]},
          titulo="Evolução mensal: PDD Estimada (colunas) × % Inadimplência (linha)", filtros=filtro_data_minima())
    p.add("gSegmento", "clusteredBarChart", 816, 184, 440, 300,
          {"Category": [coluna("dim_clientes", "segmento")], "Y": [medida("% Inadimplência")]},
          titulo="% Inadimplência por segmento", ordem=(medida("% Inadimplência"), "Descending"),
          objetos={"labels": [{"properties": {"show": lit(True)}}]})
    p.add("gCaixa", "lineChart", 24, 496, 610, 208,
          {"Category": [mes], "Y": [medida("Faturamento"), medida("Recebimentos")]},
          titulo="Faturamento × Recebimentos", filtros=filtro_data_minima())
    p.add("gDSO", "lineChart", 646, 496, 610, 208,
          {"Category": [mes], "Y": [medida("DSO (dias)")]},
          titulo="DSO — prazo médio de recebimento (dias)", filtros=filtro_data_minima(),
          objetos={"labels": [{"properties": {"show": lit(True)}}]})
    return p


def pagina_aging():
    p = Pagina("p2_aging", "Gestão de Aging List",
               "Onde está o atraso — régua de PDD por faixa e drill-down Segmento → Cliente → Fatura")
    slicers_globais(p)
    p.linha_cartoes(76, [
        ("cVencido", medida("Valor Vencido"), "Valor Vencido", True),
        ("cVencido90", medida("Valor Vencido 90+"), "Vencido 90+", True),
        ("cAtrasoMedio", medida("Atraso Médio Ponderado (dias)"), "Atraso médio ponderado (dias)"),
        ("cFaturas", medida("Faturas em Aberto"), "Faturas em aberto"),
        ("cClientesAtraso", medida("Clientes em Atraso"), "Clientes em atraso"),
    ])
    faixa = coluna("dim_aging", "Faixa")
    p.add("gAging", "clusteredColumnChart", 24, 184, 480, 250,
          {"Category": [faixa], "Y": [medida("Carteira Total Ativa (AR)")]},
          titulo="Carteira por faixa de Aging", ordem=(faixa, "Ascending"),
          objetos={"labels": [{"properties": {"show": lit(True)}}]})
    p.add("tRegua", "tableEx", 24, 446, 480, 258,
          {"Values": [proj(faixa), proj(medida("Taxa PDD da Faixa"), "Taxa"),
                      proj(medida("Carteira Total Ativa (AR)"), "Carteira"), proj(medida("PDD Estimada"), "PDD"),
                      proj(medida("% da Carteira"), "% carteira")]},
          titulo="Régua de PDD (matriz de provisão — CPC 48)", ordem=(faixa, "Ascending"))
    carteira = medida("Carteira Total Ativa (AR)")
    p.add("mAging", "pivotTable", 516, 184, 740, 520,
          {"Rows": [coluna("dim_clientes", "segmento"), coluna("dim_clientes", "nome_cliente"),
                    coluna("fato_faturas", "fatura_id")],
           "Columns": [faixa], "Values": [carteira]},
          titulo="Aging List — clique em + para descer até cliente e fatura",
          objetos={"values": [{"properties": {"backColor": cor(medida("Cor Risco Aging"))},
                               "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}],
                                            "metadata": f"{M}.Carteira Total Ativa (AR)"}}]})
    return p


def pagina_preditivo():
    p = Pagina("p3_preditivo", "Score de Risco Preditivo",
               "Probabilidade de Default (atraso > 90 dias) — Regressão Logística, AUC 0,87 — rating A a E")
    slicers_globais(p)
    p.linha_cartoes(76, [
        ("cClientes", medida("Clientes"), "Clientes"),
        ("cPDPond", medida("PD Ponderada pela Exposição"), "PD ponderada pela exposição"),
        ("cEL", medida("Perda Esperada (EL)"), "Perda Esperada (PD × EAD × LGD)", True),
        ("cLimDisp", medida("Limite Disponível"), "Limite disponível", True),
        ("cLimDE", medida("Limite Exposto em Alto Risco (D/E)"), "Limite exposto em rating D/E", True),
    ])
    rating = coluna("clientes_score_preditivo", "faixa_risco")
    p.add("gRating", "clusteredColumnChart", 24, 184, 370, 260,
          {"Category": [rating], "Y": [medida("Clientes")]},
          titulo="Clientes por rating", ordem=(rating, "Ascending"),
          objetos={"labels": [{"properties": {"show": lit(True)}}]})
    p.add("gImportancia", "clusteredBarChart", 406, 184, 410, 260,
          {"Category": [coluna("feature_importance", "variavel")],
           "Y": [medida("Importância (Logit)"), medida("Importância (Random Forest)")]},
          titulo="O que explica o risco (Feature Importance)", ordem=(medida("Importância (Logit)"), "Descending"),
          objetos={"categoryAxis": [{"properties": {"maxMarginFactor": lit(45)}}]})
    p.add("gDispersao", "scatterChart", 828, 184, 428, 260,
          {"Category": [coluna("dim_clientes", "nome_cliente")], "Series": [rating],
           "X": [proj(medida("PD Média"), "PD")], "Y": [medida("Limite Disponível")],
           "Size": [medida("Carteira Total Ativa (AR)")]},
          titulo="Limite disponível × PD (bolha = carteira)")
    p.add("tAcao", "tableEx", 24, 456, 790, 248,
          {"Values": [proj(coluna("dim_clientes", "nome_cliente"), "Cliente"), proj(rating, "Rating"),
                      proj(coluna("clientes_score_preditivo", "probabilidade_default"), "PD"),
                      proj(medida("Limite Disponível"), "Limite disp."),
                      proj(medida("Carteira Total Ativa (AR)"), "Carteira"),
                      proj(coluna("clientes_score_preditivo", "fator_risco_1"), "Principal fator de risco")]},
          titulo="Lista de ação — clientes D/E: rever limite e cobrança preventiva",
          ordem=(medida("Limite Disponível"), "Descending"),
          filtros=filtro_in("clientes_score_preditivo", "faixa_risco", ["D", "E"]))
    p.add("mRatingSeg", "pivotTable", 826, 456, 430, 248,
          {"Rows": [rating], "Columns": [coluna("dim_clientes", "segmento")],
           "Values": [medida("Perda Esperada (EL)")]},
          titulo="Perda Esperada por rating × segmento")
    return p


def pagina_simulador():
    p = Pagina("p4_simulador", "Simulador What-If de Política de Crédito",
               "Backtest: se há 9 meses reprovássemos todo cliente com PD acima do corte, quanto ganharíamos?")
    p.segmentador("sCorte", 24, 76, 300, 96, coluna("Corte PD", "Corte PD"), "PD máxima aceitável (corte)", "Single",
                  inicio=0.2)
    p.segmentador("sMargem", 336, 76, 300, 96, coluna("Margem Contribuição", "Margem Contribuição"),
                  "Margem de contribuição", "Single", inicio=0.1)
    p.cartao("cCorteOtimo", 648, 76, 196, 96, medida("Corte Ótimo de PD"), "Corte ótimo de PD")
    p.cartao("cImpactoOtimo", 856, 76, 196, 96, medida("Impacto no Corte Ótimo"), "Impacto no corte ótimo",
             milhoes=True)
    p.cartao("cAprovacao", 1064, 76, 192, 96, medida("Sim Taxa de Aprovação"), "Taxa de aprovação")
    p.linha_cartoes(184, [
        ("cPDDEvitada", medida("Sim PDD Evitada (Economia de Risco)"), "PDD evitada (economia de risco)", True),
        ("cMargemPerdida", medida("Sim Margem Perdida"), "Margem perdida (custo de oportunidade)", True),
        ("cImpacto", medida("Sim Impacto Líquido"), "Impacto líquido na margem", True),
        ("cReprovados", medida("Sim Clientes Reprovados"), "Clientes reprovados"),
        ("cInadPos", medida("Sim % Inadimplência Pós-Política"), "% Inadimplência pós-política"),
    ])
    # cartão de impacto colorido (verde/vermelho)
    impacto = next(v for v in p.visuais if v["name"] == "cImpacto")
    impacto["visual"]["objects"]["labels"][0]["properties"]["color"] = cor(medida("Cor Impacto Líquido"))
    p.add("gTradeoff", "lineChart", 24, 292, 1232, 320,
          {"Category": [coluna("Corte PD", "Corte PD")],
           "Y": [proj(medida("Sim PDD Evitada (Economia de Risco)"), "PDD evitada"),
                 proj(medida("Sim Margem Perdida"), "Margem perdida"),
                 proj(medida("Sim Impacto Líquido"), "Impacto líquido")]},
          titulo="Curva de trade-off Receita × Risco — o pico da linha de impacto líquido é o corte ótimo")
    p.interacoes.append(("sCorte", "gTradeoff"))
    p.cartao("cNarrativa", 24, 624, 1232, 80, medida("Sim Narrativa"), "Leitura do cenário", tamanho=13.0)
    return p


def main():
    if DEF.exists():
        shutil.rmtree(DEF)
    tema = "TemaRiscoCredito.json"
    escrever(RAIZ / "StaticResources" / "RegisteredResources" / tema, TEMA)
    escrever(DEF / "version.json", {"$schema": f"{SCHEMA}/versionMetadata/1.0.0/schema.json", "version": "2.0.0"})
    escrever(DEF / "report.json", {
        "$schema": f"{SCHEMA}/report/3.0.0/schema.json",
        "themeCollection": {"customTheme": {
            "name": tema, "type": "RegisteredResources",
            "reportVersionAtImport": {"visual": "2.4.0", "report": "3.0.0", "page": "2.0.0"}}},
        "resourcePackages": [{"name": "RegisteredResources", "type": "RegisteredResources",
                              "items": [{"name": tema, "path": tema, "type": "CustomTheme"}]}],
        "settings": {"useStylableVisualContainerHeader": True, "defaultDrillFilterOtherVisuals": True},
    })
    paginas = [pagina_executiva(), pagina_aging(), pagina_preditivo(), pagina_simulador()]
    for p in paginas:
        p.salvar(DEF / "pages")
    escrever(DEF / "pages" / "pages.json", {"$schema": f"{SCHEMA}/pagesMetadata/1.0.0/schema.json",
                                             "pageOrder": [p.nome for p in paginas],
                                             "activePageName": paginas[0].nome})
    print(f"{len(paginas)} páginas, {sum(len(p.visuais) for p in paginas)} visuais -> {DEF}")


if __name__ == "__main__":
    main()
