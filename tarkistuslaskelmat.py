"""Tarkistuslaskelmat: pankkien omat esimerkit + pääskenaario. Aja: python tarkistuslaskelmat.py"""
import os, sys, calendar
sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__)))
from opintolainalaskuri import Settings, Bank, simulate, default_banks, DEGREES, fmt_eur, fmt_ym, add_months

# ---------- 1) Validointi: Dansken oma esimerkki (8000 €, 15 v, 180 erää, 3,261 %, 30 € + 2,50 €/erä) ----------
def annuity_check(P, rate, n, start=(2026, 6), fee0=30, fee=2.5):
    bal, total = P, fee0
    y, m = start
    for k in range(n):
        y, m = add_months(y, m, 1)
        days = calendar.monthrange(y, m)[1]
        it = bal * rate * days / 360
        r_m = rate * 365 / 360 / 12
        left = n - k
        pmt = bal * r_m / (1 - (1 + r_m) ** -left)
        pr = bal if k == n - 1 else pmt - it
        bal -= pr
        total += it + pr + fee
    return total
print("Danske-esimerkki: laskettu", round(annuity_check(8000, 0.03261, 180), 2), "| pankki: 10640.12")
# 30/360 vertailu
def annuity_30360(P, rate, n, fee0=30, fee=2.5):
    r = rate / 12; pmt = P * r / (1 - (1 + r) ** -n); return pmt * n + fee0 + fee * n
print("  (30/360 vertailuna:", round(annuity_30360(8000, 0.03261, 180), 2), ")")

# ---------- 2) Pääskenaario ----------
banks = default_banks()
base = Settings(start_year=2026, start_month=11)
print("\n=== Pääskenaario: alku 11/2026, 3 lukuvuotta, 9 kk/v, 850 €/kk, Euribor 3,306 %, 300 op ===")
for b in banks:
    r = simulate(base, b)
    print(f"{b.name:12s} nostettu {r.drawn:8.0f}  pääom.korot(opisk) {r.capitalized_study:7.2f}  pääom.yht {r.capitalized:7.2f}  "
          f"korot {r.interest:8.2f}  kulut {r.fees:6.2f}  hyvitys {r.credit:7.2f}  netto {r.interest + r.fees - r.credit:9.2f}  "
          f"pankille {r.paid_to_bank:9.2f}  maksettu {fmt_ym(r.payoff)}  check {r.drawn + r.interest + r.fees - r.credit - r.paid_to_bank:.4f} bal_end {r.balance[-1]:.6f}")
    print("   nostot:", r.n_draws, "tukikk:", r.n_support_months, "hyvitys kk:", fmt_ym(r.credit_month), "lyhennys alkaa:", fmt_ym(r.amort_start))

print("\n=== Korkojen maksu pois (tila 0/1/2), 0 % tuotto ===")
for b in banks:
    for mode in (0, 1, 2):
        s = Settings(**{**base.__dict__, "pay_interest": mode, "return_pct": 0.0})
        r = simulate(s, b)
        print(f"{b.name:12s} tila {mode}: korot {r.interest:8.2f}  hyvitys {r.credit:7.2f}  itse maksettu opisk.aikana {r.paid_early:7.2f}  "
              f"kulut {r.fees:6.2f}  nettokust {r.interest + r.fees - r.credit:9.2f}  hyv.pohja {r.credit_base:8.2f}")

print("\n=== Korkojen maksun vaikutus hyvitykseen eri tutkinnoissa (Danske, vuosittain vs ei) ===")
for name, cap in DEGREES:
    s0 = Settings(**{**base.__dict__, "credit_max_loan": cap})
    s1 = Settings(**{**s0.__dict__, "pay_interest": 1})
    r0, r1 = simulate(s0, banks[1]), simulate(s1, banks[1])
    print(f"{name:40s} hyvitys {r0.credit:7.0f} -> {r1.credit:7.0f}  (ero {r1.credit - r0.credit:+.0f})  korkoa säästyy {r0.interest - r1.interest:6.0f}")

print("\n=== Sijoitus: mitä jää verojen jälkeen (vero 30 %), kun salkku maksaa lainan ===")
for ret in (0, 2, 3.3, 5, 6, 8):
    row = []
    for b in banks:
        for mode in (0, 1):
            s = Settings(**{**base.__dict__, "return_pct": ret, "pay_interest": mode})
            r = simulate(s, b)
            row.append(f"{b.name[:6]} m{mode}: {r.final_net_after_tax:8.0f} (oma {r.own_money:5.0f})")
    print(f"tuotto {ret:4.1f} %: " + " | ".join(row))

