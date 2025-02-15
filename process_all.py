import asyncio
import os
from pathlib import Path
from pdf_metadata_extractor import process_pdf, PDFProcessor
from rich.console import Console
from rich.table import Table
from opensearchpy import OpenSearch, OpenSearchException
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv
import hashlib

load_dotenv()

# Load environment variables with defaults
OPENSEARCH_HOST = os.getenv('OPENSEARCH_HOST', 'localhost')
OPENSEARCH_PORT = int(os.getenv('OPENSEARCH_PORT', '9200'))
OPENSEARCH_USER = os.getenv('OPENSEARCH_USER', 'admin')
OPENSEARCH_PASSWORD = os.getenv('OPENSEARCH_PASSWORD', 'admin')
OPENSEARCH_USE_SSL = os.getenv('OPENSEARCH_USE_SSL', 'true').lower() == 'true'
OPENSEARCH_VERIFY_CERTS = os.getenv('OPENSEARCH_VERIFY_CERTS', 'false').lower() == 'true'
OPENSEARCH_INDEX = os.getenv('OPENSEARCH_INDEX', 'pdf_documents')

class OpenSearchUploader:
    def __init__(self):
        self.client = None
        self.console = Console()

    def connect(self) -> bool:
        """Establish connection to OpenSearch"""
        try:
            print(f"Connecting to OpenSearch on {OPENSEARCH_HOST}")
            self.client = OpenSearch(
                hosts=[{'host': OPENSEARCH_HOST, 'port': OPENSEARCH_PORT}],
                http_auth=(OPENSEARCH_USER, OPENSEARCH_PASSWORD),
                use_ssl=OPENSEARCH_USE_SSL,
                verify_certs=OPENSEARCH_VERIFY_CERTS,
                ssl_show_warn=False
            )
            # Test connection
            self.client.info()
            return True
        except Exception as e:
            self.console.print(f"[red]Failed to connect to OpenSearch: {str(e)}[/red]")
            return False

    async def upload_document(self, metadata, file_hash: str) -> bool:
        """Upload metadata to OpenSearch"""
        if not self.client:
            if not self.connect():
                return False

        document = {
            'title': metadata.title,
            'authors': metadata.authors,
            'publication_year': metadata.publication_year,
            'file_hash': file_hash,
            'doc_type': 'Book' if hasattr(metadata, 'isbn') else 'Paper',
            'timestamp': datetime.now().isoformat(),
        }
        
        if hasattr(metadata, 'isbn'):
            document['isbn'] = metadata.isbn

        try:
            response = self.client.index(
                index=OPENSEARCH_INDEX,
                body=document,
                id=file_hash,
                refresh=True
            )
            self.console.print(f"[green]Document indexed successfully: {response['result']}[/green]")
            return True
        except OpenSearchException as e:
            self.console.print(f"[red]OpenSearch indexing error: {str(e)}[/red]")
            return False
        except Exception as e:
            self.console.print(f"[red]Unexpected error during indexing: {str(e)}[/red]")
            return False

async def process_single_pdf(pdf_path: Path, uploader: OpenSearchUploader) -> bool:
    """Process a single PDF file and upload its metadata"""
    try:
        # Compute file hash first
        with open(pdf_path, 'rb') as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()
            
        # Process the PDF
        metadata = await process_pdf(pdf_path)
        if metadata is None:
            # If file was already processed, try to get metadata from PDFProcessor
            processor = PDFProcessor()
            metadata = processor.metadata_store.get_by_hash(file_hash)
            if metadata is None:
                print(f"[red]Could not get metadata for {pdf_path}[/red]")
                return False
                
        print(f"Successfully processed {pdf_path}")
            
        # Upload to OpenSearch
        success = await uploader.upload_document(metadata, file_hash)
        return success
            
    except Exception as e:
        print(f"[red]Failed to process {pdf_path}: {str(e)}[/red]")
        import traceback
        traceback.print_exc()
        return False

async def main():
    console = Console()
    console.print("[blue]Script started![/blue]")
    
    pdf_dir = Path("./pdfs")
    console.print(f"Looking for PDFs in: {pdf_dir.absolute()}")
    
    # Check if directory exists
    if not pdf_dir.exists():
        console.print(f"[yellow]Creating directory: {pdf_dir}[/yellow]")
        pdf_dir.mkdir(parents=True)
    
    # Get list of PDFs
    pdfs = list(pdf_dir.glob("*.pdf"))
    
    if not pdfs:
        console.print(f"[yellow]No PDF files found in {pdf_dir}[/yellow]")
        return
        
    console.print(f"[green]Found {len(pdfs)} PDF files[/green]")
    
    # Initialize OpenSearch uploader
    uploader = OpenSearchUploader()
    if not uploader.connect():
        console.print("[red]Failed to establish OpenSearch connection. Exiting...[/red]")
        return

    # Process each PDF
    results = []
    for pdf_path in pdfs:
        console.print(f"\n[blue]Processing {pdf_path}[/blue]")
        success = await process_single_pdf(pdf_path, uploader)
        results.append((pdf_path, success))

    # Show processing summary
    console.print("\n[bold]Processing Summary:[/bold]")
    for path, success in results:
        status = "[green]Success[/green]" if success else "[red]Failed[/red]"
        console.print(f"{path}: {status}")

    # Show metadata summary
    show_summary()

def show_summary():
    """Show summary of processed documents"""
    processor = PDFProcessor()
    console = Console()
    
    table = Table(title="PDF Metadata Summary")
    table.add_column("Type", style="cyan")
    table.add_column("Title", style="green")
    table.add_column("Authors", style="yellow")
    table.add_column("Year", style="blue")
    table.add_column("Hash", style="magenta")

    for file_hash, metadata in processor.metadata_store.documents.items():
        doc_type = "Book" if hasattr(metadata, "isbn") else "Paper"
        table.add_row(
            doc_type,
            metadata.title[:50] + "..." if len(metadata.title) > 50 else metadata.title,
            ", ".join(metadata.authors[:2]) + ("..." if len(metadata.authors) > 2 else ""),
            str(metadata.publication_year or "N/A"),
            file_hash[:8] + "..."
        )

    console.print(table)

if __name__ == "__main__":
    print("Starting main...")  # Debug line
    asyncio.run(main()) 