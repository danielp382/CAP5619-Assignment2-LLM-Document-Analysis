# CAP5619 - Assignment 2: LLM Document Analysis
# Read SEC 8-K text files, check for new products with Ollama,
# and save valid product announcements to a CSV file.

import csv
import json
import subprocess
from pathlib import Path
from urllib.request import Request, urlopen

# Put your email here before running. The SEC requires an identifying User-Agent.
SEC_USER_AGENT = "CAP5619 Student Research your-email@example.com"
MODEL_NAME = "llama3.2:3b"

folder = Path(__file__).parent
input_file = folder / "filings_to_analyze.csv"
output_file = folder / "product_announcements.csv"
review_file = folder / "review_log.csv"

columns = [
    "company_name",
    "stock_name",
    "filing_time",
    "new_product",
    "product_description"
]


def analyze_document(document_text):
    # The LLM identifies the product, but it does not supply SEC metadata.
    prompt = f"""
You are analyzing an SEC Form 8-K filing or an attached exhibit.
Determine whether the document explicitly announces a NEW product launch.
Do not count financial reporting changes, earnings, ordinary company news,
contracts, or existing products that are not being newly launched.
Use only facts in the document. Do not invent a product or its features.
If there is a new product, provide its exact name and a factual description
of fewer than 180 characters. If there is no new product, use N/A.

Return these four lines, with no extra headings:
New Product Announced: Yes or No
Product Name: Name or N/A
Product Description: Short description or N/A
Reason: Brief explanation

SEC DOCUMENT:
{document_text}
"""

    result = subprocess.run(
        ["ollama", "run", MODEL_NAME],
        input=prompt,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=180
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Ollama returned an error")

    # Store the four fields in a dictionary.
    fields = {}
    allowed_fields = [
        "New Product Announced",
        "Product Name",
        "Product Description",
        "Reason"
    ]

    for line in result.stdout.splitlines():
        field, separator, value = line.partition(":")
        if separator and field.strip() in allowed_fields:
            fields[field.strip()] = value.strip()

    return fields


def get_sec_metadata(cik, accession_number):
    # SEC submissions API gives the company, ticker and acceptance time.
    cik = cik.zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    request = Request(url, headers={
        "User-Agent": SEC_USER_AGENT,
        "Accept": "application/json"
    })

    with urlopen(request, timeout=30) as response:
        data = json.load(response)

    recent = data["filings"]["recent"]
    try:
        index = recent["accessionNumber"].index(accession_number)
    except ValueError:
        raise ValueError("Accession not found in recent SEC submissions")

    tickers = data.get("tickers", [])
    if not tickers:
        raise ValueError("No ticker found in SEC company metadata")

    return (
        data["name"],
        tickers[0],
        recent["acceptanceDateTime"][index]
    )


def main():
    if "your-email@example.com" in SEC_USER_AGENT:
        raise SystemExit(
            "First, replace your-email@example.com with your email "
            "in assignment2_final.py."
        )

    if not input_file.exists():
        raise SystemExit("Missing filings_to_analyze.csv")

    with open(input_file, "r", encoding="utf-8-sig", newline="") as file:
        documents = list(csv.DictReader(file))

    product_rows = []
    review_rows = []
    seen_products = set()

    for number, document in enumerate(documents, start=1):
        filename = document["filename"].strip()
        cik = document["cik"].strip()
        accession = document["accession_number"].strip()
        document_path = folder / filename

        print(f"\nDocument {number} of {len(documents)}: {filename}")

        if not document_path.is_file():
            print("Skipped: the text file was not found")
            review_rows.append([filename, cik, accession, "FILE NOT FOUND", ""])
            continue

        try:
            text = document_path.read_text(encoding="utf-8")
            fields = analyze_document(text)

            announced = fields.get("New Product Announced", "").lower()
            product = fields.get("Product Name", "").strip()
            description = fields.get("Product Description", "").strip()
            reason = fields.get("Reason", "")

            print("New product announced:", announced or "MISSING")
            print("Product:", product or "MISSING")
            print("Reason:", reason)

            if announced == "no":
                review_rows.append([filename, cik, accession, "NO PRODUCT", reason])
                continue

            # Only save product announcements with usable fields.
            if (
                announced != "yes"
                or not product
                or product.upper() == "N/A"
                or not description
                or description.upper() == "N/A"
                or len(description) >= 180
            ):
                print("Skipped: missing or invalid product information")
                review_rows.append([filename, cik, accession, "INVALID RESULT", reason])
                continue

            company, ticker, filing_time = get_sec_metadata(cik, accession)
            unique_product = (accession, product.lower())

            if unique_product in seen_products:
                print("Skipped: duplicate product")
                review_rows.append([filename, cik, accession, "DUPLICATE", reason])
                continue

            seen_products.add(unique_product)
            product_rows.append([
                company, ticker, filing_time, product, description
            ])
            review_rows.append([filename, cik, accession, "SAVED", reason])
            print("Saved:", company, "-", product)
            print("Description characters:", len(description))

        except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as error:
            print("Could not complete this document:", error)
            review_rows.append([filename, cik, accession, "ERROR", str(error)])

    # Overwrite the CSV with the results from this run.
    with open(output_file, "w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(columns)
        writer.writerows(product_rows)

    # This separate log explains which documents were skipped and why.
    with open(review_file, "w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["filename", "cik", "accession_number", "status", "reason"])
        writer.writerows(review_rows)

    print("\nFinished.")
    print("Documents processed:", len(documents))
    print("Product rows saved:", len(product_rows))
    print("CSV:", output_file.name)
    print("Review log:", review_file.name)


if __name__ == "__main__":
    main()
