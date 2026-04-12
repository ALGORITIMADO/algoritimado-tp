# Algoritimado — Transfer Pricing Intelligence Platform
### MVP v0.1 | Lei 14.596/2023 · IN RFB 2.161/2023 · OECD-aligned

> AI-powered transfer pricing benchmark engine for Brazil's regulated market.

---

## 🚀 Deploy to Streamlit Cloud (10 minutes)

### Step 1 — Create GitHub repository
1. Go to https://github.com/new
2. Repository name: `algoritimado-tp`
3. Set to **Private** (recommended)
4. Click **Create repository**

### Step 2 — Upload files
Upload all files from this folder maintaining the structure:
```
algoritimado-tp/
├── app.py
├── requirements.txt
├── calculations/
│   ├── __init__.py
│   ├── base.py
│   └── methods.py
└── reports/
    ├── __init__.py
    └── pdf_generator.py
```

### Step 3 — Deploy on Streamlit Cloud
1. Go to https://share.streamlit.io
2. Sign in with GitHub
3. Click **New app**
4. Select repository: `algoritimado-tp`
5. Main file path: `app.py`
6. App URL: choose `algoritimado-tp` → will give `algoritimado-tp.streamlit.app`
7. Click **Deploy**

### Step 4 — Link from algoritimado.com (Shopify)
Add to your Shopify navigation or create a page with:
```
https://algoritimado-tp.streamlit.app
```

---

## 📋 Methods Implemented

| Method | BR Name | Description |
|--------|---------|-------------|
| TNMM | MLT | Transactional Net Margin Method — most widely used |
| CUP | PIC | Comparable Uncontrolled Price |
| RPM | PRL | Resale Price Method |
| CPM | MCM | Cost Plus Method |
| — | PCI | Import price (commodities) |
| — | PECEX | Export price (commodities) |

## 📊 Core Features
- IQR calculation with full statistical output
- Arm's length compliance checker
- Interactive Plotly visualization
- Professional PDF report (IN RFB 2.161/2023 format)
- Bilingual PT-BR / EN
- CSV comparable upload (coming in v0.2)
- CVM + SEC EDGAR data integration (Level 2 — roadmap)

---

## 🏢 About Algoritimado
Brazil's first AI-native transfer pricing compliance platform.
https://algoritimado.com
