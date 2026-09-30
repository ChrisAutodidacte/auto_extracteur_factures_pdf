#!/usr/bin/env python3
"""
Automate Traitement Factures
-----------------------------
Script de traitement automatique des factures PDF :
  Etape 1 (split)  : Decoupe les PDFs multi-factures de Inbox PDF/ en factures individuelles dans Factures/
  Etape 2 (rename) : Lit chaque facture brouillon et la renomme avec type, fournisseur, numero et date

Usage : python traitement_factures.py
"""

import os
import sys
import json
import shutil
import time
import unicodedata
import re
import base64
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF
from pypdf import PdfReader, PdfWriter
from google import genai
from google.genai import types
from dotenv import load_dotenv

# --- Configuration -----------------------------------------------------------

BASE_DIR = Path(__file__).parent
INBOX_DIR = BASE_DIR / "Inbox PDF"
FACTURES_DIR = BASE_DIR / "Factures"
ANOMALIES_DIR = BASE_DIR / "Anomalies"
TRAITES_DIR = INBOX_DIR / "Traites"
FOURNISSEURS_LCR_FILE = BASE_DIR / "fournisseurs_lcr.txt"

load_dotenv(BASE_DIR / ".env")
API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = "gemini-2.5-pro"


# --- Utilitaires -------------------------------------------------------------

def remove_accents(text: str) -> str:
    """Remplace les caracteres accentues par leur equivalent sans accent."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def safe_filename(text: str, max_len: int = 50) -> str:
    """Nettoie une chaine pour en faire un nom de fichier valide."""
    text = remove_accents(text)
    text = re.sub(r"[^a-zA-Z0-9_\-]", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text[:max_len]


def load_fournisseurs_lcr() -> list[str]:
    """Charge la liste des fournisseurs LCR depuis le fichier externe."""
    if not FOURNISSEURS_LCR_FILE.exists():
        return []
    fournisseurs = []
    for line in FOURNISSEURS_LCR_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            fournisseurs.append(line)
    return fournisseurs


def is_fournisseur_lcr(supplier: str, fournisseurs_lcr: list[str]) -> bool:
    """Verifie si un fournisseur correspond a la liste LCR (approximatif, insensible casse/accents)."""
    supplier_norm = remove_accents(supplier).lower().strip()
    for lcr in fournisseurs_lcr:
        lcr_norm = remove_accents(lcr).lower().strip()
        # Correspondance : le nom LCR est contenu dans le fournisseur ou inversement
        if lcr_norm in supplier_norm or supplier_norm in lcr_norm:
            return True
    return False


def pdf_pages_to_base64(pdf_path: Path) -> list[dict]:
    """Convertit chaque page d'un PDF en image JPEG base64 (scale 2.0 pour meilleure resolution OCR)."""
    doc = fitz.open(str(pdf_path))
    images = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("jpeg", jpg_quality=80)
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        images.append({
            "page_number": page_num + 1,
            "base64": b64,
        })
    doc.close()
    return images


def move_to_anomalies(file_path: Path, reason: str):
    """Deplace un fichier dans le dossier Anomalies."""
    ANOMALIES_DIR.mkdir(exist_ok=True)
    dest = ANOMALIES_DIR / file_path.name
    if dest.exists():
        stem = dest.stem
        suffix = dest.suffix
        dest = ANOMALIES_DIR / f"{stem}_{datetime.now():%Y%m%d_%H%M%S}{suffix}"
    shutil.move(str(file_path), str(dest))
    print(f"  [ANOMALIE] {file_path.name} -> Anomalies/ ({reason})")


class GeminiServiceUnavailableError(Exception):
    """Levee quand Gemini repond 503 apres toutes les tentatives."""


def call_gemini_with_retry(client, parts, schema, max_retries=3):
    """Appelle Gemini avec retry automatique en cas de rate limit (429) ou service indisponible (503)."""
    last_503 = False
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=types.Content(parts=parts),
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                ),
            )
            return response
        except Exception as e:
            err = str(e)
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                last_503 = False
                wait = 30 * (attempt + 1)
                print(f"  Rate limit atteint, attente {wait}s avant retry ({attempt + 1}/{max_retries})...")
                time.sleep(wait)
            elif "503" in err or "SERVICE_UNAVAILABLE" in err or "unavailable" in err.lower():
                last_503 = True
                wait = 10 * (attempt + 1)
                print(f"  Service Gemini indisponible (503), attente {wait}s avant retry ({attempt + 1}/{max_retries})...")
                time.sleep(wait)
            else:
                raise
    if last_503:
        raise GeminiServiceUnavailableError(
            f"Gemini inaccessible apres {max_retries} tentatives (503). Le fichier reste dans Inbox pour relance."
        )
    raise Exception(f"Gemini inaccessible apres {max_retries} tentatives. Document place en anomalie.")


