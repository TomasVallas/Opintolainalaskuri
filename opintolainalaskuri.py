#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Opintolainalaskuri - Nordea, Danske Bank ja OP
==============================================

Offline-työpöytäsovellus. Vaatii Pythonin (3.8+), jossa on Tkinter.
Pillow (PIL) tekee kuvaajasta ja säätimistä pehmeäreunaiset; ilman sitä
sovellus toimii silti, mutta grafiikka on karkeampi.

Käynnistys:  python opintolainalaskuri.py   (tai tuplaklikkaa Kaynnista.bat)

Oletusarvot tarkistettu 2.11.2026:
  * Kela: opintolaina 850 €/kk, takaus aikaisintaan hakukuukaudesta alkaen,
    korot pääomitetaan 15.6. ja 15.12. + yksi lukukausi tuen jälkeen,
    hyvitys 40 % 2 500 € ylittävästä osasta, katto tutkinnon mukaan
    (300 op -> 18 000 € lainaa / 6 200 € hyvitystä). Hyvityksen pohja =
    valmistuessa jäljellä oleva laina − kaikki pääomitetut korot (HE 116/2013),
    joten opintojen aikana maksetut korot pienentävät pohjaa.
  * Nordea: 12 kk Euribor + 0,50 %, avaus 0 €, korotus verkossa 10 €,
    automaattiset nostot 0 €, 2,50 € / veloitus, ylim. lyhennys 0 €.
  * Danske Bank (Akava-opiskelijaetu): 0 % marginaali 5 v, sen jälkeen 0,50 %,
    ei avaus-, nosto- eikä korotuspalkkioita, 2,50 € / maksuerä.
  * OP (omistaja-asiakas, 100 € osuusmaksu): 12 kk Euribor + marginaali (pankkikohtainen,
    vertailusivut n. 0,5 %), toimitusmaksu 0 € (muuten 30 €), nostot Kelan erissä 0 €,
    2,50 € / veloitus. OP-bonukset 2026: 0,4 %/v lainasaldosta, 30 % ennakonpidätys
    (netto 0,28 %), maksetaan kuukausittain ja saa rahana tilille.
  * 12 kk Euribor 3,306 % (30.10.2026).
  * Nordnet: Helsinki 0,06–0,20 % (min. 3–9 €), Xetra n. 0,20 % (min. 15 €),
    Nordnet Maailma Indeksi 0 € kaupat / 0,30 % juokseva kulu, valuutanvaihto 0,25 %.
  * Verotus: pääomatulo 30 % (34 % yli 30 000 €), pienet luovutukset (myyntihinnat
    enintään 1 000 €/v) verovapaita, hankintameno-olettama 20 % / 40 % (≥ 10 v),
    listattujen yhtiöiden osingoista 85 % veronalaista. OST: vain osakkeita,
    talletusraja 100 000 €, vero vasta nostosta (voitto-osuuden suhteessa).