print("\n=== Herkkyys: kesäopinnot (11 kk/v) ===")
s = Settings(**{**base.__dict__, "months_per_year": 11})
for b in banks:
    r = simulate(s, b); print(b.name, r.drawn, round(r.credit), round(r.interest, 2))

print("\n=== Ilman hyvitystä ===")
s = Settings(**{**base.__dict__, "credit_on": False})
for b in banks:
    r = simulate(s, b); print(b.name, round(r.interest, 2), round(r.fees, 2), round(r.paid_to_bank, 2))

print("\n=== Nostokatto 18 000 € (täydet erät / tasaisesti) ===")
for even in (False, True):
    s = Settings(**{**base.__dict__, "draw_cap_on": True, "draw_even": even})
    for b in banks:
        r = simulate(s, b)
        print(f"{'tasaisesti' if even else 'täydet erät':11s} {b.name:12s} nostettu {r.drawn:8.0f} viim. nosto {fmt_ym(r.last_draw)} "
              f"korot {r.interest:8.2f} kulut {r.fees:6.2f} hyvitys {r.credit:6.0f} netto {r.interest + r.fees - r.credit:9.2f} "
              f"| 6 %: jää {r.payoff_net:7.0f}")
    s1 = Settings(**{**s.__dict__, "pay_interest": 1})
    r1 = simulate(s1, banks[1]); r0 = simulate(s, banks[1])
    print(f"   korot vuosittain pois (Danske): hyvitys {r0.credit:.0f} -> {r1.credit:.0f}")

print("\n=== 18 000 € katto + pääomitettujen korkojen maksu (tila 0/1/2/3), Danske & Nordea ===")
for ret in (0.0, 6.0):
    for b in banks:
        for mode in (0, 1, 2, 3):
            s = Settings(**{**base.__dict__, "draw_cap_on": True, "pay_interest": mode, "return_pct": ret})
            r = simulate(s, b)
            print(f"{ret:3.0f} % {b.name:12s} tila {mode}: korot {r.interest:8.2f} hyvitys {r.credit:6.0f} "
                  f"maksettu itse {r.paid_early:7.2f} nettokust {r.interest + r.fees - r.credit:9.2f} jää {r.payoff_net:7.0f}")

print("\n=== Sweet spot: katto + opintojen aikana maksettavat korot (0 % tuotto = kulut) ===")
for mode in (1, 2):
    for b in banks:
        s = Settings(**{**base.__dict__, "draw_cap_on": True, "pay_interest": mode, "return_pct": 0.0})
        r = simulate(s, b)
        print(f"tila {mode} {b.name:12s}: nosta {r.drawn:9.2f} € (18 000 + {r.sweet_extra:7.2f}) -> pohja {r.credit_base:9.2f} "
              f"hyvitys {r.credit:6.0f} nettokust {r.interest + r.fees - r.credit:9.2f}")

print("\n=== AOT vs OST (Danske, Nordnetin kohteet, myynti kuukausittain / vuosittain) ===")
from opintolainalaskuri import INVEST_PRESETS
for name, vals, kind in INVEST_PRESETS[:-1]:
    for yearly in (False, True):
        row = []
        for acc in ("AOT", "OST"):
            s = Settings(**{**base.__dict__, "account": acc, "sell_yearly": yearly, **vals})
            r = simulate(s, banks[1])
            row.append(f"{acc} {r.payoff_net:7.0f} (kulut {r.inv_costs:5.0f}, verot {r.tax_total:5.0f})")
        print(f"{name[:40]:40s} {'vuosi' if yearly else 'kk   '}: " + " | ".join(row))

print("\n=== Kertamaksu heti hyvityksen jälkeen vs. pankin aikataulu (7 v) ===")
for cap in (False, True):
    for ret in (0.0, 3.3, 6.0):
        for b in banks:
            s_plan = Settings(**{**base.__dict__, "draw_cap_on": cap, "return_pct": ret})
            rp = simulate(s_plan, b)
            rl = simulate(Settings(**{**s_plan.__dict__, "repay_start": 1, "repay_years": 0}), b, horizon=len(rp.months))
            print(f"katto {'18k' if cap else 'ei '} {ret:4.1f} % {b.name:12s} kertamaksu {fmt_ym(rl.payoff)}: voitto heti {rl.payoff_net:7.0f}, "
                  f"{fmt_ym(rp.payoff)} mennessä {rl.final_net_after_tax:7.0f} | pankin aikataulu {rp.payoff_net:7.0f} "
                  f"| korot kertamaksussa {rl.interest:7.2f}")
