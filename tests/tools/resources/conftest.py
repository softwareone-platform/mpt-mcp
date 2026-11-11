import pytest


@pytest.fixture
def products_registry():
    return {
        "catalog.products": {
            "path": "/public/v1/catalog/products",
            "summary": "Products",
            "parameters": [
                {"name": "status", "in": "query", "schema": {"enum": ["Draft", "Published"]}}
            ],
        },
        "catalog.products.by_id": {
            "path": "/public/v1/catalog/products/{id}",
            "summary": "Product by ID",
            "parameters": [{"name": "id", "in": "path", "schema": {"type": "string"}}],
        },
        "catalog.products.by_id.items": {
            "path": "/public/v1/catalog/products/{id}/items",
            "summary": "Product items",
            "parameters": [],
        },
        "catalog.listings": {
            "path": "/public/v1/catalog/listings",
            "summary": "Listings",
            "parameters": [],
        },
        "catalog.items": {
            "path": "/public/v1/catalog/items",
            "summary": "Items",
            "parameters": [],
        },
        "catalog.products.search": {
            "path": "/public/v1/catalog/products/search",
            "summary": "Search products",
            "parameters": [],
        },
    }
