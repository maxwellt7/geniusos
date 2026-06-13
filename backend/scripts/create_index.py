"""Create the Pinecone index with integrated embeddings if it doesn't exist.

Usage:
    python -m scripts.create_index
"""

from pinecone import Pinecone

from app.config import get_settings


def main() -> None:
    settings = get_settings()
    pc = Pinecone(api_key=settings.pinecone_api_key)
    name = settings.pinecone_index_name

    if pc.has_index(name):
        print(f"Index '{name}' already exists.")
    else:
        pc.create_index_for_model(
            name=name,
            cloud="aws",
            region="us-east-1",
            embed={
                "model": "llama-text-embed-v2",
                "field_map": {"text": "chunk_text"},
            },
        )
        print(f"Created index '{name}' (llama-text-embed-v2, field: chunk_text).")

    desc = pc.describe_index(name)
    print(f"Host: {desc.host}")


if __name__ == "__main__":
    main()