Korko lasketaan todelliset päivät / 360 (vastaa Dansken omaa esimerkkilaskelmaa).
"""

import calendar
import datetime as dt
import math
import os
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
#  Laskentamoottori
# ---------------------------------------------------------------------------

DEGREES = [
    ("Yliopisto, kandi + maisteri 300 op", 18000.0),
    ("Yliopisto, kandi + maisteri 330 op", 20000.0),
    ("Yliopisto, kandi + maisteri 360 op", 21600.0),
    ("AMK / alempi tutkinto 180 op", 10800.0),
    ("AMK / alempi tutkinto 210 op", 12800.0),
    ("AMK / alempi tutkinto 240 op", 14400.0),
    ("AMK / alempi tutkinto 270 op", 16400.0),
]

PAY_MODES = [
    "Ei – korot pääomitetaan lainaan",
    "Kerran vuodessa (joulukuussa)",
    "Heti jokaisen pääomituksen jälkeen",
    "Vasta valmistumislukukauden jälkeen",
]
PAY_SHORT = {1: "Kerran vuodessa", 2: "Joka pääomituksen jälkeen", 3: "Valmistumisen jälkeen"}

REPAY_TYPES = ["Tasalyhennys", "Tasaerä (annuiteetti)"]

DRAW_MODES = ["Täydet erät, kunnes katto täyttyy", "Tasaisesti kaikille kuukausille"]

REPAY_STARTS = ["Pankin aikataulu", "Hyvityksen jälkeen"]

ACCOUNTS = ["AOT", "OST"]

SELL_MODES = ["Kuukausittain (kun erä erääntyy)", "Kerran vuodessa (12 kk:n puskuri)"]

# (nimi, kulut, laji) – Nordnetin hinnat 2026
INVEST_PRESETS = [
    ("Nordnet Maailma Indeksi (rahasto)",
     dict(fee_pct=0.0, min_fee=0.0, fx_pct=0.0, ter_pct=0.30, dividend_pct=0.0, account_fee=0.0), "rahasto"),
    ("ETF Xetrasta, kasvuosuus (esim. MSCI World)",
     dict(fee_pct=0.20, min_fee=15.0, fx_pct=0.0, ter_pct=0.20, dividend_pct=0.0, account_fee=0.0), "ETF"),
    ("ETF-kuukausisäästö (myynnit normaalihinnalla)",
     dict(fee_pct=0.20, min_fee=15.0, fx_pct=0.0, ter_pct=0.20, dividend_pct=0.0, account_fee=2.50), "ETF"),
    ("Suomalaiset osakkeet (Helsinki, taso 3)",
     dict(fee_pct=0.15, min_fee=7.0, fx_pct=0.0, ter_pct=0.0, dividend_pct=3.0, account_fee=0.0), "osake"),
    ("Yhdysvaltain osakkeet (valuutanvaihto 0,25 %)",
     dict(fee_pct=0.15, min_fee=15.0, fx_pct=0.25, ter_pct=0.0, dividend_pct=1.5, account_fee=0.0), "osake"),
    ("Oma", None, "oma"),
]
INVEST_FIELDS = ("fee_pct", "min_fee", "fx_pct", "ter_pct", "dividend_pct", "account_fee")


@dataclass
class Settings:
    start_year: int
    start_month: int
    monthly_draw: float = 850.0
    years_left: int = 3
    months_per_year: int = 9
    draw_cap_on: bool = False      # nostetaan enintään draw_cap euroa
    draw_cap: float = 18000.0
    cap_plus_paid: bool = True     # sweet spot: kattoon lisätään opintojen aikana maksettavat korot
    draw_even: bool = False        # True = katto jaetaan tasan kaikille kuukausille
    euribor: float = 3.306
    repay_years: float = 7.0       # 0 = koko laina kerralla
    repay_start: int = 0           # 0 = pankin aikataulu, 1 = heti hyvityksen jälkeen
    repay_type: str = "Tasalyhennys"
    credit_on: bool = True
    credit_pct: float = 40.0
    credit_deductible: float = 2500.0
    credit_max_loan: float = 18000.0
    pay_interest: int = 0          # 0 = ei, 1 = kerran vuodessa, 2 = jokaisen pääomituksen jälkeen,
                                   # 3 = vasta valmistumislukukauden jälkeen (ei pienennä hyvitystä)
    return_pct: float = 6.0        # kokonaistuotto %/v ennen kuluja (sis. osingot)
    tax_pct: float = 30.0
    account: str = "AOT"           # "AOT" = arvo-osuustili, "OST" = osakesäästötili
    fee_pct: float = 0.0           # kaupankäyntipalkkio %
    min_fee: float = 0.0           # minimipalkkio € / kauppa
    fx_pct: float = 0.0            # valuutanvaihto %
    ter_pct: float = 0.0           # juokseva kulu %/v
    dividend_pct: float = 0.0      # osinkotuotto %/v (osa kokonaistuotosta)
    account_fee: float = 0.0       # €/kk
    sell_yearly: bool = False      # myydään kerran vuodessa 12 kk:n tarpeisiin
    small_sale_limit: float = 1000.0


@dataclass
class Bank:
    name: str
    margin: float                  # normaali marginaali %
    promo_margin: float = 0.0      # etumarginaali %
    promo_years: float = 0.0       # etumarginaalin kesto vuosina lainasopimuksesta
    opening_fee: float = 0.0       # ensimmäinen nosto / avaus
    increase_fee: float = 0.0      # jokainen uusi lukuvuosi (lainan korotus)
    draw_fee: float = 0.0          # jokainen nosto
    debit_fee: float = 2.5         # jokainen koron/lyhennyksen veloitus
    extra_payment_fee: float = 0.0  # vapaaehtoinen ylimääräinen lyhennys
    other_fees_year: float = 0.0   # esim. pankkipaketti €/v
    bonus_pct: float = 0.0         # OP-bonukset %/v lainasaldosta (ennen 30 %:n ennakonpidätystä)


BANK_FIELDS = ("margin", "promo_margin", "promo_years", "opening_fee", "increase_fee", "draw_fee",
               "debit_fee", "extra_payment_fee", "other_fees_year", "bonus_pct")

YM = Tuple[int, int]


@dataclass
class Result:
    months: List[YM] = field(default_factory=list)
    balance: List[float] = field(default_factory=list)
    flows_in: List[float] = field(default_factory=list)    # nostot sijoitettavaksi (kulujen jälkeen)
    flows_out: List[float] = field(default_factory=list)   # maksut pankille
    portfolio: List[float] = field(default_factory=list)   # sijoitusten markkina-arvo
    net: List[float] = field(default_factory=list)         # netto verojen jälkeen
    drawn: float = 0.0
    full_draw: float = 0.0         # mitä täydellä nostolla olisi saanut
    sweet_extra: float = 0.0       # sweet spot: kattoon lisätty korkojen määrä
    topup: float = 0.0             # sweet spot -lisänosto valmistumislukukauden lopussa
    topup_month: Optional[YM] = None
    grad_end: Optional[YM] = None  # valmistumislukukauden viimeinen kuukausi (hyvityksen pohja lukitaan)
    schedule: List[Tuple[YM, str, float]] = field(default_factory=list)  # nostot, pääomitukset, maksut
    n_draws: int = 0
    n_support_months: int = 0
    interest: float = 0.0
    capitalized: float = 0.0
    capitalized_study: float = 0.0
    fees: float = 0.0
    credit: float = 0.0
    credit_base: float = 0.0
    bonus_gross: float = 0.0       # OP-bonukset ennen veroa
    bonus_net: float = 0.0         # OP-bonukset 30 %:n ennakonpidätyksen jälkeen
    paid_to_bank: float = 0.0
    paid_early: float = 0.0
    paid_early_study: float = 0.0
    inv_costs: float = 0.0         # kaupankäynti, valuutanvaihto, juokseva kulu, tilimaksut
    inv_taxes: float = 0.0         # jo maksetut verot (myyntivoitot, osingot, nostot)
    tax_total: float = 0.0         # verot yhteensä, kun loputkin myydään
    own_money: float = 0.0
    payoff_after_tax: float = 0.0  # salkku verojen jälkeen, kun laina on maksettu
    payoff_net: float = 0.0        # sama miinus oma raha
    final_after_tax: float = 0.0   # tarkastelujakson lopussa
    final_net_after_tax: float = 0.0
    graduation: Optional[YM] = None
    last_draw: Optional[YM] = None
    last_support: Optional[YM] = None
    last_cap: Optional[YM] = None
    credit_month: Optional[YM] = None
    amort_start: Optional[YM] = None
    payoff: Optional[YM] = None
    i_end: int = -1
    n_payments: int = 0
    events: List[Tuple[int, str]] = field(default_factory=list)


def add_months(y: int, m: int, k: int) -> YM:
    t = y * 12 + (m - 1) + k
    return t // 12, t % 12 + 1


def _loan(s: Settings, b: Bank, horizon: int = 0, topup: float = 0.0) -> Result:
    """Opintolainan kassavirrat kuukausittain (ei sijoituksia).
    topup = sweet spot -lisänosto valmistumislukukauden viimeisenä kuukautena."""
    res = Result()
    y0, m0 = s.start_year, s.start_month

    def idx(ym: YM) -> int:
        return (ym[0] - y0) * 12 + (ym[1] - m0)

    # --- Tukikuukaudet ja nostoerät lukukausittain ------------------------
    ay0 = y0 if m0 >= 8 else y0 - 1
    order = [9, 10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8]
    k_months = max(0, min(12, int(s.months_per_year)))
    years = max(0, int(s.years_left))
    groups: List[Tuple[int, int, int, YM, YM]] = []   # (idx, kk-määrä, lukuvuosi, eka kk, vika kk)
    support: List[YM] = []
    for k in range(years):
        elig = []
        for m in order[:k_months]:
            yr = ay0 + k if m >= 8 else ay0 + k + 1
            if (yr, m) < (y0, m0):
                continue                      # takausta ei saa takautuvasti
            if k == years - 1 and m in (6, 7):
                continue                      # ei kesää valmistumisen jälkeen
            elig.append((yr, m))
        sem: Dict[str, List[YM]] = {}
        for ym in elig:
            key = "syksy" if ym[1] >= 8 else ("kesä" if ym[1] >= 6 else "kevät")
            sem.setdefault(key, []).append(ym)
        for key in sorted(sem, key=lambda g: min(sem[g])):
            lst = sem[key]
            groups.append((idx(min(lst)), len(lst), k, min(lst), max(lst)))
        support += elig

    if not support or s.monthly_draw <= 0:
        return res

    # --- Nostojen määrät (mahdollinen katto) ------------------------------
    total_months = sum(g[1] for g in groups)
    res.full_draw = total_months * s.monthly_draw
    capped = s.draw_cap_on and s.draw_cap < res.full_draw
    amounts = []
    if not capped:
        amounts = [g[1] * s.monthly_draw for g in groups]
    elif s.draw_even:
        per = max(0.0, s.draw_cap) / total_months
        amounts = [g[1] * per for g in groups]
    else:
        left = max(0.0, s.draw_cap)
        for g in groups:
            a = min(g[1] * s.monthly_draw, left)
            left -= a
            amounts.append(a)

    draws: Dict[int, List[Tuple[float, float, str]]] = {}
    years_seen = set()
    for (i, nm, k, first_ym, last_ym), a in zip(groups, amounts):
        if a <= 0.005:
            continue
        fee = b.draw_fee
        if k not in years_seen:
            fee += b.opening_fee if not years_seen else b.increase_fee
            years_seen.add(k)
        draws.setdefault(i, []).append((a, fee, "draw"))
        res.n_draws += 1
        res.n_support_months += nm
        res.last_draw = first_ym
        res.last_support = last_ym
    if not draws:
        return res

    # --- Aikataulu ---------------------------------------------------------
    grad = max(support)                      # opinnot päättyvät
    res.graduation = grad
    gy, gm = grad
    if gm <= 7:      # valmistuminen kevätlukukaudella
        grad_end, credit_at = (gy, 7), (gy, 11)
    else:            # syyslukukaudella
        grad_end, credit_at = (gy, 12), (gy + 1, 4)
    ly, lm = res.last_support                # pääomitus: tuen ajan + 1 lukukausi
    last_cap = (ly, 12) if lm <= 7 else (ly + 1, 6)
    io1, io2 = add_months(*last_cap, 6), add_months(*last_cap, 12)
    T = max(0, int(round(s.repay_years * 12)))
    if s.repay_start == 1:
        amort_start = credit_at if T == 0 else add_months(*credit_at, 1)
    else:
        amort_start = add_months(*io2, 1)
    end = amort_start if T == 0 else add_months(*amort_start, T - 1)
    res.last_cap, res.credit_month = last_cap, credit_at
    res.amort_start, res.payoff = amort_start, end
    res.n_payments = max(1, T)
    res.grad_end = grad_end

    i_grad, i_credit, i_cap = idx(grad_end), idx(credit_at), idx(last_cap)

    # Sweet spot: lisäerä nostetaan valmistumislukukauden erän mukana (valmistumisen jälkeen ei
    # voi enää nostaa, Kela). Siihen mennessä maksetut pääomitukset ovat tiedossa sentilleen.
    # Valmistumislukukauden omat pääomitukset maksetaan vasta lukukauden päätyttyä (1.8./1.1.),
    # jolloin hyvityksen pohja on jo lukittu.
    sweet = s.draw_cap_on and s.cap_plus_paid and s.pay_interest in (1, 2)
    i_top = groups[-1][0]
    last_year = groups[-1][2]
    room = sum(nm * s.monthly_draw - a for (_i, nm, k, _f, _l), a in zip(groups, amounts) if k == last_year)
    t_amt = max(0.0, min(topup, room)) if sweet else 0.0
    if t_amt > 0.005:
        draws.setdefault(i_top, []).append((t_amt, b.draw_fee, "topup"))
        res.n_draws += 1
        res.topup, res.topup_month = t_amt, add_months(y0, m0, i_top)
    i_io = {idx(io1), idx(io2)}
    i_am, i_end = idx(amort_start), idx(end)
    res.i_end = i_end
    n = max(i_end + 1, int(horizon))
    res.flows_in = [0.0] * n
    res.flows_out = [0.0] * n

    bal = accrued = cap_unpaid = 0.0
    fixed_principal = None
    deferred = False

    def out(i: int, a: float) -> None:
        if a > 0:
            res.flows_out[i] += a
            res.paid_to_bank += a

    def extra_payment(i: int) -> None:
        nonlocal bal, cap_unpaid
        a = cap_unpaid
        cap_unpaid = 0.0
        bal -= a
        res.paid_early += a
        if i <= i_grad:
            res.paid_early_study += a
        res.fees += b.extra_payment_fee
        out(i, a + b.extra_payment_fee)
        res.schedule.append((add_months(y0, m0, i), "pay", a))

    for i in range(n):
        y, m = add_months(y0, m0, i)
        active = i <= i_end
        if active:
            days = calendar.monthrange(y, m)[1]
            margin = b.promo_margin if i < b.promo_years * 12 else b.margin
            rate = max(0.0, s.euribor + margin) / 100.0   # ei negatiivista korkoa

            # Nostot kuun alussa, nostokulu vähennetään nostettavasta summasta
            for amount, fee, kind in draws.get(i, []):
                bal += amount
                res.drawn += amount
                res.fees += fee
                res.paid_to_bank += fee
                res.flows_in[i] += amount - fee
                res.schedule.append(((y, m), kind, amount))

            # Korko kertyy (todelliset päivät / 360). Pääomitus- ja korkokuukausina korko
            # lasketaan ensin 15. päivään asti; kuun loppu kertyy seuraavaan jaksoon.
            is_cap = m in (6, 12) and i <= i_cap and i < i_am
            is_io = m in (6, 12) and i in i_io and i < i_am and not is_cap
            d1 = 14 if (is_cap or is_io) else days
            it = bal * rate * d1 / 360.0
            accrued += it
            res.interest += it

            if b.other_fees_year:
                res.fees += b.other_fees_year / 12.0
                out(i, b.other_fees_year / 12.0)

            if is_cap:
                # Pääomitus 15.6. ja 15.12.
                bal += accrued
                res.capitalized += accrued
                if i <= i_grad:
                    res.capitalized_study += accrued
                cap_unpaid += accrued
                res.schedule.append(((y, m), "cap", accrued))
                accrued = 0.0
                if (s.pay_interest == 2 or (s.pay_interest == 1 and (m == 12 or i == i_cap))
                        or (s.pay_interest == 3 and i > i_grad)):
                    if sweet and i_top <= i <= i_grad:
                        deferred = True          # maksetaan vasta valmistumislukukauden jälkeen
                    else:
                        extra_payment(i)
            elif is_io:
                # Tuen jälkeen pankki perii pelkät korot kaksi kertaa
                a = accrued
                accrued = 0.0
                res.fees += b.debit_fee
                out(i, a + b.debit_fee)
                res.schedule.append(((y, m), "io", a))
            if d1 < days:
                it = bal * rate * (days - d1) / 360.0
                accrued += it
                res.interest += it

            # Valmistumislukukauden jälkeen pääomitetut korot pois kerralla.
            # Hyvityksen pohja on jo lukittu, joten maksu ei pienennä hyvitystä.
            if (s.pay_interest == 3 or deferred) and i == i_grad + 1 and i < i_am and cap_unpaid > 0:
                extra_payment(i)

            # Opintolainahyvitys: Kela maksaa suoraan pankkiin.
            # Pohja = jäljellä oleva laina − kaikki pääomitetut korot (HE 116/2013, 15 f §),
            # eli opintojen aikana maksetut korot pienentävät pohjaa.
            if i == i_credit:
                res.credit_base = max(0.0, res.drawn - res.paid_early_study)
                if s.credit_on and res.credit_base > s.credit_deductible:
                    c = s.credit_pct / 100.0 * (min(s.credit_max_loan, res.credit_base) - s.credit_deductible)
                    c = max(0.0, min(c, bal))
                    bal -= c
                    res.credit = c
                    fixed_principal = None
                    res.schedule.append(((y, m), "credit", c))

            # Takaisinmaksu kuukausittain (tai kerralla)
            if i_am <= i <= i_end:
                left = i_end - i + 1
                if left == 1:
                    principal = bal
                elif s.repay_type.startswith("Tasaerä"):
                    r_m = rate * 365.0 / 360.0 / 12.0
                    payment = bal * r_m / (1.0 - (1.0 + r_m) ** -left) if r_m > 0 else bal / left
                    principal = max(0.0, payment - accrued)
                else:
                    if fixed_principal is None:
                        fixed_principal = bal / left
                    principal = fixed_principal
                principal = min(principal, bal)
                a = accrued + principal
                accrued = 0.0
                bal -= principal
                res.fees += b.debit_fee
                out(i, a + b.debit_fee)

            # OP-bonukset kuukauden lainasaldosta, maksetaan seuraavan kuun alussa rahana
            if b.bonus_pct and bal > 0:
                gross = bal * b.bonus_pct / 100.0 / 12.0
                net = gross * (1.0 - max(0.0, min(0.99, s.tax_pct / 100.0)))
                res.bonus_gross += gross
                res.bonus_net += net
                res.flows_in[min(i + 1, n - 1)] += net

        res.months.append((y, m))
        res.balance.append(bal + accrued if active else 0.0)

    res.events = [(idx(grad), "Valmistuminen"), (i_credit, "Hyvitys")]
    if i_am != i_credit:
        res.events.append((i_am, "Lyhennykset alkavat" if T else "Kertamaksu"))
    return res


def _invest(s: Settings, res: Result, account: str) -> None:
    """Sijoittaa nostot ja maksaa lainan salkusta. AOT: FIFO, myyntivoittovero
    vuosittain, pienten luovutusten vapautus, tappiot vähennetään 5 v.
    OST: ei veroa kaupoista eikä osingoista, nostosta vero voitto-osuuden mukaan."""
    n = len(res.months)
    if n == 0:
        return
    t = max(0.0, min(0.99, s.tax_pct / 100.0))
    d = max(0.0, s.dividend_pct / 100.0)
    price_m = max(1e-9, 1.0 + s.return_pct / 100.0 - d) ** (1.0 / 12.0)
    ter_m = s.ter_pct / 100.0 / 12.0
    p, mn, fx = s.fee_pct / 100.0, s.min_fee, s.fx_pct / 100.0
    ost = account == "OST"
    div_tax = 0.85 * t            # listatut yhtiöt: 85 % veronalaista

    def fee_for(amount: float) -> float:
        return max(mn, p * amount) + fx * amount if amount > 0 else 0.0

    def gross_for_net(net: float) -> float:
        S = net / max(1e-9, 1.0 - p - fx)
        if p * S < mn:
            S = (net + mn) / max(1e-9, 1.0 - fx)
        return S

    nav = 1.0
    lots: List[List[float]] = []   # [osuudet, hankintameno sis. ostokulu, ostokuukausi]
    cash = 0.0       # käteinen tilin ulkopuolella (verot jo maksettu)
    inner = 0.0      # OST: käteinen tilin sisällä
    deposits = 0.0   # OST: talletettu pääoma
    own = 0.0
    year_gain = year_sales = 0.0
    losses: List[List[float]] = []  # [määrä, viimeinen käyttövuosi]
    tax_due = 0.0

    def units_value() -> float:
        return sum(l[0] for l in lots) * nav

    def buy(amount: float, i: int) -> bool:
        f = fee_for(amount)
        if amount <= f + 0.01:
            return False
        lots.append([(amount - f) / nav, amount, i])
        res.inv_costs += f
        return True

    def lot_gain(lot, u, proceeds, fee_part, i) -> float:
        cost = lot[1] * (u / lot[0])
        deemed = (0.4 if i - lot[2] >= 120 else 0.2) * proceeds
        return proceeds - max(cost + fee_part, deemed)

    def sell(S: float, i: int) -> float:
        """Myy FIFO-järjestyksessä arvolla S, palauttaa kulujen jälkeisen summan."""
        nonlocal year_gain, year_sales
        total = units_value()
        S = min(S, total)
        if S <= 0:
            return 0.0
        f = min(fee_for(S), S)
        res.inv_costs += f
        u_left, gain = S / nav, 0.0
        while u_left > 1e-12 and lots:
            lot = lots[0]
            u = min(lot[0], u_left)
            proceeds = u * nav
            gain += lot_gain(lot, u, proceeds, f * proceeds / S, i)
            lot[1] -= lot[1] * (u / lot[0])
            lot[0] -= u
            u_left -= u
            if lot[0] <= 1e-12:
                lots.pop(0)
        if not ost:
            year_gain += gain
            year_sales += S
        return S - f

    def year_tax(gain: float, sales: float, year: int, commit: bool) -> float:
        if sales <= s.small_sale_limit:
            return 0.0
        if gain < 0:
            if commit:
                losses.append([-gain, year + 5])
            return 0.0
        for L in losses:
            if L[1] >= year and gain > 0:
                use = min(L[0], gain)
                gain -= use
                if commit:
                    L[0] -= use
        return t * gain

    def raise_cash(need: float, i: int) -> None:
        """Hankkii `need` euroa käteistä tilin ulkopuolelle."""
        nonlocal cash, inner, deposits
        if need <= 0:
            return
        if not ost:
            cash += sell(gross_for_net(need), i)
            return
        A = units_value() + inner
        if A <= 0:
            return
        gs = max(0.0, 1.0 - deposits / A)
        G = need / (1.0 - gs * t)
        if G > inner:
            inner += sell(gross_for_net(G - inner), i)
        G = min(G, inner)
        A_after = units_value() + inner
        gs = max(0.0, 1.0 - deposits / A_after) if A_after > 0 else 0.0
        tax = G * gs * t
        deposits = max(0.0, deposits - G * (1.0 - gs))
        inner -= G
        res.inv_taxes += tax
        cash += G - tax

    def liquidation(i: int, year: int) -> Tuple[float, float]:
        """(arvo verojen jälkeen, jos kaikki myytäisiin nyt; vielä maksamattomat verot)"""
        S = units_value()
        f = min(fee_for(S), S) if S > 0 else 0.0
        if ost:
            G = S - f + inner
            gs = max(0.0, 1.0 - deposits / G) if G > 0 else 0.0
            return G - G * gs * t + cash, G * gs * t
        gain = 0.0
        for lot in lots:
            proceeds = lot[0] * nav
            gain += lot_gain(lot, lot[0], proceeds, f * proceeds / S if S > 0 else 0.0, i)
        tax_now = year_tax(year_gain + gain, year_sales + S, year, commit=False) + tax_due
        return S - f + cash - tax_now, tax_now

    out_f = res.flows_out
    for i in range(n):
        y, m = res.months[i]
        a = res.flows_in[i]
        if a > 0:
            if ost:
                deposits += a
            if not buy(a, i):
                if ost:
                    inner += a
                else:
                    cash += a
        if lots:
            if d > 0 and m == 5:          # osinko kerran vuodessa, sijoitetaan uudelleen
                dv = units_value() * d
                if not ost:
                    res.inv_taxes += dv * div_tax
                    dv -= dv * div_tax
                if not buy(dv, i):
                    if ost:
                        inner += dv
                    else:
                        cash += dv
            v0 = units_value()
            nav *= price_m * (1.0 - ter_m)
            res.inv_costs += v0 * price_m * ter_m

        need = out_f[i] + s.account_fee
        res.inv_costs += s.account_fee
        if m == 1 and tax_due > 0:      # edellisen vuoden myyntivoittovero
            need += tax_due
            res.inv_taxes += tax_due
            tax_due = 0.0
        if need > 0:
            if cash < need:
                target = need
                if s.sell_yearly:
                    target += sum(out_f[i + 1:i + 12]) + 11 * s.account_fee
                raise_cash(target - cash, i)
            take = min(cash, need)
            cash -= take
            own += need - take

        if not ost and m == 12:
            tax_due += year_tax(year_gain, year_sales, y, commit=True)
            year_gain = year_sales = 0.0

        lv, latent = liquidation(i, y)
        res.portfolio.append(units_value() + cash + inner)
        res.net.append(lv - res.balance[i] - own)
        if i == res.i_end:
            res.payoff_after_tax = lv
            res.payoff_net = lv - own
            res.tax_total = res.inv_taxes + latent

    res.own_money = own
    res.final_after_tax, latent = liquidation(n - 1, res.months[-1][0])
    res.final_net_after_tax = res.final_after_tax - own
    if n - 1 > res.i_end:
        res.tax_total = res.inv_taxes + latent


def simulate(s: Settings, b: Bank, horizon: int = 0, account: Optional[str] = None) -> Result:
    res = _loan(s, b, horizon)
    # Sweet spot: nostetaan katto + opintojen aikana maksettavat korot,
    # jolloin hyvityksen pohjaksi jää tasan katto.
    # Lisäsumma nostetaan erikseen valmistumislukukauden viimeisenä kuukautena.
    if s.draw_cap_on and s.cap_plus_paid and s.pay_interest in (1, 2) and res.drawn:
        extra = 0.0
        for _ in range(20):
            if abs(res.paid_early_study - extra) < 0.005:
                break
            extra = res.paid_early_study
            res = _loan(s, b, horizon, topup=extra)
        res.sweet_extra = res.topup
    _invest(s, res, account or s.account)
    return res


def resource_path(*parts: str) -> str:
    """Tiedostopolku sovelluksen kansiosta (esim. kuvake/kuvake-256.png)."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), *parts)


