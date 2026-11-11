# 🍸 Bar Management System

A web-based Bar Management application built with **Django 6.1**, styled using **Tailwind CSS & DaisyUI (Rocket Dark Theme)**, and featuring a custom admin interface powered by **Django-Unfold**.

This project provides comprehensive tools for managing bar inventory, cocktail recipes, supplier contacts, staff shifts, and real-time table order assignment.

---

## 🚀 Features

* **Shift Dashboard**: Real-time overview of active unpaid checks, ingredients out of stock, cocktail menu statistics, and session shift visit counter.
* **Full CRUD Operations**:
  * **Drinks**: Recipe creation, editing, and deletion with volume, price, category, and multi-ingredient checkbox selection.
  * **Categories**: Alcoholic and non-alcoholic drinks classification with full CRUD support.
  * **Ingredients**: Stock inventory management with supplier links and out-of-stock indicators.
  * **Suppliers**: Supplier contact directory with phone and email management.
  * **Bartenders**: Staff registration, `staff_id` validation (8–15 characters), and profile management.
* **Interactive Order Assignment**:
  * Bartenders can take incoming table orders ("Take this order") and release them with one click, protected against race conditions using `transaction.atomic()` and `select_for_update()`.
  * Bartender profile displays all assigned active and paid checks.
* **Search & Pagination**: Real-time search across drinks, categories, ingredients, suppliers, and bartenders with preserved query parameters across pages.
* **Custom Admin Interface**: Modern dark admin dashboard powered by **Django-Unfold**.

---

## 🛠 Tech Stack

* **Backend**: Python 3.14, Django 6.1
* **UI & Styling**: Tailwind CSS, DaisyUI, Inter Typography, Crispy Forms (Bootstrap 4 pack)
* **Admin Panel**: Django-Unfold
* **Database**: SQLite3
* **Code Quality**: Flake8 (PEP8 compliance), Django Unit Tests (25 tests)

---

## 📦 Installation & Setup

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

4. **Apply database migrations:**
   ```bash
   python manage.py migrate
   ```

5. **Create a superuser (Chief Bartender):**
   ```bash
   python manage.py createsuperuser
   ```

6. **Run the development server:**
   ```bash
   python manage.py runserver
   ```
   Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) in your browser.

---

## 🧪 Running Tests & Linter

Run the unit test suite:
```bash
python manage.py test
```

Check code style with Flake8:
```bash
flake8
```
## 🚀 Live Demo

- **Website:** https://bar-manager-py.onrender.com
- **Test user:** `user` / `user12345`
