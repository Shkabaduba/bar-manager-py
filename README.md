# 🍸 Bar Management System

A web-based Bar Management application built with **Django 6**, styled using **Tailwind CSS & DaisyUI (Dracula Theme)**. Featuring a custom admin interface powered by **Django-Unfold**.

This project provides comprehensive tools for managing bar inventory, cocktail recipes, supplier contacts, and real-time shift order assignment.

---

## 🚀 Features

* **Shift Dashboard**: Tracks active unpaid checks, ingredients out of stock, cocktail menu count, and shift visit counter.
* **Full CRUD Operations**:
  * **Drinks**: Recipe creation with volume, price, category, and multi-ingredient selection with checkboxes.
  * **Categories**: Alcoholic and non-alcoholic drinks classification.
  * **Bartenders**: User registration, `staff_id` update with validation, and profile management.
* **Interactive Order Assignment**:
  * Bartenders can take incoming table orders ("Take this order") and release them with one click.
  * Profile view displays all active and completed checks assigned to the specific bartender.
* **Ingredient Stock Tracking**: Cocktail detail views display ingredient availability and supplier contact details.
* **Search & Filter**: Real-time search across drinks, categories, and bartenders with persistent query parameters during pagination.
* **Custom Admin Interface**: Modern, responsive admin dashboard powered by **Django-Unfold**.

---

## 🛠 Tech Stack

* **Backend**: Python 3.14, Django 6.1
* **UI & Styling**: Tailwind CSS, DaisyUI (Dracula Theme), Crispy Forms (Bootstrap 4 pack)
* **Admin**: Django-Unfold
* **Database**: SQLite3
* **Code Quality**: Flake8 (PEP8 compliance), Django Unit Tests

---

## 📦 Installation & Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Oleksandr-Shkabbura/bar-manager-py.git
   cd bar-manager-py

Create and activate a virtual environment:
# Windows (cmd/PowerShell)
python -m venv .venv
.venv\Scripts\activate
Install dependencies:
pip install -r requirements.txt
Apply database migrations:
python manage.py migrate
Create a superuser (Chief Bartender):
python manage.py createsuperuser
Run the development server:
python manage.py runserver
Open http://127.0.0.1:8000/ in your browser.
 
🧪 Running Tests & Linter
Run unit tests:
python manage.py test

Check code style with Flake8:
flake8
