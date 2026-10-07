# Klaus's Store — Real System V2

A secure Flask-based online clothing store starter for Klaus's Store.

## Included
- Customer storefront, search and category filters
- Product detail pages
- Session cart with stock validation
- Checkout with MTN Money, Airtel Money or Cash
- WhatsApp order fallback with cart details
- Owner-only login
- Owner dashboard with sales/order/product statistics
- Product add/edit/delete and image upload
- Stock management
- Order status management
- Password change
- CSRF protection
- Security headers
- Secure upload validation
- SQLite for local development

## Run locally
Windows:
1. Install Python 3.11+.
2. Open a terminal in this folder.
3. Run: `python -m venv .venv`
4. Activate: `.venv\Scripts\activate`
5. Run: `pip install -r requirements.txt`
6. Set a strong SECRET_KEY and owner password as environment variables.
7. Run: `python app.py`
8. Open http://127.0.0.1:5000

Demo/local owner credentials are controlled by environment variables. The defaults are only for development and MUST be changed before deployment.

## Important production work still required
- Choose and onboard a regulated MTN/Airtel payment gateway and implement its API/webhooks.
- Move database to PostgreSQL or another managed production DB.
- Move images to cloud object storage.
- Configure production secrets, HTTPS, domain, backups and monitoring.
- Add a proper email/SMS/WhatsApp notification provider.
- Complete legal/privacy/refund pages and confirm Zambia compliance requirements.
- Perform a security review and deployment test.