def split_pdf(source_path: Path, start_page: int, end_page: int, output_path: Path):
    """Extrait les pages start_page..end_page (1-based) d'un PDF et les sauvegarde."""
    reader = PdfReader(str(source_path))
    writer = PdfWriter()
    for i in range(start_page - 1, end_page):
        if i < len(reader.pages):
            writer.add_page(reader.pages[i])
    with open(output_path, "wb") as f:
        writer.write(f)


# --- Client Gemini -----------------------------------------------------------

def get_gemini_client():
    """Cree le client Gemini."""
    if not API_KEY:
        print("ERREUR : GEMINI_API_KEY manquante dans le fichier .env")
        sys.exit(1)
    return genai.Client(api_key=API_KEY)


# --- Etape 1 : Split ---------------------------------------------------------

PROMPT_SPLIT = """Tu es un expert en analyse de documents (comptabilite).
J'ai fourni {nb_pages} images representant les pages d'un fichier PDF scanne contenant plusieurs documents comptables.

Ta mission est de :
1. Identifier les limites de chaque document. Certains font une seule page, d'autres plusieurs (ex: page 1 facture, page 2 CGV).
2. Regrouper les pages consecutives appartenant au meme document.
3. Pour chaque document identifie, extraire les informations suivantes :
   - Le type de document (docType) : "facture", "avoir" ou "ticket_de_caisse"
     * "facture" = document classique avec en-tete fournisseur, numero de facture, montants HT/TVA/TTC
     * "avoir" = document similaire a une facture mais qui represente un remboursement ou un credit (souvent indique "avoir", "credit", "note de credit", montants negatifs)
     * "ticket_de_caisse" = format sobre/etroit type caisse enregistreuse, avec lignes d'articles, totaux, pas d'en-tete formel
   - Nom du fournisseur (supplier)
   - Numero de la facture/avoir/ticket (invoiceNumber)
   - Date du document (date) au format YYYY-MM-DD

Retourne les donnees sous forme de tableau JSON."""

SPLIT_SCHEMA = types.Schema(
    type=types.Type.ARRAY,
    items=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "startPage": types.Schema(type=types.Type.INTEGER, description="Index de la premiere page (commence a 1)."),
            "endPage": types.Schema(type=types.Type.INTEGER, description="Index de la derniere page (commence a 1)."),
            "docType": types.Schema(type=types.Type.STRING, description="Type: facture, avoir ou ticket_de_caisse."),
            "supplier": types.Schema(type=types.Type.STRING, description="Nom de l'entreprise emettrice."),
            "invoiceNumber": types.Schema(type=types.Type.STRING, description="Identifiant unique du document."),
            "date": types.Schema(type=types.Type.STRING, description="Date du document YYYY-MM-DD."),
        },
        required=["startPage", "endPage", "docType", "supplier", "invoiceNumber", "date"],
    ),
)


