"""UBL 2.1 invoice XML. This is the structure most national e-invoicing platforms build on; submitting it to a
government portal (with that country's signing and extra fields) is a separate, country-specific step."""
from xml.sax.saxutils import escape

from sqlalchemy.orm import Session


def _amt(v: float) -> str:
    return f"{v:.2f}"


def ubl_invoice(db: Session, d) -> str:
    inv, co, cu = d.invoice, d.company, d.customer
    cur = d.currency or co.currency
    tax_rate = d.tax_rate or 0
    lines = []
    for i, it in enumerate(d.items, start=1):
        net_line = it.line_total / (1 + tax_rate / 100) if (inv.tax_amount and abs((d.subtotal or 0) - inv.total) < 0.02) else it.line_total
        lines.append(f"""
  <cac:InvoiceLine>
    <cbc:ID>{i}</cbc:ID>
    <cbc:InvoicedQuantity unitCode="C62">{it.quantity:g}</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount currencyID="{cur}">{_amt(net_line)}</cbc:LineExtensionAmount>
    <cac:Item>
      <cbc:Name>{escape(it.product)}</cbc:Name>
      {f"<cac:SellersItemIdentification><cbc:ID>{escape(it.sku)}</cbc:ID></cac:SellersItemIdentification>" if it.sku else ""}
      <cac:ClassifiedTaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>{tax_rate:g}</cbc:Percent><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:ClassifiedTaxCategory>
    </cac:Item>
    <cac:Price><cbc:PriceAmount currencyID="{cur}">{_amt(it.unit_price)}</cbc:PriceAmount></cac:Price>
  </cac:InvoiceLine>""")
    net = inv.total - (inv.tax_amount or 0)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:UBLVersionID>2.1</cbc:UBLVersionID>
  <cbc:ID>{escape(inv.number)}</cbc:ID>
  <cbc:IssueDate>{inv.issue_date}</cbc:IssueDate>
  <cbc:DueDate>{inv.due_date}</cbc:DueDate>
  <cbc:InvoiceTypeCode>388</cbc:InvoiceTypeCode>
  <cbc:DocumentCurrencyCode>{cur}</cbc:DocumentCurrencyCode>
  <cac:AccountingSupplierParty><cac:Party>
    <cac:PartyName><cbc:Name>{escape(co.name)}</cbc:Name></cac:PartyName>
    <cac:PostalAddress><cbc:StreetName>{escape(co.address or "")}</cbc:StreetName></cac:PostalAddress>
    <cac:PartyTaxScheme><cbc:CompanyID>{escape(co.tax_number or "")}</cbc:CompanyID><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:PartyTaxScheme>
  </cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party>
    <cac:PartyName><cbc:Name>{escape(cu.name)}</cbc:Name></cac:PartyName>
    <cac:PostalAddress><cbc:StreetName>{escape(cu.address or "")}</cbc:StreetName></cac:PostalAddress>
  </cac:Party></cac:AccountingCustomerParty>
  <cac:TaxTotal>
    <cbc:TaxAmount currencyID="{cur}">{_amt(inv.tax_amount or 0)}</cbc:TaxAmount>
    <cac:TaxSubtotal>
      <cbc:TaxableAmount currencyID="{cur}">{_amt(net)}</cbc:TaxableAmount>
      <cbc:TaxAmount currencyID="{cur}">{_amt(inv.tax_amount or 0)}</cbc:TaxAmount>
      <cac:TaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>{tax_rate:g}</cbc:Percent><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:TaxCategory>
    </cac:TaxSubtotal>
  </cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount currencyID="{cur}">{_amt(net)}</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount currencyID="{cur}">{_amt(net)}</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount currencyID="{cur}">{_amt(inv.total)}</cbc:TaxInclusiveAmount>
    <cbc:PrepaidAmount currencyID="{cur}">{_amt(inv.paid_amount)}</cbc:PrepaidAmount>
    <cbc:PayableAmount currencyID="{cur}">{_amt(max(inv.total - inv.paid_amount - (inv.credited_amount or 0), 0))}</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>{"".join(lines)}
</Invoice>
"""
