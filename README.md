# AI Business Operating System

> Your business has a database. Our AI turns that data into decisions and actions.

نظام تشغيل أعمال ذكي متعدد المستأجرين (Multi-tenant SaaS) يجمع المبيعات، CRM، المخزون، المشتريات، المالية، الصلاحيات، الأتمتة، ومحلل أعمال بالذكاء الاصطناعي يقرأ قاعدة بياناتك ومستنداتك ويجيب بلغتك.

## التشغيل السريع (Docker)

```bash
cp backend/.env.example backend/.env      # اختياري: أضف ANTHROPIC_API_KEY لتفعيل وكيل Claude
docker compose up --build
```

| الخدمة | العنوان |
|---|---|
| الواجهة | http://localhost:3000 |
| API + Swagger | http://localhost:8000/docs |

**حساب تجريبي:** `owner@demo.com` / `demo1234` (أيضاً `sales@`, `finance@`, `rep@`, `warehouse@demo.com` بنفس كلمة المرور لتجربة الصلاحيات).
عند أول تشغيل يُنشئ النظام شركة تجريبية بستة أشهر من البيانات، ويشغّل قواعد الأتمتة، ويفهرس مستندات السياسات.

## التشغيل المحلي بدون Docker

```bash
# Backend (Python 3.11+, يعمل مع SQLite تلقائياً)
cd backend && pip install -r requirements.txt
python -m scripts.seed && uvicorn app.main:app --reload

# Frontend (Node 18+)
cd frontend && npm install && npm run dev
```

## ما الذي تم بناؤه (MVP كامل حسب المواصفات)

| الوحدة | المسار | الحالة |
|---|---|---|
| Companies + Users + Roles | `/api/auth`, `/api/users` | تسجيل شركة، JWT، 7 أدوار افتراضية، صلاحيات granular (`customers:delete`, `purchasing:approve`, …) |
| CRM | `/api/customers` | ملف عميل، رصيد، سجل مشتريات، سجل تواصل/شكاوى، **تقييم العميل (Score 0-100)** |
| Inventory | `/api/inventory` | منتجات، مستودعات متعددة، حركات مخزون، تحويلات، حد أدنى، دفعات/صلاحية، **توقع الطلب** |
| Sales | `/api/sales` | عروض أسعار → طلبات → فواتير → دفعات، خصومات، خصم المخزون تلقائياً |
| Purchasing | `/api/purchasing` | موردون، **طلب شراء ← موافقة ← أمر شراء ← استلام** (يزيد المخزون) |
| Finance | `/api/finance` | مصاريف، إيرادات، ذمم مدينة/دائنة، تدفق نقدي، تحليل ربحية |
| Dashboard & Reports | `/api/dashboard`, `/api/reports/{sales,inventory,finance,management}` | KPIs مع نمو شهري، 12 شهر، هوامش الفئات |
| **AI Command Center** | `/api/command-center` | يكتشف المخاطر تلقائياً: هبوط مبيعات، ارتفاع مصاريف، فئات بهامش منخفض، خصومات غير اعتيادية، نفاد مخزون، فواتير متأخرة، عملاء خاملون + ملخص سردي وإجراءات مقترحة |
| **AI Business Analyst (Agent)** | `/api/ai/ask` | وكيل بأدوات مضبوطة: `query_sales / query_profit / query_inventory / query_customers / query_finance / analyze_business / search_documents / create_report / create_task / create_purchase_request / create_customer / send_notification` |
| Knowledge / RAG | `/api/documents` | رفع PDF/DOCX/TXT → تقطيع → embeddings → بحث متجهي معزول لكل شركة |
| Alerts & Automation | `/api/alerts`, `/api/automation`, `/api/tasks` | محرك قواعد IF/THEN يعمل كل 15 دقيقة + تشغيل يدوي. القواعد الخمس من المواصفات مُضمّنة افتراضياً |
| Multi-tenant | كل الجداول | `company_id` على كل سجل، JWT يحمل الشركة، كل استعلام مقيّد، مع اختبار عزل |

### كيف يعمل الوكيل الذكي
- إذا وُجد `ANTHROPIC_API_KEY`: حلقة tool-use كاملة مع Claude — النموذج يختار الأدوات، الخادم ينفذها ضمن نطاق الشركة، ثم يصيغ الإجابة (بالعربية/العبرية/الإنجليزية حسب السؤال).
- بدون مفتاح: موجّه نوايا مدمج يجيب على الأسئلة الشائعة من نفس الأدوات، فيعمل المنتج والاختبارات دون اتصال.
- أي إجراء يغيّر البيانات (طلب شراء) يُنشأ بحالة `request` ويحتاج موافقة من صاحب صلاحية `purchasing:approve`.

### التوقع (Forecasting)
متوسط متحرك مرجّح أسّياً + اتجاه 30 يوماً + موسمية أيام الأسبوع + مهلة المورد + مخزون أمان → `risk: HIGH/MEDIUM/LOW` وكمية شراء مقترحة. راجع `backend/app/services/forecasting.py`.

## هيكل المشروع

```
backend/
  app/core        config, database, security (JWT/bcrypt), deps (tenant + permissions)
  app/models      SQLAlchemy 2.0 models (كلها تحمل company_id)
  app/schemas     Pydantic v2
  app/api         routers لكل وحدة
  app/services    analytics, forecasting, scoring, rag, automation, insights, ai_agent
  scripts/seed.py بيانات تجريبية واقعية
  tests/          اختبارات end-to-end (تدفق كامل، عزل المستأجرين، الصلاحيات)
frontend/
  src/app/(app)   command-center, dashboard, sales, customers, inventory, purchasing,
                  finance, documents, alerts, automation, settings
  src/components  ui primitives, sidebar
  src/lib         api client, hooks, formatters
docker-compose.yml   Postgres + Redis + backend + frontend
```

## الاختبارات
```bash
cd backend && python -m pytest -q     # 52 passed in the verified suite
cd frontend && npx tsc --noEmit && npm run build
```

Warehouse-transfer workflows use `/api/inventory/transfers` (including submit,
approve, ship, receive and cancel). Cash/bank transfers keep `/api/transfers`.
The frontend uses the corresponding endpoint for each operation. See
[`docs/CI_FIXES.md`](docs/CI_FIXES.md) for the fixes and regression coverage.

## الإنتاج — ما يجب تغييره
- `SECRET_KEY` عشوائي طويل، و`CORS_ORIGINS` للنطاق الحقيقي.
- استبدال embeddings المحلية (hashed n-gram) بنموذج embeddings حقيقي + `pgvector` (`rag.embed()` نقطة واحدة للتبديل).
- Alembic للهجرات بدل `create_all`.
- Nginx + HTTPS، وتخزين الملفات على object storage.
- Rate limiting و audit log للإجراءات التي ينفذها الوكيل.

## خارطة التوسع (من المواصفات)
Forecasting متقدم → وكلاء متعددون → Workflow builder → محاسبة متقدمة → تطبيق موبايل → WhatsApp/Email → تكاملات محاسبة/دفع → تحليلات صناعية.
