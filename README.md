# Louvr Performance — Backend API

Python/Flask API que conecta Meta Ads API + Claude AI para generar el análisis de creativos.

## Endpoints

| Method | Route | Descripción |
|--------|-------|-------------|
| GET | `/health` | Health check |
| POST | `/api/validate-token` | Valida el token + account ID antes de correr el report |
| POST | `/api/report` | Genera el report completo: Meta data + Claude analysis |

## Deploy en Railway (gratis)

### 1. Crear repo en GitHub

```bash
cd louvr-backend
git init
git add .
git commit -m "init"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/louvr-backend.git
git push -u origin main
```

### 2. Deploy en Railway

1. Ve a https://railway.app → New Project → Deploy from GitHub repo
2. Selecciona `louvr-backend`
3. Railway lo detecta automáticamente como Python

### 3. Variables de entorno en Railway

En Railway → tu proyecto → Variables, añade:

```
ANTHROPIC_API_KEY = sk-ant-...
```

Railway asigna PORT automáticamente.

### 4. Obtener la URL

Railway te da una URL tipo:
`https://louvr-backend-production.up.railway.app`

Esa URL va en el account.html como `API_BASE`.

---

## Uso desde el dashboard (account.html)

### Validar token
```javascript
const res = await fetch('https://TU-URL.railway.app/api/validate-token', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ token: 'EAAx...', account_id: '827707939821214' })
});
const data = await res.json();
// data.valid = true/false
// data.account_name = "VALO Gallery"
```

### Generar report
```javascript
const res = await fetch('https://TU-URL.railway.app/api/report', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ token: 'EAAx...', account_id: '827707939821214' })
});
const report = await res.json();
// report.creatives = array rankeado
// report.actions = 3 acciones de la semana
// report.insights = análisis Claude
```

---

## Errores posibles

| Error | Causa | Solución |
|-------|-------|----------|
| `no_ads` | No hay anuncios en la cuenta | Necesitas campañas activas o pausadas |
| `no_spend_data` | Anuncios existen pero sin gasto esta semana | Activa campañas |
| `meta_api_error` | Token inválido o expirado | Renovar token en Meta Graph API Explorer |
| `claude_error` | Fallo en Anthropic API | Revisar ANTHROPIC_API_KEY |

---

## Desarrollo local

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edita .env con tu ANTHROPIC_API_KEY
python app.py
```

API disponible en `http://localhost:5000`
