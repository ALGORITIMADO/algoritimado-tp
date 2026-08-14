#!/usr/bin/env python
"""Audita as fontes de comparáveis contra o dado VIVO — SEC EDGAR e CVM.

Por que existe: a seed list do EDGAR apodrece em silêncio. Empresa é adquirida,
muda de tag no XBRL ou para de publicar subtotal de resultado operacional, e o
assento vira uma cadeira vazia sem ninguém perceber. Foi assim que Emerson e GE
ficaram meses sem entregar comparável — descobrimos por acidente, quando um lead
real buscou manufatura e recebeu 4 empresas em vez de 6.

Este script troca "descobrir por acidente" por "conferir quando quiser".

    ./scripts/audit_comparables.py                    # ambas as fontes, 2 anos
    ./scripts/audit_comparables.py --years 2024 2025
    ./scripts/audit_comparables.py --source edgar --sector Manufacturing
    ./scripts/audit_comparables.py --source cvm

Sai com código 1 se houver assento morto no EDGAR ou setor da CVM abaixo do
mínimo de 3 comparáveis que o cálculo do IQR exige — dá para usar em automação.

NÃO roda no CI: depende de rede e das APIs públicas da SEC e da CVM.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

import data.edgar_fetcher as ef  # noqa: E402
import data.cvm_fetcher as cf  # noqa: E402

MIN_COMPARABLES = 3        # mínimo absoluto do IQR (calculations/base.py)
RECOMMENDED = 5            # IN RFB 2.161/2023 recomenda 5+
SEC_PAUSE = 0.12           # a SEC limita ~10 req/s; folga deliberada


def _tickers_by_cik():
    """CIK -> ticker atual. Um CIK ausente sugere baixa/aquisição."""
    try:
        r = requests.get("https://www.sec.gov/files/company_tickers.json",
                         headers=ef.HEADERS, timeout=30)
        return {v["cik_str"]: v["ticker"] for v in r.json().values()}
    except Exception as e:
        print(f"  (aviso: não consegui baixar company_tickers.json — {e})")
        return {}


from data.fiscal_calendar import latest_available_fiscal_year

# A auditoria seguia fixada em 2024 — auditava o ano errado justamente na
# temporada em que o Arquivo Local documenta 2025.
_LATEST = latest_available_fiscal_year()


def audit_edgar(years, sector_filter=None):
    """Cada seed entrega margem operacional em algum dos anos pedidos?"""
    print(f"\n{'='*74}\nSEC EDGAR — seed list por setor (anos {', '.join(map(str, years))})\n{'='*74}")
    listados = _tickers_by_cik()
    mortos, sem_ticker, total = [], [], 0

    for setor, seeds in ef.SIC_MAP.items():
        if sector_filter and sector_filter.lower() not in setor.lower():
            continue
        vivos = []
        for cik, nome in seeds:
            total += 1
            facts = ef.get_company_facts_v2.__wrapped__(cik)
            time.sleep(SEC_PAUSE)
            margens = {}
            for ano in years:
                fin = ef.extract_financials(facts, target_year=ano) if facts else None
                if fin and "operating_margin" in fin:
                    margens[ano] = fin["operating_margin"]
            if margens:
                vivos.append((nome, margens))
            else:
                mortos.append((setor, cik, nome))
            if listados and cik not in listados:
                sem_ticker.append((setor, cik, nome))

        marca = "OK " if len(vivos) >= RECOMMENDED else ("!! " if len(vivos) >= MIN_COMPARABLES else "XX ")
        print(f"\n{marca}{setor}  —  {len(vivos)}/{len(seeds)} entregam margem operacional")
        for nome, margens in vivos:
            texto = "  ".join(f"{a}: {m:>7.2f}%" for a, m in sorted(margens.items()))
            print(f"      {nome[:38]:38s} {texto}")
        for _, cik, nome in [m for m in mortos if m[0] == setor]:
            print(f"      {nome[:38]:38s} CIK {cik} — SEM MARGEM OPERACIONAL")

    print(f"\n{'-'*74}\nEDGAR: {total - len(mortos)}/{total} assentos úteis")
    if sem_ticker:
        print("\nCIKs que sumiram do company_tickers.json (aquisição? baixa de registro?):")
        for setor, cik, nome in sem_ticker:
            print(f"   {setor:34s} {nome[:30]:30s} CIK {cik}")
    return mortos


def audit_cvm(year, sector_filter=None):
    """Quantos comparáveis a CVM realmente devolve por setor, hoje."""
    print(f"\n{'='*74}\nCVM — comparáveis por setor (exercício {year})\n{'='*74}")
    cad = cf.get_cvm_company_list.__wrapped__()
    if cad is None or cad.empty:
        print("  não consegui baixar o cadastro de companhias abertas")
        return ["cadastro indisponível"]
    print(f"  pool de candidatos: {len(cad)} companhias ativas em fase operacional")

    magros = []
    for setor in cf.CNAE_MAP:
        if sector_filter and sector_filter.lower() not in setor.lower():
            continue
        df = cf.fetch_comparables_cvm(industry=setor, year=year, limit=15,
                                      pli="operating_margin")
        n = len(df)
        marca = "OK " if n >= RECOMMENDED else ("!! " if n >= MIN_COMPARABLES else "XX ")
        print(f"  {marca}{setor:36s} {n:2d} comparáveis")
        if n < MIN_COMPARABLES:
            magros.append((setor, n))
    if magros:
        print(f"\n  Abaixo do mínimo de {MIN_COMPARABLES} para o IQR:")
        for setor, n in magros:
            print(f"    {setor} ({n})")
    return magros


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", choices=["edgar", "cvm", "ambas"], default="ambas")
    p.add_argument("--years", type=int, nargs="+", default=[_LATEST - 1, _LATEST],
                   help="exercícios a testar no EDGAR (padrão: 2024 2025)")
    p.add_argument("--cvm-year", type=int, default=_LATEST,
                   help="exercício da DFP a testar na CVM (padrão: 2024)")
    p.add_argument("--sector", help="filtra por trecho do nome do setor")
    args = p.parse_args()

    problemas = []
    if args.source in ("edgar", "ambas"):
        problemas += audit_edgar(args.years, args.sector)
    if args.source in ("cvm", "ambas"):
        problemas += audit_cvm(args.cvm_year, args.sector)

    print()
    if problemas:
        print(f"⚠️  {len(problemas)} problema(s) — ver acima.")
        return 1
    print("✅ Nenhum assento morto e nenhum setor abaixo do mínimo do IQR.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
