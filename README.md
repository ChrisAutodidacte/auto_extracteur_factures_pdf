# 📑 Découpage & Renommage Automatique de Factures PDF (Gemini AI + Python)

> 🤖 **Automatisez la corvée du tri de vos factures scannées au smartphone.**  
> Découpez intelligemment un gros PDF multipages contenant plusieurs factures en documents individuels, et renommez-les automatiquement avec le type, le nom du fournisseur, le numéro de facture et la date.

[![Licence: MIT](https://img.shields.io/badge/Licence-MIT-green.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![Google Gemini API](https://img.shields.io/badge/Gemini-2.5_Flash/Pro-orange.svg)](https://aistudio.google.com)

---

## 💡 Le problème concret

Quand on gère un commerce, une entreprise ou une activité d'indépendant, on numérise souvent ses factures papier avec son smartphone (Genius Scan, Apple Notes, Google Drive...).

Le résultat ? **Un seul gros fichier PDF de 10, 20 ou 30 pages**, où toutes les factures sont collées les unes derrière les autres :
- Certaines factures font 1 page, d'autres 2 ou 3 pages.
- Le découpage manuel page par page prend un temps infini.
- Le renommage manuel (`Facture_Fournisseur_Numero_Date.pdf`) est une corvée rébarbative.
- Pire encore : on risque d'oublier quels fournisseurs prélèvent par **LCR automatique** et lesquels doivent être réglés par **virement manuel**.

Cet automate résout l'intégralité de la chaîne en quelques secondes.

---

## 🧠 Comment ça marche ? (Pipeline en 2 passes)

Plutôt que d'utiliser un OCR lourd et fragile, le script s'appuie sur la vision multimodale de **Google Gemini** :

```
                        ┌──────────────────────────────────────┐
                        │   1 Gros PDF scanné (Inbox PDF/)     │
                        └──────────────────┬───────────────────┘
                                           │
                                           ▼
      [ÉTAPE 1 : SPLIT]       🧠 Gemini Vision (Passe 1)
                              Détecte les débuts/fins de chaque facture
                                           │
                                           ▼
                              ✂️ Découpe avec pypdf
                              Génère les brouillons dans Factures/
                                           │
                                           ▼
      [ÉTAPE 2 : RENAME]      🧠 Gemini Vision (Passe 2)
                              Extrait : Type, Fournisseur, N°, Date
                                           │
                                           ▼
                              🏷️ Contrôle LCR (fournisseurs_lcr.txt)
                              Ajoute le tag _LCR si prélèvement auto
                                           │
                                           ▼
                        ┌──────────────────────────────────────┐
                        │  Fichiers finaux propres et renommés │
                        │  Facture_LCR_Fournisseur_N°_Date.pdf │
                        └──────────────────────────────────────┘
```

1. **Étape 1 (Découpage / Split) :** Chaque page est rendue en image haute résolution. Gemini analyse la suite de pages, identifie où commence et se termine chaque facture, et découpe le gros PDF en fichiers brouillons. Le PDF source est archivé dans `Inbox PDF/Traites/`.
2. **Étape 2 (Identification & Renommage) :** Gemini relit chaque facture pour extraire avec précision le nom du fournisseur, le numéro et la date.
3. **Filtre métier LCR :** Le script compare le fournisseur avec votre liste dans `fournisseurs_lcr.txt`. Si le fournisseur y figure, il ajoute automatiquement le tag `_LCR` au nom du fichier pour éviter tout paiement en double.

---

## 📁 Structure du projet

```text
├── Inbox PDF/                  # 📥 Déposez vos scans de smartphone ici
│   ├── Scan_Telephone_...pdf   # Fichier de démonstration inclus (7 pages)
│   └── Traites/                # 📦 Vos gros PDF traités y sont déplacés automatiquement
├── Factures/                   # 📄 Toutes vos factures individuelles découpées et renommées
├── Anomalies/                  # ⚠️ Fichiers illisibles ou rejetés pour contrôle manuel
├── exemples/                   # 🧪 Factures de test individuelles d'origine
├── fournisseurs_lcr.txt        # ⚙️ Liste de vos fournisseurs prélevés par LCR
├── Lancer le traitement.bat    # ⚡ Lanceur en un double-clic (Windows, sans terminal)
├── traitement_factures.py      # 🐍 Le script d'automatisation principal
├── requirements.txt            # 📦 Dépendances Python
├── .env.example                # 🔑 Modèle pour votre clé API Gemini
└── README.md
```

---

## 🚀 Installation rapide

### 1. Prérequis
- **Python 3.10 ou supérieur** installé sur votre machine.
- Une **clé API Google Gemini** (gratuite sur [Google AI Studio](https://aistudio.google.com/)).

### 2. Cloner le projet
```bash
git clone https://github.com/ChrisAutodidacte/decoupe-factures-pdf-ia.git
cd decoupe-factures-pdf-ia
```

### 3. Installer les dépendances
```bash
python -m venv venv
# Sur Windows :
venv\Scripts\activate
# Sur Linux / macOS :
source venv/bin/activate

pip install -r requirements.txt
```

### 4. Configurer votre clé API
Copiez le fichier `.env.example` en `.env` :
```bash
cp .env.example .env
```
Ouvrez `.env` et collez votre clé :
```env
GEMINI_API_KEY=votre_cle_api_ici
```

---

## ⚡ Utilisation (En un double-clic !)

1. Déposez votre ou vos fichiers PDF scannés dans le dossier **`Inbox PDF/`** (un scan de test de 7 pages y est déjà présent pour faire vos premiers essais).
2. Ajustez si besoin la liste de vos fournisseurs prélevés automatiquement dans **`fournisseurs_lcr.txt`**.
3. **Lancez le traitement :**
   - **Sous Windows (recommandé pour les pros) :** Double-cliquez simplement sur **`Lancer le traitement.bat`** (aucun terminal à ouvrir ni commande à taper).
   - **En ligne de commande :**
     ```bash
     python traitement_factures.py
     ```
4. Ouvrez le dossier **`Factures/`** : tous vos documents individuels sont découpés, renommés et classés !

---

## 🛡️ Confidentialité & Données

- Aucune donnée n'est stockée sur un serveur tiers autre que les requêtes sécurisées à l'API Gemini.
- Le fichier `.env` contenant votre clé API est strictement protégé par le `.gitignore`.

---

## 👤 Auteur & Communauté

Créé par **Chris l'Autodidacte** — Retours d'expériences concrets et outils pragmatiques pour les indépendants et professionnels.
- Site web : [chrisautodidacte.com](https://chrisautodidacte.com)
- Chaîne YouTube : [Chris l'Autodidacte](https://www.youtube.com/@ChrisAutodidacte)

Licence : [MIT](LICENSE)
