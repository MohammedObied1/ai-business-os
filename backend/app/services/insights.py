"""AI Command Center: detect risks, positives and produce a narrative summary."""
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.services import analytics

TEXT = {
    "en": {
        "sales_down": ("Sales decreased {pct:.1f}%", "Revenue this month vs last month.", "Analyze sales decline"),
        "revenue_up": ("Revenue increased {pct:.1f}%", "Compared with last month.", None),
        "margin_squeeze": ("Profitability decreased {pct:.1f}% while revenue grew", "Margins are shrinking: check costs, discounts and product mix.", "Review margins"),
        "expenses_up": ("Operating expenses increased {pct:.1f}%", "Expenses this month: {amount:,.0f}.", "Investigate operating expenses"),
        "low_margin_category": ("{category} category has lower margins ({margin}%)", "Average across categories is {avg:.1f}%.", "Review {category} pricing"),
        "high_discounts": ("{count} orders with unusually high discounts", "Customers: {names}.", "Review discount policies"),
        "stockout": ("{count} products may stock out", "Below minimum stock or predicted to run out before supplier lead time.", "Review low-stock products"),
        "overdue": ("{count} invoices are overdue", "Total receivables: {amount:,.0f}.", "Review overdue invoices"),
        "inactive": ("{count} customers inactive for 60+ days", "Sales follow-ups were created automatically.", "Run retention campaign"),
        "overall": {"healthy": "Overall business performance is healthy.", "critical": "Overall business performance is under pressure.",
                    "attention": "Overall business performance is stable but needs attention."},
        "revenue_line": "Revenue {dir} {pct:.1f}% this month",
        "profit_line": ", profitability {pdir} {pct:.1f}%.",
        "up": "increased", "down": "decreased", "p_up": "increased", "p_down": "decreased",
        "contributors": "Main contributors: ",
        "recommended": "Recommended actions: ",
        "sep": "; ", "list_sep": ", ",
    },
    "ar": {
        "sales_down": ("المبيعات نزلت {pct:.1f}%", "مقارنة بين مبيعات هالشهر والشهر الماضي.", "ليش نزلت المبيعات؟"),
        "revenue_up": ("المبيعات زادت {pct:.1f}%", "مقارنة مع الشهر الماضي.", None),
        "margin_squeeze": ("الربح نزل {pct:.1f}% مع إنه المبيعات زادت", "هامش الربح عم يقل: راجع التكاليف والخصومات ونوع المنتجات اللي بتنباع.", "وين الربح والهامش أقل؟"),
        "expenses_up": ("المصاريف زادت {pct:.1f}%", "مصاريف هالشهر: {amount:,.0f}.", "ليش المصاريف زادت؟"),
        "low_margin_category": ("فئة {category} ربحها أقل من غيرها ({margin}%)", "المعدل لكل الفئات {avg:.1f}%.", "ربح فئة {category}"),
        "high_discounts": ("{count} طلبات فيها خصومات عالية بشكل غير طبيعي", "الزباين: {names}.", "شو سياسة الخصومات؟"),
        "stockout": ("{count} منتجات ممكن يخلص مخزونها", "تحت الحد الأدنى أو متوقع تخلص قبل ما توصل بضاعة من المورد.", "شو المنتجات اللي ممكن يخلص مخزونها؟"),
        "overdue": ("{count} فواتير متأخرة بالدفع", "مجموع الديون اللي إلك عند الزباين: {amount:,.0f}.", "شو الفواتير المتأخرة؟"),
        "inactive": ("{count} زباين ما اشتروا من 60 يوم أو أكثر", "انعملت مهام متابعة إلهم أوتوماتيك.", "مين الزباين اللي بطّلوا يشتروا؟"),
        "overall": {"healthy": "وضع الشركة منيح.", "critical": "وضع الشركة تحت ضغط.",
                    "attention": "وضع الشركة مستقر بس في أشياء بدها انتباه."},
        "revenue_line": "المبيعات {dir} {pct:.1f}% هالشهر",
        "profit_line": "، والربح {pdir} {pct:.1f}%.",
        "up": "زادت", "down": "نزلت", "p_up": "زاد", "p_down": "نزل",
        "contributors": "أهم الأسباب: ",
        "recommended": "الخطوات المقترحة: ",
        "sep": "؛ ", "list_sep": "، ",
    },
}