for yrs in (1, 2, 3):
    s = Settings(**{**base.__dict__, "repay_start": 1, "repay_years": yrs})
    r = simulate(s, banks[1])
    print(f"Danske, lyhennys {yrs} v hyvityksen jälkeen: {fmt_ym(r.amort_start)}-{fmt_ym(r.payoff)} korot {r.interest:.2f} jää {r.payoff_net:.0f}")

print("\n=== Danske: korkojen maksu heti + sweet spot (lisäerä kevään 2029 erän mukana) ===")
from dataclasses import replace
dan = banks[1]
s_sw = replace(base, draw_cap_on=True, pay_interest=2, cap_plus_paid=True, return_pct=0.0)
r_sw = simulate(s_sw, dan)
for ym, kind, a in r_sw.schedule:
    print(f"   {fmt_ym(ym):8s} {kind:6s} {a:9.2f}")
print(f"   nostettu {r_sw.drawn:.2f} (lisäerä {r_sw.topup:.2f} {fmt_ym(r_sw.topup_month)}), "
      f"maksettu opisk.aikana {r_sw.paid_early_study:.2f}, pohja {r_sw.credit_base:.2f}, hyvitys {r_sw.credit:.2f}")
assert abs(r_sw.topup - r_sw.paid_early_study) < 0.01 and abs(r_sw.credit_base - 18000) < 0.01

# Riippumaton tarkistus päivän tarkkuudella: nostot oikeina päivinä, pääomitus 15.6./15.12.,
# maksu samana päivänä, valmistumislukukauden pääomitus maksetaan 1.8.2029.
import datetime as _dt
D = _dt.date
rate = 0.03306
draws_d = [(D(2026, 11, 1), 1700), (D(2027, 1, 1), 4250), (D(2027, 9, 1), 3400),
           (D(2028, 1, 1), 4250), (D(2028, 9, 1), 3400), (D(2029, 1, 1), 1000)]
caps = [D(2026, 12, 15), D(2027, 6, 15), D(2027, 12, 15), D(2028, 6, 15), D(2028, 12, 15), D(2029, 6, 15)]
def day_sched(topup):
    ev = sorted([(d, 0, a) for d, a in draws_d] + [(D(2029, 1, 1), 0, topup)] + [(d, 1, 0) for d in caps])
    bal, acc, last, paid_study, out = 0.0, 0.0, ev[0][0], 0.0, []
    for d, typ, a in ev:
        acc += bal * rate * (d - last).days / 360
        last = d
        if typ == 0:
            bal += a
        else:
            out.append((d, acc))
            if d < D(2029, 1, 1):
                paid_study += acc          # maksetaan heti
            else:
                bal += acc                 # 15.6.2029 jää lainaan 1.8. asti
            acc = 0.0
    return out, paid_study
t = 0.0
for _ in range(5):
    out, t = day_sched(t)
for d, a in out:
    print(f"   päivä {d.day}.{d.month}.{d.year}: pääomitus {a:8.2f}")
print(f"   päivän tarkkuudella lisäerä {t:.2f} (laskuri {r_sw.topup:.2f}, ero {t - r_sw.topup:+.2f})")

print("\n=== Danske: säästö korkoa korolle -ilmiöstä (katto 18 000 €) ===")
for ret in (0.0, 2.0, 3.3, 6.0):
    row = []
    for label, kw in (("ei maksuja", dict(pay_interest=0)), ("heti+sweet", dict(pay_interest=2)),
                      ("heti, ei lisäerää", dict(pay_interest=2, cap_plus_paid=False)),
                      ("valm.jälkeen", dict(pay_interest=3))):
        r = simulate(replace(base, draw_cap_on=True, return_pct=ret, **kw), dan)
        row.append(f"{label} {r.payoff_net:7.0f} (korot {r.interest:6.0f}, hyv {r.credit:5.0f})")
    print(f"{ret:3.1f} %: " + " | ".join(row))
