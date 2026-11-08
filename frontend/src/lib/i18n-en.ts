// English text for keys that are codes rather than English sentences ("Sales help", "gl.asset", message templates).
// Everything else uses the key itself as the English text.
export const EN: Record<string, string> = {
  // page help lines
  "2FA help": "After your password we ask for a code from an app on your phone. Even if someone learns your password, they can't get in.",
  "Accounting help": "Full double-entry accounting: every invoice, payment and expense posts its own entry. Chart of accounts, journal, trial balance and balance sheet.",
  "Accounts help": "All your money: the cash box and every bank account. Every payment in or out is recorded here.",
  "Admin help": "Open new companies and manage them all. Each company's data is fully separate.",
  "Admin security help": "Protect the platform admin account and see sign-ins across all companies.",
  "Alerts help": "The system watches your business and raises an alert or task here when something looks wrong.",
  "Approvals help": "Sales with a big discount or below cost and large expenses wait for you here, along with payment notices sent by customers.",
  "Audit help": "Every change in the system: who made it, when, and what changed.",
  "Automation help": "Rules that run by themselves every 15 minutes: \"if this happens, do that\".",
  "Backups help": "A full copy of the database is made every day and the last 30 are kept.",
  "Batch help": "If the goods have a batch number or expiry date (medicine, food), write it. The system sells the earliest expiry first.",
  "Cheques help": "Cheques from customers and cheques you wrote to suppliers, with their due dates.",
  "Company settings help": "Your company details that appear on invoices, and your password.",
  "Customer portal help": "A private link where the customer sees their invoices and statement and can send a payment notice.",
  "Customers help": "All your customers: what they bought, what they owe, and a score for each. Click a customer to open their file.",
  "Deliveries help": "Assign orders to drivers. Drivers see their deliveries on the phone and record the handover and any cash collected.",
  "Export help": "Download a copy of your data as Excel, for the accountant or your archive.",
  "Field sales help": "The rep's route for today: their customers, balances, directions, and logging each visit with its location.",
  "Files help": "Put company policies, contracts and price lists here; the AI assistant reads them and answers from them.",
  "HR help": "Employee files, daily attendance, advances and monthly payroll.",
  "Import help": "Enter your data once from an Excel file instead of one by one, and export any data to Excel.",
  "Integrations help": "API keys and webhooks to connect your website or any other program to the system.",
  "Inventory help": "Stock in every warehouse, what is running low and how much to order.",
  "Labels help": "Print barcode labels for your products on any label printer or A4 sticker paper.",
  "Manufacturing help": "A recipe for each product (what goes into it), then production: components leave the warehouse and the finished product comes in at their cost.",
  "Money help": "Money in and out, expenses, and who owes you.",
  "Outbox help": "Every email the system sent or saved (password resets, invoices, morning summary).",
  "Payment voucher help": "For money going out that isn't an invoice or expense: owner withdrawal, loan repayment…",
  "Payroll help": "Pick the month and press \"Prepare payroll\": salary, allowances and overtime are calculated, absences and advances deducted.",
  "Plans help": "Subscription plans you sell to companies, and the limits of each.",
  "Platform billing help": "Subscription bills for companies. Created automatically on the 1st of each month for paid plans; marking one paid extends the subscription.",
  "Pricing help": "Special price lists (wholesale, distributors…) and offers that apply automatically at the cashier and in sales.",
  "Pricing ideas help": "Products sold below cost, fast sellers with a thin margin, and slow stock. Based on the last 90 days.",
  "Purchasing help": "Buying goods: purchase request → manager approves → order from the supplier → stock goes up when it arrives.",
  "Receipt voucher help": "For money coming in that isn't from an invoice: capital, a loan, other income.",
  "Receive payment help": "The amount is spread automatically over the oldest open invoices.",
  "Reports help": "Company reports for any period. Print them or save as PDF.",
  "Return help": "Write how many of each item came back (in pieces). Stock returns to the warehouse, the customer's debt goes down, and if they had paid, the money is refunded from the cash box.",
  "Sales help": "Create orders for customers, issue invoices and record payments.",
  "Security help": "Two-step verification, sign-in history and signing out of every device.",
  "Stock count help": "Count what is really on the shelves and compare it with the system. The difference is valued, and applying the count corrects the quantities.",
  "Team help": "Who uses the system and what each person is allowed to see or do.",
  "Template help": "The template has the right columns and a sample row. If you already have an Excel file, just rename its columns to match.",
  "VAT help": "For example 16 in Palestine. If your prices include VAT, the system takes the tax out of them; if not, it adds it to the invoice.",
  "Warning signs help": "Numbers per employee over the last 30 days worth a look (cancellations, discounts, refunds, cash differences). Not proof of anything — just where to check.",
  // message templates
  "Reminder message": "Hello {name}, a friendly reminder from {company}: you have an outstanding balance of {amount}. Thank you.",
  "Invoice message": "Hello {name}, your invoice {number} from {company} for {amount}. You can view it here:",
  "Portal message": "Hello {name}, this is your account link at {company}. See your invoices and balance, and tell us when you pay:",
  // codes
  "gl.asset": "Asset", "gl.liability": "Liability", "gl.equity": "Equity", "gl.revenue": "Revenue", "gl.expense": "Expense",
  "login.ok": "Signed in", "login.bad_password": "Wrong password", "login.unknown": "Unknown email", "login.2fa_failed": "Wrong 2FA code",
  "login.2fa_required": "2FA code asked", "login.locked": "Locked", "login.inactive": "Inactive user", "login.failed": "Failed",
  "visit.not_interested": "Not interested", "price.below_cost": "Below cost", "price.raise": "Raise the price", "price.slow": "Slow stock — discount",
  "risk.many_cancellations": "Many cancellations", "risk.high_discounts": "High discounts", "risk.below_cost": "Sold below cost",
  "risk.many_refunds": "Many refunds", "risk.cash_short": "Cash short", "mail.saved": "Saved (not sent)", "bill.void": "Cancelled",
  // lowercase words used inside sentences stay lowercase
  "pack": "pack",  "piece": "piece",  "optional": "optional",  "free": "free",  "vs last month": "vs last month",  "you": "you",  "written text": "written text",  "sold": "sold",  "or write the text here": "or write the text here",  "in stock": "in stock",  "category": "category",
  "pending_approval": "Waiting for approval", "payments i sent": "Payments I sent", "vat": "VAT",
};

/** "gl.asset" → "Asset", "trial balance" → "Trial balance", "not_interested" → "Not interested". */
export function humanize(key: string): string {
  let s = /^[a-z0-9_]+\.[a-z0-9_]+$/.test(key) ? key.split(".").pop()! : key;
  if (/^[a-z][a-z0-9_ &]*$/.test(s)) { s = s.replace(/_/g, " "); s = s[0].toUpperCase() + s.slice(1); }
  return s;
}