def build_command_center(db: Session, cid: int, lang: str = "en") -> dict:
    tx = TEXT.get(lang, TEXT["en"])
    k = analytics.dashboard_kpis(db, cid)
    today = date.today()
    s, e = analytics.month_bounds(today)
    signals: list[dict] = []
    actions: list[str] = []

    def add(kind: str, code: str, metric: float, **params) -> None:
        title, detail, action = tx[code]
        sig = {"kind": kind, "code": code, "title": title.format(**params), "detail": detail.format(**params), "metric": metric}
        if action:
            sig["action"] = action.format(**params)
        signals.append(sig)

    rg, pg, eg = k["revenue_growth_pct"], k["profit_growth_pct"], k["expenses_growth_pct"]

    if rg is not None and rg <= -10:
        add("risk", "sales_down", rg, pct=abs(rg))
        actions.append(signals[-1]["action"])
    elif rg is not None and rg >= 5:
        add("positive", "revenue_up", rg, pct=rg)

    if pg is not None and pg < 0 and (rg or 0) >= 0:
        add("risk", "margin_squeeze", pg, pct=abs(pg))

    if eg is not None and eg >= 10:
        add("risk", "expenses_up", eg, pct=eg, amount=k["expenses"])
        actions.append(signals[-1]["action"])

    cats = analytics.category_margins(db, cid, s, e)
    if cats:
        avg_margin = sum(c["margin_pct"] for c in cats) / len(cats)
        for c in cats:
            if c["revenue"] > 0 and c["margin_pct"] < avg_margin - 8:
                add("risk", "low_margin_category", c["margin_pct"], category=c["category"], margin=c["margin_pct"], avg=avg_margin)
                actions.append(signals[-1]["action"])

    disc = analytics.high_discount_orders(db, cid, s, e)
    if disc:
        names = tx["list_sep"].join(sorted({d["customer"] for d in disc})[:3])
        add("risk", "high_discounts", max(d["discount_pct"] for d in disc), count=len(disc), names=names)
        actions.append(signals[-1]["action"])

    low = k["low_stock_count"]
    if low:
        add("risk", "stockout", low, count=low)
        actions.append(signals[-1]["action"])

    od = k["overdue_invoices"]
    if od:
        add("risk", "overdue", od, count=od, amount=k["receivables"])
        actions.append(signals[-1]["action"])

    inactive = analytics.inactive_customers(db, cid, 60)
    if inactive:
        add("info", "inactive", len(inactive), count=len(inactive))

    risks = [x for x in signals if x["kind"] == "risk"]
    health = "healthy" if not risks else ("attention" if len(risks) <= 2 else "critical")

    parts = [tx["overall"][health]]
    if rg is not None:
        parts.append(tx["revenue_line"].format(dir=tx["up"] if rg >= 0 else tx["down"], pct=abs(rg)))
        if pg is not None:
            parts[-1] += tx["profit_line"].format(pdir=tx["p_up"] if pg >= 0 else tx["p_down"], pct=abs(pg))
        else:
            parts[-1] += "."
    if risks:
        titles = [r["title"].lower() if lang == "en" else r["title"] for r in risks[:3]]
        parts.append(tx["contributors"] + tx["sep"].join(titles) + ".")
    if actions:
        parts.append(tx["recommended"] + tx["list_sep"].join(dict.fromkeys(actions)) + ".")

    return {
        "summary": " ".join(parts),
        "health": health,
        "signals": signals,
        "recommended_actions": list(dict.fromkeys(actions)),
        "generated_at": datetime.utcnow(),
        "kpis": k,
    }