def etape_split(client):
    """Etape 1 : Scanner Inbox PDF, analyser avec Gemini, decouper en documents individuels."""
    print("\n" + "=" * 60)
    print("ETAPE 1 : DECOUPAGE DES PDFs")
    print("=" * 60)

    INBOX_DIR.mkdir(exist_ok=True)
    FACTURES_DIR.mkdir(exist_ok=True)
    TRAITES_DIR.mkdir(exist_ok=True)

    pdf_files = sorted(INBOX_DIR.glob("*.pdf"))
    if not pdf_files:
        print("Aucun PDF trouve dans Inbox PDF/")
        return

    print(f"{len(pdf_files)} PDF(s) a traiter.\n")

    for pdf_path in pdf_files:
        print(f"--- Traitement : {pdf_path.name} ---")
        try:
            images = pdf_pages_to_base64(pdf_path)
            print(f"  {len(images)} page(s) convertie(s) en images.")

            parts = []
            for img in images:
                parts.append(types.Part.from_bytes(
                    data=base64.b64decode(img["base64"]),
                    mime_type="image/jpeg",
                ))
            parts.append(types.Part.from_text(text=PROMPT_SPLIT.format(nb_pages=len(images))))

            print("  Analyse par Gemini en cours...")
            response = call_gemini_with_retry(client, parts, SPLIT_SCHEMA)

            if not response.text:
                move_to_anomalies(pdf_path, "Pas de reponse de Gemini")
                continue

            invoices = json.loads(response.text)
            if not invoices:
                move_to_anomalies(pdf_path, "Aucun document detecte par Gemini")
                continue

            print(f"  {len(invoices)} document(s) detecte(s).")

            # Valider les plages de pages
            nb_pages = len(images)
            valid = True
            for inv in invoices:
                if inv["startPage"] < 1 or inv["endPage"] > nb_pages or inv["startPage"] > inv["endPage"]:
                    valid = False
                    break
            if not valid:
                move_to_anomalies(pdf_path, "Plages de pages invalides")
                continue

            # Decouper le PDF
            now = datetime.now()
            for idx, inv in enumerate(invoices, 1):
                filename = f"facture_brouillon_{now:%Y%m%d_%H%M%S}_{idx:03d}.pdf"
                output_path = FACTURES_DIR / filename
                split_pdf(pdf_path, inv["startPage"], inv["endPage"], output_path)
                doc_type = inv.get("docType", "facture")
                print(f"  -> {filename} (pages {inv['startPage']}-{inv['endPage']}, {doc_type}, {inv.get('supplier', '?')})")

            # Deplacer le PDF source dans Traites/
            dest = TRAITES_DIR / pdf_path.name
            if dest.exists():
                dest = TRAITES_DIR / f"{pdf_path.stem}_{now:%Y%m%d_%H%M%S}{pdf_path.suffix}"
            shutil.move(str(pdf_path), str(dest))
            print(f"  PDF source deplace dans Traites/")

        except GeminiServiceUnavailableError as e:
            print(f"  [503] {e}")
            print(f"  Le fichier reste dans Inbox PDF/ pour relance ulterieure.")
        except Exception as e:
            print(f"  ERREUR : {e}")
            move_to_anomalies(pdf_path, str(e))


# --- Etape 2 : Rename --------------------------------------------------------

PROMPT_RENAME = """Tu es un expert en analyse de documents (comptabilite).
Ces images representent un document comptable (possiblement sur plusieurs pages).

Extrais les informations suivantes :
- Le type de document (docType) :
  * "facture" = document classique avec en-tete fournisseur, numero de facture, montants HT/TVA/TTC
  * "avoir" = document similaire a une facture mais qui represente un remboursement ou un credit (souvent indique "avoir", "credit", "note de credit", montants negatifs)
  * "ticket_de_caisse" = format sobre/etroit type caisse enregistreuse, avec lignes d'articles, totaux, pas d'en-tete formel
- Nom du fournisseur (supplier) : le nom de l'entreprise qui a emis le document
- Numero du document (invoiceNumber) : l'identifiant unique
- Date du document (date) : au format YYYY-MM-DD

Sois precis et retourne les donnees en JSON."""

RENAME_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "docType": types.Schema(type=types.Type.STRING, description="Type: facture, avoir ou ticket_de_caisse."),
        "supplier": types.Schema(type=types.Type.STRING, description="Nom de l'entreprise emettrice."),
        "invoiceNumber": types.Schema(type=types.Type.STRING, description="Identifiant unique du document."),
        "date": types.Schema(type=types.Type.STRING, description="Date du document YYYY-MM-DD."),
    },
    required=["docType", "supplier", "invoiceNumber", "date"],
)

# Mapping type de document -> prefixe de nom de fichier
DOC_TYPE_PREFIX = {
    "facture": "Facture",
    "avoir": "Avoir",
    "ticket_de_caisse": "Ticket_de_caisse",
}