def default_start() -> YM:
    t = dt.date.today()
    return t.year, t.month


def default_banks() -> List[Bank]:
    return [
        Bank("Nordea", margin=0.50, promo_margin=0.50, promo_years=0, opening_fee=0,
             increase_fee=10, draw_fee=0, debit_fee=2.50, extra_payment_fee=0, other_fees_year=0),
        Bank("Danske Bank", margin=0.50, promo_margin=0.00, promo_years=5, opening_fee=0,
             increase_fee=0, draw_fee=0, debit_fee=2.50, extra_payment_fee=0, other_fees_year=0),
        # OP: omistaja-asiakas (100 € osuusmaksu), toimitusmaksu 0 € (muuten 30 €),
        # nostot Kelan erissä 0 €, marginaali pankkikohtainen (vertailusivut 0,5 %)
        Bank("OP", margin=0.50, promo_margin=0.50, promo_years=0, opening_fee=0,
             increase_fee=0, draw_fee=0, debit_fee=2.50, extra_payment_fee=0, other_fees_year=0,
             bonus_pct=0.40),
    ]

BANK_KEYS = [("nordea", "Nordea"), ("danske", "Danske Bank"), ("op", "OP")]
BANK_SHORT = {"Nordea": "Nordea", "Danske Bank": "Danske", "OP": "OP"}


# ---------------------------------------------------------------------------
#  Muotoilu
# ---------------------------------------------------------------------------

def fmt_num(x: float, dec: int = 0) -> str:
    if abs(round(x, dec)) < 10 ** (-dec) / 2:
        x = 0.0
    s = f"{abs(x):,.{dec}f}".replace(",", " ").replace(".", ",")
    return ("−" if x < 0 else "") + s


def fmt_eur(x: float, dec: int = 0, sign: bool = False) -> str:
    s = fmt_num(x, dec)
    if sign and round(x, dec) > 0:
        s = "+" + s
    elif sign and s in ("0", "0," + "0" * dec):
        s = "±" + s
    return s + " €"


def fmt_ym(ym: Optional[YM]) -> str:
    return f"{ym[1]}/{ym[0]}" if ym else "–"


def nice_ticks(lo: float, hi: float, n: int = 6):
    if hi - lo < 1e-9:
        hi = lo + 1.0
    span = hi - lo
    raw = span / n
    mag = 10 ** math.floor(math.log10(raw))
    step = mag
    for mult in (1, 2, 2.5, 5, 10):
        step = mult * mag
        if span / step <= n:
            break
    tlo = math.floor(lo / step) * step
    thi = math.ceil(hi / step) * step
    ticks, v = [], tlo
    while v <= thi + step * 1e-6:
        ticks.append(v)
        v += step
    return tlo, thi, ticks


def dash_polyline(P, on: float, off: float):
    """Pilkkoo murtoviivan katkoviivan paloiksi."""
    segs, cur = [], [P[0]]
    drawing, remaining = True, on
    for (x0, y0), (x1, y1) in zip(P, P[1:]):
        L = math.hypot(x1 - x0, y1 - y0)
        pos = 0.0
        while L - pos > remaining:
            pos += remaining
            t = pos / L
            pt = (x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
            if drawing:
                cur.append(pt)
                segs.append(cur)
            else:
                cur = [pt]
            drawing = not drawing
            remaining = on if drawing else off
        remaining -= L - pos
        if drawing:
            cur.append((x1, y1))
    if drawing and len(cur) >= 2:
        segs.append(cur)
    return segs


# ---------------------------------------------------------------------------
#  Käyttöliittymä
# ---------------------------------------------------------------------------

import tkinter as tk
from tkinter import ttk
import tkinter.font as tkfont

try:  # pehmeäreunainen grafiikka
    from PIL import Image, ImageDraw, ImageTk
    _BOX = getattr(Image, "Resampling", Image).BOX
    HAVE_PIL = hasattr(ImageDraw.ImageDraw, "rounded_rectangle")
except Exception:  # pragma: no cover
    HAVE_PIL = False

SS = 4  # ylinäytteistys: piirretään 4x tarkkuudella ja pienennetään

C = {
    "bg": "#0B0F15",
    "card": "#121821",
    "card2": "#18202B",
    "input": "#0D1219",
    "border": "#243042",
    "grid": "#1C2533",
    "text": "#E6EDF3",
    "muted": "#8B98AA",
    "faint": "#5A6677",
    "blue": "#3B82F6",
    "blue2": "#60A5FA",
    "sky": "#7DD3FC",
    "purple": "#C084FC",
    "area": "#10213B",
    "red": "#F87171",
    "bad": "#EF4444",
}


class Toggle(tk.Canvas):
    def __init__(self, master, variable: tk.BooleanVar, sc: float, bg: str, command=None):
        self.w, self.h = int(44 * sc), int(24 * sc)
        super().__init__(master, width=self.w, height=self.h, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self.var, self.sc, self.bgcol, self.command = variable, sc, bg, command
        self._imgs: Dict[bool, object] = {}
        self.bind("<Button-1>", self._click)
        variable.trace_add("write", lambda *a: self.draw())
        self.draw()

    def _click(self, _e=None):
        self.var.set(not self.var.get())
        if self.command:
            self.command()

    def _render(self, on: bool):
        w, h = self.w, self.h
        img = Image.new("RGB", (w * SS, h * SS), self.bgcol)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, w * SS - 1, h * SS - 1], radius=h * SS / 2,
                            fill=C["blue"] if on else C["border"])
        p = 3 * self.sc * SS
        x = (w - h) * SS if on else 0
        d.ellipse([x + p, p, x + h * SS - p, h * SS - p], fill="#FFFFFF")
        return ImageTk.PhotoImage(img.resize((w, h), _BOX))

    def draw(self):
        self.delete("all")
        w, h, on = self.w, self.h, bool(self.var.get())
        if HAVE_PIL:
            if on not in self._imgs:
                self._imgs[on] = self._render(on)
            self.create_image(0, 0, image=self._imgs[on], anchor="nw")
            return
        col = C["blue"] if on else C["border"]
        self.create_oval(0, 0, h, h, fill=col, outline=col)
        self.create_oval(w - h, 0, w, h, fill=col, outline=col)
        self.create_rectangle(h / 2, 0, w - h / 2, h, fill=col, outline=col)
        p = 3 * self.sc
        x = w - h if on else 0
        self.create_oval(x + p, p, x + h - p, h - p, fill="#FFFFFF", outline="")


class Slider(tk.Canvas):
    def __init__(self, master, variable: tk.DoubleVar, lo: float, hi: float, step: float,
                 sc: float, bg: str, command=None, width: int = 200):
        super().__init__(master, height=int(30 * sc), width=width, bg=bg, highlightthickness=0,
                         bd=0, cursor="hand2", takefocus=1)
        self.var, self.lo, self.hi, self.step = variable, lo, hi, step
        self.sc, self.bgcol, self.command = sc, bg, command
        self.pad = 14 * sc
        self._img = None
        for ev in ("<Button-1>", "<B1-Motion>"):
            self.bind(ev, self._drag)
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<MouseWheel>", self._wheel)
        self.bind("<Left>", lambda e: self._nudge(-1))
        self.bind("<Right>", lambda e: self._nudge(1))
        variable.trace_add("write", lambda *a: self.draw())

    def _set(self, v: float):
        v = round(round(v / self.step) * self.step, 4)
        v = max(self.lo, min(self.hi, v))
        if abs(v - self.var.get()) > 1e-9:
            self.var.set(v)
            if self.command:
                self.command()

    def _drag(self, e):
        self.focus_set()
        w = self.winfo_width()
        frac = (e.x - self.pad) / max(1, w - 2 * self.pad)
        self._set(self.lo + frac * (self.hi - self.lo))

    def _wheel(self, e):
        self._nudge(1 if e.delta > 0 else -1)
        return "break"  # ei rullata samalla koko paneelia

    def _nudge(self, d: int):
        self._set(self.var.get() + d * self.step)

    def draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 10:
            return
        sc, p, cy = self.sc, self.pad, h / 2
        frac = (self.var.get() - self.lo) / (self.hi - self.lo)
        x = p + frac * (w - 2 * p)
        has_zero = self.lo < 0 < self.hi
        x0 = p + (-self.lo) / (self.hi - self.lo) * (w - 2 * p) if has_zero else p
        tw, r = 6 * sc, 9 * sc
        if HAVE_PIL:
            img = Image.new("RGB", (w * SS, h * SS), self.bgcol)
            d = ImageDraw.Draw(img)

            def bar(a, b, col):
                a, b = min(a, b), max(a, b)
                d.rounded_rectangle([(a - tw / 2) * SS, (cy - tw / 2) * SS, (b + tw / 2) * SS,
                                     (cy + tw / 2) * SS], radius=tw / 2 * SS, fill=col)
            bar(p, w - p, C["border"])
            if has_zero:
                d.rectangle([x0 * SS - SS / 2, (cy - 8 * sc) * SS, x0 * SS + SS / 2, (cy + 8 * sc) * SS],
                            fill=C["faint"])
            if abs(x - x0) > 0.5:
                bar(x0, x, C["blue"])
            d.ellipse([(x - r) * SS, (cy - r) * SS, (x + r) * SS, (cy + r) * SS], fill=C["blue"])
            ri = r - 2.4 * sc
            d.ellipse([(x - ri) * SS, (cy - ri) * SS, (x + ri) * SS, (cy + ri) * SS], fill="#FFFFFF")
            self._img = ImageTk.PhotoImage(img.resize((w, h), _BOX))
            self.create_image(0, 0, image=self._img, anchor="nw")
            return
        self.create_line(p, cy, w - p, cy, fill=C["border"], width=tw, capstyle="round")
        if has_zero:
            self.create_line(x0, cy - 8 * sc, x0, cy + 8 * sc, fill=C["faint"], width=1)
        self.create_line(x0, cy, x, cy, fill=C["blue"], width=tw, capstyle="round")
        self.create_oval(x - r, cy - r, x + r, cy + r, fill="#FFFFFF", outline=C["blue"], width=2 * sc)


