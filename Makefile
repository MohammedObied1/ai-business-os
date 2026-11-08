.PHONY: up down seed test backend frontend
up:        ; docker compose up --build
down:      ; docker compose down -v
backend:   ; cd backend && uvicorn app.main:app --reload
frontend:  ; cd frontend && npm run dev
seed:      ; cd backend && python -m scripts.seed
test:      ; cd backend && python -m pytest -q