def etape_rename(client):
    """Etape 2 : Lire chaque facture brouillon, extraire les infos, renommer."""
    print("\n" + "=" * 60)
    print("ETAPE 2 : IDENTIFICATION ET RENOMMAGE DES DOCUMENTS")
    print("=" * 60)

    # Charger la liste des fournisseurs LCR
    fournisseurs_lcr = load_fournisseurs_lcr()
    if fournisseurs_lcr:
        print(f"Fournisseurs LCR charges : {', '.join(fournisseurs_lcr)}")
    else:
        print("Aucun fournisseur LCR configure (fichier fournisseurs_lcr.txt)")
    print()

    brouillons = sorted(FACTURES_DIR.glob("facture_brouillon_*.pdf"))
    if not brouillons:
        print("Aucune facture brouillon a traiter dans Factures/")
        return

    print(f"{len(brouillons)} document(s) brouillon a identifier.\n")

    for pdf_path in brouillons:
        print(f"--- Identification : {pdf_path.name} ---")
        try:
            images = pdf_pages_to_base64(pdf_path)

            parts = []
            for img in images:
                parts.append(types.Part.from_bytes(
                    data=base64.b64decode(img["base64"]),
                    mime_type="image/jpeg",
                ))
            parts.append(types.Part.from_text(text=PROMPT_RENAME))

            print("  Lecture par Gemini en cours...")
            response = call_gemini_with_retry(client, parts, RENAME_SCHEMA)

            if not response.text:
                move_to_anomalies(pdf_path, "Pas de reponse de Gemini")
                continue

            data = json.loads(response.text)

            doc_type = data.get("docType", "facture").strip().lower()
            supplier = data.get("supplier", "").strip()
            invoice_number = data.get("invoiceNumber", "").strip()
            date_str = data.get("date", "").strip()

            # Validation
            if not supplier or supplier.lower() in ("inconnu", "unknown", ""):
                move_to_anomalies(pdf_path, "Fournisseur non identifie")
                continue

            if not invoice_number:
                move_to_anomalies(pdf_path, "Numero de document non identifie")
                continue

            if not date_str:
                move_to_anomalies(pdf_path, "Date non identifiee")
                continue

            # Convertir date YYYY-MM-DD -> JJMMAAAA
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                date_formatted = dt.strftime("%d%m%Y")
            except ValueError:
                for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y%m%d"):
                    try:
                        dt = datetime.strptime(date_str, fmt)
                        date_formatted = dt.strftime("%d%m%Y")
                        break
                    except ValueError:
                        continue
                else:
                    move_to_anomalies(pdf_path, f"Format de date invalide : {date_str}")
                    continue

            # Determiner le prefixe (type + LCR si applicable)
            prefix = DOC_TYPE_PREFIX.get(doc_type, "Facture")
            is_lcr = is_fournisseur_lcr(supplier, fournisseurs_lcr)
            if is_lcr:
                prefix = f"{prefix}_LCR"

            # Construire le nom de fichier final
            safe_supplier = safe_filename(supplier)
            safe_number = safe_filename(invoice_number, max_len=30)
            new_name = f"{prefix}_{safe_supplier}_{safe_number}_{date_formatted}.pdf"

            new_path = FACTURES_DIR / new_name
            if new_path.exists():
                new_name = f"{prefix}_{safe_supplier}_{safe_number}_{date_formatted}_{datetime.now():%H%M%S}.pdf"
                new_path = FACTURES_DIR / new_name

            pdf_path.rename(new_path)
            lcr_tag = " [LCR]" if is_lcr else ""
            print(f"  -> Renomme : {new_name}")
            print(f"     Type: {doc_type}{lcr_tag} | Fournisseur: {supplier} | N: {invoice_number} | Date: {date_formatted}")

        except GeminiServiceUnavailableError as e:
            print(f"  [503] {e}")
            print(f"  Le brouillon reste dans Factures/ pour relance ulterieure.")
        except Exception as e:
            print(f"  ERREUR : {e}")
            move_to_anomalies(pdf_path, str(e))


# --- Main --------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  AUTOMATE TRAITEMENT FACTURES")
    print(f"  {datetime.now():%d/%m/%Y %H:%M:%S}")
    print("=" * 60)

    client = get_gemini_client()

    etape_split(client)
    etape_rename(client)

    print("\n" + "=" * 60)
    print("TRAITEMENT TERMINE")
    print("=" * 60)

    # Resume
    factures_finales = [f for f in FACTURES_DIR.glob("*.pdf") if not f.name.startswith("facture_brouillon_")]
    anomalies = list(ANOMALIES_DIR.glob("*.pdf")) if ANOMALIES_DIR.exists() else []
    brouillons_restants = list(FACTURES_DIR.glob("facture_brouillon_*.pdf"))

    print(f"  Documents traites : {len(factures_finales)}")
    print(f"  Anomalies         : {len(anomalies)}")
    if brouillons_restants:
        print(f"  Brouillons restants : {len(brouillons_restants)}")


if __name__ == "__main__":
    main()