class Segmented(tk.Frame):
    def __init__(self, master, options: List[str], variable: tk.StringVar, sc: float,
                 font, command=None):
        super().__init__(master, bg=C["card2"], highlightthickness=1,
                         highlightbackground=C["border"])
        self.var, self.command, self.labels = variable, command, {}
        for opt in options:
            lbl = tk.Label(self, text=opt, font=font, padx=int(12 * sc), pady=int(4 * sc),
                           cursor="hand2", bd=0)
            lbl.pack(side="left")
            lbl.bind("<Button-1>", lambda e, o=opt: self._pick(o))
            self.labels[opt] = lbl
        self.refresh()

    def _pick(self, opt: str):
        self.var.set(opt)
        self.refresh()
        if self.command:
            self.command()

    def refresh(self):
        for opt, lbl in self.labels.items():
            on = opt == self.var.get()
            lbl.configure(bg=C["blue"] if on else C["card2"], fg="#FFFFFF" if on else C["muted"])


class ScrollFrame(tk.Frame):
    """Pystysuunnassa rullattava alue.

    grow: widget (esim. kuvaaja), joka venyy täyttämään vapaan korkeuden, mutta ei
    kutistu alle grow_min-korkeuden – silloin alue alkaa rullata.
    autohide: vierityspalkki näkyy vain, kun sisältö ei mahdu."""

    def __init__(self, master, bg: str, width: int = 0, autohide: bool = False):
        super().__init__(master, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0, width=width)
        self.sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview,
                                style="Dark.Vertical.TScrollbar")
        self.inner = tk.Frame(self.canvas, bg=bg)
        self.win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.autohide = autohide
        self.grow: Optional[tk.Widget] = None
        self.grow_min = 0
        self._job = None
        self.inner.bind("<Configure>", self._schedule_fit)
        self.canvas.bind("<Configure>", self._canvas_resized)
        self.canvas.configure(yscrollcommand=self.sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        if not autohide:
            self.sb.pack(side="right", fill="y")
        self.bind("<Enter>", lambda e: self.bind_all("<MouseWheel>", self._wheel))
        self.bind("<Leave>", lambda e: self.unbind_all("<MouseWheel>"))

    def _canvas_resized(self, e):
        self.canvas.itemconfigure(self.win, width=e.width)
        self._schedule_fit()

    def _schedule_fit(self, _e=None):
        if self._job is None:
            self._job = self.after(15, self._fit)

    def _fit(self):
        self._job = None
        self.update_idletasks()
        ch = self.canvas.winfo_height()
        if ch < 2:
            return
        if self.grow is not None:
            cur = self.grow.winfo_reqheight()
            want = max(self.grow_min, ch - (self.inner.winfo_reqheight() - cur))
            if want != cur:
                self.grow.configure(height=want)
                self.update_idletasks()
        if self.autohide:
            # Kapeampi alue vain lisää korkeutta, joten palkki ei jää vilkkumaan.
            need = self.inner.winfo_reqheight() > ch + 1
            if need and not self.sb.winfo_ismapped():
                self.sb.pack(side="right", fill="y", before=self.canvas)
            elif not need and self.sb.winfo_ismapped():
                self.sb.pack_forget()
                self.canvas.yview_moveto(0)
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _wheel(self, e):
        if self.inner.winfo_height() > self.canvas.winfo_height():
            self.canvas.yview_scroll(int(-e.delta / 120), "units")


class Chart(tk.Canvas):
    # (Result-kenttä, nimi, väri, katkoviiva)
    SERIES = [("portfolio", "Sijoitussalkku", "blue", False),
              ("balance", "Opintolainan saldo", "red", False),
              ("net", "Netto verojen jälkeen", "sky", False)]
    ALT = ("net", "Kertamaksu, netto", "purple", True)

    def __init__(self, master, sc: float, fonts: dict):
        super().__init__(master, bg=C["card"], highlightthickness=0, bd=0)
        self.sc, self.f = sc, fonts
        self.res: Optional[Result] = None
        self.alt: Optional[Result] = None
        self.geom = None
        self._photo = None
        self._dots: Dict[str, object] = {}
        self._job = None
        self.bind("<Configure>", lambda e: self._later())
        self.bind("<Motion>", self._hover)
        self.bind("<Leave>", lambda e: self.delete("hover"))

    def _later(self):
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(30, self.redraw)

    def set_data(self, res: Optional[Result], alt: Optional[Result] = None):
        self.res, self.alt = res, alt
        self.redraw()

    def _series(self):
        out = [(getattr(self.res, k), name, col, dashed) for k, name, col, dashed in self.SERIES]
        if self.alt and len(self.alt.net) == len(self.res.net):
            k, name, col, dashed = self.ALT
            out.append((getattr(self.alt, k), name, col, dashed))
        return out

    def redraw(self):
        self._job = None
        self.delete("all")
        W, H = self.winfo_width(), self.winfo_height()
        sc, res = self.sc, self.res
        if W < 50 or H < 50:
            return
        if not res or not res.months:
            self.create_text(W / 2, H / 2, text="Ei nostoja – tarkista syötteet",
                             fill=C["muted"], font=self.f["body"])
            return
        series = self._series()
        L, R, T, B = 78 * sc, 96 * sc, 50 * sc, 34 * sc
        n = len(res.months)
        vals = [v for data, *_ in series for v in data]
        lo, hi = min(0.0, min(vals)), max(vals)
        tlo, thi, ticks = nice_ticks(lo, hi, 7)
        pw, ph = W - L - R, H - T - B

        def X(i):
            return L + pw * (i / max(1, n - 1))

        def Y(v):
            return T + ph * (1 - (v - tlo) / (thi - tlo))

        self.geom = (L, R, T, B, n, X, Y)
        items, texts = [], []
        for v in ticks:
            items.append(("hline", L, W - R, Y(v), C["grid"] if abs(v) > 1e-9 else C["faint"]))
            texts.append((L - 10 * sc, Y(v), fmt_num(v), "e", C["muted"], "small"))
        texts.append((L - 10 * sc, T - 18 * sc, "€", "e", C["faint"], "small"))
        years = [i for i, (yy, mm) in enumerate(res.months) if mm == 1]
        stepy = 1 if len(years) <= 14 else 2
        for j, i in enumerate(years):
            if j % stepy == 0:
                items.append(("vline", X(i), T, T + ph, C["grid"], False))
                texts.append((X(i), T + ph + 14 * sc, str(res.months[i][0]), "center", C["muted"], "small"))
        # tapahtumat: lähekkäiset yhdistetään, tekstit enintään kolmelle riville
        evs = []
        for i, label in sorted(res.events):
            if 0 <= i < n:
                if evs and i - evs[-1][0] <= 2:
                    evs[-1][1] += " · " + label.lower()
                    evs[-1][2].append(i)
                else:
                    evs.append([i, label, [i]])
        right_edge = [-1e9, -1e9, -1e9]
        for i, label, idxs in evs:
            for j in idxs:
                items.append(("vline", X(j), T, T + ph, C["faint"], True))
            x, tw = X(i), self.f["tiny"].measure(label)
            free = [r for r in range(3) if x > right_edge[r] + 6 * sc]
            row = free[0] if free else min(range(3), key=lambda r: right_edge[r])
            right_edge[row] = x + 4 * sc + tw
            if x + 4 * sc + tw > W - 4 * sc:
                texts.append((x - 4 * sc, T - (10 + 13 * row) * sc, label, "e", C["muted"], "tiny"))
            else:
                texts.append((x + 4 * sc, T - (10 + 13 * row) * sc, label, "w", C["muted"], "tiny"))
        y0 = Y(0)
        poly = [(X(0), y0)] + [(X(i), Y(max(0.0, v))) for i, v in enumerate(res.portfolio)] + [(X(n - 1), y0)]
        items.append(("poly", poly, C["area"]))
        for data, _name, col, dashed in series:
            items.append(("line", [(X(i), Y(v)) for i, v in enumerate(data)], C[col], 2.2 * sc, dashed))
        # loppuarvot oikeaan reunaan
        ends = []
        for data, _name, col, _d in series[2:]:
            ends.append([Y(data[-1]), data[-1], col])
            items.append(("dot", X(n - 1), Y(data[-1]), 4 * sc, C[col], C["card"], 2 * sc))
        ends.sort()
        for k in range(1, len(ends)):
            if ends[k][0] - ends[k - 1][0] < 16 * sc:
                ends[k][0] = ends[k - 1][0] + 16 * sc
        for yy, v, col in ends:
            texts.append((X(n - 1) + 10 * sc, yy, fmt_eur(v), "w", C[col], "bodyb"))

        if HAVE_PIL:
            self._paint_pil(W, H, items)
        else:
            self._paint_tk(items)
        for x, y, text, anchor, col, font in texts:
            self.create_text(x, y, text=text, anchor=anchor, fill=col, font=self.f[font])

    def _paint_pil(self, W: int, H: int, items):
        sc = self.sc
        img = Image.new("RGB", (W * SS, H * SS), C["card"])
        d = ImageDraw.Draw(img)
        for it in items:
            kind = it[0]
            if kind == "hline":     # tasan yhden pikselin rivi = terävä
                _, x0, x1, y, col = it
                yy = int(y)
                d.rectangle([int(x0) * SS, yy * SS, int(x1) * SS, yy * SS + SS - 1], fill=col)
            elif kind == "vline":
                _, x, y0, y1, col, dashed = it
                xx = int(x)
                if dashed:
                    yy = y0
                    while yy < y1:
                        d.rectangle([xx * SS, yy * SS, xx * SS + SS - 1, min(yy + 3 * sc, y1) * SS], fill=col)
                        yy += 7 * sc
                else:
                    d.rectangle([xx * SS, y0 * SS, xx * SS + SS - 1, y1 * SS], fill=col)
            elif kind == "poly":
                _, pts, col = it
                d.polygon([(x * SS, y * SS) for x, y in pts], fill=col)
            elif kind == "line":
                _, pts, col, width, dashed = it
                P = [(x * SS, y * SS) for x, y in pts]
                w = max(1, int(round(width * SS)))
                segs = dash_polyline(P, 7 * sc * SS, 5 * sc * SS) if dashed else [P]
                rr = w / 2
                for seg in segs:
                    if len(seg) >= 2:
                        d.line(seg, fill=col, width=w, joint="curve")
                        for (x, y) in (seg[0], seg[-1]):
                            d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=col)
            elif kind == "dot":
                _, x, y, r, col, outline, ow = it
                d.ellipse([(x - r - ow) * SS, (y - r - ow) * SS, (x + r + ow) * SS, (y + r + ow) * SS], fill=outline)
                d.ellipse([(x - r) * SS, (y - r) * SS, (x + r) * SS, (y + r) * SS], fill=col)
        self._photo = ImageTk.PhotoImage(img.resize((W, H), _BOX))
        self.create_image(0, 0, image=self._photo, anchor="nw")

    def _paint_tk(self, items):
        for it in items:
            kind = it[0]
            if kind == "hline":
                _, x0, x1, y, col = it
                self.create_line(x0, y, x1, y, fill=col)
            elif kind == "vline":
                _, x, y0, y1, col, dashed = it
                kw = {"dash": (3, 4)} if dashed else {}
                self.create_line(x, y0, x, y1, fill=col, **kw)
            elif kind == "poly":
                _, pts, col = it
                self.create_polygon([c for p in pts for c in p], fill=col, outline="")
            elif kind == "line":
                _, pts, col, width, dashed = it
                kw = {"dash": (6, 4)} if dashed else {}
                self.create_line([c for p in pts for c in p], fill=col, width=max(2, width),
                                 capstyle="round", joinstyle="round", **kw)
            elif kind == "dot":
                _, x, y, r, col, outline, ow = it
                self.create_oval(x - r, y - r, x + r, y + r, fill=col, outline=outline, width=ow)

    def _dot(self, col: str):
        if col not in self._dots:
            r, ow = 4.5 * self.sc, 2 * self.sc
            size = int(2 * (r + ow) + 3)
            img = Image.new("RGBA", (size * SS, size * SS), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            c = size * SS / 2
            d.ellipse([c - (r + ow) * SS, c - (r + ow) * SS, c + (r + ow) * SS, c + (r + ow) * SS], fill=C["card"])
            d.ellipse([c - r * SS, c - r * SS, c + r * SS, c + r * SS], fill=col)
            self._dots[col] = ImageTk.PhotoImage(img.resize((size, size), _BOX))
        return self._dots[col]

    def _hover(self, e):
        self.delete("hover")
        if not self.res or not self.res.months or not self.geom:
            return
        L, R, T, B, n, X, Y = self.geom
        W, H = self.winfo_width(), self.winfo_height()
        if e.x < L or e.x > W - R:
            return
        i = int(round((e.x - L) / max(1, W - L - R) * (n - 1)))
        i = max(0, min(n - 1, i))
        x, sc = X(i), self.sc
        self.create_line(x, T, x, H - B, fill=C["muted"], tags="hover")
        lines = [fmt_ym(self.res.months[i])]
        for data, name, col, _d in self._series():
            v = data[i]
            if HAVE_PIL:
                self.create_image(x, Y(v), image=self._dot(C[col]), tags="hover")
            else:
                r = 4 * sc
                self.create_oval(x - r, Y(v) - r, x + r, Y(v) + r, fill=C[col], outline=C["card"], tags="hover")
            lines.append((name, v, col))
        bw, lh = 220 * sc, 18 * sc
        bh = lh * len(lines) + 10 * sc
        bx = x + 14 * sc
        if bx + bw > W - 4 * sc:
            bx = x - 14 * sc - bw
        by = max(T, min(e.y - bh / 2, H - B - bh))
        self.create_rectangle(bx, by, bx + bw, by + bh, fill=C["card2"], outline=C["border"], tags="hover")
        self.create_text(bx + 10 * sc, by + 6 * sc + lh / 2, text=lines[0], anchor="w",
                         fill=C["text"], font=self.f["bodyb"], tags="hover")
        for k, (name, v, col) in enumerate(lines[1:], start=1):
            yy = by + 6 * sc + lh * k + lh / 2
            self.create_rectangle(bx + 10 * sc, yy - 4 * sc, bx + 18 * sc, yy + 4 * sc,
                                  fill=C[col], outline="", tags="hover")
            self.create_text(bx + 24 * sc, yy, text=name, anchor="w", fill=C["muted"],
                             font=self.f["small"], tags="hover")
            self.create_text(bx + bw - 10 * sc, yy, text=fmt_eur(v), anchor="e", fill=C["text"],
                             font=self.f["small"], tags="hover")


KPI_ROWS = [
    ("drawn", "Nostettu laina", None),
    ("capitalized_study", "Pääomitetut korot opiskeluaikana", "low"),
    ("interest", "Korot yhteensä", "low"),
    ("fees", "Pankin kulut yhteensä", "low"),
    ("credit", "Opintolainahyvitys (Kela)", "high"),
    ("bonus_net", "OP-bonukset (verojen jälkeen)", "high"),
    ("net_cost", "Lainan nettokustannus *", "low"),
    ("paid_to_bank", "Pankille maksetaan yhteensä", "low"),
    ("inv_costs", "Sijoituskulut (Nordnet)", None),
    ("tax_total", "Sijoitusten verot yhteensä", None),
    ("final", "Sijoituksista jää lopuksi", "high"),
    ("lump", "Kertamaksu hyvityksen jälkeen", "high"),
    ("payoff", "Laina maksettu", None),
]


APP_ID = "TomasVallas.Opintolainalaskuri"
CHART_MIN_H = 340  # kuvaajan vähimmäiskorkeus (px @ 100 %); matalalla näytöllä oikea puoli rullaa


def set_window_app_id(hwnd: int, app_id: str = APP_ID) -> None:
    """Ikkunakohtainen sovellustunniste (Windows), jotta tehtäväpalkissa näkyy oma kuvake
    eikä Pythonin logo – toimii myös Microsoft Storen Pythonilla."""
    import ctypes
    from ctypes import wintypes as wt

    class GUID(ctypes.Structure):
        _fields_ = [("d1", wt.DWORD), ("d2", wt.WORD), ("d3", wt.WORD), ("d4", ctypes.c_ubyte * 8)]

    class PROPERTYKEY(ctypes.Structure):
        _fields_ = [("fmtid", GUID), ("pid", wt.DWORD)]

    class PROPVARIANT(ctypes.Structure):
        _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort),
                    ("r3", ctypes.c_ushort), ("val", ctypes.c_wchar_p), ("pad", ctypes.c_void_p)]

    def guid(s: str) -> GUID:
        g = GUID()
        ctypes.windll.ole32.CLSIDFromString(ctypes.c_wchar_p(s), ctypes.byref(g))
        return g

    iid_store = guid("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")                  # IPropertyStore
    key = PROPERTYKEY(guid("{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"), 5)       # PKEY_AppUserModel_ID
    store = ctypes.c_void_p()
    if ctypes.windll.shell32.SHGetPropertyStoreForWindow(wt.HWND(hwnd), ctypes.byref(iid_store),
                                                         ctypes.byref(store)) != 0:
        return
    vt = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    value = PROPVARIANT(31, 0, 0, 0, app_id, None)                             # VT_LPWSTR
    ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(PROPERTYKEY),
                       ctypes.POINTER(PROPVARIANT))(vt[6])(store, ctypes.byref(key), ctypes.byref(value))
    ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vt[7])(store)           # Commit
    ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vt[2])(store)          # Release


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Opintolainalaskuri – Nordea, Danske Bank ja OP")
        self.configure(bg=C["bg"])
        self.sc = self.winfo_fpixels("1i") / 96.0
        sc = self.sc
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = min(int(1400 * sc), sw - 40), min(int(960 * sc), sh - 80)
        self.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2 - 20)}")
        self.minsize(min(int(1150 * sc), w), min(int(700 * sc), h))
        self._icon()
        if os.name == "nt":
            try:
                self.update_idletasks()
                set_window_app_id(int(self.wm_frame(), 16))
            except Exception:
                pass
        self._fonts()
        self._style()
        self.vars: Dict[str, tk.Variable] = {}
        self.entries: Dict[str, tk.Entry] = {}
        self._job = None
        self._loading_preset = False
        self.results: Dict[str, Result] = {}
        self.lump: Dict[str, Result] = {}
        self._build()
        self.reset_defaults()

    # ---- ulkoasu -----------------------------------------------------------
    def S(self, px: float) -> int:
        return int(round(px * self.sc))

    def _icon(self):
        # Ikkunan ja tehtäväpalkin kuvake PNG:stä usealla koolla (Tk ei lue PNG-pakattua .ico:ta).
        png = resource_path("kuvake", "kuvake-256.png")
        try:
            if os.path.exists(png):
                if HAVE_PIL:
                    src = Image.open(png).convert("RGBA")
                    lz = getattr(Image, "Resampling", Image).LANCZOS
                    self._imgs = [ImageTk.PhotoImage(src.resize((n, n), lz), master=self)
                                  for n in (256, 64, 48, 32, 24, 16)]
                else:
                    self._imgs = [tk.PhotoImage(file=png, master=self)]
                self.iconphoto(True, *self._imgs)
                return
        except (tk.TclError, OSError):
            pass
        try:  # varakuvake, jos kuvake-kansio puuttuu
            img = tk.PhotoImage(width=32, height=32)
            img.put(C["bg"], to=(0, 0, 32, 32))
            img.put(C["blue"], to=(3, 3, 29, 29))
            for x0, h in ((8, 8), (14, 13), (20, 18)):
                img.put("#FFFFFF", to=(x0, 25 - h, x0 + 4, 25))
            self.iconphoto(True, img)
            self._img = img
        except tk.TclError:
            pass

    def _fonts(self):
        fam = "Segoe UI" if "Segoe UI" in tkfont.families() else "TkDefaultFont"
        self.f = {
            "title": tkfont.Font(family=fam, size=17, weight="bold"),
            "h": tkfont.Font(family=fam, size=9, weight="bold"),
            "body": tkfont.Font(family=fam, size=10),
            "bodyb": tkfont.Font(family=fam, size=10, weight="bold"),
            "small": tkfont.Font(family=fam, size=9),
            "tiny": tkfont.Font(family=fam, size=8),
            "big": tkfont.Font(family=fam, size=14, weight="bold"),
        }

    def _style(self):
        st = ttk.Style(self)
        st.theme_use("clam")
        st.configure("TCombobox", fieldbackground=C["input"], background=C["card2"],
                     foreground=C["text"], arrowcolor=C["blue2"], bordercolor=C["border"],
                     lightcolor=C["input"], darkcolor=C["input"], insertcolor=C["text"],
                     selectbackground=C["input"], selectforeground=C["text"], padding=self.S(3))
        st.map("TCombobox", fieldbackground=[("readonly", C["input"])],
               foreground=[("readonly", C["text"])], background=[("active", C["border"])],
               bordercolor=[("focus", C["blue"])], selectbackground=[("readonly", C["input"])],
               selectforeground=[("readonly", C["text"])])
        self.option_add("*TCombobox*Listbox.background", C["card2"])
        self.option_add("*TCombobox*Listbox.foreground", C["text"])
        self.option_add("*TCombobox*Listbox.selectBackground", C["blue"])
        self.option_add("*TCombobox*Listbox.selectForeground", "#FFFFFF")
        self.option_add("*TCombobox*Listbox.font", self.f["body"])
        self.option_add("*TCombobox*Listbox.borderWidth", 0)
        st.configure("Dark.Vertical.TScrollbar", background=C["card2"], troughcolor=C["bg"],
                     bordercolor=C["bg"], arrowcolor=C["muted"], lightcolor=C["card2"],
                     darkcolor=C["card2"], gripcount=0)
        st.map("Dark.Vertical.TScrollbar", background=[("active", C["border"])])

    # ---- rakennuspalikat ---------------------------------------------------
    def card(self, parent, title: str, **pack):
        outer = tk.Frame(parent, bg=C["card"], highlightthickness=1, highlightbackground=C["border"])
        outer.pack(**{"fill": "x", **pack})
        tk.Label(outer, text=title.upper(), bg=C["card"], fg=C["blue2"], font=self.f["h"]).pack(
            anchor="w", padx=self.S(16), pady=(self.S(12), self.S(6)))
        body = tk.Frame(outer, bg=C["card"])
        body.pack(fill="both", expand=True, padx=self.S(16), pady=(0, self.S(14)))
        return outer, body

    def entry(self, parent, key: str, width: int = 9) -> tk.Entry:
        var = tk.StringVar()
        var.trace_add("write", lambda *a: self.schedule())
        e = tk.Entry(parent, textvariable=var, width=width, justify="right", bg=C["input"],
                     fg=C["text"], insertbackground=C["text"], relief="flat", font=self.f["body"],
                     highlightthickness=1, highlightbackground=C["border"], highlightcolor=C["blue"],
                     selectbackground=C["blue"], selectforeground="#FFFFFF")
        self.vars[key], self.entries[key] = var, e
        return e

    def label(self, parent, text: str = "", fg: str = None, font: str = "body", **kw) -> tk.Label:
        return tk.Label(parent, text=text, bg=C["card"], fg=fg or C["muted"], font=self.f[font], **kw)

    def row(self, parent, r: int, label: str, key: str, unit: str = ""):
        self.label(parent, label).grid(row=r, column=0, sticky="w", pady=self.S(3))
        self.entry(parent, key).grid(row=r, column=1, sticky="e", ipady=self.S(3))
        self.label(parent, unit, fg=C["faint"], font="small", width=5, anchor="w").grid(
            row=r, column=2, sticky="w", padx=(self.S(6), 0))
        parent.columnconfigure(0, weight=1)

    def toggle_row(self, parent, r: int, key: str, text=None, textvariable=None, fg=None, pady=None):
        lbl = tk.Label(parent, text=text or "", textvariable=textvariable, bg=C["card"],
                       fg=fg or C["text"], font=self.f["body"], justify="left", anchor="w")
        lbl.grid(row=r, column=0, columnspan=2, sticky="w", pady=pady or self.S(3))
        self.vars[key] = tk.BooleanVar(value=False)
        Toggle(parent, self.vars[key], self.sc, C["card"], self.schedule).grid(
            row=r, column=2, sticky="e", pady=pady or self.S(3))
        return lbl

    def combo(self, parent, key: str, values: List[str], width: int = 30) -> ttk.Combobox:
        var = tk.StringVar(value=values[0])
        cb = ttk.Combobox(parent, textvariable=var, values=values, state="readonly",
                          width=width, font=self.f["body"])
        cb.bind("<<ComboboxSelected>>", lambda e: (cb.selection_clear(), self.schedule()))
        self.vars[key] = var
        return cb

    def note(self, parent, text: str = "", fg: str = None, wrap: int = 360) -> tk.Label:
        return tk.Label(parent, text=text, bg=C["card"], fg=fg or C["muted"], font=self.f["small"],
                        justify="left", anchor="w", wraplength=self.S(wrap))

    def slider_block(self, parent, title: str, key: str, lo: float, hi: float, step: float, fmt):
        top = tk.Frame(parent, bg=C["card"])
        top.pack(fill="x")
        self.label(top, title).pack(side="left", anchor="s")
        val = self.label(top, fg=C["blue2"], font="big")
        val.pack(side="right")
        var = tk.DoubleVar(value=lo)
        self.vars[key] = var
        Slider(parent, var, lo, hi, step, self.sc, C["card"], self.schedule,
               width=self.S(300)).pack(fill="x", pady=(self.S(2), self.S(10)))
        var.trace_add("write", lambda *a: val.configure(text=fmt(var.get())))

    # ---- näkymä ------------------------------------------------------------
    def _build(self):
        S = self.S
        head = tk.Frame(self, bg=C["bg"])
        head.pack(fill="x", padx=S(22), pady=(S(16), S(10)))
        tk.Frame(head, bg=C["blue"], width=S(5), height=S(38)).pack(side="left", padx=(0, S(12)))
        tt = tk.Frame(head, bg=C["bg"])
        tt.pack(side="left")
        tk.Label(tt, text="Opintolainalaskuri", bg=C["bg"], fg=C["text"], font=self.f["title"]).pack(anchor="w")
        tk.Label(tt, text="Nordea · Danske Bank · OP  ·  opintolainahyvitys  ·  OP-bonukset  ·  "
                          "korkojen pääomitus  ·  sijoitustuotto Nordnetissä (AOT / OST)",
                 bg=C["bg"], fg=C["muted"], font=self.f["small"]).pack(anchor="w")
        btn = tk.Label(head, text="↺  Palauta oletukset", bg=C["card2"], fg=C["text"], font=self.f["small"],
                       padx=S(12), pady=S(6), cursor="hand2", highlightthickness=1,
                       highlightbackground=C["border"])
        btn.pack(side="right")
        btn.bind("<Button-1>", lambda e: self.reset_defaults())
        self.status = tk.Label(head, text="", bg=C["bg"], fg=C["bad"], font=self.f["bodyb"])
        self.status.pack(side="right", padx=S(14))

        body = tk.Frame(self, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=S(22), pady=(0, S(16)))
        left = ScrollFrame(body, C["bg"], S(430))
        left.pack(side="left", fill="y")
        # Oikea puoli rullaa, jos näyttö on matala: kuvaaja täyttää vapaan tilan,
        # mutta pysyy vähintään CHART_MIN_H korkeana.
        right = ScrollFrame(body, C["bg"], autohide=True)
        right.pack(side="left", fill="both", expand=True, padx=(S(16), 0))
        self._build_inputs(left.inner)
        self._build_outputs(right.inner)
        self.chart.configure(height=S(CHART_MIN_H))
        right.grow, right.grow_min = self.chart, S(CHART_MIN_H)

    def _build_inputs(self, root):
        S = self.S
        pad = dict(pady=(0, S(12)), padx=(0, S(10)))

        _, b = self.card(root, "Opintolaina", **pad)
        self.row(b, 0, "Ensimmäinen nostokuukausi (kk/vvvv)", "start")
        self.row(b, 1, "Opintolaina kuukaudessa", "monthly_draw", "€/kk")
        self.row(b, 2, "Lukuvuosia jäljellä (sis. nykyinen)", "years_left", "v")
        self.row(b, 3, "Tukikuukausia lukuvuodessa", "months_per_year", "kk")
        self.cap_text = tk.StringVar(value="Nosta vain hyvityskaton verran")
        self.toggle_row(b, 4, "draw_cap_on", textvariable=self.cap_text, pady=(S(8), S(3)))
        self.toggle_row(b, 5, "cap_plus_paid", text="+ opintojen aikana maksettavat korot\n   (sweet spot)",
                        fg=C["muted"])
        self.label(b, "Nostojen jako, kun katto on päällä").grid(row=6, column=0, columnspan=3, sticky="w",
                                                                 pady=(S(4), S(3)))
        self.combo(b, "draw_mode", DRAW_MODES, width=40).grid(row=7, column=0, columnspan=3, sticky="we")
        self.label(b, "Lyhennystapa").grid(row=8, column=0, sticky="w", pady=(S(8), S(3)))
        self.combo(b, "repay_type", REPAY_TYPES, width=20).grid(row=8, column=1, columnspan=2, sticky="e",
                                                                pady=(S(8), S(3)))
        self.info_loan = self.note(b)
        self.info_loan.grid(row=9, column=0, columnspan=3, sticky="w", pady=(S(8), 0))

        _, b = self.card(root, "Korko ja pääomitus", **pad)
        self.row(b, 0, "12 kk Euribor", "euribor", "%")
        self.label(b, "Pääomitetut korot maksetaan pois").grid(row=1, column=0, columnspan=3, sticky="w",
                                                              pady=(S(6), S(3)))
        self.combo(b, "pay_interest", PAY_MODES, width=40).grid(row=2, column=0, columnspan=3, sticky="we")
        self.info_pay = self.note(b)
        self.info_pay.grid(row=3, column=0, columnspan=3, sticky="w", pady=(S(8), 0))

        _, b = self.card(root, "Maksuaikataulu", **pad)
        self.sched_title = self.label(b, "", fg=C["text"], font="small")
        self.sched_title.pack(anchor="w", pady=(0, S(6)))
        self.sched_box = tk.Frame(b, bg=C["card"])
        self.sched_box.pack(fill="x")
        self.sched_note = self.note(b)
        self.sched_note.pack(anchor="w", pady=(S(8), 0))

        _, b = self.card(root, "Sijoitus (Nordnet)", **pad)
        self.label(b, "Tili").grid(row=0, column=0, sticky="w", pady=S(3))
        self.vars["account"] = tk.StringVar(value="AOT")
        self.seg_acc = Segmented(b, ACCOUNTS, self.vars["account"], self.sc, self.f["small"], self.schedule)
        self.seg_acc.grid(row=0, column=1, columnspan=2, sticky="e", pady=S(3))
        self.label(b, "Sijoituskohde").grid(row=1, column=0, columnspan=3, sticky="w", pady=(S(6), S(3)))
        cb = self.combo(b, "preset", [p[0] for p in INVEST_PRESETS], width=40)
        cb.grid(row=2, column=0, columnspan=3, sticky="we")
        cb.bind("<<ComboboxSelected>>", self._preset_changed, add="+")
        self.row(b, 3, "Kaupankäyntipalkkio", "fee_pct", "%")
        self.row(b, 4, "Minimipalkkio / kauppa", "min_fee", "€")
        self.row(b, 5, "Valuutanvaihto", "fx_pct", "%")
        self.row(b, 6, "Juokseva kulu", "ter_pct", "%/v")
        self.row(b, 7, "Osinkotuotto (osa tuotosta)", "dividend_pct", "%/v")
        self.row(b, 8, "Kuukausimaksu", "account_fee", "€/kk")
        self.row(b, 9, "Pääomatulovero", "tax_pct", "%")
        self.label(b, "Myyn sijoituksia lainanmaksuun").grid(row=10, column=0, columnspan=3, sticky="w",
                                                            pady=(S(6), S(3)))
        self.combo(b, "sell_mode", SELL_MODES, width=40).grid(row=11, column=0, columnspan=3, sticky="we")
        self.info_inv = self.note(b)
        self.info_inv.grid(row=12, column=0, columnspan=3, sticky="w", pady=(S(8), 0))
        self.warn_inv = self.note(b, fg=C["red"])
        self.warn_inv.grid(row=13, column=0, columnspan=3, sticky="w", pady=(S(4), 0))

        _, b = self.card(root, "Pankkien korot ja kulut", **pad)
        for c, (_key, name) in enumerate(BANK_KEYS, start=1):
            self.label(b, BANK_SHORT[name], fg=C["text"], font="bodyb").grid(
                row=0, column=c, sticky="e", padx=(S(6), 0), pady=(0, S(4)))
        fee_rows = [
            ("margin", "Marginaali (%)"),
            ("promo_margin", "Etumarginaali (%)"),
            ("promo_years", "Etumarginaali kestää (v)"),
            ("opening_fee", "Avausmaksu (€)"),
            ("increase_fee", "Korotus / lukuvuosi (€)"),
            ("draw_fee", "Nostopalkkio (€)"),
            ("debit_fee", "Veloitus / erä (€)"),
            ("extra_payment_fee", "Ylim. lyhennys (€)"),
            ("other_fees_year", "Muut kulut (€/v)"),
            ("bonus_pct", "Bonukset (%/v saldosta)"),
        ]
        for r, (key, label) in enumerate(fee_rows, start=1):
            self.label(b, label).grid(row=r, column=0, sticky="w", pady=S(3))
            for c, (bank, _name) in enumerate(BANK_KEYS, start=1):
                self.entry(b, f"{bank}.{key}", width=6).grid(row=r, column=c, sticky="e",
                                                             padx=(S(6), 0), ipady=S(3))
        b.columnconfigure(0, weight=1)
        self.note(b, "Danske: Akava-opiskelijaetu (0 % marginaali 5 v, ei avaus-/nosto-/korotuspalkkioita). "
                     "Nordea: automaattinen nostosopimus, korotus verkossa 10 €. OP: omistaja-asiakas "
                     "(100 € osuusmaksu, palautetaan erotessa), toimitusmaksu 0 € (muuten 30 €), nostot "
                     "Kelan erissä 0 €; marginaali pankkikohtainen (vertailut n. 0,5 %). OP-bonukset "
                     "0,4 %/v lainasaldosta, 30 % ennakonpidätys → 0,28 %, saa rahana tilille.").grid(
            row=len(fee_rows) + 1, column=0, columnspan=4, sticky="w", pady=(S(8), 0))

        _, b = self.card(root, "Opintolainahyvitys", **pad)
        self.toggle_row(b, 0, "credit_on", text="Saan hyvityksen (valmistun määräajassa)")
        cb = self.combo(b, "degree", [d[0] for d in DEGREES], width=40)
        cb.grid(row=1, column=0, columnspan=3, sticky="we", pady=(S(6), S(4)))
        cb.bind("<<ComboboxSelected>>", self._degree_changed, add="+")
        self.row(b, 2, "Hyvitysprosentti", "credit_pct", "%")
        self.row(b, 3, "Omavastuu (ei hyvitetä)", "credit_deductible", "€")
        self.row(b, 4, "Hyvitettävä laina enintään", "credit_max_loan", "€")
        self.info_credit = self.note(b)
        self.info_credit.grid(row=5, column=0, columnspan=3, sticky="w", pady=(S(8), 0))

        tk.Label(root, text="Oletukset tarkistettu 2.11.2026: Kela, Nordea, Danske Bank, OP, Nordnet, "
                            "Verohallinto, 12 kk Euribor 30.10.2026. Laskelma on arvio, ei sijoitusneuvontaa. "
                            "Korko: todelliset päivät / 360, korko ja tuotto pysyvät samana koko ajan.",
                 bg=C["bg"], fg=C["faint"], font=self.f["tiny"], justify="left",
                 wraplength=self.S(400)).pack(anchor="w", padx=(S(2), S(10)), pady=(0, S(8)))

    def _build_outputs(self, root):
        S = self.S
        top = tk.Frame(root, bg=C["bg"])
        top.pack(fill="x")

        # --- säätimet (pakataan ensin, jotta ne saavat koko leveytensä) ---
        _, b = self.card(top, "Takaisinmaksu ja tuotto", side="right", fill="y", padx=(S(12), 0))
        self.slider_block(b, "Vuosituotto (ennen kuluja)", "return_pct", -5.0, 15.0, 0.1,
                          lambda v: f"{fmt_num(v, 1)} %/v")
        self.slider_block(b, "Takaisinmaksuaika", "repay_years", 0.0, 15.0, 0.5,
                          lambda v: "Kertamaksu" if v < 0.25 else f"{fmt_num(v, 1)} v")
        self.label(b, "Takaisinmaksu alkaa").pack(anchor="w", pady=(0, S(4)))
        self.vars["repay_start"] = tk.StringVar(value=REPAY_STARTS[0])
        self.seg_start = Segmented(b, REPAY_STARTS, self.vars["repay_start"], self.sc,
                                   self.f["small"], self.schedule)
        self.seg_start.pack(anchor="w")
        self.plan_info = self.note(b, wrap=300)
        self.plan_info.pack(anchor="w", fill="x", pady=(S(10), 0))

        # --- vertailutaulukko ---
        _, b = self.card(top, "Vertailu", side="left", fill="both", expand=True)
        heads = [""] + [BANK_SHORT[name] for _k, name in BANK_KEYS] + ["Paras"]
        ncol = len(heads)
        for c, h in enumerate(heads):
            self.label(b, h, font="bodyb", anchor="e" if c else "w").grid(
                row=0, column=c, sticky="we", padx=(S(10) if c else 0, 0), pady=(0, S(4)))
        self.kpi = {}
        for r, (key, label, _) in enumerate(KPI_ROWS, start=1):
            bg = C["card2"] if r % 2 else C["card"]
            tk.Frame(b, bg=bg, height=1).grid(row=r, column=0, columnspan=ncol, sticky="nsew")
            tk.Label(b, text=label, bg=bg, fg=C["text"], font=self.f["body"], anchor="w").grid(
                row=r, column=0, sticky="we", ipadx=S(4))
            cells = []
            for c in range(1, ncol):
                lbl = tk.Label(b, text="", bg=bg, fg=C["text"], font=self.f["body"], anchor="e")
                lbl.grid(row=r, column=c, sticky="we", ipadx=S(6))
                cells.append(lbl)
            self.kpi[key] = cells
        b.columnconfigure(0, weight=4)
        for c in range(1, ncol):
            b.columnconfigure(c, weight=1)
        self.kpi_note = tk.Label(b, text="", bg=C["card"], fg=C["faint"], font=self.f["tiny"],
                                 justify="left", anchor="w")
        self.kpi_note.grid(row=len(KPI_ROWS) + 1, column=0, columnspan=ncol, sticky="w", pady=(S(6), 0))

        # --- kuvaaja ---
        _, b = self.card(root, "Sijoituksen kehitys", fill="both", expand=True, pady=(S(12), 0))
        row = tk.Frame(b, bg=C["card"])
        row.pack(fill="x")
        self.vars["chart_bank"] = tk.StringVar(value="Danske Bank")
        self.seg = Segmented(row, [name for _k, name in BANK_KEYS], self.vars["chart_bank"], self.sc,
                             self.f["small"], self.schedule)
        self.seg.pack(side="left")
        for _k, name, col, dashed in reversed(Chart.SERIES + [Chart.ALT]):
            self.label(row, name, font="small").pack(side="right", padx=(0, S(4)))
            self.label(row, "╌╌" if dashed else "■", fg=C[col], font="small").pack(
                side="right", padx=(S(12), S(3)))
        self.main_info = tk.Label(b, text="", bg=C["card"], fg=C["sky"], font=self.f["body"],
                                  anchor="w", justify="left")
        self.main_info.pack(fill="x", pady=(S(8), S(2)))
        alt_row = tk.Frame(b, bg=C["card"])
        alt_row.pack(fill="x", pady=(0, S(4)))
        self.vars["compare"] = tk.BooleanVar(value=True)
        Toggle(alt_row, self.vars["compare"], self.sc, C["card"], self.update_chart).pack(
            side="left", anchor="n", padx=(0, S(8)))
        self.alt_info = tk.Label(alt_row, text="", bg=C["card"], fg=C["purple"], font=self.f["body"],
                                 anchor="w", justify="left")
        self.alt_info.pack(side="left", fill="x", expand=True)
        for lbl in (self.main_info, self.alt_info):
            lbl.bind("<Configure>", lambda e, l=lbl: l.configure(wraplength=max(100, e.width - 8)))
        self.chart = Chart(b, self.sc, self.f)
        self.chart.pack(fill="both", expand=True)

    # ---- tila --------------------------------------------------------------
    def reset_defaults(self):
        y, m = default_start()
        d = {
            "start": f"{m}/{y}", "monthly_draw": "850", "years_left": "3", "months_per_year": "9",
            "euribor": "3,306", "credit_pct": "40", "credit_deductible": "2500",
            "credit_max_loan": "18000", "tax_pct": "30",
        }
        for bank, (key, _name) in zip(default_banks(), BANK_KEYS):
            for fld in BANK_FIELDS:
                v = getattr(bank, fld)
                d[f"{key}.{fld}"] = fmt_num(v, 2 if fld in ("margin", "promo_margin", "debit_fee",
                                                           "bonus_pct") else 0)
        for k, v in d.items():
            self.vars[k].set(v)
        self.vars["repay_type"].set(REPAY_TYPES[0])
        self.vars["pay_interest"].set(PAY_MODES[0])
        self.vars["draw_mode"].set(DRAW_MODES[0])
        self.vars["degree"].set(DEGREES[0][0])
        self.vars["sell_mode"].set(SELL_MODES[0])
        self.vars["account"].set("AOT")
        self.vars["draw_cap_on"].set(False)
        self.vars["cap_plus_paid"].set(True)
        self.vars["credit_on"].set(True)
        self.vars["compare"].set(True)
        self.vars["return_pct"].set(6.0)
        self.vars["repay_years"].set(7.0)
        self.vars["repay_start"].set(REPAY_STARTS[0])
        self.vars["chart_bank"].set("Danske Bank")
        self.vars["preset"].set(INVEST_PRESETS[0][0])
        self._preset_changed()
        self.seg.refresh()
        self.seg_start.refresh()
        self.seg_acc.refresh()
        self.recalc()

    @staticmethod
    def _fmt_field(v: float) -> str:
        return fmt_num(v, 2) if abs(v - round(v)) > 1e-9 else fmt_num(v)

    def _preset_changed(self, _e=None):
        name = self.vars["preset"].get()
        for n, vals, _kind in INVEST_PRESETS:
            if n == name and vals:
                self._loading_preset = True
                for k in INVEST_FIELDS:
                    self.vars[k].set(self._fmt_field(vals[k]).replace(" ", ""))
                self._loading_preset = False
        self.schedule()

    def _degree_changed(self, _e=None):
        name = self.vars["degree"].get()
        for n, cap in DEGREES:
            if n == name:
                self.vars["credit_max_loan"].set(fmt_num(cap).replace(" ", ""))
        self.schedule()

    def schedule(self, *_):
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(60, self.recalc)

    @staticmethod
    def _mark(e: tk.Entry, ok: bool):
        if ok:
            e.configure(highlightbackground=C["border"], bg=C["input"], fg=C["text"])
        else:
            e.configure(highlightbackground=C["bad"], bg="#2A1316", fg="#FCA5A5")

    def _num(self, key: str, lo: float = None, hi: float = None, errors: list = None) -> float:
        txt = self.vars[key].get()
        e = self.entries[key]
        try:
            v = float(txt.replace(" ", "").replace(" ", "").replace(" ", "")
                      .replace(",", ".").replace("€", "").replace("%", "").replace("−", "-"))
            if (lo is not None and v < lo) or (hi is not None and v > hi) or math.isnan(v):
                raise ValueError
            self._mark(e, True)
            return v
        except ValueError:
            self._mark(e, False)
            errors.append(key)
            return 0.0

    def read_inputs(self):
        err: list = []
        start_txt = self.vars["start"].get().replace(".", "/").replace("-", "/").split("/")
        try:
            sm, sy = int(start_txt[0]), int(start_txt[1])
            if not (1 <= sm <= 12 and 2000 <= sy <= 2100):
                raise ValueError
            self._mark(self.entries["start"], True)
        except (ValueError, IndexError):
            self._mark(self.entries["start"], False)
            err.append("start")
            sm, sy = 1, 2000
        max_loan = self._num("credit_max_loan", 0, 1e6, err)
        s = Settings(
            start_year=sy, start_month=sm,
            monthly_draw=self._num("monthly_draw", 0, 5000, err),
            years_left=int(self._num("years_left", 0, 15, err)),
            months_per_year=int(self._num("months_per_year", 0, 12, err)),
            draw_cap_on=bool(self.vars["draw_cap_on"].get()),
            draw_cap=max_loan,
            cap_plus_paid=bool(self.vars["cap_plus_paid"].get()),
            draw_even=self.vars["draw_mode"].get() == DRAW_MODES[1],
            euribor=self._num("euribor", -5, 25, err),
            repay_years=float(self.vars["repay_years"].get()),
            repay_start=REPAY_STARTS.index(self.vars["repay_start"].get()),
            repay_type=self.vars["repay_type"].get(),
            credit_on=bool(self.vars["credit_on"].get()),
            credit_pct=self._num("credit_pct", 0, 100, err),
            credit_deductible=self._num("credit_deductible", 0, 1e6, err),
            credit_max_loan=max_loan,
            pay_interest=PAY_MODES.index(self.vars["pay_interest"].get()),
            return_pct=float(self.vars["return_pct"].get()),
            tax_pct=self._num("tax_pct", 0, 99, err),
            account=self.vars["account"].get(),
            fee_pct=self._num("fee_pct", 0, 10, err),
            min_fee=self._num("min_fee", 0, 1000, err),
            fx_pct=self._num("fx_pct", 0, 10, err),
            ter_pct=self._num("ter_pct", 0, 10, err),
            dividend_pct=self._num("dividend_pct", 0, 20, err),
            account_fee=self._num("account_fee", 0, 1000, err),
            sell_yearly=self.vars["sell_mode"].get() == SELL_MODES[1],
        )
        banks = []
        limits = {"margin": (-5, 20), "promo_margin": (-5, 20), "promo_years": (0, 40), "bonus_pct": (0, 10)}
        for key, name in BANK_KEYS:
            vals = {f: self._num(f"{key}.{f}", *limits.get(f, (0, 1e6)), errors=err) for f in BANK_FIELDS}
            banks.append(Bank(name, **vals))
        return (None, None) if err else (s, banks)

    def _preset_kind(self, s: Settings) -> str:
        """Valitun sijoituskohteen laji; käsin muutetut kulut = "oma"."""
        name = self.vars["preset"].get()
        for n, vals, kind in INVEST_PRESETS:
            if n == name and vals:
                if all(abs(getattr(s, k) - vals[k]) < 1e-9 for k in INVEST_FIELDS):
                    return kind
                self.vars["preset"].set(INVEST_PRESETS[-1][0])
        return "oma"

    # ---- maksuaikataulu ------------------------------------------------------
    def _fill_schedule(self, r: Result, cname: str, s: Settings) -> None:
        box, S = self.sched_box, self.S
        for w in box.winfo_children():
            w.destroy()
        if not r.months:
            self.sched_title.configure(text="Ei nostoja näillä syötteillä.")
            self.sched_note.configure(text="")
            return
        self.sched_title.configure(text=f"{cname}: nostot, pääomitukset ja maksut ennen lyhennyksiä")

        def day(ym: YM, kind: str) -> str:
            return f"15.{ym[1]}.{ym[0]}" if kind in ("cap", "io", "pay") and ym[1] in (6, 12) else fmt_ym(ym)

        rows = []      # (pvm, teksti, summa, väri)
        sch, k, sep_done = r.schedule, 0, False
        while k < len(sch):
            ym, kind, a = sch[k]
            if not sep_done and r.grad_end and ym > r.grad_end:
                rows.append(("", f"{fmt_ym(r.grad_end)}: valmistumislukukausi päättyy – hyvityksen pohja lukittu "
                                 f"({fmt_eur(r.credit_base)})", None, C["faint"]))
                sep_done = True
            nxt = sch[k + 1] if k + 1 < len(sch) else None
            if kind == "cap" and nxt and nxt[1] == "pay" and nxt[0] == ym and abs(nxt[2] - a) < 0.005:
                rows.append((day(ym, kind), "Korot pääomitetaan → maksa heti pois", a, C["sky"]))
                k += 2
                continue
            if kind == "cap":
                txt, col = "Korot pääomitetaan lainaan", C["muted"]
            elif kind == "pay":
                txt, col = ("Maksa pääomitetut korot pois" if ym[1] in (6, 12)
                            else f"Maksa korot pois ({1}.{ym[1]}. jälkeen)"), C["sky"]
            elif kind == "draw":
                txt, col = "Nosto", C["text"]
            elif kind == "topup":
                txt, col = "Lisäerä = tähän asti maksetut korot", C["blue2"]
            elif kind == "io":
                txt, col = "Pankki perii korot (ei lyhennystä)", C["muted"]
            else:
                txt, col = "Opintolainahyvitys (Kela maksaa pankkiin)", C["blue2"]
            rows.append((day(ym, kind), txt, a, col))
            k += 1
        box.columnconfigure(1, weight=1)
        for j, (d, txt, a, col) in enumerate(rows):
            if a is None:
                self.label(box, txt, fg=col, font="tiny").grid(row=j, column=0, columnspan=3, sticky="w",
                                                               pady=(S(4), S(4)))
                continue
            self.label(box, d, fg=C["faint"], font="small").grid(row=j, column=0, sticky="w", padx=(0, S(10)))
            self.label(box, txt, fg=col, font="small").grid(row=j, column=1, sticky="w")
            self.label(box, fmt_eur(a, 2), fg=col, font="small").grid(row=j, column=2, sticky="e")

        notes = [f"Nostot yhteensä {fmt_eur(r.drawn, 2)}"
                 + (f", josta lisäerä {fmt_eur(r.topup, 2)} ({fmt_ym(r.topup_month)})" if r.topup > 0.005 else "")
                 + f". Maksat pääomitettuja korkoja pois {fmt_eur(r.paid_early, 2)}."]
        if r.topup > 0.005:
            notes.append("Lisäerä = opintojen aikana pois maksetut pääomitukset sentilleen, joten hyvityksen pohjaksi "
                         f"jää tasan {fmt_eur(min(s.draw_cap, r.credit_base))}. Nosta se valmistumislukukauden erän "
                         "mukana – valmistumisen jälkeen lainaa ei voi enää nostaa. Valmistumislukukauden oma "
                         "pääomitus maksetaan vasta lukukauden päätyttyä, jottei se pienennä hyvitystä.")
        notes.append("Summat ovat laskurin arvio (Euribor pysyy samana). Maksa aina se summa, jonka pankki "
                     "näyttää pääomitetuksi – lisäerä on niiden tarkka summa.")
        self.sched_note.configure(text="\n".join(notes))

    # ---- laskenta ja päivitys ----------------------------------------------
    def recalc(self):
        self._job = None
        if self._loading_preset:
            return
        s, banks = self.read_inputs()
        if s is None:
            self.status.configure(text="⚠  Tarkista punaisella merkityt kentät – tulokset eivät päivity")
            return
        self.status.configure(text="")
        self.settings, self.banks = s, banks
        kind = self._preset_kind(s)
        self.results = {b.name: simulate(s, b) for b in banks}
        lump_s = replace(s, repay_start=1, repay_years=0.0)
        self.lump = {b.name: simulate(lump_s, b, horizon=len(self.results[b.name].months)) for b in banks}
        self.same_as_lump = s.repay_start == 1 and s.repay_years < 0.25
        show = [2 if s.pay_interest == 2 else 1, 3]
        base = {b.name: simulate(replace(s, pay_interest=0), b) for b in banks}
        alts = {mode: {b.name: simulate(replace(s, pay_interest=mode), b) for b in banks} for mode in show}
        chart_bank = next(b for b in banks if b.name == self.vars["chart_bank"].get())
        rc = self.results[chart_bank.name]
        cname = BANK_SHORT[chart_bank.name]
        names = " / ".join(BANK_SHORT[b.name] for b in banks)
        other_acc = "OST" if s.account == "AOT" else "AOT"
        acc_cmp = {s.account: rc, other_acc: simulate(s, chart_bank, account=other_acc)}

        # info: laina, nostokatto ja sweet spot
        self.cap_text.set(f"Nosta vain hyvityskaton verran ({fmt_eur(s.credit_max_loan)})")
        if rc.months:
            if s.draw_cap_on and s.draw_even and rc.drawn < rc.full_draw - 0.5:
                how = f"{rc.n_support_months} kk × {fmt_eur(rc.drawn / rc.n_support_months)}"
            else:
                how = f"{rc.n_support_months} kk, {rc.n_draws} nostoa, viimeinen {fmt_ym(rc.last_draw)}"
            txt = f"{cname}: nostat {fmt_eur(rc.drawn)} ({how})."
            if s.draw_cap_on and s.cap_plus_paid:
                if s.pay_interest in (1, 2):
                    spots = ", ".join(f"{BANK_SHORT[b.name]} {fmt_eur(self.results[b.name].drawn)}" for b in banks)
                    txt += (f" Sweet spot (katto + opintojen aikana maksettavat korot): {spots} → hyvityksen "
                            f"pohjaksi jää tasan {fmt_eur(min(s.draw_cap, rc.credit_base))}.")
                    if rc.topup > 0.005:
                        txt += f" Lisäerä {fmt_eur(rc.topup, 2)} nostetaan {fmt_ym(rc.topup_month)} (ks. maksuaikataulu)."
                else:
                    txt += " (Sweet spot vaikuttaa vain, kun korkoja maksetaan opintojen aikana.)"
            if rc.full_draw > rc.drawn + 0.5:
                txt += f" Täydellä nostolla saisit {fmt_eur(rc.full_draw)}."
            txt += f" Valmistut {fmt_ym(rc.graduation)}, hyvitys n. {fmt_ym(rc.credit_month)}."
            self.info_loan.configure(text=txt, fg=C["muted"])
        else:
            self.info_loan.configure(text="Ei nostoja näillä syötteillä.", fg=C["bad"])

        # info: korkojen maksu
        lines = [f"Vaikutus verrattuna pääomitukseen ({names}):"]
        credit_drop = False

        def pair(vals):
            return " / ".join(fmt_eur(v, sign=True) for v in vals)
        for mode in show:
            d = [(alts[mode][b.name], base[b.name]) for b in banks]
            credit_drop |= any(a.credit < z.credit - 0.5 for a, z in d)
            mark = "▸" if mode == s.pay_interest else "•"
            lines.append(f"{mark} {PAY_SHORT[mode]}: korot {pair(a.interest - z.interest for a, z in d)}, "
                         f"hyvitys {pair(a.credit - z.credit for a, z in d)}, "
                         f"loppusalkku {pair(a.payoff_net - z.payoff_net for a, z in d)}")
        lines.append(f"Loppusalkku = valitulla {fmt_num(s.return_pct, 1)} %:n tuotolla.")
        lines.append("Pääomitusaikana korkoja ei voi maksaa niiden sijaan (Kela) – ne maksetaan ylimääräisenä "
                     "lyhennyksenä heti 15.6./15.12. jälkeen. Pyydä pankkia kohdistamaan maksu pääomaan "
                     "(ei ennakkomaksuksi).")
        if credit_drop:
            lines.append("Huom: Kela vähentää valmistuessa jäljellä olevasta lainasta kaikki pääomitetut "
                         "korot, myös jo maksetut. Opintojen aikana maksettu korko pienentää siis hyvitystä, "
                         "jos nostot eivät ylitä kattoa. Valmistumislukukauden jälkeen maksaminen ei pienennä.")
        self.info_pay.configure(text="\n".join(lines), fg=C["red"] if credit_drop else C["muted"])
        self._fill_schedule(rc, cname, s)

        # info: sijoitus (AOT vs OST)
        ra, ro = acc_cmp["AOT"], acc_cmp["OST"]
        diff = ro.payoff_net - ra.payoff_net
        better = "OST" if diff > 0.5 else ("AOT" if diff < -0.5 else None)
        txt = (f"{cname}, {fmt_num(s.return_pct, 1)} %: AOT:lle jää {fmt_eur(ra.payoff_net)}, "
               f"OST:lle {fmt_eur(ro.payoff_net)}"
               + (f" → {better} {fmt_eur(abs(diff))} parempi." if better else " → ei eroa.")
               + f" Verot yhteensä AOT {fmt_eur(ra.tax_total)} / OST {fmt_eur(ro.tax_total)}.")
        warn = ""
        if s.account == "OST" and kind in ("rahasto", "ETF"):
            warn = ("⚠ OST:lle ei voi ostaa rahastoja eikä ETF:iä – vain listattuja osakkeita. "
                    "Valitse kohteeksi osakkeet tai tiliksi AOT.")
        if s.min_fee >= 5 and not s.sell_yearly:
            warn += ("\n" if warn else "") + (f"Vinkki: minimipalkkio {fmt_eur(s.min_fee)} jokaisesta kuukausimyynnistä "
                                              "nostaa kuluja – kokeile myyntiä kerran vuodessa.")
        txt += ("\nAOT: myyntivoitosta vero vuosittain (FIFO), alle 1 000 €:n vuosimyynnit verovapaita, "
                "osingoista vero heti. OST: ei veroa kaupoista eikä osingoista, nostoista vero voitto-osuuden "
                "mukaan; vain osakkeita, talletukset enintään 100 000 €.")
        self.info_inv.configure(text=txt)
        self.warn_inv.configure(text=warn)

        # info: hyvitys
        if not s.credit_on:
            self.info_credit.configure(text="Hyvitys pois päältä.", fg=C["muted"])
        elif rc.months:
            counted = min(s.credit_max_loan, rc.credit_base)
            txt = (f"{fmt_num(s.credit_pct)} % × ({fmt_eur(counted)} − {fmt_eur(s.credit_deductible)}) "
                   f"= {fmt_eur(rc.credit)}.  Pohja = valmistuessa jäljellä oleva laina − pääomitetut korot "
                   f"({cname} {fmt_eur(rc.credit_base)}). Kela maksaa hyvityksen pankkiin n. "
                   f"{fmt_ym(rc.credit_month)}.")
            if rc.credit_base < s.credit_max_loan - 0.5:
                txt += f"  Katto ({fmt_eur(s.credit_max_loan)}) ei täyty."
            elif rc.credit_base > s.credit_max_loan + 0.5:
                txt += f"  Katto täyttyy: {fmt_eur(rc.credit_base - s.credit_max_loan)} lainasta ei saa hyvitystä."
            else:
                txt += "  Pohja on tasan katto: saat maksimihyvityksen."
            self.info_credit.configure(text=txt, fg=C["muted"])

        # vertailutaulukko: paras pankki sinisellä, viimeisessä sarakkeessa sen nimi
        nb = len(banks)
        for key, _label, better in KPI_ROWS:
            cells = self.kpi[key]
            vals = []
            for c, b in zip(cells[:nb], banks):
                r = self.results[b.name]
                if key == "payoff":
                    c.configure(text=fmt_ym(r.payoff), fg=C["text"], font=self.f["body"])
                    continue
                v = self._kpi_value(key, r, self.lump[b.name])
                vals.append(v)
                c.configure(text=fmt_eur(v), fg=C["text"], font=self.f["body"])
            cells[nb].configure(text="", fg=C["blue2"])
            if not better or len(vals) < nb:
                continue
            best = min(vals) if better == "low" else max(vals)
            winners = [k for k, v in enumerate(vals) if abs(v - best) < 0.5]
            if len(winners) == nb:
                cells[nb].configure(text="sama", fg=C["muted"])
                continue
            for k in winners:
                cells[k].configure(fg=C["blue2"], font=self.f["bodyb"])
            cells[nb].configure(text=" / ".join(BANK_SHORT[banks[k].name] for k in winners))
        self.kpi_note.configure(text=f"* korot + kulut − hyvitys − OP-bonukset (negatiivinen = maksat takaisin "
                                     f"vähemmän kuin nostit).\nSijoitusrivit: {s.account}, tuotto "
                                     f"{fmt_num(s.return_pct, 1)} %/v ennen kuluja, vero {fmt_num(s.tax_pct)} %, "
                                     f"voitto verojen jälkeen.")
        self.update_chart()

    @staticmethod
    def _kpi_value(key: str, r: Result, lump: Result) -> float:
        if key == "net_cost":
            return r.interest + r.fees - r.credit - r.bonus_net
        if key == "final":
            return r.payoff_net
        if key == "lump":
            return lump.payoff_net
        return getattr(r, key)

    def update_chart(self):
        name = self.vars["chart_bank"].get()
        res, lump = self.results.get(name), self.lump.get(name)
        show_alt = bool(self.vars["compare"].get()) and not getattr(self, "same_as_lump", False)
        self.chart.set_data(res, lump if show_alt else None)
        if not res or not res.months:
            for lbl in (self.main_info, self.alt_info, self.plan_info):
                lbl.configure(text="")
            return
        s = self.settings
        if s.repay_years < 0.25:
            plan = (f"Koko laina maksetaan kerralla {fmt_ym(res.payoff)}"
                    + (", heti kun Kela on maksanut hyvityksen." if s.repay_start else
                       " (pankin aikataulun 1. lyhennyskuukausi)."))
        elif s.repay_start:
            plan = (f"Lyhennykset alkavat heti hyvityksen jälkeen: {fmt_ym(res.amort_start)}–"
                    f"{fmt_ym(res.payoff)}, {res.n_payments} erää.")
        else:
            plan = (f"Pankin aikataulu: korot pääomitetaan {fmt_ym(res.last_cap)} asti, sitten pelkät korot "
                    f"kahdesti, lyhennykset {fmt_ym(res.amort_start)}–{fmt_ym(res.payoff)} ({res.n_payments} erää).")
        self.plan_info.configure(text=f"{name}: {plan}")

        txt = (f"Valittu maksutapa: laina maksettu {fmt_ym(res.payoff)}, salkkuun jää verojen jälkeen "
               f"{fmt_eur(res.payoff_after_tax)} ({s.account}).")
        if res.own_money > 0.5:
            txt += (f"  Salkku ei riittänyt, omaa rahaa tarvittiin {fmt_eur(res.own_money)} "
                    f"→ nettotulos {fmt_eur(res.payoff_net)}.")
        self.main_info.configure(text=txt, fg=C["sky"] if res.payoff_net >= 0 else C["red"])
        if show_alt and lump and lump.months:
            diff = lump.final_net_after_tax - res.final_net_after_tax
            txt = (f"Kertamaksu hyvityksen jälkeen ({fmt_ym(lump.payoff)}): voittoa jää heti "
                   f"{fmt_eur(lump.payoff_net)}. Sijoitettuna se kasvaa {fmt_eur(lump.final_net_after_tax)} "
                   f"{fmt_ym(res.payoff)} mennessä ({fmt_eur(diff, sign=True)} vs. valittu maksutapa).")
            self.alt_info.configure(text=txt, fg=C["purple"])
        elif getattr(self, "same_as_lump", False):
            self.alt_info.configure(text="Valittu maksutapa on jo kertamaksu hyvityksen jälkeen.",
                                    fg=C["muted"])
        else:
            self.alt_info.configure(text="Vertailu: koko laina pois heti hyvityksen jälkeen (pois päältä)",
                                    fg=C["muted"])


def main():
    try:  # terävä teksti Windowsin skaalatuilla näytöillä
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        # Oma tehtäväpalkkikuvake Pythonin logon sijaan (ks. myös set_window_app_id)
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass
    App().mainloop()


if __name__ == "__main__":
    main()
