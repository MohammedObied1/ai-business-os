# رفع النظام على سيرفر (Production)

هاد الدليل لما تقرر تنقل النظام من جهازك لسيرفر على الإنترنت، عشان الشركات والموظفين يدخلوا من أي مكان.

## اللي بتحتاجه

| الشي | ملاحظة |
|---|---|
| سيرفر VPS | Ubuntu 22.04 أو 24.04، على الأقل 2 GB رام و 2 CPU (Hetzner، DigitalOcean، Contabo…) |
| دومين | مثلاً `app.yourcompany.com`، ووجّه سجل **A** تبعه على IP السيرفر |
| مفتاح Claude (اختياري) | من console.anthropic.com لتفعيل المساعد الذكي وقراءة فواتير الموردين |

## 1) تجهيز السيرفر (مرة وحدة)

```bash
# ادخل على السيرفر
ssh root@SERVER_IP

# نزّل Docker
curl -fsSL https://get.docker.com | sh

# انقل ملفات المشروع (من جهازك: zip وارفعه، أو git clone إذا حاطه على GitHub)
mkdir -p /opt/bizos && cd /opt/bizos
```

## 2) ملف الإعدادات `.env` جنب docker-compose.yml

```env
DOMAIN=app.yourcompany.com
APP_URL=https://app.yourcompany.com
SECRET_KEY=حط-هون-نص-طويل-عشوائي-60-حرف
POSTGRES_PASSWORD=كلمة-سر-قوية-لقاعدة-البيانات
PLATFORM_ADMIN_EMAIL=you@yourcompany.com
PLATFORM_ADMIN_PASSWORD=كلمة-سر-قوية-للمدير
ANTHROPIC_API_KEY=

# الإيميل (تغيير كلمة السر، إرسال الفواتير، ملخص الصبح). بدونه الإيميلات بتنحفظ بس بصفحة "الإيميلات" عند المدير.
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=app-password-من-حساب-جوجل
SMTP_FROM=you@gmail.com

# مراقبة الأخطاء (اختياري): DSN من مشروع على sentry.io
SENTRY_DSN=
```

> بالإنتاج الواجهة بتحكي مع الباك من نفس الدومين (Caddy بيوجّه `/api` للباك)، فما بتحتاج `API_URL`.

لتوليد SECRET_KEY:  `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`

## 3) التشغيل

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

- **Caddy** بيطلّع شهادة HTTPS لحاله وبيجددها.
- افتح `https://app.yourcompany.com` وادخل بحساب مدير المنصة.
- بالإنتاج ما في شركة تجريبية (`SEED_DEMO=false`).

## 3.5) دومين خاص لكل شركة (White-label)

1. من لوحة المدير ← الشركة ← اكتب **الدومين الخاص** (مثلاً `erp.clientco.com`).
2. الشركة بتعمل سجل **A** للدومين على IP السيرفر.
3. أول ما حدا يفتح الدومين، Caddy بيسأل الباك (`/api/public/domain-check`) إذا الدومين لشركة فعّالة، وبيطلّع شهادة HTTPS لحاله.
4. صفحة الدخول على هالدومين بتطلع باسم الشركة وشعارها ولونها.

## 4) نقل بياناتك من جهازك (إذا بدك)

قاعدة البيانات على جهازك موجودة هون:
`C:\Users\<اسمك>\AppData\Local\BizOS\data\bizos.db`

```bash
# ارفع الملف للسيرفر
scp bizos.db root@SERVER_IP:/opt/bizos/

# انسخه لجوّا الباك واعمل النقل (قبل ما تفتح النظام للناس، والقاعدة لسا فاضية)
docker compose cp bizos.db backend:/app/bizos.db
docker compose exec backend python -m scripts.sqlite_to_postgres \
  --sqlite /app/bizos.db \
  --postgres "postgresql+psycopg2://bizos:${POSTGRES_PASSWORD}@db:5432/bizos"
```

> ملاحظة: إذا شغّلت الباك مرة قبل النقل، رح يعمل حساب مدير منصة جديد. السكربت بيرفض النقل إذا لقى شركات بالقاعدة. إذا صار هيك، امسح القاعدة وابدأ من جديد: `docker compose down -v` (بتمسح كل شي على السيرفر).

## 5) النسخ الاحتياطي

- الباك بيعمل `pg_dump` يومي لحاله، وبيحتفظ بآخر 30 نسخة في `/data/backups` جوّا الـvolume `appdata`.
- بتقدر تنزّلهم من لوحة المدير ← **النسخ الاحتياطي**.
- **مهم:** انسخهم كمان لبرّا السيرفر (Backups تبع مزوّد السيرفر، أو rclone لـGoogle Drive).

## 6) التحديث لنسخة جديدة

```bash
cd /opt/bizos
# انقل الملفات الجديدة، بعدين:
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

الجداول والأعمدة الجديدة بتنضاف لحالها عند التشغيل، والبيانات ما بتنمسح.
الباك بيشغّل كمان `alembic upgrade head` قبل ما يبدأ. إذا القاعدة انعملت قبل Alembic (مثلاً نقلتها من جهازك)، علّمها مرة وحدة:

```bash
docker compose exec backend alembic stamp head
```

## أوامر مفيدة

```bash
docker compose logs -f backend      # سجل الباك
docker compose ps                   # حالة الخدمات
docker compose exec db psql -U bizos bizos   # الدخول لقاعدة البيانات
docker compose exec backend pytest -q        # تشغيل الفحوصات
```

## الفحوصات التلقائية (CI)

إذا رفعت المشروع على GitHub، الملف `.github/workflows/ci.yml` بيشغّل فحوصات الباك (pytest) وبيبني الواجهة مع كل push.
