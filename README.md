# 🍸 Bar Management System

A full-featured Bar Management web application built with **Django 6.1.3**, styled with a custom **Cyber Bento Dark** CSS architecture (zero external runtime CDNs), powered by **HTMX** interactive workflows, bilingual **EN / UK** localization, **3-tier RBAC**, a transactional inventory & POS service layer, and a **Django-Unfold** admin panel.

---

## 🚀 Features

* **Shift Bento Dashboard**:
  * Cached KPI snapshot (`AnalyticsService.get_dashboard_snapshot()`) invalidated on transaction commit (`on_commit`), showing active table checks, low-stock alerts, today's revenue/margin, and menu availability without redundant session writes.
* **3-Tier Role-Based Access Control (RBAC)**:
  * **`OWNER`**: Full access, staff management (`Role` + Django groups sync), protection against self-deletion/demotion and deleting the last active owner, and `AuditLog` inspection.
  * **`MANAGER`**: Suppliers, inventory operations, cocktail recipes & costing, analytics & CSV export, and Manager Force Close on orders.
  * **`BARTENDER`**: Table orders (POS workflow, claiming/releasing orders, standard checkout), read-only access to menu & ingredients, and custom `403` access-denied handling.
* **Inventory & Accounting Ledger**:
  * Stock-in with automatic weighted-average unit cost recalculation, spoilage/write-offs, and stock count adjustments (shortage/surplus) logged to an immutable `StockMovement` ledger and `AuditLog`.
  * Database-level `CHECK` / `UNIQUE` constraints and `PROTECT` foreign-key deletion guards.
* **Cocktail Recipe Calculator & Costing**:
  * Live HTMX costing simulator (`Decimal` precision) computing Unit Cost, Food Cost %, Gross Margin, Markup, Recommended Price, and dynamic availability / stop-list bottlenecks per cocktail.
* **Interactive POS & Concurrency Safety**:
  * Split-pane HTMX POS workspace with `select_for_update()` locking (ascending ingredient PK order to avoid deadlocks), optimistic `version` locking, strict stop-list deficit breakdown, idempotent payment, and audited **Manager Force Close** with mandatory override reason.
* **Analytics & Safe CSV Export**:
  * Period filters (`today`, `7d`, `30d`), pure SVG daily revenue/cost chart, top-selling cocktails and bartender rankings, and formula-injection-safe CSV export.
* **Cyber Bento Dark UI, Strict CSP & i18n (`EN | UK`)**:
  * Local CSS bundle (`tokens.css`, `bento.css`, `components.css`, `animations.css`), vendored `htmx.min.js` + `app.js`, slide-over drawers, toast notifications, CSS View Transitions, strict CSP (`script-src 'self'`), rate-limiting middleware, and instant **EN | UK** switching via `polib` (`manage.py compile_locales`).

---

## 🛠 Tech Stack

* **Backend**: Python 3.14, Django 6.1.3, Gunicorn, WhiteNoise (`CompressedManifestStaticFilesStorage`)
* **Frontend**: Custom Cyber Bento Dark CSS bundle, HTMX 2 (vendored locally), pure SVG charts (no Tailwind CDN, no Crispy Forms)
* **Admin Panel**: Django-Unfold
* **Database**: SQLite (development) / PostgreSQL via `psycopg` 3 + `dj-database-url` (production)
* **Localization**: Django i18n (`en` / `uk`) compiled with `polib` (`python manage.py compile_locales`)
* **Code Quality & Testing**: Flake8 (`flake8-quotes`, `flake8-variables-names`, `pep8-naming`, `mccabe`), modular Django test suite (`bar/tests/`, 113 tests including multi-threaded `TransactionTestCase` concurrency and `assertNumQueries` performance suites)

---

## 📦 Installation & Local Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Shkabaduba/bar-manager-py.git
   cd bar-manager-py
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # macOS / Linux:
   source .venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Compile localization catalogs (`en` / `uk`):**
   ```bash
   python manage.py compile_locales
   ```

5. **Apply database migrations:**
   ```bash
   python manage.py migrate
   ```

6. **Seed demo roles, stock, and cocktails (or create a superuser):**
   ```bash
   python manage.py seed_demo_data
   # Optional manual admin creation:
   # python manage.py createsuperuser
   ```
   `seed_demo_data` idempotently creates three demo accounts:
   * **Owner**: `owner` / `OwnerPass123!`
   * **Manager**: `manager` / `ManagerPass123!`
   * **Bartender**: `user` / `user12345`

7. **Run the development server:**
   ```bash
   python manage.py runserver
   ```
   Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) in your browser.

---

## ☁️ Production Deployment (Render)

* **Required Environment Variables:**
  * `DJANGO_SETTINGS_MODULE=bar_service.settings.prod`
  * `SECRET_KEY` (random >= 50 characters)
  * `ALLOWED_HOSTS=bar-manager-py.onrender.com`
  * `CSRF_TRUSTED_ORIGINS=https://bar-manager-py.onrender.com`
  * `DATABASE_URL` (PostgreSQL connection string with SSL)
* **Build Command:**
  ```bash
  pip install -r requirements.txt && python manage.py compile_locales && python manage.py collectstatic --noinput && python manage.py migrate
  ```
* **Start Command:**
  ```bash
  gunicorn bar_service.wsgi:application --workers 1 --threads 4
  ```

---

## 🧪 Running Tests, Linter & Deploy Checks

Run the modular test suite:
```bash
python manage.py test bar --verbosity=2
```

Check code style with Flake8:
```bash
flake8
```

Verify production configuration:
```bash
python manage.py check --deploy
```

---

## 🚀 Live Demo

* **Website:** https://bar-manager-py.onrender.com
* **Demo Credentials:**
  * **Bartender:** `user` / `user12345`
  * **Manager:** `manager` / `ManagerPass123!` *(when seeded via `seed_demo_data`)*
  * **Owner:** `owner` / `OwnerPass123!` *(when seeded via `seed_demo_data`)*
