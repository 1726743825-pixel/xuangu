# Database migrations

From `backend/`, initialize or upgrade the database with:

```powershell
python -m app.db.init_db
```

Create future revisions with:

```powershell
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```
